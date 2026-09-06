"""Tests de parse_vms_messages, contra una fixture con 4 casos reales.

Fixture construida a partir de una descarga real (2026-09-06) de
https://nap.dgt.es/datex2/v3/dgt/VmsPublication/datex2_v37.xml, con 4
vmsControllerStatus reales completos que cubren:

  - 167938: panel apagado (todas las zonas con pictograma "0", sin texto)
  - 61441:  mensaje normal multilínea, con pictogramas
  - 61459:  varias páginas con contenido DISTINTO en cada una (aviso de
            incendio en español + inglés, no una traducción exacta)
  - 168606: página con texto bilingüe DENTRO de una misma línea (usa "/")
"""

from __future__ import annotations

import unittest

from ._load import fixture_bytes, load

vms_messages = load("vms_messages")


class TestParseVmsMessages(unittest.TestCase):
    def setUp(self) -> None:
        xml_bytes = fixture_bytes("vms_messages_sample.xml")
        self.estados = vms_messages.parse_vms_messages(xml_bytes)

    def test_devuelve_los_cuatro_paneles(self) -> None:
        self.assertEqual(set(self.estados), {"167938", "61441", "61459", "168606"})

    def test_panel_apagado(self) -> None:
        estado = self.estados["167938"]
        self.assertTrue(estado.off)
        self.assertEqual(estado.lines, [])
        self.assertEqual(estado.pictogram_codes, [])
        self.assertEqual(estado.text, "")

    def test_mensaje_normal_multilinea(self) -> None:
        estado = self.estados["61441"]
        self.assertFalse(estado.off)
        self.assertEqual(estado.lines, ["VELOCIDAD", "CONTROLADA", "POR RADAR"])
        self.assertEqual(estado.text, "VELOCIDAD / CONTROLADA / POR RADAR")
        self.assertEqual(set(estado.pictogram_codes), {"R301100I", "E17"})
        self.assertIsNotNone(estado.last_set)

    def test_pagina_secundaria_con_contenido_distinto(self) -> None:
        estado = self.estados["61459"]
        self.assertFalse(estado.off)
        self.assertEqual(estado.lines, ["RIESGO DE", "INCENDIO", "EXTREMO"])
        # La segunda página no es una traducción concatenada: se guarda
        # aparte, no mezclada con la principal.
        self.assertEqual(len(estado.other_pages), 1)
        self.assertIn("FIRE", estado.other_pages[0])

    def test_linea_bilingue_con_barra_no_se_separa_como_si_fueran_lineas(self) -> None:
        estado = self.estados["168606"]
        self.assertFalse(estado.off)
        # La barra "/" va DENTRO de una línea (SOLO/NOMES), no se trata
        # como separador de líneas: sigue siendo una única línea física.
        self.assertIn("SOLO/NOMES", estado.lines)
        self.assertEqual(len(estado.lines), 4)

    def test_texto_recortado_a_255_para_el_estado(self) -> None:
        estado = vms_messages.PanelMessageState(
            device_id="x",
            text="a" * 300,
            text_full="a" * 300,
        )
        # El propio parser ya recorta "text"; esta prueba fija el límite
        # real de Home Assistant que se usa para recortar (255).
        self.assertEqual(vms_messages.MAX_STATE_LENGTH, 255)


if __name__ == "__main__":
    unittest.main()
