"""Tests de __init__.py: qué se limpia en cada recarga vs. al borrar de verdad.

Cubre M-08 de la auditoría: antes, la caché del inventario de cámaras y las
ubicaciones de paneles (varios MB) y el coordinador compartido de mensajes
de paneles se destruían en CADA recarga de la única entrada existente
(añadir/quitar un dispositivo, activar el interruptor de mapa...), no solo
al borrarla de verdad.
"""

from __future__ import annotations

import unittest

from ._load import load

integracion = load("__init__")
const_mod = load("const")


class _PlatformsFalso:
    async def async_unload_platforms(self, entry, platforms):
        return True

    async def async_forward_entry_setups(self, entry, platforms):
        return None


class _HassFalso:
    def __init__(self) -> None:
        self.data: dict = {}
        self.config_entries = _PlatformsFalso()


class _EntradaFalsa:
    def __init__(self, entry_id: str, device_type: str | None = None) -> None:
        self.entry_id = entry_id
        self.data: dict = {}
        if device_type is not None:
            self.data[const_mod.CONF_DEVICE_TYPE] = device_type
        self.options: dict = {}
        self.title = f"Entrada {entry_id}"

    def async_on_unload(self, callback) -> None:
        pass


class TestUnloadNoLimpiaCachesCompartidas(unittest.IsolatedAsyncioTestCase):
    """M-08: async_unload_entry (que también corre en cada recarga) no debe
    destruir cachés ni coordinadores compartidos; eso es cosa de
    async_remove_entry, que solo se llama al borrar la entrada de verdad."""

    def setUp(self) -> None:
        self._clear_inventory_original = integracion.clear_inventory_cache
        self._clear_vms_original = integracion.clear_vms_locations_cache
        self._release_original = integracion.vms_coordinator.async_release

        self.inventory_limpiado = False
        self.vms_locations_limpiado = False
        self.coordinador_liberado = False

        def clear_inventory():
            self.inventory_limpiado = True

        def clear_vms():
            self.vms_locations_limpiado = True

        async def release(hass, entry_id):
            self.coordinador_liberado = True

        integracion.clear_inventory_cache = clear_inventory
        integracion.clear_vms_locations_cache = clear_vms
        integracion.vms_coordinator.async_release = release

    def tearDown(self) -> None:
        integracion.clear_inventory_cache = self._clear_inventory_original
        integracion.clear_vms_locations_cache = self._clear_vms_original
        integracion.vms_coordinator.async_release = self._release_original

    async def test_unload_de_la_unica_entrada_no_limpia_nada_compartido(self) -> None:
        hass = _HassFalso()
        entry = _EntradaFalsa("entry1", const_mod.DEVICE_TYPE_VMS)
        hass.data.setdefault(const_mod.DOMAIN, {}).setdefault("huellas_entradas", {})[
            entry.entry_id
        ] = ("algo",)

        resultado = await integracion.async_unload_entry(hass, entry)

        self.assertTrue(resultado)
        self.assertFalse(self.inventory_limpiado)
        self.assertFalse(self.vms_locations_limpiado)
        self.assertFalse(self.coordinador_liberado)

    async def test_unload_si_quita_la_huella_de_esta_entrada(self) -> None:
        hass = _HassFalso()
        entry = _EntradaFalsa("entry1")
        huellas = hass.data.setdefault(const_mod.DOMAIN, {}).setdefault(
            "huellas_entradas", {}
        )
        huellas[entry.entry_id] = ("algo",)

        await integracion.async_unload_entry(hass, entry)

        self.assertNotIn(entry.entry_id, huellas)


class TestRemoveEntrySiLimpia(unittest.IsolatedAsyncioTestCase):
    """async_remove_entry SÍ debe limpiar, pero solo cuando no queda ninguna
    entrada (huellas vacío) y liberar el coordinador para entradas de panel."""

    def setUp(self) -> None:
        self._clear_inventory_original = integracion.clear_inventory_cache
        self._clear_vms_original = integracion.clear_vms_locations_cache
        self._release_original = integracion.vms_coordinator.async_release

        self.inventory_limpiado = False
        self.vms_locations_limpiado = False
        self.entry_liberado: str | None = None

        def clear_inventory():
            self.inventory_limpiado = True

        def clear_vms():
            self.vms_locations_limpiado = True

        async def release(hass, entry_id):
            self.entry_liberado = entry_id

        integracion.clear_inventory_cache = clear_inventory
        integracion.clear_vms_locations_cache = clear_vms
        integracion.vms_coordinator.async_release = release

    def tearDown(self) -> None:
        integracion.clear_inventory_cache = self._clear_inventory_original
        integracion.clear_vms_locations_cache = self._clear_vms_original
        integracion.vms_coordinator.async_release = self._release_original

    async def test_borrar_la_ultima_entrada_limpia_las_cachés(self) -> None:
        hass = _HassFalso()
        entry = _EntradaFalsa("entry1")
        # async_unload_entry ya habría quitado la huella antes de llegar
        # aquí; con huellas vacío, se simula justo ese momento.
        hass.data.setdefault(const_mod.DOMAIN, {}).setdefault("huellas_entradas", {})

        await integracion.async_remove_entry(hass, entry)

        self.assertTrue(self.inventory_limpiado)
        self.assertTrue(self.vms_locations_limpiado)

    async def test_borrar_una_entrada_de_paneles_libera_el_coordinador(self) -> None:
        hass = _HassFalso()
        entry = _EntradaFalsa("entry1", const_mod.DEVICE_TYPE_VMS)
        hass.data.setdefault(const_mod.DOMAIN, {}).setdefault("huellas_entradas", {})

        await integracion.async_remove_entry(hass, entry)

        self.assertEqual(self.entry_liberado, "entry1")

    async def test_borrar_una_entrada_de_camaras_no_toca_el_coordinador(self) -> None:
        hass = _HassFalso()
        entry = _EntradaFalsa("entry1")  # sin device_type -> cámara
        hass.data.setdefault(const_mod.DOMAIN, {}).setdefault("huellas_entradas", {})

        await integracion.async_remove_entry(hass, entry)

        self.assertIsNone(self.entry_liberado)

    async def test_borrar_una_entrada_mientras_queda_otra_no_limpia_nada(self) -> None:
        hass = _HassFalso()
        entry = _EntradaFalsa("entry1")
        # Queda otra entrada activa (huellas no está vacío).
        hass.data.setdefault(const_mod.DOMAIN, {}).setdefault("huellas_entradas", {})[
            "entry2"
        ] = ("otra",)

        await integracion.async_remove_entry(hass, entry)

        self.assertFalse(self.inventory_limpiado)
        self.assertFalse(self.vms_locations_limpiado)


if __name__ == "__main__":
    unittest.main()
