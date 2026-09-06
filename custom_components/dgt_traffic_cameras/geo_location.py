"""Plataforma 'geo_location': cámaras y paneles en el mapa de Home Assistant.

DISEÑO IMPORTANTE para evitar bugs de entidades huérfanas: esta plataforma
se reenvía SIEMPRE, tanto para entradas de cámaras como de paneles,
independientemente del valor del interruptor "Mostrar en el mapa"
(CONF_SHOW_ON_MAP, en entry.options). Es la propia plataforma la que
decide, YA AQUÍ DENTRO al arrancar, si crea entidades o no según ese valor.

POR QUÉ NO CONDICIONAR LA LISTA DE PLATAFORMAS REENVIADAS: si en vez de
esto la lista de plataformas dependiera de la opción, activarla o
desactivarla (que dispara una recarga con el valor ya actualizado) podría
dejar el registro de plataformas de Home Assistant inconsistente con lo
que realmente estaba cargado la vez anterior.

SOBRE LA ETIQUETA DEL PIN EN EL MAPA: Home Assistant, por defecto, pone en
cada pin las iniciales del nombre de la entidad (p.ej. "G9E"). Mostrar el
TEXTO del mensaje del panel ahí es una opción de la tarjeta de Mapa
("label_mode: attribute" señalando al atributo "mensaje" que se expone
aquí), no algo que esta integración pueda forzar en el panel de Mapa por
defecto del menú lateral. Ver el README para los pasos exactos.
"""

from __future__ import annotations

import logging

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.location import distance as calcular_distancia_metros

from .const import (
    CONF_CAMERAS,
    CONF_DEVICE_TYPE,
    CONF_PANELS,
    CONF_SHOW_ON_MAP,
    DEVICE_TYPE_VMS,
    DOMAIN,
)
from .coordinator import DgtVmsMessagesCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea los puntos del mapa, solo si el interruptor está activado."""
    if not entry.options.get(CONF_SHOW_ON_MAP, False):
        return

    es_panel = entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS
    dispositivos = entry.data.get(CONF_PANELS if es_panel else CONF_CAMERAS, [])

    home_lat = hass.config.latitude
    home_lon = hass.config.longitude

    coordinator: DgtVmsMessagesCoordinator | None = None
    if es_panel:
        coordinator = hass.data[DOMAIN]["vms_coordinator_by_entry"][entry.entry_id]

    vistas: set[str] = set()
    entities: list[GeolocationEvent] = []
    for data in dispositivos:
        device_id = data.get("device_id")
        if not device_id or device_id in vistas:
            continue
        if data.get("latitude") is None or data.get("longitude") is None:
            # Sin coordenadas no hay dónde ponerlo en el mapa.
            continue
        vistas.add(device_id)

        if es_panel:
            entities.append(
                DgtPanelGeolocationEvent(coordinator, entry, data, home_lat, home_lon)
            )
        else:
            entities.append(
                DgtCameraGeolocationEvent(entry, data, home_lat, home_lon)
            )

    async_add_entities(entities)


def _distancia_km(
    home_lat: float | None,
    home_lon: float | None,
    lat: float | None,
    lon: float | None,
) -> float | None:
    """Distancia en km desde la ubicación "Casa" de Home Assistant.

    homeassistant.util.location.distance() devuelve metros; el resto de
    plataformas geo_location de HA usan km como unidad habitual.
    """
    if lat is None or lon is None:
        return None
    metros = calcular_distancia_metros(home_lat, home_lon, lat, lon)
    return round(metros / 1000, 1) if metros is not None else None


class DgtCameraGeolocationEvent(GeolocationEvent):
    """Punto del mapa para una cámara: ubicación fija, sin datos en vivo."""

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:cctv"
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        data: dict,
        home_lat: float | None,
        home_lon: float | None,
    ) -> None:
        device_id = data["device_id"]
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_geo"
        self._attr_name = data.get("name") or f"Cámara DGT {device_id}"
        self._attr_latitude = data.get("latitude")
        self._attr_longitude = data.get("longitude")
        self._attr_distance = _distancia_km(
            home_lat, home_lon, self._attr_latitude, self._attr_longitude
        )
        self._attr_extra_state_attributes = {
            "carretera": data.get("road_name"),
            "sentido_hacia": data.get("road_destination"),
            "provincia": data.get("province"),
            "punto_kilometrico": data.get("kilometer_point"),
        }


class DgtPanelGeolocationEvent(
    CoordinatorEntity[DgtVmsMessagesCoordinator], GeolocationEvent
):
    """Punto del mapa para un panel: ubicación fija + mensaje en vivo.

    A diferencia de las cámaras, aquí sí interesa que la etiqueta del pin
    pueda mostrar algo que cambia (el mensaje actual), así que comparte el
    mismo DataUpdateCoordinator que sensor.py en vez de ser una entidad
    estática.
    """

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:message-text-outline"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DgtVmsMessagesCoordinator,
        entry: ConfigEntry,
        data: dict,
        home_lat: float | None,
        home_lon: float | None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = data["device_id"]
        self._panel_data = data
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}_geo"
        self._attr_name = data.get("name") or f"Panel DGT {self._device_id}"
        self._attr_latitude = data.get("latitude")
        self._attr_longitude = data.get("longitude")
        self._attr_distance = _distancia_km(
            home_lat, home_lon, self._attr_latitude, self._attr_longitude
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Incluye "mensaje": el atributo pensado para usar con label_mode:attribute.

        Ver README: en una tarjeta de Mapa, configurando esa entidad con
        label_mode "attribute" y attribute "mensaje", el pin muestra este
        texto en vez de las iniciales del nombre.
        """
        estado = self.coordinator.data.get(self._device_id) if self.coordinator.data else None
        mensaje = "Sin datos"
        apagado = None
        if estado is not None:
            apagado = estado.off
            mensaje = "Sin mensaje" if estado.off else (estado.text or "Sin datos")

        return {
            "carretera": self._panel_data.get("road_name"),
            "sentido_hacia": self._panel_data.get("road_destination"),
            "provincia": self._panel_data.get("province"),
            "punto_kilometrico": self._panel_data.get("kilometer_point"),
            "mensaje": mensaje,
            "apagado": apagado,
        }
