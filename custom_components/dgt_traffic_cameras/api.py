"""Acceso a los datos públicos de la DGT.

Responsabilidades de este módulo:
  - descargar el inventario XML de cámaras (con límite de tamaño y caché),
  - convertir ese XML en objetos Python manejables,
  - validar que las URLs de imagen apuntan de verdad a la DGT.
"""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from homeassistant.core import HomeAssistant

from .const import (
    ALLOWED_IMAGE_DOMAINS,
    CAMERA_INVENTORY_URL,
    INVENTORY_CACHE_SECONDS,
    INVENTORY_HEADERS,
    INVENTORY_TIMEOUT_SECONDS,
    MAX_INVENTORY_BYTES,
    XML_NAMESPACES,
)

_LOGGER = logging.getLogger(__name__)


class InventoryTooLargeError(Exception):
    """El XML descargado supera el tamaño máximo permitido."""


@dataclass
class DgtCamera:
    """Representa una cámara tal y como la describe el feed de la DGT."""

    device_id: str
    road_name: str | None  # p.ej. "A-62"
    road_destination: str | None  # p.ej. "BURGOS" (hacia dónde apunta)
    province: str | None  # p.ej. "PALENCIA"
    kilometer_point: str | None  # p.ej. "25.3"
    direction: str | None  # "positive" / "negative" / "unknown"
    latitude: float | None
    longitude: float | None
    image_url: str

    @property
    def display_name(self) -> str:
        """Nombre legible para el selector y para la entidad."""
        parts = [
            p
            for p in (
                self.road_name,
                self.kilometer_point and f"km {self.kilometer_point}",
            )
            if p
        ]
        base = " ".join(parts) if parts else f"Cámara {self.device_id}"
        if self.road_destination:
            base += f" (sent. {self.road_destination})"
        return base


