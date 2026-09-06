"""Integración 'Cámaras de tráfico DGT' para Home Assistant.

Descarga datos públicos de la Dirección General de Tráfico (nap.dgt.es,
formato DATEX II) y permite elegir, con un selector guiado (provincia ->
carretera -> selección), qué dispositivos añadir a Home Assistant:

  - Cámaras de tráfico, como entidades camera.*.
  - Paneles de mensaje variable (PMV), como entidades sensor.*.

Limitaciones conocidas:
- Ninguno de los dos feeds incluye País Vasco ni Cataluña (fuera del ámbito
  de la DGT).
- Las cámaras son instantáneas fijas, no vídeo en directo, y se renuevan
  como mucho cada 10 minutos para no saturar a la DGT.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import coordinator as vms_coordinator
from .api import clear_inventory_cache, clear_vms_locations_cache
from .const import (
    CONF_CAMERAS,
    CONF_DEVICE_TYPE,
    CONF_PANELS,
    CONF_SHOW_ON_MAP,
    DEVICE_TYPE_VMS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Clave interna donde guardamos, por cada entrada, la "huella" de su
# configuración la última vez que se cargó (qué dispositivos tiene y, desde
# la Fase 3, si el interruptor de mapa está activado).
_HUELLAS = "huellas_entradas"


def _platforms_for_entry(entry: ConfigEntry) -> list[str]:
    """Qué plataformas reenviar según el tipo de la entrada.

    Una entrada creada por una versión anterior (solo había cámaras) no
    tiene CONF_DEVICE_TYPE guardado; se sigue tratando como cámara.
    """
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS:
        return ["sensor"]
    return ["camera"]


def _huella_entry(entry: ConfigEntry) -> tuple[str, ...]:
    """Resume la configuración actual como una tupla ordenada.

    Sirve para responder a una única pregunta: ¿ha cambiado de verdad algo
    que afecte a las entidades (la lista de dispositivos, o el interruptor
    de mapa), o nos están avisando de un cambio que no importa?
    """
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS:
        dispositivos = entry.data.get(CONF_PANELS, [])
    else:
        dispositivos = entry.data.get(CONF_CAMERAS, [])

    ids = tuple(sorted(d.get("device_id", "") for d in dispositivos))
    # El interruptor de mapa (Fase 3) se añade aquí desde ya: así, cuando
    # exista, activarlo/desactivarlo disparará una recarga sin tener que
    # tocar de nuevo esta función.
    mostrar_en_mapa = bool(entry.options.get(CONF_SHOW_ON_MAP, False))
    return ids + (f"show_on_map={mostrar_en_mapa}",)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una entrada ya creada."""
    hass.data.setdefault(DOMAIN, {}).setdefault(_HUELLAS, {})[entry.entry_id] = (
        _huella_entry(entry)
    )

    es_panel = entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS
    if es_panel:
        # El coordinador es compartido por todas las entradas de paneles:
        # una sola descarga de ~4 MB sirve para todas, en vez de una por
        # entrada. async_get_or_create ya se encarga de hacer el primer
        # refresco (solo la primera vez de verdad; ver coordinator.py) ANTES
        # de devolver el coordinador: hacerlo dentro de la propia plataforma
        # sensor lanzaría un ConfigEntryError ("raised in forwarded
        # platform") en Home Assistant.
        coordinator = await vms_coordinator.async_get_or_create(hass, entry.entry_id)
        hass.data[DOMAIN].setdefault("vms_coordinator_by_entry", {})[entry.entry_id] = (
            coordinator
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada (elimina sus entidades)."""
    descargada = await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )

    if descargada:
        domain_data = hass.data.get(DOMAIN, {})
        huellas = domain_data.get(_HUELLAS, {})
        huellas.pop(entry.entry_id, None)

        if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS:
            domain_data.get("vms_coordinator_by_entry", {}).pop(entry.entry_id, None)
            await vms_coordinator.async_release(hass, entry.entry_id)

        # Si ya no queda ninguna entrada de esta integración, soltamos los
        # datos guardados en memoria (varios MB) en lugar de dejarlos
        # ocupando sitio para siempre.
        if not huellas:
            clear_inventory_cache()
            clear_vms_locations_cache()
            hass.data.pop(DOMAIN, None)

    return descargada


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada solo si su configuración ha cambiado de verdad.

    POR QUÉ NO RECARGAMOS SIEMPRE: al añadir dispositivos desde el diálogo
    de opciones, Home Assistant nos avisa DOS veces seguidas (una al
    guardar los datos y otra al cerrar el diálogo). Recargar en ambas
    supone dos rondas completas de descarga para nada.

    POR QUÉ COMPARAMOS UNA "HUELLA" Y NO LAS ENTIDADES EXISTENTES: contar
    las entidades ya creadas no vale, porque la recarga tarda un momento en
    completarse y el segundo aviso puede llegar mientras aún está a medias,
    viendo un recuento antiguo y recargando otra vez. La huella se calcula
    directamente de la configuración guardada, así que no depende de si la
    recarga anterior ha terminado o no.
    """
    huellas = hass.data.setdefault(DOMAIN, {}).setdefault(_HUELLAS, {})
    anterior = huellas.get(entry.entry_id)
    actual = _huella_entry(entry)

    if anterior == actual:
        _LOGGER.debug(
            "'%s': la configuración no ha cambiado; se omite la recarga",
            entry.title,
        )
        return

    _LOGGER.debug(
        "'%s': la configuración ha cambiado; recargando",
        entry.title,
    )
    huellas[entry.entry_id] = actual
    await hass.config_entries.async_reload(entry.entry_id)
