"""Constantes de la integración 'Cámaras de tráfico DGT'.

Todo lo que pueda cambiar de sitio (URL del feed, intervalos, límites, etc.)
vive aquí para no tener que buscarlo dentro de la lógica de config_flow.py,
api.py o camera.py.
"""

from __future__ import annotations

# Identificador interno único de la integración dentro de Home Assistant.
# Debe coincidir con el campo "domain" de manifest.json.
DOMAIN = "dgt_traffic_cameras"

# ---------------------------------------------------------------------------
# Fuente de datos
# ---------------------------------------------------------------------------

# Feed oficial y público de la DGT (Punto de Acceso Nacional de Tráfico y
# Movilidad, nap.dgt.es) con el inventario de cámaras en formato DATEX II.
# No requiere API key. Verificado manualmente el 2026-09-05: cada <device>
# trae id, carretera, provincia, punto kilométrico, sentido, coordenadas y
# una URL de imagen fija en <fse:deviceUrl>.
#
# IMPORTANTE (limitación real de la fuente, no de esta integración):
# el feed NO incluye País Vasco ni Cataluña, porque la gestión de tráfico
# está transferida a sus propias administraciones.
CAMERA_INVENTORY_URL = (
    "https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v37.xml"
)

# Dominios desde los que aceptamos descargar imágenes de cámara.
#
# POR QUÉ ESTO EXISTE (seguridad): la URL de cada imagen no la elegimos
# nosotros, viene dentro del XML que descargamos de internet. Si ese feed
# estuviera comprometido o mal configurado, podría contener URLs apuntando
# a cualquier sitio, incluidos equipos de TU RED INTERNA (esto se llama
# ataque SSRF). Comprobando el dominio antes de pedir nada, Home Assistant
# solo hablará con servidores de la DGT y con nadie más.
ALLOWED_IMAGE_DOMAINS = (
    "dgt.es",
    "etraffic.dgt.es",
    "infocar.dgt.es",
    "nap.dgt.es",
)

# Espacios de nombres XML usados por el feed DATEX II de la DGT.
# Se necesitan porque el XML usa prefijos (ns2:, loc:, lse:, fse:, com:)
# y ElementTree exige la URI completa, no el prefijo, para hacer búsquedas.
XML_NAMESPACES = {
    "d2": "http://levelC/schema/3/d2Payload",
    "com": "http://levelC/schema/3/common",
    "loc": "http://levelC/schema/3/locationReferencing",
    "ns2": "http://levelC/schema/3/faultAndStatus",
    "lse": "http://levelC/schema/3/locationReferencingSpanishExtension",
    "fse": "http://levelC/schema/3/faultAndStatusSpanishExtension",
}

# Clave usada dentro de config_entry.data para guardar la lista de cámaras
# que el usuario ha seleccionado.
CONF_CAMERAS = "cameras"

# ---------------------------------------------------------------------------
# Control de frecuencia de peticiones (lo importante para no ser bloqueados)
# ---------------------------------------------------------------------------

# Intervalo mínimo entre descargas reales de una imagen para una misma
# cámara: 10 minutos.
#
# Aunque abras el panel y la tarjeta parpadee cada pocos segundos, la
# integración solo pedirá una foto nueva a la DGT cada 10 minutos por
# cámara. Entre medias sirve la última foto guardada en memoria, que es
# instantáneo y no genera ni una sola petición.
MIN_SECONDS_BETWEEN_IMAGE_FETCH = 600

# Cada cuánto le decimos a Home Assistant que "como mucho" tiene sentido
# refrescar la imagen. HA usa este valor para no pedir fotogramas más
# rápido de la cuenta. Lo alineamos con el intervalo de arriba para que
# el propio HA colabore en no generar peticiones de más.
FRAME_INTERVAL_SECONDS = float(MIN_SECONDS_BETWEEN_IMAGE_FETCH)

# --- Backoff: qué hacer cuando la DGT nos falla ---------------------------
#
# ESTE ES EL ARREGLO MÁS IMPORTANTE DE LA VERSIÓN 1.1.
#
# En la versión anterior, si la descarga fallaba NO se actualizaba el reloj
# del caché. Resultado: mientras la DGT estuviera caída o rechazándonos, el
# límite de "una petición cada X" desaparecía y se reintentaba en CADA
# refresco del panel. Con muchas cámaras eso son cientos de peticiones por
# minuto contra un servidor que ya nos está diciendo que no: la forma más
# rápida de que te bloqueen la IP.
#
# Ahora, tras cada fallo consecutivo se espera cada vez más antes de
# volver a intentarlo: 60s, 120s, 240s, 480s... hasta un tope de 1 hora.
BACKOFF_INITIAL_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
BACKOFF_MULTIPLIER = 2

# Tiempo máximo de espera por una respuesta HTTP antes de dar el intento
# por fallido.
HTTP_TIMEOUT_SECONDS = 15
# El inventario XML es un fichero grande, necesita más margen que una foto.
INVENTORY_TIMEOUT_SECONDS = 60

# --- Límites de tamaño (protección de memoria) ----------------------------
#
# Sin un tope, una respuesta anormalmente grande (por error del servidor o
# por manipulación) se cargaría entera en la RAM de tu Home Assistant.
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 15 MB: muy por encima de una foto normal
MAX_INVENTORY_BYTES = 100 * 1024 * 1024  # 100 MB: margen amplio para el XML

# Cuánto tiempo reutilizamos el inventario ya descargado en lugar de volver
# a bajarlo. Evita re-descargar varios MB cada vez que abres el diálogo de
# configuración o el de opciones.
INVENTORY_CACHE_SECONDS = 900  # 15 minutos