def is_allowed_image_url(url: str) -> bool:
    """Comprueba que una URL de imagen es HTTPS y de un dominio de la DGT.

    Se usa en dos momentos: al parsear el inventario (para descartar
    entradas raras) y antes de cada descarga (por si una configuración
    guardada hace tiempo contuviera algo que ya no aceptamos).

    Sin esta comprobación, una URL manipulada en el feed podría hacer que
    tu Home Assistant lanzara peticiones contra equipos de tu red interna.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    # Aceptamos el dominio exacto o cualquier subdominio suyo. La
    # comprobación con "." delante evita que un dominio malicioso como
    # "dgt.es.atacante.com" o "notdgt.es" cuele.
    return any(
        host == dominio or host.endswith(f".{dominio}")
        for dominio in ALLOWED_IMAGE_DOMAINS
    )


# --- Caché del inventario --------------------------------------------------
#
# El inventario completo pesa varios MB. Antes se re-descargaba entero cada
# vez que abrías el diálogo de configuración o el de opciones. Ahora se
# guarda en memoria y se reutiliza durante INVENTORY_CACHE_SECONDS.
_inventory_cache: list[DgtCamera] | None = None
_inventory_cached_at: float = 0.0
_inventory_lock = asyncio.Lock()


def clear_inventory_cache() -> None:
    """Vacía el inventario guardado en memoria.

    Se llama cuando se desinstala la última entrada de la integración, para
    no dejar varios MB de datos retenidos en la memoria de Home Assistant
    cuando ya no hacen falta.
    """
    global _inventory_cache, _inventory_cached_at
    _inventory_cache = None
    _inventory_cached_at = 0.0
    _LOGGER.debug("Caché del inventario DGT vaciada")


async def async_fetch_camera_inventory(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    force_refresh: bool = False,
) -> list[DgtCamera]:
    """Devuelve el inventario de cámaras, descargándolo solo si hace falta.

    Lanza aiohttp.ClientError, TimeoutError, InventoryTooLargeError o
    ET.ParseError si algo va mal; quien llame debe capturarlo y mostrar un
    error legible al usuario.
    """
    global _inventory_cache, _inventory_cached_at

    # El lock evita que, si dos diálogos se abren casi a la vez, se lancen
    # dos descargas del mismo fichero de varios MB en paralelo.
    async with _inventory_lock:
        ahora = time.monotonic()
        cache_valido = (
            _inventory_cache is not None
            and (ahora - _inventory_cached_at) < INVENTORY_CACHE_SECONDS
        )
        if cache_valido and not force_refresh:
            _LOGGER.debug(
                "Inventario DGT servido desde caché (%d cámaras)",
                len(_inventory_cache),
            )
            return _inventory_cache

        xml_bytes = await _async_download_inventory(session)

        # El parseo del XML es síncrono y con varios MB puede tardar cientos
        # de milisegundos. Si se ejecutara aquí directamente, Home Assistant
        # ENTERO se quedaría congelado durante ese rato (luces que no
        # responden, automatizaciones paradas...). Por eso lo lanzamos en un
        # hilo aparte con async_add_executor_job.
        cameras = await hass.async_add_executor_job(
            _parse_camera_inventory, xml_bytes
        )

        _inventory_cache = cameras
        _inventory_cached_at = ahora
        return cameras


async def _async_download_inventory(session: aiohttp.ClientSession) -> bytes:
    """Descarga el XML del inventario respetando un límite de tamaño."""
    async with asyncio.timeout(INVENTORY_TIMEOUT_SECONDS):
        async with session.get(
            CAMERA_INVENTORY_URL, headers=INVENTORY_HEADERS
        ) as response:
            response.raise_for_status()

            # Si el servidor nos anuncia de antemano un tamaño desmesurado,
            # cortamos antes de descargar nada.
            declarado = response.content_length
            if declarado is not None and declarado > MAX_INVENTORY_BYTES:
                raise InventoryTooLargeError(
                    f"El inventario declara {declarado} bytes, "
                    f"por encima del límite de {MAX_INVENTORY_BYTES}"
                )

            # Leemos por trozos para poder abortar a mitad si el servidor
            # miente sobre el tamaño (o no lo declara).
            trozos: list[bytes] = []
            total = 0
            async for trozo in response.content.iter_chunked(64 * 1024):
                total += len(trozo)
                if total > MAX_INVENTORY_BYTES:
                    raise InventoryTooLargeError(
                        f"El inventario superó el límite de {MAX_INVENTORY_BYTES} bytes"
                    )
                trozos.append(trozo)

            return b"".join(trozos)


def _parse_camera_inventory(xml_bytes: bytes) -> list[DgtCamera]:
    """Convierte el XML DATEX II en una lista de objetos DgtCamera.

    NOTA: esta función es síncrona a propósito y está pensada para
    ejecutarse en un hilo aparte (ver async_fetch_camera_inventory).
    """
    root = ET.fromstring(xml_bytes)
    ns = XML_NAMESPACES

    cameras: list[DgtCamera] = []
    descartadas_por_url = 0

    for device in root.iter(f"{{{ns['ns2']}}}device"):
        device_id = device.get("id")
        if not device_id:
            continue

        image_url_el = device.find(f"{{{ns['fse']}}}deviceUrl")
        if image_url_el is None or not image_url_el.text:
            # Sin URL de imagen no podemos crear una cámara útil.
            continue

        image_url = image_url_el.text.strip()

        # Filtro de seguridad: descartamos cualquier URL que no sea HTTPS
        # y de un dominio de la DGT, para no acabar guardando y pidiendo
        # direcciones que no controlamos.
        if not is_allowed_image_url(image_url):
            descartadas_por_url += 1
            continue

        road_info = device.find(f".//{{{ns['loc']}}}roadInformation")
        road_name = _find_text(road_info, f"{{{ns['loc']}}}roadName")
        road_destination = _find_text(road_info, f"{{{ns['loc']}}}roadDestination")

        ext_point = device.find(f".//{{{ns['loc']}}}extendedTpegNonJunctionPoint")
        province = _find_text(ext_point, f"{{{ns['lse']}}}province")
        km_point = _find_text(ext_point, f"{{{ns['lse']}}}kilometerPoint")

        direction = _find_text(device, f".//{{{ns['lse']}}}tpegDirectionRoad")

        lat_el = device.find(f".//{{{ns['loc']}}}latitude")
        lon_el = device.find(f".//{{{ns['loc']}}}longitude")
        latitude = _safe_float(lat_el.text if lat_el is not None else None)
        longitude = _safe_float(lon_el.text if lon_el is not None else None)

        cameras.append(
            DgtCamera(
                device_id=device_id,
                road_name=road_name,
                road_destination=road_destination,
                province=province,
                kilometer_point=km_point,
                direction=direction,
                latitude=latitude,
                longitude=longitude,
                image_url=image_url,
            )
        )

    if descartadas_por_url:
        _LOGGER.warning(
            "Inventario DGT: %d cámaras descartadas por tener una URL de "
            "imagen no válida o fuera de los dominios permitidos",
            descartadas_por_url,
        )

    _LOGGER.debug("Inventario DGT: %d cámaras parseadas", len(cameras))
    return cameras


def _find_text(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
