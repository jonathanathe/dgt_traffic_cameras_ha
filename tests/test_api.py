"""Tests del parseo de XML en api.py, contra fixtures reales de la DGT."""

from __future__ import annotations

import unittest

from ._load import fixture_bytes, load

api = load("api")


class TestParseVmsLocations(unittest.TestCase):
    """_parse_vms_locations contra tests/fixtures/vms_locations_sample.xml.

    Fixture construida a partir de una descarga real (2026-09-06) de
    https://nap.dgt.es/datex2/v3/dgt/DevicePublication/vms_datex2_v37.xml,
    con 4 dispositivos reales completos.
    """

    def setUp(self) -> None:
        xml_bytes = fixture_bytes("vms_locations_sample.xml")
        self.panels = api._parse_vms_locations(xml_bytes)
        self.by_id = {p.device_id: p for p in self.panels}

    def test_parsea_los_cuatro_paneles(self) -> None:
        self.assertEqual(len(self.panels), 4)
        self.assertEqual(
            set(self.by_id), {"167938", "61441", "61459", "168606"}
        )

    def test_campos_de_un_panel_conocido(self) -> None:
        panel = self.by_id["61441"]
        self.assertEqual(panel.road_name, "M-607")
        self.assertEqual(panel.road_destination, "MADRID")
        self.assertEqual(panel.province, "MADRID")
        self.assertEqual(panel.kilometer_point, "18.532")
        self.assertEqual(panel.direction, "negative")
        self.assertAlmostEqual(panel.latitude, 40.56056)
        self.assertAlmostEqual(panel.longitude, -3.713396)

    def test_punto_kilometrico_ya_esta_en_km_no_en_metros(self) -> None:
        # Ver const.py: se verificó con datos reales que el feed YA trae el
        # punto kilométrico en km (18.532, no 18532), a diferencia de lo que
        # se asumía antes de comprobarlo.
        panel = self.by_id["61459"]
        self.assertEqual(panel.kilometer_point, "85.0")

    def test_display_name_no_rompe_sin_campos(self) -> None:
        for panel in self.panels:
            self.assertTrue(panel.display_name)


class TestParseCameraInventoryRegression(unittest.TestCase):
    """El refactor de api.py (clase base compartida, descargador genérico)
    no debe cambiar el resultado del parseo de cámaras."""

    def test_camara_minima_sigue_funcionando(self) -> None:
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:com="http://levelC/schema/3/common"
  xmlns:loc="http://levelC/schema/3/locationReferencing"
  xmlns:fse="http://levelC/schema/3/faultAndStatusSpanishExtension"
  xmlns:ns2="http://levelC/schema/3/faultAndStatus"
  xmlns:d2="http://levelC/schema/3/d2Payload"
  xmlns:lse="http://levelC/schema/3/locationReferencingSpanishExtension">
  <ns2:device id="123" version="1">
    <fse:deviceUrl>https://etraffic.dgt.es/camarasEtraffic/123.jpg</fse:deviceUrl>
    <ns2:pointLocation>
      <loc:supplementaryPositionalDescription>
        <loc:roadInformation>
          <loc:roadDestination>MADRID</loc:roadDestination>
          <loc:roadName>A-1</loc:roadName>
        </loc:roadInformation>
      </loc:supplementaryPositionalDescription>
      <loc:tpegPointLocation>
        <loc:point>
          <loc:pointCoordinates>
            <loc:latitude>40.1</loc:latitude>
            <loc:longitude>-3.5</loc:longitude>
          </loc:pointCoordinates>
          <loc:_tpegNonJunctionPointExtension>
            <loc:extendedTpegNonJunctionPoint>
              <lse:kilometerPoint>10.5</lse:kilometerPoint>
              <lse:province>MADRID</lse:province>
            </loc:extendedTpegNonJunctionPoint>
          </loc:_tpegNonJunctionPointExtension>
        </loc:point>
        <loc:_tpegSimplePointExtension>
          <loc:extendedTpegSimplePoint>
            <lse:tpegDirectionRoad>positive</lse:tpegDirectionRoad>
          </loc:extendedTpegSimplePoint>
        </loc:_tpegSimplePointExtension>
      </loc:tpegPointLocation>
    </ns2:pointLocation>
  </ns2:device>
</d2:payload>"""
        cameras = api._parse_camera_inventory(xml)
        self.assertEqual(len(cameras), 1)
        c = cameras[0]
        self.assertEqual(c.device_id, "123")
        self.assertEqual(c.image_url, "https://etraffic.dgt.es/camarasEtraffic/123.jpg")
        self.assertEqual(c.road_name, "A-1")
        self.assertEqual(c.province, "MADRID")
        self.assertEqual(c.kilometer_point, "10.5")
        self.assertEqual(c.direction, "positive")

    def test_camara_con_url_no_https_se_descarta(self) -> None:
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:d2="http://levelC/schema/3/d2Payload"
  xmlns:fse="http://levelC/schema/3/faultAndStatusSpanishExtension"
  xmlns:ns2="http://levelC/schema/3/faultAndStatus">
  <ns2:device id="999" version="1">
    <fse:deviceUrl>http://sitio-no-dgt.example/foto.jpg</fse:deviceUrl>
  </ns2:device>
</d2:payload>"""
        cameras = api._parse_camera_inventory(xml)
        self.assertEqual(cameras, [])


if __name__ == "__main__":
    unittest.main()
