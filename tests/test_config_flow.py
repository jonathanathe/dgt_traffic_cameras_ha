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


const_mod = load("const")


def _clave_del_schema(schema, nombre_campo: str):
    """El stub de vol.Schema guarda un dict {vol.Required(...): validador};
    hay que buscar la CLAVE (que es la que lleva el .default), no el valor."""
    for clave in schema.schema_dict:
        if clave.key == nombre_campo:
            return clave
    raise KeyError(nombre_campo)


class _EntradaFalsa:
    def __init__(self, entry_id: str, data: dict | None = None) -> None:
        self.entry_id = entry_id
        self.data = data or {}


class _ConfigEntriesFalso:
    """Suficiente de hass.config_entries para probar los pasos que llaman a
    async_update_entry (añadir/editar dispositivos ya guardados).

    Replica a propósito el detalle real de Home Assistant que causó un bug:
    ConfigEntries.async_update_entry NO avisa a los listeners (por tanto no
    recarga la entrada) si el "nuevo" data es == al que ya tenía la entrada,
    sea cual sea la razón. Si el código de producción mutara los dicts de
    entry.data in situ ANTES de llamar aquí, esta comparación los vería
    iguales y "entradas_actualizadas" se quedaría vacío aunque se hubiera
    llamado a esta función -- justo lo que hay que detectar."""

    def __init__(self) -> None:
        self.entradas_actualizadas: list[str] = []

    def async_update_entry(self, entry, *, data=None):  # noqa: ANN001, ANN201 - stub
        if data is not None and data != entry.data:
            entry.data = data
            self.entradas_actualizadas.append(entry.entry_id)


def _options_flow_con(entrada: _EntradaFalsa) -> "config_flow_mod.DgtTrafficCamerasOptionsFlow":
    flow = config_flow_mod.DgtTrafficCamerasOptionsFlow(entrada)
    flow.hass = type("HassFalso", (), {"config_entries": _ConfigEntriesFalso()})()
    flow.config_entry = entrada
    return flow


class TestMapaAlAnadirCamaras(unittest.IsolatedAsyncioTestCase):
    """CONF_SHOW_ON_MAP se pregunta al añadir dispositivos, y se guarda POR
    DISPOSITIVO dentro de cada dict, no en options ni de forma global."""

    def setUp(self) -> None:
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = set()

    async def test_el_formulario_usa_activado_como_default(self) -> None:
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        resultado = await flow.async_step_camera_map(None)

        self.assertEqual(resultado["step_id"], "camera_map")
        clave = _clave_del_schema(resultado["data_schema"], const_mod.CONF_SHOW_ON_MAP)
        self.assertTrue(clave.default)

    async def test_aplica_el_valor_a_todas_las_camaras_pendientes(self) -> None:
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        flow._province = "MADRID"
        flow._road = "A-1"
        flow._pending_cameras = [{"device_id": "a"}, {"device_id": "b"}]

        resultado = await flow.async_step_camera_map(
            {const_mod.CONF_SHOW_ON_MAP: False}
        )

        camaras = resultado["data"][const_mod.CONF_CAMERAS]
        self.assertTrue(
            all(c[const_mod.CONF_SHOW_ON_MAP] is False for c in camaras)
        )


