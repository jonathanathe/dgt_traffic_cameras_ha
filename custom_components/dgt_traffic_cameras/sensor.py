"""Plataforma 'sensor' de la integración: paneles de mensaje variable (PMV).

A diferencia de las cámaras (una entidad, su propia descarga y caché), aquí
todas las entidades comparten un único DataUpdateCoordinator (ver
coordinator.py): una sola descarga de ~4 MB cada 5 minutos sirve para todos
los paneles configurados, sea cual sea el número de entradas.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PANELS, DOMAIN
from .coordinator import DgtVmsMessagesCoordinator
from .vms_messages import PanelMessageState

_LOGGER = logging.getLogger(__name__)

_SIN_DATOS = "Sin datos"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea una entidad sensor por cada panel guardado en la ConfigEntry."""
    panels_data = entry.data.get(CONF_PANELS, [])

    # El coordinador ya se creó y refrescó en __init__.py, ANTES de
    # reenviar a esta plataforma (hacerlo aquí dentro lanzaría un
    # ConfigEntryError "raised in forwarded platform" en Home Assistant).
    coordinator: DgtVmsMessagesCoordinator = hass.data[DOMAIN][
        "vms_coordinator_by_entry"
    ][entry.entry_id]

    # Misma protección contra duplicados que ya tienen las cámaras.
    vistas: set[str] = set()
    entities: list[DgtPanelSensor] = []
    for panel_data in panels_data:
        device_id = panel_data.get("device_id")
        if not device_id or device_id in vistas:
            continue
        vistas.add(device_id)
        entities.append(DgtPanelSensor(coordinator, entry, panel_data))

    async_add_entities(entities)


class DgtPanelSensor(CoordinatorEntity[DgtVmsMessagesCoordinator], SensorEntity):
    """Un panel de mensaje variable concreto de la DGT."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:message-text-outline"

    def __init__(
        self,
        coordinator: DgtVmsMessagesCoordinator,
        entry: ConfigEntry,
        panel_data: dict,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._panel_data = panel_data
        self._device_id = panel_data["device_id"]

        # NOTA: igual que en camera.py, el unique_id incluye entry_id por
        # coherencia con el resto de la integración (y para poder tener el
        # mismo device_id en dos entradas de configuración distintas sin
        # que sus entidades choquen). No se cambia una vez creado: haría
        # que Home Assistant tratara la entidad como si fuera nueva.
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}"
        self._attr_name = panel_data.get("name") or f"Panel DGT {self._device_id}"

        self._static_attributes: dict = {
            "carretera": panel_data.get("road_name"),
            "sentido_hacia": panel_data.get("road_destination"),
            "provincia": panel_data.get("province"),
            "punto_kilometrico": panel_data.get("kilometer_point"),
        }
        if panel_data.get("latitude") is not None and panel_data.get("longitude") is not None:
            self._static_attributes["latitude"] = panel_data.get("latitude")
            self._static_attributes["longitude"] = panel_data.get("longitude")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Dirección General de Tráfico (DGT)",
            model="Panel de mensaje variable DATEX II",
            configuration_url="https://nap.dgt.es/dataset",
        )

    @property
    def _estado(self) -> PanelMessageState | None:
        """El estado de este panel en la última descarga, si venía en ella.

        No es un error que un panel no aparezca: no todos emiten siempre.
        Se distingue de "la descarga entera ha fallado" (available, que
        hereda de CoordinatorEntity y sí refleja fallos de red reales).
        """
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._device_id)

    @property
    def native_value(self) -> str:
        estado = self._estado
        if estado is None:
            return _SIN_DATOS
        if estado.off:
            return "Sin mensaje"
        return estado.text or _SIN_DATOS

    @property
    def extra_state_attributes(self) -> dict:
        estado = self._estado
        atributos = dict(self._static_attributes)

        if estado is None:
            atributos["texto_completo"] = None
            atributos["lineas"] = []
            atributos["otras_paginas"] = []
            atributos["pictogramas"] = []
            atributos["apagado"] = None
            atributos["ultimo_cambio"] = None
            return atributos

        atributos["texto_completo"] = estado.text_full
        atributos["lineas"] = estado.lines
        atributos["otras_paginas"] = estado.other_pages
        atributos["pictogramas"] = estado.pictogram_codes
        atributos["apagado"] = estado.off
        atributos["ultimo_cambio"] = estado.last_set
        return atributos
