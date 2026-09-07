"""Tests de sensor.py: estado (native_value) de un panel según su PanelMessageState.

Cubre M-02 de la auditoría: un panel con pictograma activo pero sin texto
(p.ej. un aviso de velocidad controlada) se mostraba como "Sin datos",
dando a entender que no había venido en la última descarga, cuando en
realidad sí estaba emitiendo.
"""

from __future__ import annotations

import unittest

from ._load import load

sensor_mod = load("sensor")
vms_messages_mod = load("vms_messages")


class _CoordinatorFalso:
    def __init__(self, data: dict | None) -> None:
        self.data = data


def _crear_sensor(coordinator_data: dict | None) -> "sensor_mod.DgtPanelSensor":
    coordinator = _CoordinatorFalso(coordinator_data)
    entry = type("EntradaFalsa", (), {"entry_id": "entry1", "title": "DGT PMV · Test"})()
    panel_data = {
        "device_id": "167938",
        "name": "Panel Test",
        "road_name": "A-54",
        "road_destination": "LUGO",
        "province": "LUGO",
        "kilometer_point": "0.65",
    }
    return sensor_mod.DgtPanelSensor(coordinator, entry, panel_data)


class TestNativeValue(unittest.TestCase):
    def test_sin_datos_cuando_el_panel_no_aparece_en_la_descarga(self) -> None:
        sensor = _crear_sensor({})
        self.assertEqual(sensor.native_value, "Sin datos")

    def test_sin_mensaje_cuando_el_panel_esta_apagado(self) -> None:
        estado = vms_messages_mod.PanelMessageState(
            device_id="167938", text="", text_full="", off=True
        )
        sensor = _crear_sensor({"167938": estado})
        self.assertEqual(sensor.native_value, "Sin mensaje")

    def test_texto_normal_se_muestra_tal_cual(self) -> None:
        estado = vms_messages_mod.PanelMessageState(
            device_id="167938",
            text="VELOCIDAD / CONTROLADA",
            text_full="VELOCIDAD / CONTROLADA",
            lines=["VELOCIDAD", "CONTROLADA"],
            off=False,
        )
        sensor = _crear_sensor({"167938": estado})
        self.assertEqual(sensor.native_value, "VELOCIDAD / CONTROLADA")

    def test_solo_pictograma_no_se_confunde_con_sin_datos(self) -> None:
        """M-02: pictograma activo, sin texto -> no puede ser 'Sin datos'."""
        estado = vms_messages_mod.PanelMessageState(
            device_id="167938",
            text="",
            text_full="",
            lines=[],
            pictogram_codes=["R301100I"],
            off=False,
        )
        sensor = _crear_sensor({"167938": estado})
        self.assertNotEqual(sensor.native_value, "Sin datos")
        self.assertIn("R301100I", sensor.native_value)


class TestNombreEntidad(unittest.TestCase):
    def test_nombre_no_repite_la_carretera(self) -> None:
        """M-10: con has_entity_name=True, HA antepone el nombre del
        dispositivo (que ya incluye la carretera) al de la entidad."""
        sensor = _crear_sensor({})
        self.assertNotIn("A-54", sensor._attr_name)


if __name__ == "__main__":
    unittest.main()
