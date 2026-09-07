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

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
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

# Evita que dos entradas de paneles configurándose casi a la vez (Home
# Assistant puede hacerlo concurrentemente) creen el coordinador o lancen
# su primer refresco dos veces en paralelo, duplicando la descarga de ~4 MB
# que este diseño existe precisamente para evitar. Es a nivel de módulo,
# igual que el lock del inventario de cámaras en api.py.
_coordinator_lock = asyncio.Lock()


class DgtVmsMessagesCoordinator(DataUpdateCoordinator[dict[str, PanelMessageState]]):
    """Descarga y parsea el fichero de mensajes de paneles cada 5 minutos."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            # config_entry=None A PROPÓSITO. Si no se pasa nada, Home
            # Assistant coge "la entrada que se esté configurando ahora
            # mismo" (vía ContextVar) y, lo importante, hace
            # entry.async_on_unload(self.async_shutdown): ata el APAGADO
            # del coordinador a ESA entrada concreta.
            #
            # Con un coordinador compartido por varias entradas, eso es un
            # bug real y ya confirmado: si esa primera entrada se recarga o
            # se borra, el coordinador se apaga (async_shutdown pone
            # _shutdown_requested=True) aunque otras entradas lo sigan
            # usando, y se queda muerto en hass.data sin que nada lo
            # detecte ni lo vuelva a levantar. Pasando None explícito, el
            # coordinador no depende del ciclo de vida de ninguna entrada
            # en particular; su vida la controlamos nosotros a mano en
            # async_get_or_create/async_release.
            config_entry=None,
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
    quita) para saber cuándo ya no lo necesita nadie y se puede liberar. El
    entry_id solo se añade a ese recuento si esta llamada consigue datos de
    verdad (aquí o de una llamada anterior); así una entrada que nunca llega
    a arrancar no se queda "usando" el coordinador para siempre.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    entries: set[str] = domain_data.setdefault(_DATA_COORDINATOR_ENTRIES, set())

    # Home Assistant puede configurar varias entradas de paneles a la vez
    # (concurrentemente, no en paralelo real, pero sí entrelazadas en el
    # bucle de eventos). Sin este lock, dos entradas podrían ver
    # "coordinador == None" o "coordinador.data == None" a la vez y lanzar
    # dos descargas simultáneas del mismo fichero de ~4 MB.
    async with _coordinator_lock:
        coordinator: DgtVmsMessagesCoordinator | None = domain_data.get(_DATA_COORDINATOR)
        if coordinator is None:
            coordinator = DgtVmsMessagesCoordinator(hass)
            domain_data[_DATA_COORDINATOR] = coordinator

        if coordinator.data is None:
            # Cubre dos casos con el mismo código: el coordinador se acaba
            # de crear (primera entrada de paneles de verdad), o ya existía
            # pero una descarga anterior falló y nunca llegó a tener datos.
            # En ambos, un simple async_refresh() basta: no depende de
            # ninguna ConfigEntry ni de su estado (a diferencia de
            # async_config_entry_first_refresh(), que ya no se puede usar
            # aquí ahora que el coordinador se crea con config_entry=None).
            await coordinator.async_refresh()

            if coordinator.data is None:
                # La descarga ha fallado de verdad. Igual que hacía
                # async_config_entry_first_refresh() antes, se hace fallar
                # el setup de esta entrada (Home Assistant reintentará solo
                # más adelante) en vez de dejarla "cargada" sin ningún dato.
                raise ConfigEntryNotReady(
                    "No se pudieron descargar los mensajes de los paneles de la DGT"
                )

        entries.add(entry_id)
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