class TestMapaAlAnadirPaneles(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        config_flow_mod.DgtTrafficCamerasConfigFlow.unique_ids_configurados = set()

    async def test_aplica_el_valor_a_todos_los_paneles_pendientes(self) -> None:
        flow = config_flow_mod.DgtTrafficCamerasConfigFlow()
        flow._province = "BALEARS, ILLES"
        flow._road = "Ma-19"
        flow._pending_panels = [{"device_id": "p1"}, {"device_id": "p2"}]

        resultado = await flow.async_step_panel_map({const_mod.CONF_SHOW_ON_MAP: True})

        paneles = resultado["data"][const_mod.CONF_PANELS]
        self.assertTrue(all(p[const_mod.CONF_SHOW_ON_MAP] is True for p in paneles))


class TestMapaAlAnadirDesdeOpciones(unittest.IsolatedAsyncioTestCase):
    """Mismo mecanismo que en la configuración inicial, pero fusionando con
    lo que ya hubiera en la entrada (ver async_step_cameras_map/panels_map)."""

    async def test_las_camaras_nuevas_llevan_el_valor_elegido_y_las_viejas_no_se_tocan(
        self,
    ) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_CAMERAS: [
                    {"device_id": "vieja", const_mod.CONF_SHOW_ON_MAP: False}
                ]
            },
        )
        flow = _options_flow_con(entrada)
        flow._pending_cameras = [{"device_id": "nueva"}]

        resultado = await flow.async_step_cameras_map(
            {const_mod.CONF_SHOW_ON_MAP: True}
        )

        self.assertEqual(resultado["data"], {})
        camaras = {c["device_id"]: c for c in entrada.data[const_mod.CONF_CAMERAS]}
        self.assertTrue(camaras["nueva"][const_mod.CONF_SHOW_ON_MAP])
        self.assertFalse(camaras["vieja"][const_mod.CONF_SHOW_ON_MAP])

    async def test_los_paneles_nuevos_llevan_el_valor_elegido(self) -> None:
        entrada = _EntradaFalsa("entry1", data={const_mod.CONF_PANELS: []})
        flow = _options_flow_con(entrada)
        flow._pending_panels = [{"device_id": "nuevo"}]

        await flow.async_step_panels_map({const_mod.CONF_SHOW_ON_MAP: False})

        panel = entrada.data[const_mod.CONF_PANELS][0]
        self.assertFalse(panel[const_mod.CONF_SHOW_ON_MAP])


class TestEditarMapaDeDispositivosExistentes(unittest.IsolatedAsyncioTestCase):
    """async_step_edit_map: cambiar la visibilidad de dispositivos YA
    guardados en la entrada, sin tener que quitarlos y volver a añadirlos."""

    async def test_aborta_si_la_entrada_no_tiene_dispositivos(self) -> None:
        entrada = _EntradaFalsa("entry1", data={const_mod.CONF_CAMERAS: []})
        flow = _options_flow_con(entrada)

        resultado = await flow.async_step_edit_map(None)
        self.assertEqual(resultado["type"], "abort")

    async def test_el_formulario_premarca_los_que_ya_se_ven(self) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_CAMERAS: [
                    {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: True},
                    {"device_id": "b", const_mod.CONF_SHOW_ON_MAP: False},
                ]
            },
        )
        flow = _options_flow_con(entrada)

        resultado = await flow.async_step_edit_map(None)

        clave = _clave_del_schema(resultado["data_schema"], "camera_ids")
        self.assertEqual(clave.default, ["a"])

    async def test_cambiar_la_seleccion_actualiza_solo_los_dispositivos_que_cambian(
        self,
    ) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_CAMERAS: [
                    {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: True},
                    {"device_id": "b", const_mod.CONF_SHOW_ON_MAP: False},
                ]
            },
        )
        flow = _options_flow_con(entrada)

        # Se desmarca "a" y se marca "b": el resultado debe ser justo al revés.
        await flow.async_step_edit_map({"camera_ids": ["b"]})

        camaras = {c["device_id"]: c for c in entrada.data[const_mod.CONF_CAMERAS]}
        self.assertFalse(camaras["a"][const_mod.CONF_SHOW_ON_MAP])
        self.assertTrue(camaras["b"][const_mod.CONF_SHOW_ON_MAP])

    async def test_no_actualiza_nada_si_la_seleccion_no_cambia(self) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_CAMERAS: [
                    {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: True}
                ]
            },
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_edit_map({"camera_ids": ["a"]})

        self.assertNotIn("entry1", flow.hass.config_entries.entradas_actualizadas)

    async def test_no_muta_en_sitio_los_dicts_originales(self) -> None:
        """Bug real detectado en producción: si se mutan in situ los dicts
        que ya cuelgan de entry.data ANTES de llamar a async_update_entry,
        Home Assistant de verdad ve entry.data == data (mismos objetos ya
        modificados) y NO recarga la entrada -- aunque el propio dato quede
        bien guardado, dando la falsa impresión de que "ya se ha aplicado"
        al releer el formulario. Aquí se comprueba con identidad de objeto,
        no solo con el valor final."""
        dispositivo_original = {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: True}
        entrada = _EntradaFalsa(
            "entry1", data={const_mod.CONF_CAMERAS: [dispositivo_original]}
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_edit_map({"camera_ids": []})

        self.assertTrue(dispositivo_original[const_mod.CONF_SHOW_ON_MAP])
        self.assertIn("entry1", flow.hass.config_entries.entradas_actualizadas)

    async def test_usa_panel_ids_cuando_la_entrada_es_de_paneles(self) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_DEVICE_TYPE: const_mod.DEVICE_TYPE_VMS,
                const_mod.CONF_PANELS: [
                    {"device_id": "p1", const_mod.CONF_SHOW_ON_MAP: True}
                ],
            },
        )
        flow = _options_flow_con(entrada)

        resultado = await flow.async_step_edit_map(None)
        self.assertEqual(resultado["step_id"], "edit_map")
        # No debe reventar buscando "camera_ids" en una entrada de paneles.
        _clave_del_schema(resultado["data_schema"], "panel_ids")


