"""Integración 'Cámaras de tráfico DGT' para Home Assistant.

Descarga el inventario público de cámaras de tráfico de la Dirección
General de Tráfico (nap.dgt.es, formato DATEX II) y permite elegir, con un
selector guiado (provincia -> carretera -> cámaras), cuáles añadir como
entidades camera.* en Home Assistant.

Limitaciones conocidas:
- No incluye cámaras de País Vasco ni Cataluña (fuera del feed de la DGT).
- Las imágenes son instantáneas fijas, no vídeo en directo.
- Cada foto se renueva como mucho cada 10 minutos, para no saturar a la DGT.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import clear_inventory_cache
from .const import CONF_CAMERAS, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["camera"]

# Clave interna donde guardamos, por cada entrada, la "huella" de las cámaras
# que estaban configuradas la última vez que se cargó.
_HUELLAS = "huellas_camaras"


def _huella_camaras(entry: ConfigEntry) -> tuple[str, ...]:
    """Resume la configuración actual como una lista ordenada de IDs.

    Sirve para responder a una única pregunta: ¿han cambiado de verdad las
    cámaras configuradas, o nos están avisando de un cambio que no afecta a
    las entidades?
    """
    camaras = entry.data.get(CONF_CAMERAS, [])
    return tuple(sorted(c.get("device_id", "") for c in camaras))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una entrada ya creada (reenvía a la plataforma camera)."""
    # Anotamos con qué cámaras arrancamos, para que el listener de cambios
    # pueda comparar después.
    hass.data.setdefault(DOMAIN, {}).setdefault(_HUELLAS, {})[entry.entry_id] = (
        _huella_camaras(entry)
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada (elimina sus entidades camera.*)."""
    descargada = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if descargada:
        huellas = hass.data.get(DOMAIN, {}).get(_HUELLAS, {})
        huellas.pop(entry.entry_id, None)

        # Si ya no queda ninguna entrada de esta integración, soltamos el
        # inventario guardado en memoria (son varios MB) en lugar de
        # dejarlo ocupando sitio para siempre.
        if not huellas:
            clear_inventory_cache()
            hass.data.pop(DOMAIN, None)

    return descargada


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada solo si las cámaras configuradas han cambiado.

    POR QUÉ NO RECARGAMOS SIEMPRE: al añadir cámaras desde el diálogo de
    opciones, Home Assistant nos avisa DOS veces seguidas (una al guardar
    los datos y otra al cerrar el diálogo). Recargar en ambas supone dos
    rondas completas de descarga de imágenes para nada.

    POR QUÉ COMPARAMOS UNA "HUELLA" Y NO LAS ENTIDADES EXISTENTES: contar
    las entidades ya creadas no vale, porque la recarga tarda un momento en
    completarse y el segundo aviso puede llegar mientras aún está a medias,
    viendo un recuento antiguo y recargando otra vez. La huella se calcula
    directamente de la configuración guardada, así que no depende de si la
    recarga anterior ha terminado o no.
    """
    huellas = hass.data.setdefault(DOMAIN, {}).setdefault(_HUELLAS, {})
    anterior = huellas.get(entry.entry_id)
    actual = _huella_camaras(entry)

    if anterior == actual:
        _LOGGER.debug(
            "'%s': la lista de cámaras no ha cambiado; se omite la recarga",
            entry.title,
        )
        return

    _LOGGER.debug(
        "'%s': la lista de cámaras ha cambiado (%d -> %d); recargando",
        entry.title,
        len(anterior) if anterior else 0,
        len(actual),
    )
    huellas[entry.entry_id] = actual
    await hass.config_entries.async_reload(entry.entry_id)
