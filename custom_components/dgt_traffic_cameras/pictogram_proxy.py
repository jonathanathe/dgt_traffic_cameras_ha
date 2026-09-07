"""Proxy de las imágenes de pictogramas de los paneles de la DGT.

I-06: sin este proxy, el navegador de quien viera un panel (la tarjeta
Lovelace o el entity_picture del propio sensor) contactaba directamente con
etraffic.dgt.es para cada pictograma, dejando la IP de ese visitante en los
registros de la DGT. Con este proxy, es Home Assistant quien hace esa
petición; el navegador solo habla con la propia instancia de Home Assistant.

Las dos imágenes FIJAS de la tarjeta (icono de cabecera y fondo del cartel)
se resolvieron aparte, empaquetándolas dentro de www/ (no cambian nunca, a
diferencia de los pictogramas: son cientos de códigos distintos cuya URL
exacta viene en el feed de cada panel, así que no se pueden empaquetar de
antemano).

Este módulo es la lógica pura (descarga + caché en memoria), sin nada de
aiohttp.web: la vista HTTP que la expone vive en http_views.py.
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from .api import is_allowed_image_url

_LOGGER = logging.getLogger(__name__)

# Un pictograma no cambia una vez publicado; una hora de caché en memoria
# de sobra evita redescargarlo en cada refresco del dashboard.
PICTOGRAM_CACHE_SECONDS = 3600
# Generoso para un icono de aviso de tráfico; protege contra un feed que
# apuntara (por error o manipulación) a algo desproporcionadamente grande.
MAX_PICTOGRAM_BYTES = 512 * 1024
PICTOGRAM_FETCH_TIMEOUT_SECONDS = 10

# url -> (contenido, content_type, cuándo se guardó en caché)
_cache: dict[str, tuple[bytes, str, float]] = {}


async def async_fetch_pictogram(
    session: aiohttp.ClientSession, url: str
) -> tuple[bytes, str] | None:
    """Descarga (o sirve de caché) el pictograma en `url`.

    None si la URL no está permitida (mismo filtro que el resto de la
    integración: HTTPS + dominio de la DGT) o si la descarga falla; nunca
    lanza una excepción de red, porque quien llama (la vista HTTP) solo
    necesita saber si hay imagen que servir o no.
    """
    if not is_allowed_image_url(url):
        _LOGGER.warning("Proxy de pictogramas: URL no permitida, descartada: %s", url)
        return None

    cacheado = _cache.get(url)
    if cacheado is not None:
        contenido, content_type, guardado_en = cacheado
        if (time.monotonic() - guardado_en) < PICTOGRAM_CACHE_SECONDS:
            return contenido, content_type

    try:
        async with asyncio.timeout(PICTOGRAM_FETCH_TIMEOUT_SECONDS):
            async with session.get(url) as response:
                response.raise_for_status()
                content_type = response.content_type or "image/png"

                trozos: list[bytes] = []
                total = 0
                async for trozo in response.content.iter_chunked(64 * 1024):
                    total += len(trozo)
                    if total > MAX_PICTOGRAM_BYTES:
                        _LOGGER.warning(
                            "Proxy de pictogramas: %s superó el límite de %d bytes",
                            url,
                            MAX_PICTOGRAM_BYTES,
                        )
                        return None
                    trozos.append(trozo)
                contenido = b"".join(trozos)
    except Exception:  # noqa: BLE001 - cualquier fallo de red cuenta como "no se pudo"
        _LOGGER.debug("Proxy de pictogramas: fallo al descargar %s", url, exc_info=True)
        return None

    _cache[url] = (contenido, content_type, time.monotonic())
    return contenido, content_type


def clear_pictogram_cache() -> None:
    """Vacía la caché en memoria (se llama al borrar la última entrada)."""
    global _cache
    _cache = {}
