"""Coordinador único para los mensajes de los paneles de tráfico (PMV).

A diferencia de las cámaras (una petición HTTP por cámara), un solo fichero
de ~4 MB trae el mensaje de TODOS los paneles de España a la vez. Por eso
aquí no hay "una entidad, una descarga": hay una única descarga compartida
por todas las entidades sensor.*, sea cual sea el número de paneles
configurados o de entradas de configuración de tipo panel que existan.

La instancia se guarda en hass.data[DOMAIN] y se comparte entre entradas
mediante un recuento de referencias (ver async_get_or_create / async_release
en __init__.py), igual que ya se hace con la caché del inventario de cámaras
en api.py.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InventoryTooLargeError, async_download_xml
from .const import (
    DOMAIN,
    INVENTORY_HEADERS,
    INVENTORY_TIMEOUT_SECONDS,
    MAX_VMS_MESSAGES_BYTES,
    VMS_MESSAGES_UPDATE_INTERVAL_SECONDS,
    VMS_MESSAGES_URL,
)
from .vms_messages import PanelMessageState, parse_vms_messages

_LOGGER = logging.getLogger(__name__)

# Claves dentro de hass.data[DOMAIN] para el coordinador único y el
# recuento de qué entradas de configuración lo están usando.
_DATA_COORDINATOR = "vms_coordinator"
_DATA_COORDINATOR_ENTRIES = "vms_coordinator_entries"


class DgtVmsMessagesCoordinator(DataUpdateCoordinator[dict[str, PanelMessageState]]):
    """Descarga y parsea el fichero de mensajes de paneles cada 5 minutos."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Mensajes de paneles DGT",
            update_interval=timedelta(seconds=VMS_MESSAGES_UPDATE_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict[str, PanelMessageState]:
        session = async_get_clientsession(self.hass)
        try:
            xml_bytes = await async_download_xml(
                session,
                VMS_MESSAGES_URL,
                headers=INVENTORY_HEADERS,
                timeout_seconds=INVENTORY_TIMEOUT_SECONDS,
                max_bytes=MAX_VMS_MESSAGES_BYTES,
            )
        except (InventoryTooLargeError, TimeoutError) as err:
            raise UpdateFailed(f"No se pudo descargar el fichero de mensajes: {err}") from err
        except Exception as err:  # noqa: BLE001 - cualquier fallo de red cuenta como error del coordinador
            raise UpdateFailed(f"No se pudo descargar el fichero de mensajes: {err}") from err

        # El parseo es síncrono y con ~4 MB puede tardar; se ejecuta en un
        # hilo aparte para no congelar Home Assistant (mismo motivo que el
        # inventario de cámaras y las ubicaciones de paneles).
        try:
            return await self.hass.async_add_executor_job(parse_vms_messages, xml_bytes)
        except Exception as err:  # noqa: BLE001 - XML corrupto, formato inesperado...
            raise UpdateFailed(f"No se pudo interpretar el fichero de mensajes: {err}") from err


async def async_get_or_create(hass: HomeAssistant, entry_id: str) -> DgtVmsMessagesCoordinator:
    """Devuelve el coordinador único, creándolo si es la primera entrada de paneles.

    Se lleva un recuento de qué entry_id lo están usando (async_release lo
    quita) para saber cuándo ya no lo necesita nadie y se puede liberar.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    entries: set[str] = domain_data.setdefault(_DATA_COORDINATOR_ENTRIES, set())
    entries.add(entry_id)

    coordinator: DgtVmsMessagesCoordinator | None = domain_data.get(_DATA_COORDINATOR)
    if coordinator is None:
        coordinator = DgtVmsMessagesCoordinator(hass)
        domain_data[_DATA_COORDINATOR] = coordinator

    return coordinator


async def async_release(hass: HomeAssistant, entry_id: str) -> None:
    """Marca que una entrada de paneles ya no usa el coordinador.

    Cuando ya no queda ninguna, lo libera de hass.data para no dejar la
    descarga periódica corriendo (ni los ~4 MB del último resultado en
    memoria) sin que ningún panel configurado la necesite.
    """
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return

    entries: set[str] | None = domain_data.get(_DATA_COORDINATOR_ENTRIES)
    if entries is not None:
        entries.discard(entry_id)
        if entries:
            return
        domain_data.pop(_DATA_COORDINATOR_ENTRIES, None)

    coordinator = domain_data.pop(_DATA_COORDINATOR, None)
    if coordinator is not None:
        # async_shutdown existe desde HA 2024.x; si no estuviera disponible
        # en una instalación muy antigua, basta con soltar la referencia:
        # sin nadie apuntando a él, deja de recibir updates y lo recoge el
        # recolector de basura.
        shutdown = getattr(coordinator, "async_shutdown", None)
        if shutdown is not None:
            await shutdown()
        _LOGGER.debug("Coordinador de mensajes de paneles liberado")
