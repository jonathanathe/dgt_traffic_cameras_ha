"""Tests de camera.py: atributos de la entidad DgtTrafficCamera.

Cubre M-07 de la auditoría: no había ninguna forma de saber, mirando la
entidad, cuándo se había confirmado por última vez que la foto servida
seguía siendo la actual (una cámara averiada sigue "available" para
siempre porque _cached_image nunca se invalida).
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone

from ._load import load

camera_mod = load("camera")
const_mod = load("const")


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
    options: dict = {}


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

    def test_atributos_de_ubicacion_presentes_incluso_sin_coordenadas(self) -> None:
        """L-02: antes, sin latitude/longitude, no se exponía carretera/
        provincia/etc. Debe comportarse igual que sensor.py, que siempre
        los expone."""
        datos = _camera_data()
        del datos["latitude"]
        del datos["longitude"]
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), datos)
        atributos = camara.extra_state_attributes
        self.assertEqual(atributos["carretera"], "A-1")
        self.assertEqual(atributos["provincia"], "MADRID")
        self.assertNotIn("latitude", atributos)
        self.assertNotIn("longitude", atributos)

    def test_coordenadas_ocultas_si_el_interruptor_de_mapa_esta_desactivado(self) -> None:
        """CONF_SHOW_ON_MAP es POR DISPOSITIVO: vive en camera_data, no en
        las options de la entrada."""
        datos = _camera_data(**{const_mod.CONF_SHOW_ON_MAP: False})
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), datos)
        atributos = camara.extra_state_attributes
        self.assertNotIn("latitude", atributos)
        self.assertNotIn("longitude", atributos)
        # El resto de atributos se sigue exponiendo igual: el interruptor
        # solo afecta a las coordenadas.
        self.assertEqual(atributos["carretera"], "A-1")

    def test_coordenadas_presentes_si_el_interruptor_de_mapa_esta_activado_explicitamente(
        self,
    ) -> None:
        datos = _camera_data(**{const_mod.CONF_SHOW_ON_MAP: True})
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), datos)
        atributos = camara.extra_state_attributes
        self.assertEqual(atributos["latitude"], 40.1)
        self.assertEqual(atributos["longitude"], -3.5)

    def test_coordenadas_presentes_por_defecto_si_el_dispositivo_no_tiene_la_clave(
        self,
    ) -> None:
        """Un dispositivo guardado antes de que existiera CONF_SHOW_ON_MAP
        no tiene esa clave en su dict; debe comportarse como activado."""
        datos = _camera_data()
        self.assertNotIn(const_mod.CONF_SHOW_ON_MAP, datos)
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), datos)
        atributos = camara.extra_state_attributes
        self.assertEqual(atributos["latitude"], 40.1)
        self.assertEqual(atributos["longitude"], -3.5)


class TestUltimaActualizacionEsDatetime(unittest.TestCase):
    def test_es_datetime_con_zona_horaria_no_string(self) -> None:
        """I-04: antes se guardaba como string ISO (.isoformat()); ahora es
        un datetime con tzinfo, para que Home Assistant lo reconozca como
        fecha de verdad en vez de un string crudo a merced del frontend."""
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())
        camara._ultima_actualizacion = datetime.now(timezone.utc)
        valor = camara.extra_state_attributes["ultima_actualizacion"]
        self.assertIsInstance(valor, datetime)
        self.assertIsNotNone(valor.tzinfo)


class TestBackoff(unittest.TestCase):
    def test_espera_se_satura_en_backoff_max_seconds(self) -> None:
        """L-03: tras muchos fallos, la espera sigue acotada a
        BACKOFF_MAX_SECONDS (antes, el exponente crecía sin límite y
        calculaba un entero enorme en cada fallo, solo para descartarlo)."""
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())
        for _ in range(500):
            camara._registrar_fallo()

        espera = camara._reintentar_a_partir_de - time.monotonic()
        self.assertLessEqual(espera, const_mod.BACKOFF_MAX_SECONDS)
        self.assertGreater(espera, const_mod.BACKOFF_MAX_SECONDS - 5)

    def test_fallos_consecutivos_sigue_contando_de_verdad(self) -> None:
        """El contador en sí (para el log "fallo nº%d") no se toca, solo
        el exponente usado internamente para calcular la espera."""
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())
        for _ in range(15):
            camara._registrar_fallo()
        self.assertEqual(camara._fallos_consecutivos, 15)


class TestNombreEntidad(unittest.TestCase):
    def test_nombre_no_repite_la_carretera(self) -> None:
        """M-10: con has_entity_name=True, HA antepone el nombre del
        dispositivo (que ya incluye la carretera) al de la entidad."""
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())
        self.assertNotIn("A-1", camara._attr_name)


class TestAsyncAddedToHass(unittest.IsolatedAsyncioTestCase):
    """Sin esto, una cámara recién (re)creada -- tras CUALQUIER recarga de
    la entrada, no solo al cambiar el interruptor de mapa -- se queda
    "no disponible" (sin _cached_image) hasta que algo pida su foto de
    verdad, y mientras tanto desaparece del mapa nativo de Home Assistant
    aunque sus atributos de ubicación sean correctos: una entidad no
    disponible no expone extra_state_attributes."""

    async def test_pide_una_foto_en_segundo_plano_al_anadirse(self) -> None:
        camara = camera_mod.DgtTrafficCamera(_EntradaFalsa(), _camera_data())

        llamadas: list[object] = []

        def _async_create_task(coro):  # noqa: ANN001, ANN202 - stub
            llamadas.append(coro)
            return coro

        camara.hass = type("HassFalso", (), {"async_create_task": staticmethod(_async_create_task)})()

        pedida = False

        async def _async_camera_image_falso(*args, **kwargs):  # noqa: ANN002, ANN003
            nonlocal pedida
            pedida = True
            return None

        camara.async_camera_image = _async_camera_image_falso

        await camara.async_added_to_hass()

        self.assertEqual(len(llamadas), 1)
        await llamadas[0]
        self.assertTrue(pedida)


if __name__ == "__main__":
    unittest.main()
