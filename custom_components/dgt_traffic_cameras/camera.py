"""Plataforma 'camera' de la integración.

Cada cámara elegida en el config_flow se convierte en una entidad Camera.
No hay vídeo: la DGT publica fotos fijas que se renuevan cada pocos minutos.

CÓMO SE PROTEGE AL SERVIDOR DE LA DGT (importante):

  1. Caché normal: una foto nueva como mucho cada 10 minutos por cámara.
     Aunque el panel refresque la tarjeta cada pocos segundos, entre medias
     se sirve la copia guardada en memoria, sin pedir nada por internet.

  2. Caché condicional (ETag / Last-Modified): cuando toca refrescar, le
     preguntamos al servidor "¿ha cambiado desde la última vez?". Si no ha
     cambiado responde 304, que son unos pocos bytes en lugar de la foto
     entera.

  3. Backoff ante fallos: si la DGT falla, se espera cada vez más antes de
     reintentar (60s, 120s, 240s... hasta 1 hora). Esto es lo que evita que
     un servidor caído provoque una tormenta de reintentos por nuestra parte.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import time

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from PIL import Image

from .api import is_allowed_image_url
from .const import (
    BACKOFF_INITIAL_SECONDS,
    BACKOFF_MAX_SECONDS,
    BACKOFF_MULTIPLIER,
    CONF_CAMERAS,
    DOMAIN,
    FRAME_INTERVAL_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    IMAGE_HEADERS,
    IMAGE_MAGIC_BYTES,
    IMAGE_MAGIC_OFFSET_CHECKS,
    MAX_IMAGE_BYTES,
    MIN_SECONDS_BETWEEN_IMAGE_FETCH,
    PLACEHOLDER_IMAGE_AHASH,
    PLACEHOLDER_IMAGE_AHASH_MAX_DISTANCE,
    PLACEHOLDER_IMAGE_SHA256_HASHES,
    REJECTED_CONTENT_TYPE_PREFIXES,
)

_LOGGER = logging.getLogger(__name__)

# Marcador interno para distinguir tres resultados distintos al descargar:
#   - unos bytes  -> hemos bajado una foto nueva
#   - _SIN_CAMBIOS -> el servidor dice que la foto no ha cambiado (304)
#   - None         -> ha fallado
_SIN_CAMBIOS = object()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea una entidad Camera por cada cámara guardada en la ConfigEntry."""
    cameras_data = entry.data.get(CONF_CAMERAS, [])

    # Protección contra duplicados DENTRO de la misma entrada: si por
    # cualquier motivo la configuración guardada contuviera la misma cámara
    # dos veces, crearíamos dos entidades pidiendo la misma foto al doble
    # de ritmo. Nos quedamos con la primera aparición de cada device_id.
    vistas: set[str] = set()
    entities: list[DgtTrafficCamera] = []
    for camera_data in cameras_data:
        device_id = camera_data.get("device_id")
        if not device_id or device_id in vistas:
            continue
        vistas.add(device_id)
        entities.append(DgtTrafficCamera(entry, camera_data))

    async_add_entities(entities)


