"""Tests de frontend_registration.py: registro de la tarjeta del panel.

Cubre justo lo que es lógica propia y comprobable sin Home Assistant real:
qué ruta estática se registra, qué carpeta le pasamos (debe existir de
verdad y contener el .js) y qué aviso de Reparaciones se crea. Que Home
Assistant sirva de verdad esos ficheros por HTTP, o que Reparaciones
muestre el aviso en la interfaz, se prueba a mano en la instancia real
(ver la nota de frontend_registration.py sobre el riesgo de tocar la
colección de recursos de Lovelace).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from ._load import load

frontend_registration = load("frontend_registration")
const = load("const")

issue_registry = sys.modules["homeassistant.helpers.issue_registry"]


class _FakeHttp:
    def __init__(self) -> None:
        self.rutas_registradas = []

    async def async_register_static_paths(self, configs) -> None:
        self.rutas_registradas.extend(configs)


class _FakeHass:
    def __init__(self) -> None:
        self.http = _FakeHttp()


class TestAsyncRegisterFrontend(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._avisos_creados = []
        self._async_create_issue_original = issue_registry.async_create_issue
        issue_registry.async_create_issue = (
            lambda *args, **kwargs: self._avisos_creados.append((args, kwargs))
        )

    def tearDown(self) -> None:
        issue_registry.async_create_issue = self._async_create_issue_original

    async def test_registra_la_carpeta_frontend_real_sin_cabeceras_de_cache(self) -> None:
        hass = _FakeHass()

        await frontend_registration.async_register_frontend(hass)

        self.assertEqual(len(hass.http.rutas_registradas), 1)
        config = hass.http.rutas_registradas[0]
        self.assertEqual(config.url_path, const.FRONTEND_URL_BASE)
        self.assertFalse(config.cache_headers)

        carpeta_servida = Path(config.path)
        self.assertTrue(carpeta_servida.is_dir())
        self.assertTrue((carpeta_servida / const.FRONTEND_CARD_FILENAME).is_file())

    async def test_crea_un_unico_aviso_con_la_url_completa_de_la_tarjeta(self) -> None:
        hass = _FakeHass()

        await frontend_registration.async_register_frontend(hass)

        self.assertEqual(len(self._avisos_creados), 1)
        args, kwargs = self._avisos_creados[0]

        self.assertEqual(args[0], hass)
        self.assertEqual(args[1], const.DOMAIN)
        self.assertEqual(
            kwargs["translation_placeholders"]["url"],
            f"{const.FRONTEND_URL_BASE}/{const.FRONTEND_CARD_FILENAME}",
        )
        self.assertFalse(kwargs["is_fixable"])


if __name__ == "__main__":
    unittest.main()
