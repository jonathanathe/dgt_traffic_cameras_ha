"""Tests de camera.py: atributos de la entidad DgtTrafficCamera.

Cubre M-07 de la auditoría: no había ninguna forma de saber, mirando la
entidad, cuándo se había confirmado por última vez que la foto servida
seguía siendo la actual (una cámara averiada sigue "available" para
siempre porque _cached_image nunca se invalida).
"""

from __future__ import annotations

import unittest

from ._load import load

camera_mod = load("camera")


def _camera_data(**overrides) -> dict:
    base = {
        "device_id": "123",
        "name": "Cámara Test",
        "road_name": "A-1",
        "road_destination": "MADRID",
        "province": "MADRID",
        "kilometer_point": "10.5",
        "direction": "positive",
        "latitude": 40.1,
        "longitude": -3.5,
        "image_url": "https://etraffic.dgt.es/camarasEtraffic/123.jpg",
    }
    base.update(overrides)
    return base


class _EntradaFalsa:
    entry_id = "entry1"
    title = "DGT · Madrid · A-1"


class TestExtraStateAttributes(unittest.TestCase):
    def test_ultima_actualizacion_empieza_en_none(self) -> None:
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())
        self.assertIsNone(camara.extra_state_attributes["ultima_actualizacion"])

    def test_atributos_de_ubicacion_presentes_con_coordenadas(self) -> None:
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())
        atributos = camara.extra_state_attributes
        self.assertEqual(atributos["carretera"], "A-1")
        self.assertEqual(atributos["provincia"], "MADRID")

    def test_ultima_actualizacion_aparece_siempre_aunque_no_haya_coordenadas(self) -> None:
        """Antes, sin latitude/longitude, no se exponía NINGÚN atributo."""
        datos = _camera_data()
        del datos["latitude"]
        del datos["longitude"]
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), datos)
        self.assertIn("ultima_actualizacion", camara.extra_state_attributes)


if __name__ == "__main__":
    unittest.main()
