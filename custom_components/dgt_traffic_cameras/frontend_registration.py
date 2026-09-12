"""Registro del recurso frontend de la tarjeta de Lovelace (dgt-panel-card).

Sirve el .js y sus dos imágenes (custom_components/dgt_traffic_cameras/
frontend/) desde una ruta HTTP propia de la integración, en vez de exigir
copiarlos a mano a config/www/ (como hasta la versión 1.7.0). Esto SÍ es
seguro de automatizar del todo: registrar una ruta estática no toca ningún
almacenamiento de Home Assistant, solo sirve ficheros ya incluidos en el
propio paquete.

LO QUE NO SE AUTOMATIZA A PROPÓSITO: crear o actualizar el recurso de
Lovelace (Ajustes > Paneles de control > Recursos) que apunta a esa URL.
Existe un bug conocido y, a fecha de escribir esto, aún abierto en Home
Assistant (home-assistant/core#165767) por el que tocar la colección de
recursos de Lovelace ANTES de que esté cargada de disco puede BORRAR todos
los recursos existentes del usuario, no solo el nuestro. Para una
integración personal ese riesgo no compensa el ahorro de un paso manual:
en su lugar, se avisa una única vez mediante Reparaciones (Ajustes >
Sistema > Reparaciones) para que el propio usuario añada o actualice el
recurso a mano. cache_headers=False al registrar la ruta, para que un
cambio en el .js en una futura actualización no se quede cacheado en el
navegador (ya nos pasó una vez con la copia manual en www/).
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, FRONTEND_CARD_FILENAME, FRONTEND_DIR_NAME, FRONTEND_URL_BASE

# Id fijo del aviso de Reparaciones: con el mismo id en cada arranque, Home
# Assistant no lo duplica ni lo vuelve a mostrar como "nuevo" una vez que
# el usuario lo ha marcado como resuelto.
_ISSUE_RECURSO_LOVELACE = "recurso_lovelace_tarjeta_panel"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Sirve la tarjeta del panel y avisa (una vez) de cómo añadirla.

    Se llama desde async_setup (no async_setup_entry): es un recurso a
    nivel de integración, no de una entrada de configuración concreta.
    """
    carpeta_frontend = Path(__file__).parent / FRONTEND_DIR_NAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(carpeta_frontend), False)]
    )

    ir.async_create_issue(
        hass,
        DOMAIN,
        _ISSUE_RECURSO_LOVELACE,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=_ISSUE_RECURSO_LOVELACE,
        translation_placeholders={
            "url": f"{FRONTEND_URL_BASE}/{FRONTEND_CARD_FILENAME}",
        },
    )