# ---------------------------------------------------------------------------
# Cabeceras HTTP
# ---------------------------------------------------------------------------

# Nos identificamos como un navegador porque algunos servidores de la
# administración responden distinto (o rechazan) al user-agent por defecto
# de la librería aiohttp. Esto es una mitigación, no una garantía: si el
# bloqueo fuese por IP o por volumen, esto no lo arreglaría.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cabeceras para pedir IMÁGENES.
IMAGE_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://etraffic.dgt.es/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# Cabeceras para pedir el INVENTARIO XML.
#
# En la versión anterior se reutilizaban las cabeceras de imagen también
# aquí, es decir, le pedíamos al servidor "quiero una imagen" cuando en
# realidad queríamos un XML. Funcionaba de milagro, gracias al "*/*" del
# final; un servidor más estricto habría respondido 406 Not Acceptable.
INVENTORY_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://nap.dgt.es/",
    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
}

# --- Cómo comprobamos que lo recibido es de verdad una foto ---------------
#
# EL PROBLEMA A EVITAR: si la DGT devuelve una página HTML de error pero con
# código 200 (habitual en portales de la administración), sin comprobar nada
# guardaríamos ese HTML en el caché COMO SI FUERA UNA FOTO.
#
# POR QUÉ NO BASTA CON MIRAR EL "Content-Type": muchos servidores sirven
# imágenes como "application/octet-stream", y algunos ni siquiera envían esa
# cabecera (en ese caso la librería aiohttp también dice
# "application/octet-stream"). Si exigiéramos que empezara por "image/"
# estaríamos rechazando fotos perfectamente válidas y activando el freno de
# emergencia sin motivo.
#
# LA SOLUCIÓN: rechazamos de entrada solo los tipos que sabemos seguro que
# NO son una imagen (HTML, JSON, texto...), y para todo lo demás miramos los
# primeros bytes del fichero. Cada formato de imagen empieza por una "firma"
# reconocible, y eso no se puede falsear con una cabecera mal puesta.
REJECTED_CONTENT_TYPE_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
)

# Firmas ("números mágicos") de los formatos de imagen habituales.
IMAGE_MAGIC_BYTES = (
    b"\xff\xd8\xff",      # JPEG  <- el que usa la DGT
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"GIF87a",            # GIF
    b"GIF89a",            # GIF
    b"BM",                # BMP
)
# WEBP y AVIF necesitan mirar también unos bytes más adelante, por eso van
# aparte: su cabecera es "RIFF....WEBP" / "....ftypavif".
IMAGE_MAGIC_OFFSET_CHECKS = (
    (0, b"RIFF", 8, b"WEBP"),
    (4, b"ftyp", 8, b"avif"),
)

# --- Imagen de "no disponible" de la propia DGT ----------------------------
#
# Cuando una cámara está averiada o retirada, la DGT no devuelve un error:
# responde con un JPEG válido de verdad, siempre el mismo, con el dibujo de
# un carrete de película y el texto "IMAGEN NO DISPONIBLE". Como es una
# imagen legítima, la comprobación de "¿esto parece una foto?" la deja
# pasar, y sin este chequeo la guardaríamos en el caché como si fuera la
# foto real de la carretera.
#
# Al ser siempre el fichero exacto (comprobado: los metadatos EXIF llevan
# fechas fijas de 2015/2025, no se generan al vuelo), se puede reconocer con
# total fiabilidad calculando su hash SHA-256 y comparándolo, en vez de
# fiarse del tamaño en bytes, que si varía según la cámara o la hora del día.
PLACEHOLDER_IMAGE_SHA256_HASHES = frozenset(
    {
        # "Imagen no disponible" (carrete de película sobre fondo gris),
        # variante servida con más compresión (~32 KB).
        "e8703ff5957fa4136be7c39ef1bc8c61d7d2c54a46537791a1fb08467145cdb3",
        # Misma imagen, variante servida con menos compresión (~9 KB). La
        # DGT no siempre sirve el mismo fichero exacto para este aviso, así
        # que además del hash exacto (rápido, pero solo pilla variantes ya
        # vistas) se comprueba también un hash "perceptual" más abajo, que
        # detecta cualquier otra variante nueva sin tener que añadirla aquí.
        "3b6ace4fb0afcd5eeae11ec27659946fa2028b3fc87ec5fd1878a3057e71b1d",
    }
)

# Hash perceptual (aHash de 16x16 en escala de grises) de la imagen de "no
# disponible" de arriba. A diferencia del SHA-256, es el mismo aunque el
# fichero cambie de compresión o de calidad JPEG, porque compara el
# ASPECTO de la imagen, no sus bytes exactos.
#
# Cómo se calculó: convertir a escala de grises, reducir a 16x16 píxeles,
# y por cada píxel poner un "1" si es más claro que la media de la imagen
# o un "0" si no. Los 256 bits resultantes, leídos como un único número.
PLACEHOLDER_IMAGE_AHASH = int(
    "ffffffffffffffffc9ffc1ffc83fc83fc007c007c9ffffffffffffffffffffff", 16
)

# Cuántos de esos 256 bits pueden diferir como máximo para seguir
# considerando que es la misma imagen. Las dos variantes reales que hemos
# visto dan distancia 0 entre sí; un margen de 16 bits (~6%) da colchón
# para variaciones de compresión sin arriesgarse a confundir una foto de
# carretera de verdad (que da una distancia altísima, cientos de bits)
# con el aviso de "no disponible".
PLACEHOLDER_IMAGE_AHASH_MAX_DISTANCE = 16