class DgtTrafficCamera(Camera):
    """Una cámara individual de tráfico de la DGT."""

    _attr_has_entity_name = True
    # Debe ser un CameraEntityFeature (IntFlag), no un int plano: el propio
    # componente 'camera' de HA hace comprobaciones tipo
    # "CameraEntityFeature.STREAM not in self.supported_features", y eso
    # revienta con TypeError si aquí hay un int normal en vez de un IntFlag.
    _attr_supported_features = CameraEntityFeature(0)  # sin stream

    # Icono que se muestra en las listas de entidades y en las tarjetas
    # cuando todavía no hay imagen cargada. "cctv" es el de una cámara de
    # vigilancia, más adecuado que la videocámara genérica por defecto.
    _attr_icon = "mdi:cctv"

    def __init__(self, entry: ConfigEntry, camera_data: dict) -> None:
        super().__init__()
        self._entry = entry
        self._camera_data = camera_data
        self._image_url: str = camera_data["image_url"]

        device_id = camera_data["device_id"]
        # NOTA: el unique_id incluye entry_id por motivos históricos. NO se
        # cambia a propósito: modificarlo haría que Home Assistant tratara
        # estas cámaras como entidades nuevas, perdiendo los entity_id
        # actuales y rompiendo las tarjetas del panel ya configuradas.
        self._attr_unique_id = f"{entry.entry_id}_{device_id}"
        self._attr_name = camera_data.get("name") or f"Cámara DGT {device_id}"

        if (
            camera_data.get("latitude") is not None
            and camera_data.get("longitude") is not None
        ):
            self._attr_extra_state_attributes = {
                "carretera": camera_data.get("road_name"),
                "sentido_hacia": camera_data.get("road_destination"),
                "provincia": camera_data.get("province"),
                "punto_kilometrico": camera_data.get("kilometer_point"),
                "latitude": camera_data.get("latitude"),
                "longitude": camera_data.get("longitude"),
            }

        # Agrupa todas las cámaras de esta ConfigEntry bajo un mismo
        # "dispositivo" en Home Assistant.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Dirección General de Tráfico (DGT)",
            model="Cámara de tráfico DATEX II",
            configuration_url="https://nap.dgt.es/dataset",
        )

        # --- Estado del caché en memoria ---
        self._cached_image: bytes | None = None
        self._cached_at: float = 0.0
        self._fetch_lock = asyncio.Lock()

        # Validadores para la caché condicional. Los guarda el servidor y
        # se los devolvemos para que nos diga si la foto ha cambiado.
        self._etag: str | None = None
        self._last_modified: str | None = None

        # --- Estado del backoff ---
        # Número de fallos consecutivos y momento a partir del cual se
        # permite volver a intentarlo.
        self._fallos_consecutivos = 0
        self._reintentar_a_partir_de: float = 0.0

    @property
    def frame_interval(self) -> float:
        """Segundos que HA debe esperar entre fotogramas."""
        return FRAME_INTERVAL_SECONDS

    @property
    def available(self) -> bool:
        """False mientras no tengamos ninguna foto real guardada.

        Cubre dos casos: no se ha podido conectar todavía (red, timeout...),
        y la DGT ha respondido con su imagen de "no disponible" (ver
        _async_descargar_imagen). En ambos, sin esto, Home Assistant
        mostraría la tarjeta de la cámara con un icono de imagen rota en
        lugar de marcarla claramente como no disponible.
        """
        return self._cached_image is not None

    def _registrar_fallo(self) -> None:
        """Aumenta el contador de fallos y calcula cuándo reintentar.

        Cada fallo consecutivo duplica la espera: 60s, 120s, 240s, 480s...
        con un tope de 1 hora. Mientras tanto, async_camera_image devuelve
        la última foto buena sin tocar la red.
        """
        self._fallos_consecutivos += 1
        espera = min(
            BACKOFF_INITIAL_SECONDS
            * (BACKOFF_MULTIPLIER ** (self._fallos_consecutivos - 1)),
            BACKOFF_MAX_SECONDS,
        )
        self._reintentar_a_partir_de = time.monotonic() + espera
        _LOGGER.debug(
            "Cámara %s: fallo nº%d, no se reintentará hasta dentro de %ss",
            self._attr_name,
            self._fallos_consecutivos,
            espera,
        )

    def _registrar_exito(self) -> None:
        """Reinicia el backoff tras una descarga correcta."""
        self._fallos_consecutivos = 0
        self._reintentar_a_partir_de = 0.0

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Devuelve la última instantánea, descargándola solo si toca."""
        async with self._fetch_lock:
            ahora = time.monotonic()

            # 1) ¿La copia en memoria sigue siendo suficientemente reciente?
            if (
                self._cached_image is not None
                and (ahora - self._cached_at) < MIN_SECONDS_BETWEEN_IMAGE_FETCH
            ):
                return self._cached_image

            # 2) ¿Estamos en periodo de penalización por fallos previos?
            #    Si es así, ni siquiera intentamos conectar. Esto es lo que
            #    impide la tormenta de reintentos que había antes.
            if ahora < self._reintentar_a_partir_de:
                return self._cached_image

            # 3) Comprobación de seguridad antes de cada descarga: la URL
            #    guardada podría venir de una configuración antigua.
            if not is_allowed_image_url(self._image_url):
                _LOGGER.error(
                    "Cámara %s: la URL guardada (%s) no es HTTPS de un dominio "
                    "de la DGT; no se descargará. Vuelve a añadir la cámara.",
                    self._attr_name,
                    self._image_url,
                )
                self._registrar_fallo()
                return self._cached_image

            disponible_antes = self._cached_image is not None

            imagen = await self._async_descargar_imagen()
            if imagen is None:
                # _async_descargar_imagen ya registró el fallo y el motivo.
                return self._cached_image

            self._registrar_exito()
            self._cached_at = ahora
            if imagen is not _SIN_CAMBIOS:
                self._cached_image = imagen

            # Las entidades "camera" no se sondean solas (should_poll es
            # False): si no avisamos aquí, Home Assistant nunca vuelve a
            # mirar la propiedad "available", y la entidad se queda
            # congelada en "No disponible" desde el arranque aunque ya
            # tengamos una foto real guardada.
            if not disponible_antes and self._cached_image is not None:
                self.async_write_ha_state()

            return self._cached_image

    async def _async_descargar_imagen(self) -> bytes | None | object:
        """Descarga la foto. Devuelve los bytes, _SIN_CAMBIOS, o None si falla."""
        session = async_get_clientsession(self.hass)

        # Caché condicional: si ya tenemos una foto, le preguntamos al
        # servidor si ha cambiado en lugar de pedirla entera otra vez.
        headers = dict(IMAGE_HEADERS)
        if self._cached_image is not None:
            if self._etag:
                headers["If-None-Match"] = self._etag
            if self._last_modified:
                headers["If-Modified-Since"] = self._last_modified

        try:
            async with asyncio.timeout(HTTP_TIMEOUT_SECONDS):
                async with session.get(self._image_url, headers=headers) as response:
                    # 304 = "no ha cambiado nada". No hay cuerpo que leer;
                    # nos quedamos con la foto que ya teníamos y, sobre
                    # todo, no hemos gastado ancho de banda.
                    if response.status == 304:
                        _LOGGER.debug(
                            "Cámara %s: sin cambios (304)", self._attr_name
                        )
                        return _SIN_CAMBIOS

                    response.raise_for_status()

                    # Rechazo rápido: si el servidor nos anuncia claramente
                    # que esto NO es una imagen (una página de error HTML,
                    # un JSON...), cortamos sin descargar el cuerpo.
                    #
                    # Ojo: NO exigimos que diga "image/", porque muchos
                    # servidores sirven fotos como "application/octet-stream"
                    # o directamente no envían la cabecera. Exigirlo
                    # rechazaría imágenes buenas. La comprobación de verdad
                    # se hace más abajo, mirando los bytes del fichero.
                    content_type = (response.content_type or "").lower()
                    if content_type.startswith(REJECTED_CONTENT_TYPE_PREFIXES):
                        _LOGGER.warning(
                            "Cámara %s: el servidor devolvió '%s' en lugar de "
                            "una imagen; se descarta la respuesta",
                            self._attr_name,
                            content_type,
                        )
                        self._registrar_fallo()
                        return None

                    # Límite de tamaño anunciado.
                    declarado = response.content_length
                    if declarado is not None and declarado > MAX_IMAGE_BYTES:
                        _LOGGER.warning(
                            "Cámara %s: imagen demasiado grande (%d bytes), "
                            "se descarta",
                            self._attr_name,
                            declarado,
                        )
                        self._registrar_fallo()
                        return None

                    # Lectura por trozos con tope real, por si el servidor
                    # no declara el tamaño o miente.
                    trozos: list[bytes] = []
                    total = 0
                    async for trozo in response.content.iter_chunked(64 * 1024):
                        total += len(trozo)
                        if total > MAX_IMAGE_BYTES:
                            _LOGGER.warning(
                                "Cámara %s: la descarga superó %d bytes, se aborta",
                                self._attr_name,
                                MAX_IMAGE_BYTES,
                            )
                            self._registrar_fallo()
                            return None
                        trozos.append(trozo)

                    if total == 0:
                        _LOGGER.warning(
                            "Cámara %s: el servidor devolvió una imagen vacía",
                            self._attr_name,
                        )
                        self._registrar_fallo()
                        return None

                    datos = b"".join(trozos)

                    # Comprobación definitiva: ¿los primeros bytes son los de
                    # una imagen de verdad? Esto no se puede falsear con una
                    # cabecera mal configurada, y pilla el caso de la página
                    # de error HTML servida con código 200.
                    if not _parece_imagen(datos):
                        _LOGGER.warning(
                            "Cámara %s: la respuesta no parece una imagen "
                            "(empieza por %r); se descarta",
                            self._attr_name,
                            datos[:16],
                        )
                        self._registrar_fallo()
                        return None

                    # La DGT devuelve, con código 200 y un JPEG válido de
                    # verdad, su propia imagen de "no disponible" cuando la
                    # cámara está averiada. Hay que descartarla igual que un
                    # fallo de red: si no, se guardaría en el caché como si
                    # fuera la foto real de la carretera.
                    #
                    # Primero el hash exacto (rápido, no hace falta decodificar
                    # la imagen) y, si no coincide, el hash perceptual (más
                    # lento pero detecta esta misma imagen aunque la DGT la
                    # sirva con otra compresión, como ya nos ha pasado).
                    if hashlib.sha256(
                        datos
                    ).hexdigest() in PLACEHOLDER_IMAGE_SHA256_HASHES or await self.hass.async_add_executor_job(
                        _es_imagen_no_disponible, datos
                    ):
                        _LOGGER.debug(
                            "Cámara %s: la DGT devolvió su imagen de "
                            "'no disponible'; se trata como un fallo",
                            self._attr_name,
                        )
                        self._registrar_fallo()
                        return None

                    # Guardamos los validadores para la próxima vez.
                    self._etag = response.headers.get("ETag")
                    self._last_modified = response.headers.get("Last-Modified")

                    return datos

        except TimeoutError:
            _LOGGER.warning(
                "Cámara %s: el servidor de la DGT no respondió en %ss",
                self._attr_name,
                HTTP_TIMEOUT_SECONDS,
            )
            self._registrar_fallo()
            return None
        except Exception as err:  # noqa: BLE001
            # Se registra el motivo exacto (código HTTP, error de conexión...)
            # porque "no se pudo descargar" a secas no sirve para diagnosticar.
            _LOGGER.warning(
                "Cámara %s: no se pudo descargar la imagen (%s): %s",
                self._attr_name,
                self._image_url,
                err,
            )
            self._registrar_fallo()
            return None



def _parece_imagen(datos: bytes) -> bool:
    """Comprueba si unos bytes empiezan por la firma de un formato de imagen.

    Cada formato de imagen arranca con una secuencia de bytes característica
    (los llamados "números mágicos"). Un JPEG siempre empieza por FF D8 FF,
    un PNG por 89 50 4E 47... Una página HTML de error empezaría por "<!DOC"
    o "<html", que no coincide con ninguna, y así la detectamos.
    """
    if len(datos) < 12:
        return False

    if datos.startswith(IMAGE_MAGIC_BYTES):
        return True

    # Formatos cuya firma está partida en dos sitios (WEBP, AVIF).
    for pos1, firma1, pos2, firma2 in IMAGE_MAGIC_OFFSET_CHECKS:
        if (
            datos[pos1 : pos1 + len(firma1)] == firma1
            and datos[pos2 : pos2 + len(firma2)] == firma2
        ):
            return True

    return False


def _calcular_ahash(datos: bytes, tamano: int = 16) -> int:
    """Calcula el hash perceptual (average hash) de una imagen.

    Reduce la imagen a una cuadrícula de tamano x tamano en escala de
    grises y anota, píxel a píxel, si es más claro o más oscuro que la
    media. El resultado son tamano*tamano bits que describen el ASPECTO
    general de la imagen, no sus bytes exactos: dos imágenes casi iguales
    (por ejemplo la misma foto con distinta compresión JPEG) dan un hash
    idéntico o casi idéntico, a diferencia de un hash criptográfico como
    SHA-256, que cambiaría por completo con solo un byte distinto.

    Esta función hace trabajo de CPU (decodificar la imagen), así que
    SIEMPRE se llama desde un hilo aparte (hass.async_add_executor_job),
    nunca directamente desde el bucle de eventos.
    """
    with Image.open(io.BytesIO(datos)) as img:
        gris = img.convert("L").resize((tamano, tamano), Image.LANCZOS)
        pixeles = list(gris.getdata())

    media = sum(pixeles) / len(pixeles)
    bits = "".join("1" if p >= media else "0" for p in pixeles)
    return int(bits, 2)


def _es_imagen_no_disponible(datos: bytes) -> bool:
    """¿Son estos bytes una variante de la imagen "no disponible" de la DGT?

    Compara el hash perceptual de la imagen descargada con el de la imagen
    de referencia (ver PLACEHOLDER_IMAGE_AHASH en const.py) contando en
    cuántos de los 256 bits difieren (distancia de Hamming). Una foto de
    carretera real, al ser visualmente muy distinta, da una distancia
    altísima; esta misma imagen con otra compresión da una distancia muy
    baja o nula.

    Si la imagen no se puede decodificar (formato raro, fichero corrupto...)
    se asume que NO es el aviso de "no disponible": ya la ha aceptado antes
    _parece_imagen, así que lo prudente es tratarla como una foto real en
    vez de descartarla por un fallo al decodificarla.
    """
    try:
        hash_actual = _calcular_ahash(datos)
    except Exception:  # noqa: BLE001 - cualquier fallo al decodificar cuenta como "no es el aviso"
        _LOGGER.debug(
            "No se pudo calcular el hash perceptual de la imagen descargada",
            exc_info=True,
        )
        return False

    distancia = bin(hash_actual ^ PLACEHOLDER_IMAGE_AHASH).count("1")
    return distancia <= PLACEHOLDER_IMAGE_AHASH_MAX_DISTANCE

    return False