class TestMostrarOcultarTodosDeGolpe(unittest.IsolatedAsyncioTestCase):
    """async_step_map_show_all / async_step_map_hide_all: entradas de menú
    directas (sin formulario) para marcar/desmarcar todos los dispositivos
    de la entrada de una vez, sin tener que ir uno a uno en "edit_map"."""

    async def test_mostrar_todos_marca_los_que_estaban_ocultos(self) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_CAMERAS: [
                    {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: False},
                    {"device_id": "b", const_mod.CONF_SHOW_ON_MAP: True},
                ]
            },
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_map_show_all()

        camaras = entrada.data[const_mod.CONF_CAMERAS]
        self.assertTrue(all(c[const_mod.CONF_SHOW_ON_MAP] for c in camaras))
        self.assertIn("entry1", flow.hass.config_entries.entradas_actualizadas)

    async def test_ocultar_todos_desmarca_los_que_estaban_visibles(self) -> None:
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_DEVICE_TYPE: const_mod.DEVICE_TYPE_VMS,
                const_mod.CONF_PANELS: [
                    {"device_id": "p1", const_mod.CONF_SHOW_ON_MAP: True},
                ],
            },
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_map_hide_all()

        panel = entrada.data[const_mod.CONF_PANELS][0]
        self.assertFalse(panel[const_mod.CONF_SHOW_ON_MAP])

    async def test_no_actualiza_nada_si_ya_estaban_todos_como_se_pide(self) -> None:
        """Evita una recarga de más si el menú se pulsa sin que cambie nada."""
        entrada = _EntradaFalsa(
            "entry1",
            data={
                const_mod.CONF_CAMERAS: [
                    {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: True},
                ]
            },
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_map_show_all()

        self.assertNotIn("entry1", flow.hass.config_entries.entradas_actualizadas)

    async def test_dispositivos_sin_la_clave_cuentan_como_visibles_por_defecto(
        self,
    ) -> None:
        """Un dispositivo antiguo sin CONF_SHOW_ON_MAP debe tratarse como
        activado (CONF_SHOW_ON_MAP_DEFAULT); "ocultar todos" debe tocarlo."""
        entrada = _EntradaFalsa(
            "entry1",
            data={const_mod.CONF_CAMERAS: [{"device_id": "a"}]},
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_map_hide_all()

        camara = entrada.data[const_mod.CONF_CAMERAS][0]
        self.assertFalse(camara[const_mod.CONF_SHOW_ON_MAP])

    async def test_no_muta_en_sitio_los_dicts_originales(self) -> None:
        """Ver el comentario equivalente en TestEditarMapaDeDispositivosExistentes."""
        dispositivo_original = {"device_id": "a", const_mod.CONF_SHOW_ON_MAP: False}
        entrada = _EntradaFalsa(
            "entry1", data={const_mod.CONF_CAMERAS: [dispositivo_original]}
        )
        flow = _options_flow_con(entrada)

        await flow.async_step_map_show_all()

        self.assertFalse(dispositivo_original[const_mod.CONF_SHOW_ON_MAP])
        self.assertIn("entry1", flow.hass.config_entries.entradas_actualizadas)


if __name__ == "__main__":
    unittest.main()
