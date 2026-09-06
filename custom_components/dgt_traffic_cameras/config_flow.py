"""Config flow de 'Cámaras de tráfico DGT'.

Con ~1420 cámaras en el feed nacional, no tiene sentido mostrar una lista
plana: sería imposible de usar en un selector. Por eso el flujo se divide
en 3 pasos que van acotando el conjunto:

  1) elegir provincia
  2) elegir carretera dentro de esa provincia
  3) elegir, con casillas, las cámaras concretas de esa carretera

Cada entrada de configuración (ConfigEntry) representa "una tanda de
cámaras añadidas". Si el usuario quiere cámaras de otra provincia o
carretera más adelante, puede volver a ejecutar la integración desde
Ajustes > Dispositivos y servicios > Añadir integración, o usar el
"Options flow" para añadir más a una entrada ya existente.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import DgtCamera, InventoryTooLargeError, async_fetch_camera_inventory
from .const import CONF_CAMERAS, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _get_inventory_or_error(hass) -> tuple[list[DgtCamera] | None, str | None]:
    """Descarga el inventario y traduce cualquier fallo a una clave de error.

    Devuelve (lista_de_camaras, None) si todo va bien, o (None, "clave_error")
    si algo falla, para que el paso del flujo pueda mostrar un mensaje
    comprensible en vez de una traza técnica.
    """
    session = async_get_clientsession(hass)
    try:
        # El inventario se cachea dentro de api.py, así que abrir este
        # diálogo varias veces seguidas NO vuelve a descargar los varios MB
        # del XML: se reutiliza la copia reciente.
        cameras = await async_fetch_camera_inventory(hass, session)
    except TimeoutError:
        return None, "timeout"
    except InventoryTooLargeError:
        _LOGGER.error("El inventario de la DGT superó el tamaño máximo permitido")
        return None, "inventory_too_large"
    except Exception:  # noqa: BLE001 - cualquier fallo de red/parseo cuenta como error genérico
        _LOGGER.exception("Fallo al descargar/parsear el inventario de cámaras de la DGT")
        return None, "cannot_connect"

    if not cameras:
        return None, "no_cameras_found"

    return cameras, None


class DgtTrafficCamerasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Maneja la creación inicial de la integración."""

    VERSION = 1

    def __init__(self) -> None:
        self._all_cameras: list[DgtCamera] = []
        self._province: str | None = None
        self._road: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Primer paso: descargar el inventario y pedir la provincia."""
        errors: dict[str, str] = {}

        if not self._all_cameras:
            cameras, error = await _get_inventory_or_error(self.hass)
            if error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({}),
                    errors={"base": error},
                )
            self._all_cameras = cameras

        # OJO con la comprobación: cuando la descarga falla mostramos un
        # formulario SIN campos, y al reenviarlo Home Assistant nos entrega
        # un diccionario VACÍO, que no es lo mismo que None. Si aquí sólo
        # comprobáramos "is not None", intentaríamos leer una provincia que
        # nadie ha elegido todavía y la interfaz daría un error 500.
        if user_input:
            self._province = user_input["province"]
            return await self.async_step_road()

        provinces = sorted(
            {c.province for c in self._all_cameras if c.province}
        )
        schema = vol.Schema(
            {
                vol.Required("province"): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=p, label=p.title()) for p in provinces],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_road(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Segundo paso: elegir la carretera dentro de la provincia elegida."""
        if user_input is not None:
            self._road = user_input["road"]
            return await self.async_step_cameras()

        roads = sorted(
            {
                c.road_name
                for c in self._all_cameras
                if c.province == self._province and c.road_name
            }
        )
        if not roads:
            # No debería pasar (la provincia salió de estos mismos datos),
            # pero si pasa, es mejor avisar que dejar un selector vacío.
            return self.async_abort(reason="no_roads_found")

        schema = vol.Schema(
            {
                vol.Required("road"): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=r, label=r) for r in roads],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="road", data_schema=schema)

    async def async_step_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Tercer paso: elegir, con casillas, las cámaras concretas."""
        candidates = [
            c
            for c in self._all_cameras
            if c.province == self._province and c.road_name == self._road
        ]
        # Orden por punto kilométrico para que la lista tenga sentido visual.
        candidates.sort(key=lambda c: _km_sort_key(c.kilometer_point))

        if user_input is not None:
            selected_ids = set(user_input["camera_ids"])
            selected = [
                _camera_to_dict(c) for c in candidates if c.device_id in selected_ids
            ]
            if not selected:
                return self.async_show_form(
                    step_id="cameras",
                    data_schema=_cameras_schema(candidates),
                    errors={"base": "no_cameras_selected"},
                )
            # Marcamos la entrada con un identificador único basado en
            # provincia + carretera. Si el usuario intenta añadir otra vez
            # esa misma combinación, Home Assistant lo detecta y aborta en
            # lugar de crear una entrada duplicada.
            #
            # POR QUÉ IMPORTA: dos entradas duplicadas significan dos
            # entidades distintas pidiendo LA MISMA foto a la DGT, cada una
            # con su propio caché. Es decir, el doble de peticiones para
            # exactamente la misma información.
            await self.async_set_unique_id(f"{self._province}_{self._road}")
            self._abort_if_unique_id_configured()

            title = f"DGT · {self._province.title()} · {self._road}"
            return self.async_create_entry(
                title=title,
                data={CONF_CAMERAS: selected},
            )

        return self.async_show_form(
            step_id="cameras", data_schema=_cameras_schema(candidates)
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return DgtTrafficCamerasOptionsFlow(config_entry)


class DgtTrafficCamerasOptionsFlow(config_entries.OptionsFlow):
    """Permite añadir o quitar cámaras de una entrada ya existente.

    Para añadir, reutiliza el mismo flujo de 3 pasos que la configuración
    inicial, pero al terminar fusiona las cámaras nuevas con las que ya
    había, en vez de reemplazarlas. Para quitar, muestra directamente las
    cámaras ya guardadas en esta entrada.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # OJO: NO asignar self.config_entry aquí. En versiones recientes de
        # Home Assistant (>= 2024.11), OptionsFlow.config_entry es una
        # propiedad de solo lectura que el propio framework rellena; hacer
        # "self.config_entry = config_entry" lanza una excepción interna
        # (se traduce en un 500 al abrir el flujo de opciones). El framework
        # ya nos da acceso a self.config_entry sin que tengamos que guardarlo.
        self._all_cameras: list[DgtCamera] = []
        self._province: str | None = None
        self._road: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["add_cameras", "remove_cameras"]
        )

    async def async_step_add_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_province(user_input)

    async def async_step_province(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if not self._all_cameras:
            cameras, error = await _get_inventory_or_error(self.hass)
            if error:
                return self.async_show_form(
                    step_id="province", data_schema=vol.Schema({}), errors={"base": error}
                )
            self._all_cameras = cameras

        # Misma precaución que en el flujo de configuración: un formulario
        # de error reenviado llega como diccionario vacío, no como None.
        if user_input:
            self._province = user_input["province"]
            return await self.async_step_road()

        provinces = sorted({c.province for c in self._all_cameras if c.province})
        schema = vol.Schema(
            {
                vol.Required("province"): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=p, label=p.title()) for p in provinces],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="province", data_schema=schema)

    async def async_step_road(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._road = user_input["road"]
            return await self.async_step_cameras()

        roads = sorted(
            {
                c.road_name
                for c in self._all_cameras
                if c.province == self._province and c.road_name
            }
        )
        if not roads:
            # El flujo de configuración inicial ya tenía esta guardia, pero
            # al flujo de opciones se me olvidó ponérsela: sin ella se
            # mostraría un desplegable vacío del que no se puede salir.
            return self.async_abort(reason="no_roads_found")

        schema = vol.Schema(
            {
                vol.Required("road"): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=r, label=r) for r in roads],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="road", data_schema=schema)

    async def async_step_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        candidates = [
            c
            for c in self._all_cameras
            if c.province == self._province and c.road_name == self._road
        ]
        candidates.sort(key=lambda c: _km_sort_key(c.kilometer_point))

        if user_input is not None:
            selected_ids = set(user_input["camera_ids"])
            new_cameras = [
                _camera_to_dict(c) for c in candidates if c.device_id in selected_ids
            ]
            existing = list(self.config_entry.data.get(CONF_CAMERAS, []))
            existing_ids = {c["device_id"] for c in existing}
            realmente_nuevas = [
                c for c in new_cameras if c["device_id"] not in existing_ids
            ]

            if not realmente_nuevas:
                # El usuario solo eligió cámaras que ya tenía. No tocamos la
                # configuración: así evitamos una recarga (y con ella, una
                # ronda entera de descargas de imágenes) para nada.
                return self.async_create_entry(title="", data={})

            merged = existing + realmente_nuevas

            # async_update_entry ya dispara por sí solo el listener que
            # recarga la integración (ver __init__.py). Antes, además de
            # esto, el async_create_entry final provocaba una SEGUNDA
            # recarga innecesaria; ahora el listener filtra ese caso.
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_CAMERAS: merged}
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="cameras", data_schema=_cameras_schema(candidates)
        )

    async def async_step_remove_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Quita de esta entrada las cámaras que el usuario marque.

        A diferencia de "añadir", aquí no hace falta descargar el inventario
        de la DGT: las cámaras candidatas son directamente las que ya están
        guardadas en la ConfigEntry.
        """
        existing = list(self.config_entry.data.get(CONF_CAMERAS, []))

        if user_input is not None:
            selected_ids = set(user_input["camera_ids"])
            if not selected_ids:
                return self.async_show_form(
                    step_id="remove_cameras",
                    data_schema=_remove_cameras_schema(existing),
                    errors={"base": "no_cameras_selected"},
                )

            remaining = [c for c in existing if c["device_id"] not in selected_ids]
            if not remaining:
                # Dejar la entrada sin ninguna cámara no tiene sentido: si el
                # usuario quiere quitarlas todas, lo correcto es eliminar la
                # entrada entera desde Ajustes > Dispositivos y servicios.
                return self.async_show_form(
                    step_id="remove_cameras",
                    data_schema=_remove_cameras_schema(existing),
                    errors={"base": "cannot_remove_all_cameras"},
                )

            # Además de sacarlas de la configuración, hay que borrar su
            # entidad del registro. Si no lo hiciéramos, la entidad se
            # quedaría "huérfana" (aparecería como no disponible en
            # Ajustes > Entidades) en vez de desaparecer del todo.
            registry = er.async_get(self.hass)
            for camera_data in existing:
                device_id = camera_data.get("device_id")
                if device_id not in selected_ids:
                    continue
                unique_id = f"{self.config_entry.entry_id}_{device_id}"
                entity_id = registry.async_get_entity_id("camera", DOMAIN, unique_id)
                if entity_id:
                    registry.async_remove(entity_id)

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_CAMERAS: remaining},
            )
            return self.async_create_entry(title="", data={})

        if not existing:
            return self.async_abort(reason="no_cameras_to_remove")

        return self.async_show_form(
            step_id="remove_cameras", data_schema=_remove_cameras_schema(existing)
        )


def _remove_cameras_schema(cameras: list[dict[str, Any]]) -> vol.Schema:
    options = [
        SelectOptionDict(
            value=c["device_id"], label=c.get("name") or c["device_id"]
        )
        for c in cameras
    ]
    return vol.Schema(
        {
            vol.Required("camera_ids"): SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
    )


def _cameras_schema(candidates: list[DgtCamera]) -> vol.Schema:
    options = [
        SelectOptionDict(value=c.device_id, label=c.display_name) for c in candidates
    ]
    return vol.Schema(
        {
            vol.Required("camera_ids"): SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
    )


def _camera_to_dict(camera: DgtCamera) -> dict[str, Any]:
    """Serializa una DgtCamera a dict plano para guardarla en ConfigEntry.data.

    ConfigEntry solo admite tipos serializables a JSON, así que no podemos
    guardar el dataclass directamente.
    """
    return {
        "device_id": camera.device_id,
        "name": camera.display_name,
        "road_name": camera.road_name,
        "road_destination": camera.road_destination,
        "province": camera.province,
        "kilometer_point": camera.kilometer_point,
        "direction": camera.direction,
        "latitude": camera.latitude,
        "longitude": camera.longitude,
        "image_url": camera.image_url,
    }


def _km_sort_key(km: str | None) -> float:
    try:
        return float(km) if km is not None else float("inf")
    except ValueError:
        return float("inf")
