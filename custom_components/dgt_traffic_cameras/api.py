"""Acceso a los datos públicos de la DGT.

Responsabilidades de este módulo:
  - descargar el inventario XML de cámaras (con límite de tamaño y caché),
  - descargar la ubicación de los paneles de mensaje variable (PMV),
  - convertir esos XML en objetos Python manejables,
  - validar que las URLs de imagen apuntan de verdad a la DGT.

Cámaras y paneles comparten el mismo esquema DevicePublication de la DGT
para su UBICACIÓN (carretera, provincia, punto kilométrico, coordenadas...);
solo difieren en typeOfDevice y en que las cámaras además traen una URL de
imagen. Por eso DgtCamera y DgtPanelLocation comparten la clase base
DgtLocatedDevice, y ambos parseos comparten _parse_located_device_fields.

Los MENSAJES de los paneles (qué muestra cada uno ahora mismo) son un feed
totalmente distinto, con su propio esquema; ver vms_messages.py.
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
    MAX_VMS_LOCATIONS_BYTES,
    VMS_LOCATIONS_CACHE_SECONDS,
    VMS_LOCATIONS_URL,
    XML_NAMESPACES,
)

_LOGGER = logging.getLogger(__name__)


class InventoryTooLargeError(Exception):
    """El XML descargado supera el tamaño máximo permitido."""


@dataclass
class DgtLocatedDevice:
    """Campos de ubicación comunes a cualquier dispositivo de la DGT.

    Cámaras y paneles se describen, en el feed de ubicaciones, con
    exactamente esta misma información; solo cambia qué más añade cada uno
    (la cámara, una URL de imagen) y qué se hace con ellos después.
    """

    device_id: str
    road_name: str | None  # p.ej. "A-62"
    road_destination: str | None  # p.ej. "BURGOS" (hacia dónde apunta)
    province: str | None  # p.ej. "PALENCIA"
    kilometer_point: str | None  # p.ej. "25.3"
    direction: str | None  # "positive" / "negative" / "unknown"
    latitude: float | None
    longitude: float | None

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
        base = " ".join(parts) if parts else f"Dispositivo {self.device_id}"
        if self.road_destination:
            base += f" (sent. {self.road_destination})"
        return base


@dataclass
class DgtCamera(DgtLocatedDevice):
    """Representa una cámara tal y como la describe el feed de la DGT."""

    image_url: str = ""


@dataclass
class DgtPanelLocation(DgtLocatedDevice):
    """Representa la ubicación de un panel de mensaje variable (PMV).

    Solo la ubicación: qué está mostrando el panel ahora mismo viene de un
    feed totalmente distinto (ver vms_messages.py), enlazado por device_id.
    """


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


async def async_download_xml(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    max_bytes: int,
) -> bytes:
    """Descarga un XML respetando un límite de tamaño.

    Genérica a propósito: la usan el inventario de cámaras, las ubicaciones
    de paneles y los mensajes de paneles, que solo difieren en la URL, las
    cabeceras y los límites a aplicar.
    """
    async with asyncio.timeout(timeout_seconds):
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()

            # Si el servidor nos anuncia de antemano un tamaño desmesurado,
            # cortamos antes de descargar nada.
            declarado = response.content_length
            if declarado is not None and declarado > max_bytes:
                raise InventoryTooLargeError(
                    f"{url} declara {declarado} bytes, "
                    f"por encima del límite de {max_bytes}"
                )

            # Leemos por trozos para poder abortar a mitad si el servidor
            # miente sobre el tamaño (o no lo declara).
            trozos: list[bytes] = []
            total = 0
            async for trozo in response.content.iter_chunked(64 * 1024):
                total += len(trozo)
                if total > max_bytes:
                    raise InventoryTooLargeError(
                        f"{url} superó el límite de {max_bytes} bytes"
                    )
                trozos.append(trozo)

            return b"".join(trozos)


async def _async_download_inventory(session: aiohttp.ClientSession) -> bytes:
    """Descarga el XML del inventario de cámaras."""
    return await async_download_xml(
        session,
        CAMERA_INVENTORY_URL,
        headers=INVENTORY_HEADERS,
        timeout_seconds=INVENTORY_TIMEOUT_SECONDS,
        max_bytes=MAX_INVENTORY_BYTES,
    )


def _parse_located_device_fields(
    device: ET.Element, ns: dict[str, str]
) -> dict[str, str | float | None]:
    """Extrae los campos de ubicación comunes a cámaras y paneles.

    Ambos comparten exactamente esta parte del esquema DevicePublication de
    la DGT (carretera, provincia, punto kilométrico, sentido, coordenadas);
    lo único que cambia entre uno y otro es qué se hace con este dict
    después (una cámara añade su URL de imagen, un panel no añade nada más).
    """
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

    return {
        "road_name": road_name,
        "road_destination": road_destination,
        "province": province,
        "kilometer_point": km_point,
        "direction": direction,
        "latitude": latitude,
        "longitude": longitude,
    }


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

        campos = _parse_located_device_fields(device, ns)
        cameras.append(DgtCamera(device_id=device_id, image_url=image_url, **campos))

    if descartadas_por_url:
        _LOGGER.warning(
            "Inventario DGT: %d cámaras descartadas por tener una URL de "
            "imagen no válida o fuera de los dominios permitidos",
            descartadas_por_url,
        )

    _LOGGER.debug("Inventario DGT: %d cámaras parseadas", len(cameras))
    return cameras


# --- Caché de las ubicaciones de paneles (PMV) ------------------------------
#
# Igual que el inventario de cámaras, pero con su propia caché en memoria
# (variables separadas) y un TTL mucho más largo (~1 día en vez de 15
# minutos), porque la ubicación física de un panel casi nunca cambia.
_vms_locations_cache: list[DgtPanelLocation] | None = None
_vms_locations_cached_at: float = 0.0
_vms_locations_lock = asyncio.Lock()


def clear_vms_locations_cache() -> None:
    """Vacía las ubicaciones de paneles guardadas en memoria."""
    global _vms_locations_cache, _vms_locations_cached_at
    _vms_locations_cache = None
    _vms_locations_cached_at = 0.0
    _LOGGER.debug("Caché de ubicaciones de paneles DGT vaciada")


async def async_fetch_vms_locations(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    force_refresh: bool = False,
) -> list[DgtPanelLocation]:
    """Devuelve la ubicación de los paneles, descargándola solo si hace falta."""
    global _vms_locations_cache, _vms_locations_cached_at

    async with _vms_locations_lock:
        ahora = time.monotonic()
        cache_valido = (
            _vms_locations_cache is not None
            and (ahora - _vms_locations_cached_at) < VMS_LOCATIONS_CACHE_SECONDS
        )
        if cache_valido and not force_refresh:
            _LOGGER.debug(
                "Ubicaciones de paneles servidas desde caché (%d paneles)",
                len(_vms_locations_cache),
            )
            return _vms_locations_cache

        xml_bytes = await async_download_xml(
            session,
            VMS_LOCATIONS_URL,
            headers=INVENTORY_HEADERS,
            timeout_seconds=INVENTORY_TIMEOUT_SECONDS,
            max_bytes=MAX_VMS_LOCATIONS_BYTES,
        )

        panels = await hass.async_add_executor_job(_parse_vms_locations, xml_bytes)

        _vms_locations_cache = panels
        _vms_locations_cached_at = ahora
        return panels


def _parse_vms_locations(xml_bytes: bytes) -> list[DgtPanelLocation]:
    """Convierte el XML de ubicaciones de paneles en una lista de DgtPanelLocation.

    NOTA: síncrona a propósito, pensada para ejecutarse en un hilo aparte
    (ver async_fetch_vms_locations).
    """
    root = ET.fromstring(xml_bytes)
    ns = XML_NAMESPACES

    panels: list[DgtPanelLocation] = []

    for device in root.iter(f"{{{ns['ns2']}}}device"):
        device_id = device.get("id")
        if not device_id:
            continue

        # El fichero real solo trae paneles (comprobado: 2517/2517 con
        # typeOfDevice=vms), pero se filtra igualmente por si algún día
        # mezclara otros tipos de dispositivo.
        tipo_el = device.find(f"{{{ns['ns2']}}}typeOfDevice")
        if tipo_el is None or (tipo_el.text or "").strip() != "vms":
            continue

        campos = _parse_located_device_fields(device, ns)
        panels.append(DgtPanelLocation(device_id=device_id, **campos))

    _LOGGER.debug("Ubicaciones de paneles DGT: %d paneles parseados", len(panels))
    return panels


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
