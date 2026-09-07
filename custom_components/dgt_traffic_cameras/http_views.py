"""Vista HTTP que expone el proxy de pictogramas (ver pictogram_proxy.py).

Fichero separado a propósito: es la única parte de la integración que
depende de aiohttp.web / HomeAssistantView, y aislarla aquí evita mezclar
esa capa HTTP con la lógica pura y ya testeada de pictogram_proxy.py.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .pictogram_proxy import async_fetch_pictogram

PICTOGRAM_PROXY_URL = "/api/dgt_traffic_cameras/pictogram"


class DgtPictogramProxyView(HomeAssistantView):
    """GET /api/dgt_traffic_cameras/pictogram?url=<url de la DGT>.

    Sin autenticación a propósito (requires_auth = False): son imágenes
    públicas de la propia DGT (avisos de tráfico en la vía pública, no
    datos de la instalación de nadie), así que funcionan igual de bien en
    un dashboard compartido o en una pantalla tipo "kiosco" sin sesión
    iniciada — el propio entity_picture de Home Assistant tiene el mismo
    tratamiento para otros tipos de entidad. Lo que impide que esto se
    use como proxy abierto hacia cualquier otra URL es el filtro de
    is_allowed_image_url (HTTPS + dominio de la DGT), no la autenticación.
    """

    url = PICTOGRAM_PROXY_URL
    name = "api:dgt_traffic_cameras:pictogram"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        url = request.query.get("url")
        if not url:
            return web.Response(status=400, text="Falta el parámetro 'url'")

        hass: HomeAssistant = request.app["hass"]
        session = async_get_clientsession(hass)
        resultado = await async_fetch_pictogram(session, url)
        if resultado is None:
            return web.Response(status=502, text="No se pudo obtener el pictograma")

        contenido, content_type = resultado
        return web.Response(body=contenido, content_type=content_type)
