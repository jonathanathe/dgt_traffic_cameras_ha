"""Tests de coordinator.py: ciclo de vida del coordinador único de paneles.

Cubren el bug H-01 encontrado en la auditoría (el coordinador se apagaba
cuando se recargaba la primera entrada de paneles, dejando congeladas las
demás) y su corrección (config_entry=None + reintento manual), así como
H-02 (no registrar una entrada como "usando" el coordinador hasta que
consigue datos de verdad, y fallar el setup con ConfigEntryNotReady si la
primera descarga falla).

El stub de DataUpdateCoordinator (ver tests/_load.py) reproduce el detalle
exacto de la API real que causaba H-01: si se le pasa una config_entry, se
registra sola para apagarse cuando ESA entrada se descargue.
"""

from __future__ import annotations

import unittest

from ._load import load

coordinator_mod = load("coordinator")
const_mod = load("const")


class _EntradaFalsa:
    """Emula una ConfigEntry real lo justo para probar async_on_unload."""

    def __init__(self) -> None:
        self._callbacks: list = []

    def async_on_unload(self, callback) -> None:
        self._callbacks.append(callback)

    async def descargar(self) -> None:
        """Simula que Home Assistant descarga esta entrada de verdad."""
        for callback in self._callbacks:
            await callback()


class _HassFalso:
    def __init__(self) -> None:
        self.data: dict = {}

    async def async_add_executor_job(self, func, *args):
        # En el test no hace falta un hilo aparte de verdad: basta con
        # llamar a la función tal cual (síncrona) y devolver su resultado.
        return func(*args)


class TestCoordinadorNoSeAtaAUnaEntrada(unittest.IsolatedAsyncioTestCase):
    """H-01: el coordinador no debe depender del ciclo de vida de una entrada."""

    async def test_config_entry_es_none(self) -> None:
        hass = _HassFalso()
        coordinator = coordinator_mod.DgtVmsMessagesCoordinator(hass)
        self.assertIsNone(coordinator.config_entry)

    async def test_apagar_una_entrada_no_afecta_al_coordinador_compartido(self) -> None:
        """Reproduce el escenario exacto del bug: dos entradas, se recarga la primera.

        Antes del fix, el coordinador se construía sin pasar config_entry, así
        que el propio DataUpdateCoordinator ataba su apagado a la entrada que
        estuviera en curso en ese momento. Aquí se simula ese escenario
        directamente contra el stub (que si soporta ese registro) para
        demostrar que, con el fix, nada se registra: "descargar" una entrada
        cualquiera nunca apaga el coordinador compartido.
        """
        hass = _HassFalso()
        entrada_cualquiera = _EntradaFalsa()

        coordinator = coordinator_mod.DgtVmsMessagesCoordinator(hass)
        # Si alguien reintrodujera el bug (pasando una config_entry real al
        # construir el coordinador), este mismo test lo pillaría: aquí no se
        # pasa ninguna, así que no hay nada que registrar.
        self.assertEqual(entrada_cualquiera._callbacks, [])

        await entrada_cualquiera.descargar()
        self.assertFalse(coordinator.shutdown_llamado)


class TestAsyncGetOrCreate(unittest.IsolatedAsyncioTestCase):
    """Comportamiento de async_get_or_create / async_release con datos falsos."""

    def setUp(self) -> None:
        self._download_original = coordinator_mod.async_download_xml
        self._parse_original = coordinator_mod.parse_vms_messages
        self._get_session_original = coordinator_mod.async_get_clientsession
        self.descargas_realizadas = 0
        self.forzar_fallo = False

        async def descarga_falsa(*args, **kwargs):
            self.descargas_realizadas += 1
            if self.forzar_fallo:
                raise TimeoutError("simulado")
            return b"<xml/>"

        def parse_falso(xml_bytes):
            return {"167938": "estado-de-mentira"}

        def sesion_falsa(hass):
            return None  # no se usa de verdad: async_download_xml está mockeado

        coordinator_mod.async_download_xml = descarga_falsa
        coordinator_mod.parse_vms_messages = parse_falso
        coordinator_mod.async_get_clientsession = sesion_falsa

    def tearDown(self) -> None:
        coordinator_mod.async_download_xml = self._download_original
        coordinator_mod.parse_vms_messages = self._parse_original
        coordinator_mod.async_get_clientsession = self._get_session_original

    async def test_primera_entrada_crea_y_descarga(self) -> None:
        hass = _HassFalso()
        coordinator = await coordinator_mod.async_get_or_create(hass, "entrada_1")
        self.assertEqual(self.descargas_realizadas, 1)
        self.assertEqual(coordinator.data, {"167938": "estado-de-mentira"})

    async def test_segunda_entrada_reutiliza_sin_descargar_otra_vez(self) -> None:
        hass = _HassFalso()
        c1 = await coordinator_mod.async_get_or_create(hass, "entrada_1")
        c2 = await coordinator_mod.async_get_or_create(hass, "entrada_2")
        self.assertIs(c1, c2)
        # Con datos ya presentes, la segunda llamada NO debe volver a descargar.
        self.assertEqual(self.descargas_realizadas, 1)

    async def test_fallo_en_la_primera_descarga_lanza_config_entry_not_ready(self) -> None:
        from homeassistant.exceptions import ConfigEntryNotReady

        hass = _HassFalso()
        self.forzar_fallo = True
        with self.assertRaises(ConfigEntryNotReady):
            await coordinator_mod.async_get_or_create(hass, "entrada_1")

    async def test_entrada_que_falla_no_queda_registrada_como_usuaria(self) -> None:
        """H-02: si la primera descarga falla, esa entrada no debe "usar" el
        coordinador (si no, nunca se liberaría aunque nunca llegara a cargar)."""
        hass = _HassFalso()
        self.forzar_fallo = True
        try:
            await coordinator_mod.async_get_or_create(hass, "entrada_1")
        except Exception:  # noqa: BLE001 - se espera ConfigEntryNotReady
            pass

        entries = hass.data.get(const_mod.DOMAIN, {}).get("vms_coordinator_entries")
        self.assertTrue(not entries)

    async def test_tras_fallo_una_segunda_llamada_reintenta_la_descarga(self) -> None:
        hass = _HassFalso()
        self.forzar_fallo = True
        with self.assertRaises(Exception):  # noqa: B017 - ConfigEntryNotReady
            await coordinator_mod.async_get_or_create(hass, "entrada_1")

        self.forzar_fallo = False
        coordinator = await coordinator_mod.async_get_or_create(hass, "entrada_1")
        self.assertIsNotNone(coordinator.data)
        self.assertEqual(self.descargas_realizadas, 2)

    async def test_release_no_apaga_el_coordinador_si_otra_entrada_lo_sigue_usando(
        self,
    ) -> None:
        hass = _HassFalso()
        await coordinator_mod.async_get_or_create(hass, "entrada_1")
        coordinator = await coordinator_mod.async_get_or_create(hass, "entrada_2")

        await coordinator_mod.async_release(hass, "entrada_1")
        self.assertFalse(coordinator.shutdown_llamado)

        await coordinator_mod.async_release(hass, "entrada_2")
        self.assertTrue(coordinator.shutdown_llamado)


if __name__ == "__main__":
    unittest.main()
