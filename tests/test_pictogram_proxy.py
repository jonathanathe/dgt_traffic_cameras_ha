"""Tests de pictogram_proxy.py: I-06, proxy de pictogramas a través de HA.

Cubre la lógica pura (validación de URL, descarga, caché en memoria), no la
vista HTTP en sí (http_views.py): probar esa capa de verdad exigiría aiohttp
real, que este repo no instala como dependencia de test (igual que
async_download_xml de api.py tampoco tiene test de red directo, solo de su
lógica de parseo/límites).
"""

from __future__ import annotations

import unittest

from ._load import load

pictogram_proxy = load("pictogram_proxy")


class _FakeStreamContent:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def iter_chunked(self, size: int):
        datos = self._data

        async def _gen():
            yield datos

        return _gen()


class _FakeResponse:
    def __init__(self, data: bytes, content_type: str = "image/png", status: int = 200) -> None:
        self.content_type = content_type
        self.status = status
        self.content = _FakeStreamContent(data)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeSession:
    """Imita justo lo que async_fetch_pictogram usa de aiohttp.ClientSession."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.llamadas = 0

    def get(self, url):
        self.llamadas += 1
        return self._response


class TestAsyncFetchPictogram(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        pictogram_proxy.clear_pictogram_cache()

    async def test_url_no_permitida_se_rechaza_sin_tocar_la_red(self) -> None:
        """El filtro de dominio/HTTPS es lo único que evita que esto se use
        como proxy abierto hacia cualquier URL; debe aplicarse ANTES de
        intentar ninguna descarga."""
        resultado = await pictogram_proxy.async_fetch_pictogram(
            None, "https://sitio-no-dgt.example/icono.png"
        )
        self.assertIsNone(resultado)

    async def test_descarga_y_devuelve_contenido_y_content_type(self) -> None:
        respuesta = _FakeResponse(b"contenido-de-mentira", content_type="image/png")
        session = _FakeSession(respuesta)

        resultado = await pictogram_proxy.async_fetch_pictogram(
            session,
            "https://etraffic.dgt.es/estaticosEtraffic/Iconografia/pictogramas/E17.png",
        )

        self.assertEqual(resultado, (b"contenido-de-mentira", "image/png"))
        self.assertEqual(session.llamadas, 1)

    async def test_segunda_llamada_usa_cache_no_vuelve_a_descargar(self) -> None:
        """Un pictograma no cambia; no hace falta redescargarlo en cada
        refresco del dashboard mientras la caché siga siendo válida."""
        respuesta = _FakeResponse(b"x")
        session = _FakeSession(respuesta)
        url = "https://etraffic.dgt.es/estaticosEtraffic/Iconografia/pictogramas/E17.png"

        primera = await pictogram_proxy.async_fetch_pictogram(session, url)
        segunda = await pictogram_proxy.async_fetch_pictogram(session, url)

        self.assertEqual(primera, segunda)
        self.assertEqual(session.llamadas, 1)


if __name__ == "__main__":
    unittest.main()
