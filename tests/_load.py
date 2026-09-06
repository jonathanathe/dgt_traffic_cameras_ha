"""Carga aislada de módulos de custom_components/dgt_traffic_cameras para tests.

Estos tests corren SIN Home Assistant instalado (no es una dependencia de
desarrollo de este repo), así que:

  1. Se registran stubs mínimos de "homeassistant" y "aiohttp" en
     sys.modules ANTES de importar nada del paquete real, solo con lo
     estrictamente necesario para que los módulos bajo prueba (que son
     puros: parseo de XML, cálculo de una "huella") se puedan cargar.
  2. Cada módulo se carga con importlib a partir de su ruta de fichero, en
     vez de con "import custom_components.dgt_traffic_cameras.X", para no
     depender de que "custom_components" sea un paquete Python instalado.

Esto prueba el comportamiento REAL de las funciones (parseo de XML de
verdad, contra fixtures reales), no una simulación.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "dgt_traffic_cameras"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _module(name: str) -> types.ModuleType:
    """Registra name (y todos sus paquetes padre) en sys.modules.

    Necesario para que "from homeassistant.helpers.x import y" funcione con
    módulos inyectados a mano: Python necesita encontrar cada eslabón de la
    cadena (homeassistant, homeassistant.helpers, ...) ya registrado y
    enlazado como atributo de su padre, igual que haría un paquete real.
    """
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        partial = ".".join(parts[:i])
        if partial not in sys.modules:
            mod = types.ModuleType(partial)
            sys.modules[partial] = mod
            if i > 1:
                parent = sys.modules[".".join(parts[: i - 1])]
                setattr(parent, parts[i - 1], mod)
    return sys.modules[name]


def _ensure_stubs() -> None:
    """Registra en sys.modules justo lo que los módulos bajo prueba importan.

    Son stubs "de forma", no de comportamiento: bastan para que las
    sentencias import no fallen y para que las funciones puramente lógicas
    (parseo de XML, cálculo de una huella) se puedan probar de verdad sin
    tener Home Assistant instalado. No sirven para probar nada que dependa
    de cómo se comporta HA de verdad (eso se prueba a mano en la instancia
    real, como en el resto de esta integración).
    """
    if "homeassistant.core" not in sys.modules:
        core = _module("homeassistant.core")

        class HomeAssistant:  # noqa: D401 - stub
            data: dict = {}

        core.HomeAssistant = HomeAssistant

    if "homeassistant.config_entries" not in sys.modules:
        config_entries = _module("homeassistant.config_entries")

        class ConfigEntry:  # noqa: D401 - stub
            pass

        class ConfigFlow:  # noqa: D401 - stub
            def __init_subclass__(cls, **kwargs):
                pass

        class OptionsFlow:  # noqa: D401 - stub
            pass

        config_entries.ConfigEntry = ConfigEntry
        config_entries.ConfigFlow = ConfigFlow
        config_entries.OptionsFlow = OptionsFlow
        config_entries.ConfigFlowResult = dict

    if "homeassistant.helpers.aiohttp_client" not in sys.modules:
        aiohttp_client = _module("homeassistant.helpers.aiohttp_client")

        def async_get_clientsession(hass):  # noqa: ANN001, ANN201 - stub
            raise NotImplementedError("stub de test, no llamar de verdad")

        aiohttp_client.async_get_clientsession = async_get_clientsession

    if "homeassistant.helpers.update_coordinator" not in sys.modules:
        update_coordinator = _module("homeassistant.helpers.update_coordinator")

        class DataUpdateCoordinator:  # noqa: D401 - stub
            def __class_getitem__(cls, item):
                return cls

            def __init__(self, hass, logger, *, name, update_interval=None):
                pass

        class UpdateFailed(Exception):
            pass

        update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
        update_coordinator.UpdateFailed = UpdateFailed

    if "aiohttp" not in sys.modules:
        aiohttp = _module("aiohttp")

        class ClientSession:  # noqa: D401 - stub
            pass

        aiohttp.ClientSession = ClientSession


def load(module_name: str) -> types.ModuleType:
    """Carga custom_components/dgt_traffic_cameras/<module_name>.py aislado.

    Reutiliza el módulo ya cargado si se llama dos veces (varios tests
    pidiendo, por ejemplo, "const").
    """
    _ensure_stubs()

    full_name = f"custom_components.dgt_traffic_cameras.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    if "custom_components" not in sys.modules:
        pkg = types.ModuleType("custom_components")
        pkg.__path__ = [str(REPO_ROOT / "custom_components")]
        sys.modules["custom_components"] = pkg
    if "custom_components.dgt_traffic_cameras" not in sys.modules:
        # __path__ real (no un stub) para que las importaciones relativas
        # dentro del paquete ("from . import coordinator", etc.) encuentren
        # los ficheros de verdad mediante el mecanismo normal de import.
        pkg = types.ModuleType("custom_components.dgt_traffic_cameras")
        pkg.__path__ = [str(COMPONENT_DIR)]
        sys.modules["custom_components.dgt_traffic_cameras"] = pkg

    spec = importlib.util.spec_from_file_location(
        full_name, COMPONENT_DIR / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()
