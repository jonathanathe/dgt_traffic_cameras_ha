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
    CONF_SHOW_ON_MAP_DEFAULT,
    DEVICE_TYPE_VMS,
    DOMAIN,
)
from .http_views import DgtPictogramProxyView
from .pictogram_proxy import clear_pictogram_cache

_LOGGER = logging.getLogger(__name__)

# Clave interna donde guardamos, por cada entrada, la "huella" de su
# configuración la última vez que se cargó: qué dispositivos tiene, y el
# valor del interruptor de mapa (CONF_SHOW_ON_MAP) de CADA UNO.
_HUELLAS = "huellas_entradas"


def _platforms_for_entry(entry: ConfigEntry) -> list[str]:
    """Qué plataformas reenviar según el tipo de la entrada.

    Una entrada creada por una versión anterior (solo había cámaras) no
    tiene CONF_DEVICE_TYPE guardado; se sigue tratando como cámara.
    """
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS:
        return ["sensor"]
    return ["camera"]


def _huella_entry(entry: ConfigEntry) -> tuple[tuple[str, bool], ...]:
    """Resume la configuración actual como una tupla ordenada.

    Sirve para responder a una única pregunta: ¿ha cambiado de verdad algo
    que afecte a las entidades (la lista de dispositivos, o el interruptor
    de mapa), o nos están avisando de un cambio que no importa?
    """
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS:
        dispositivos = entry.data.get(CONF_PANELS, [])
    else:
        dispositivos = entry.data.get(CONF_CAMERAS, [])

    return tuple(
        sorted(
            (
                d.get("device_id", ""),
                bool(d.get(CONF_SHOW_ON_MAP, CONF_SHOW_ON_MAP_DEFAULT)),
            )
            for d in dispositivos
        )
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registra recursos a nivel de COMPONENTE, no de entrada concreta.

    Home Assistant llama a esto una sola vez por arranque, antes de
    configurar ninguna entrada — a diferencia de async_setup_entry, que se
    llama una vez por cada entrada (podría haber varias). El proxy de
    pictogramas (I-06) es una única ruta HTTP compartida por todas las
    entidades sensor.*, así que tiene que registrarse aquí y no allí: si
    se registrara en async_setup_entry, tener dos entradas de paneles
    intentaría registrar la misma ruta dos veces.
    """
    hass.http.register_view(DgtPictogramProxyView())
    return True


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
        hass.data[DOMAIN].setdefault(vms_coordinator.DATA_COORDINATOR_BY_ENTRY, {})[entry.entry_id] = (
            coordinator
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada (elimina sus entidades).

    OJO: esto se ejecuta también en cada RECARGA de la entrada (añadir o
    quitar un dispositivo, activar el interruptor de mapa...), no solo
    cuando el usuario la borra de verdad. Por eso aquí SOLO se hace la
    limpieza que es correcta repetir en cada recarga (la huella, que se
    vuelve a rellenar en el siguiente async_setup_entry). Lo que solo tiene
    sentido al borrar la entrada para siempre —soltar el coordinador de
    paneles y las cachés de inventario/ubicaciones— vive en
    async_remove_entry, que Home Assistant solo llama en un borrado real.
    """
    descargada = await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )

    if descargada:
        huellas = hass.data.get(DOMAIN, {}).get(_HUELLAS, {})
        huellas.pop(entry.entry_id, None)

    return descargada


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Se ejecuta solo cuando esta entrada se BORRA de verdad (nunca en una recarga).

    Antes, esta limpieza vivía en async_unload_entry, que también se
    ejecuta en cada recarga: si solo había una entrada, cada vez que se
    añadía o quitaba un dispositivo se destruían y volvían a descargar
    tanto el inventario de cámaras/ubicaciones de paneles (varios MB) como
    el coordinador compartido de mensajes de paneles, aunque la entrada
    siguiera existiendo un instante después.
    """
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_VMS:
        hass.data.get(DOMAIN, {}).get(vms_coordinator.DATA_COORDINATOR_BY_ENTRY, {}).pop(
            entry.entry_id, None
        )
        await vms_coordinator.async_release(hass, entry.entry_id)

    # Si ya no queda ninguna entrada de esta integración, soltamos los
    # datos guardados en memoria (varios MB) en lugar de dejarlos ocupando
    # sitio para siempre. async_unload_entry ya quitó la huella de esta
    # entrada antes de llegar aquí, así que "vacío" es fiable.
    huellas = hass.data.get(DOMAIN, {}).get(_HUELLAS, {})
    if not huellas:
        clear_inventory_cache()
        clear_vms_locations_cache()
        clear_pictogram_cache()
        hass.data.pop(DOMAIN, None)


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
