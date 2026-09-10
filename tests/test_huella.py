"""Tests de _huella_entry (__init__.py): decide si hay que recargar una entrada.

Cubre el ciclo del interruptor de "mostrar en el mapa": cambiarlo en un
dispositivo debe cambiar la huella (y por tanto disparar una recarga),
volver a ponerlo como estaba debe volver a cambiarla igual.

CONF_SHOW_ON_MAP es POR DISPOSITIVO: vive dentro de cada dict de
"cameras"/"panels" en entry.data, no en entry.options. Por eso la huella ya
no es una tupla plana de device_ids: es una tupla de (device_id, mostrar_en_mapa).
"""

from __future__ import annotations

import unittest

from ._load import load

integracion = load("__init__")


class _EntradaFalsa:
    """Doble mínimo de ConfigEntry: solo lo que _huella_entry necesita leer."""

    def __init__(self, data: dict) -> None:
        self.data = data


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
        ids = {device_id for device_id, _ in huella}
        self.assertIn("a", ids)
        self.assertNotIn("z", ids)


class TestHuellaPaneles(unittest.TestCase):
    def test_lee_panels_no_cameras_cuando_el_tipo_es_vms(self) -> None:
        entrada = _EntradaFalsa(
            {"device_type": "vms", "panels": [{"device_id": "p1"}]}
        )
        huella = integracion._huella_entry(entrada)
        ids = {device_id for device_id, _ in huella}
        self.assertIn("p1", ids)


class TestHuellaInterruptorMapa(unittest.TestCase):
    """Simula el ciclo completo activar -> desactivar del interruptor de mapa
    de UN dispositivo concreto dentro de la entrada.

    Por defecto está ACTIVADO (CONF_SHOW_ON_MAP_DEFAULT = True): antes de que
    existiera este interruptor, las coordenadas siempre se exponían sin
    condición alguna, así que un dispositivo sin esta clave en su dict debe
    comportarse igual que uno que la tiene puesta a True explícitamente.
    """

    def test_no_configurarlo_equivale_a_tenerlo_activado(self) -> None:
        sin_configurar = _EntradaFalsa({"cameras": [{"device_id": "a"}]})
        activado_explicito = _EntradaFalsa(
            {"cameras": [{"device_id": "a", "show_on_map": True}]}
        )
        self.assertEqual(
            integracion._huella_entry(sin_configurar),
            integracion._huella_entry(activado_explicito),
        )

    def test_desactivarlo_cambia_la_huella(self) -> None:
        activado = _EntradaFalsa(
            {"cameras": [{"device_id": "a", "show_on_map": True}]}
        )
        desactivado = _EntradaFalsa(
            {"cameras": [{"device_id": "a", "show_on_map": False}]}
        )
        self.assertNotEqual(
            integracion._huella_entry(activado),
            integracion._huella_entry(desactivado),
        )

    def test_desactivarlo_en_un_dispositivo_no_afecta_a_otro_de_la_misma_entrada(
        self,
    ) -> None:
        entrada = _EntradaFalsa(
            {
                "cameras": [
                    {"device_id": "a", "show_on_map": False},
                    {"device_id": "b", "show_on_map": True},
                ]
            }
        )
        huella = dict(integracion._huella_entry(entrada))
        self.assertFalse(huella["a"])
        self.assertTrue(huella["b"])

    def test_ciclo_completo_desactivar_reactivar_vuelve_a_la_huella_original(self) -> None:
        base = _EntradaFalsa({"cameras": [{"device_id": "a"}]})
        huella_inicial = integracion._huella_entry(base)

        base.data = {"cameras": [{"device_id": "a", "show_on_map": False}]}
        huella_desactivado = integracion._huella_entry(base)
        self.assertNotEqual(huella_inicial, huella_desactivado)

        base.data = {"cameras": [{"device_id": "a", "show_on_map": True}]}
        huella_reactivado = integracion._huella_entry(base)
        self.assertEqual(huella_inicial, huella_reactivado)


if __name__ == "__main__":
    unittest.main()
