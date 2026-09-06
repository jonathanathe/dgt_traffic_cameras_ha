"""Mensajes actuales de los paneles de mensaje variable (PMV) de la DGT.

Feed totalmente distinto del de ubicaciones (ver api.py): mismo estándar
DATEX2 v3.7, pero otro esquema (espacio de nombres "vms"), enlazado con las
ubicaciones por un simple id numérico de dispositivo — NO por un GUID.

Estructura real del XML (verificada con una descarga real, no asumida):

  vmsControllerStatus                    (uno por panel)
    vmsControllerReference[id]           (enlaza con el device_id de ubicaciones)
    vmsStatus > vmsStatus
      vmsMessage[messageIndex]           (una o más "páginas" del mensaje,
                                           pueden rotar mostrando cosas
                                           distintas, no son traducciones)
        vmsMessage
          timeLastSet
          displayAreaSettings[displayAreaIndex]   (una o más zonas del panel)
            displayAreaSettings[xsi:type=PictogramDisplay]
              pictogramDisplayUrl, pictogram > customPictogramCode ("0"=nada)
            displayAreaSettings[xsi:type=TextDisplay]
              textLine[lineIndex] > textLine > textLine   (texto con saltos
                                     de línea REALES \\n separando las líneas
                                     físicas del cartel; el símbolo "/" solo
                                     aparece a veces DENTRO de una línea para
                                     texto bilingüe en esa misma línea, no
                                     como separador de líneas)

Un panel "apagado" / sin mensaje real es aquel en el que NINGUNA página tiene
texto ni pictogramas distintos de "0".
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .const import XML_NAMESPACES

_LOGGER = logging.getLogger(__name__)

# Límite real de Home Assistant para el "state" de una entidad (ver
# homeassistant.core.MAX_LENGTH_STATE_STATE). Si se supera, HA lo rechaza
# y la entidad cae a "unknown"; mejor recortar nosotros con criterio.
MAX_STATE_LENGTH = 255


@dataclass
class PanelMessageState:
    """Lo que está mostrando un panel concreto, ya interpretado."""

    device_id: str
    text: str  # colapsado en una frase, recortado a MAX_STATE_LENGTH
    text_full: str  # colapsado en una frase, SIN recortar
    lines: list[str] = field(default_factory=list)  # líneas físicas de la página principal
    other_pages: list[str] = field(default_factory=list)  # texto colapsado de otras páginas, si las hay
    pictogram_codes: list[str] = field(default_factory=list)  # de la página principal, sin los "0"
    off: bool = False  # ninguna página tiene texto ni pictogramas
    last_set: str | None = None  # hora ISO del último cambio (página principal)


def parse_vms_messages(xml_bytes: bytes) -> dict[str, PanelMessageState]:
    """Convierte el XML de mensajes en un dict indexado por device_id.

    NOTA: síncrona a propósito, pensada para ejecutarse en un hilo aparte
    (ver coordinator.py) — con ~4 MB de XML, parsearla en el bucle de
    eventos congelaría Home Assistant entero durante el proceso.
    """
    root = ET.fromstring(xml_bytes)
    ns = XML_NAMESPACES

    estados: dict[str, PanelMessageState] = {}

    for status in root.iter(f"{{{ns['vms']}}}vmsControllerStatus"):
        ref = status.find(f"{{{ns['vms']}}}vmsControllerReference")
        device_id = ref.get("id") if ref is not None else None
        if not device_id:
            continue

        paginas = sorted(
            status.iter(f"{{{ns['vms']}}}vmsMessage"),
            key=lambda m: _indice_seguro(m.get("messageIndex")),
        )
        # "vms:vmsMessage" aparece dos veces anidado (el contenedor con
        # messageIndex y, dentro, el mensaje en sí); nos quedamos solo con
        # los que tienen el atributo, que son los contenedores de página.
        paginas = [p for p in paginas if p.get("messageIndex") is not None]

        if not paginas:
            continue

        paginas_parseadas = [_parse_pagina(p, ns) for p in paginas]
        principal = paginas_parseadas[0]
        otras = paginas_parseadas[1:]

        todo_vacio = all(
            not p["lines"] and not p["pictogram_codes"] for p in paginas_parseadas
        )

        texto_completo = " / ".join(principal["lines"])

        estados[device_id] = PanelMessageState(
            device_id=device_id,
            text=texto_completo[:MAX_STATE_LENGTH],
            text_full=texto_completo,
            lines=principal["lines"],
            other_pages=[
                " / ".join(p["lines"]) for p in otras if p["lines"] or p["pictogram_codes"]
            ],
            pictogram_codes=principal["pictogram_codes"],
            off=todo_vacio,
            last_set=principal["last_set"],
        )

    _LOGGER.debug("Mensajes de paneles DGT: %d paneles con estado", len(estados))
    return estados


def _parse_pagina(pagina_el: ET.Element, ns: dict[str, str]) -> dict:
    """Extrae líneas de texto, pictogramas y hora de una página (messageIndex)."""
    # El messageIndex está en el elemento contenedor; el contenido real va
    # anidado un nivel más adentro, en otro <vms:vmsMessage> sin atributos.
    contenido = pagina_el.find(f"{{{ns['vms']}}}vmsMessage")
    if contenido is None:
        return {"lines": [], "pictogram_codes": [], "last_set": None}

    last_set_el = contenido.find(f"{{{ns['vms']}}}timeLastSet")
    last_set = last_set_el.text.strip() if last_set_el is not None and last_set_el.text else None

    lines: list[str] = []
    pictogram_codes: list[str] = []

    for area in contenido.findall(f"{{{ns['vms']}}}displayAreaSettings"):
        area_tipo = area.find(f"{{{ns['vms']}}}displayAreaSettings")
        if area_tipo is None:
            continue

        # Zona de texto: el texto real está en tres niveles anidados de
        # <vms:textLine> (contenedor con lineIndex > mensaje > texto hoja).
        for text_line_el in area_tipo.findall(f"{{{ns['vms']}}}textLine"):
            hoja = text_line_el.find(f"{{{ns['vms']}}}textLine")
            if hoja is None:
                continue
            texto_el = hoja.find(f"{{{ns['vms']}}}textLine")
            if texto_el is None or not texto_el.text:
                continue
            # Las líneas físicas del cartel vienen separadas por saltos de
            # línea reales dentro de este único nodo de texto, NO por "/".
            for linea in texto_el.text.split("\n"):
                linea = linea.strip()
                if linea:
                    lines.append(linea)

        # Zona de pictograma: "0" significa "sin pictograma en esta zona".
        pictograma_el = area_tipo.find(f"{{{ns['vms']}}}pictogram")
        if pictograma_el is not None:
            codigo_el = pictograma_el.find(f"{{{ns['vms']}}}customPictogramCode")
            codigo = codigo_el.text.strip() if codigo_el is not None and codigo_el.text else None
            if codigo and codigo != "0":
                pictogram_codes.append(codigo)

    return {"lines": lines, "pictogram_codes": pictogram_codes, "last_set": last_set}


def _indice_seguro(valor: str | None) -> int:
    """Convierte messageIndex a int para poder ordenar páginas; 0 si falta."""
    try:
        return int(valor) if valor is not None else 0
    except ValueError:
        return 0
