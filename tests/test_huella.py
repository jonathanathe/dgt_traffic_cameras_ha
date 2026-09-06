"""Tests de _huella_entry (__init__.py): decide si hay que recargar una entrada.

Cubre el ciclo del interruptor de "mostrar en el mapa" (Fase 3) pedido en el
prompt: activar debe cambiar la huella (y por tanto disparar una recarga),
desactivar debe volver a cambiarla.
"""

from __future__ import annotations

import unittest

from ._load import load

integracion = load("__init__")


class _EntradaFalsa:
    """Doble mínimo de ConfigEntry: solo lo que _huella_entry necesita leer."""

    def __init__(self, data: dict, options: dict | None = None) -> None:
        self.data = data
        self.options = options or {}


class TestHuellaCamaras(unittest.TestCase):
    def test_misma_lista_misma_huella(self) -> None:
        entrada = _EntradaFalsa({"cameras": [{"device_id": "a"}, {"device_id": "b"}]})
        self.assertEqual(
            integracion._huella_entry(entrada), integracion._huella_entry(entrada)
        )

    def test_anadir_camara_cambia_la_huella(self) -> None:
        antes = _EntradaFalsa({"cameras": [{"device_id": "a"}]})
        despues = _EntradaFalsa({"cameras": [{"device_id": "a"}, {"device_id": "b"}]})
        self.assertNotEqual(
            integracion._huella_entry(antes), integracion._huella_entry(despues)
        )

    def test_orden_de_la_lista_no_importa(self) -> None:
        a = _EntradaFalsa({"cameras": [{"device_id": "x"}, {"device_id": "y"}]})
        b = _EntradaFalsa({"cameras": [{"device_id": "y"}, {"device_id": "x"}]})
        self.assertEqual(integracion._huella_entry(a), integracion._huella_entry(b))

    def test_entrada_antigua_sin_device_type_se_trata_como_camara(self) -> None:
        # Compatibilidad con entradas creadas antes de que existieran los
        # paneles: sin CONF_DEVICE_TYPE, debe leer "cameras", no "panels".
        entrada = _EntradaFalsa({"cameras": [{"device_id": "a"}], "panels": [{"device_id": "z"}]})
        huella = integracion._huella_entry(entrada)
        self.assertIn("a", huella)
        self.assertNotIn("z", huella)


class TestHuellaPaneles(unittest.TestCase):
    def test_lee_panels_no_cameras_cuando_el_tipo_es_vms(self) -> None:
        entrada = _EntradaFalsa(
            {"device_type": "vms", "panels": [{"device_id": "p1"}]}
        )
        huella = integracion._huella_entry(entrada)
        self.assertIn("p1", huella)


class TestHuellaInterruptorMapa(unittest.TestCase):
    """Simula el ciclo completo activar -> desactivar del interruptor de mapa."""

    def test_activar_el_mapa_cambia_la_huella(self) -> None:
        apagado = _EntradaFalsa({"cameras": [{"device_id": "a"}]}, options={})
        encendido = _EntradaFalsa(
            {"cameras": [{"device_id": "a"}]}, options={"show_on_map": True}
        )
        self.assertNotEqual(
            integracion._huella_entry(apagado), integracion._huella_entry(encendido)
        )

    def test_desactivar_el_mapa_tambien_cambia_la_huella(self) -> None:
        encendido = _EntradaFalsa(
            {"cameras": [{"device_id": "a"}]}, options={"show_on_map": True}
        )
        apagado_de_nuevo = _EntradaFalsa(
            {"cameras": [{"device_id": "a"}]}, options={"show_on_map": False}
        )
        self.assertNotEqual(
            integracion._huella_entry(encendido),
            integracion._huella_entry(apagado_de_nuevo),
        )

    def test_ciclo_completo_activar_desactivar_vuelve_a_la_huella_original(self) -> None:
        base = _EntradaFalsa({"cameras": [{"device_id": "a"}]}, options={})
        huella_inicial = integracion._huella_entry(base)

        base.options = {"show_on_map": True}
        huella_activado = integracion._huella_entry(base)
        self.assertNotEqual(huella_inicial, huella_activado)

        base.options = {"show_on_map": False}
        huella_desactivado = integracion._huella_entry(base)
        self.assertEqual(huella_inicial, huella_desactivado)


if __name__ == "__main__":
    unittest.main()
