"""Tests de config_flow.py: primera cobertura real de este fichero.

La auditoría señaló que config_flow.py no tenía ningún test. Este fichero
no pretende cubrirlo entero (el flujo completo depende mucho de mecanismos
internos de Home Assistant difíciles de emular fielmente), pero sí cubre
L-07: antes, si la combinación provincia+carretera ya estaba configurada,
el aviso solo aparecía al FINAL del asistente (tras elegir también las
cámaras/paneles concretos), no en cuanto se sabía la carretera.
"""

from __future__ import annotations

import unittest

from ._load import load

config_flow_mod = load("config_flow")

from homeassistant.config_entries import AbortFlow  # noqa: E402


class TestUniqueIdCamaras(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = set()

    async def test_avisa_en_el_paso_de_carretera_si_ya_existe(self) -> None:
        """L-07: antes había que completar los 3 pasos para enterarse."""
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        flow._province = "MADRID"
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = {
            "MADRID_A-1"
        }

        with self.assertRaises(AbortFlow):
            await flow.async_step_camera_road({"road": "A-1"})

    async def test_no_avisa_si_la_combinacion_es_nueva(self) -> None:
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        flow._province = "MADRID"
        flow._all_cameras = []  # ninguna candidata, pero no debe abortar

        resultado = await flow.async_step_camera_road({"road": "A-1"})
        # No lanza AbortFlow; llega hasta el paso de elegir cámaras.
        self.assertEqual(resultado["step_id"], "cameras")


class TestUniqueIdPaneles(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = set()

    async def test_avisa_en_el_paso_de_carretera_si_ya_existe(self) -> None:
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        flow._province = "BALEARS, ILLES"
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = {
            "panel_BALEARS, ILLES_Ma-19"
        }

        with self.assertRaises(AbortFlow):
            await flow.async_step_panel_road({"road": "Ma-19"})

    async def test_el_prefijo_panel_no_choca_con_una_camara_de_la_misma_via(
        self,
    ) -> None:
        """El unique_id de paneles lleva el prefijo "panel_" para no
        bloquearse mutuamente con una entrada de cámaras de la misma
        provincia y carretera."""
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        flow._province = "MADRID"
        flow._all_panels = []
        # Ya existe una entrada de CÁMARAS para Madrid/A-1 (sin prefijo).
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = {
            "MADRID_A-1"
        }

        # No debe abortar: el unique_id de paneles es "panel_MADRID_A-1".
        resultado = await flow.async_step_panel_road({"road": "A-1"})
        self.assertEqual(resultado["step_id"], "panels")


if __name__ == "__main__":
    unittest.main()
