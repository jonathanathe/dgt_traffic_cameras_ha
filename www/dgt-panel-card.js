/**
 * Tarjeta de Lovelace personalizada para paneles de mensaje variable (PMV)
 * de la integración "Cámaras de tráfico DGT".
 *
 * Reproduce visualmente el cartel tal y como lo muestra la propia DGT en
 * su visor oficial (fondo del panel, pictograma a la izquierda, texto
 * amarillo monoespaciado centrado), a partir de los atributos que ya
 * expone la entidad sensor.* del panel: "carretera", "punto_kilometrico",
 * "sentido_hacia" y "lineas". El pictograma se toma de entity_picture,
 * que Home Assistant ya calcula solo (ver sensor.py).
 *
 * SEGURIDAD: el texto del cartel viene, en última instancia, de un XML que
 * descarga la integración desde internet. Por eso todo el contenido
 * dinámico se escribe con textContent (nunca con innerHTML ni
 * interpolación de cadenas), para que un feed manipulado no pueda inyectar
 * HTML o JavaScript en el dashboard.
 *
 * Instalación: copia este fichero a config/www/dgt-panel-card.js y añádelo
 * como recurso en Configuración > Paneles de control > Recursos (tipo
 * "Módulo JavaScript", URL "/local/dgt-panel-card.js"). Después, en
 * cualquier dashboard, añade una tarjeta de tipo "Custom: DGT Panel Card"
 * (o en YAML: type: custom:dgt-panel-card, entity: sensor.tu_panel).
 */

const URL_ICONO_CABECERA =
  "https://etraffic.dgt.es/estaticosEtraffic/Iconografia/iconos/pmv.png";
const URL_FONDO_CARTEL =
  "https://etraffic.dgt.es/estaticosEtraffic/Iconografia/iconografiaGeneral/panel_cms.png";

// Datos de mentira para cuando la tarjeta se muestra sin una entidad
// configurada (por ejemplo, en la vista previa del selector de tarjetas
// de Lovelace), para que se vea un ejemplo real en vez de un error.
const DATOS_DEMO = {
  carretera: "Ma-19",
  punto_kilometrico: "8.92",
  sentido_hacia: "Llucmajor",
  entity_picture:
    "https://etraffic.dgt.es/estaticosEtraffic/Iconografia/pictogramas/XE90a.png",
  lineas: ["S.NOGUERA  9m", "LLUCMAJOR 10m", "CAMPOS   16m"],
};

class DgtPanelCard extends HTMLElement {
  setConfig(config) {
    // No hace falta "entity" para poder configurarse: sin ella, la
    // tarjeta se muestra con datos de ejemplo (ver DATOS_DEMO) en vez de
    // dar un error. Esto es lo que permite que el selector de tarjetas de
    // Lovelace pueda mostrar una vista previa en vivo antes de elegirla.
    this._config = config || {};
    this._construida = false;
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    return null;
  }

  static getStubConfig(hass, entities) {
    // Si el usuario ya tiene algún panel configurado, se usa uno real de
    // verdad para la vista previa (se detecta por tener el atributo
    // "punto_kilometrico", propio de esta integración). Si no hay
    // ninguno todavía, se deja sin entidad: la tarjeta usará DATOS_DEMO.
    const candidato = (entities || []).find((entityId) => {
      const estado = hass && hass.states && hass.states[entityId];
      return Boolean(estado && estado.attributes && "punto_kilometrico" in estado.attributes);
    });
    return { entity: candidato || "" };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._construida) {
      this._construirEsqueleto();
      this._construida = true;
    }
    this._actualizar();
  }

  _construirEsqueleto() {
    // Solo la ESTRUCTURA es HTML fijo, sin ningún dato del feed dentro.
    this.innerHTML = `
      <ha-card>
        <style>
          .dgt-panel-card { padding: 12px 16px 16px; }
          .dgt-panel-header {
            display: flex;
            align-items: center;
            justify-content: center;
            flex-wrap: wrap;
            gap: 0.3rem;
            font-size: 14px;
            color: var(--primary-text-color);
          }
          .dgt-panel-header img { height: 22px; width: 22px; }
          .dgt-panel-header .valor { color: rgb(171, 48, 0); font-weight: 600; }
          .dgt-panel-sign {
            margin-top: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-radius: 6px;
            background-image: url("${URL_FONDO_CARTEL}");
            background-repeat: no-repeat;
            background-size: contain;
            background-position: center center;
            width: 100%;
            height: 100px;
          }
          .dgt-panel-pictograma,
          .dgt-panel-hueco {
            width: 60px;
            text-align: center;
            flex-shrink: 0;
          }
          .dgt-panel-pictograma img {
            height: 42px;
            max-width: 90%;
            object-fit: contain;
          }
          .dgt-panel-texto {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: rgb(255, 215, 0);
            font-family: "Courier New", monospace;
            font-weight: 600;
            font-size: 13px;
            text-align: center;
            line-height: 1.3;
          }
          .dgt-panel-sin-mensaje {
            color: rgba(255, 215, 0, 0.35);
            font-family: "Courier New", monospace;
            font-size: 12px;
          }
        </style>
        <div class="dgt-panel-card">
          <div class="dgt-panel-header">
            <img src="${URL_ICONO_CABECERA}" alt="PMV">
            <b>Carretera</b><span class="valor campo-carretera"></span>
            <b>km</b><span class="valor campo-km"></span>
            <b>Sentido</b><span class="valor campo-sentido"></span>
          </div>
          <div class="dgt-panel-sign">
            <div class="dgt-panel-pictograma"><img class="campo-pictograma" hidden></div>
            <div class="dgt-panel-texto campo-texto"></div>
            <div class="dgt-panel-hueco"></div>
          </div>
        </div>
      </ha-card>
    `;

    this._elCarretera = this.querySelector(".campo-carretera");
    this._elKm = this.querySelector(".campo-km");
    this._elSentido = this.querySelector(".campo-sentido");
    this._elPictograma = this.querySelector(".campo-pictograma");
    this._elTexto = this.querySelector(".campo-texto");
  }

  _actualizar() {
    const entityId = this._config.entity;

    let atributos;
    if (!entityId) {
      // Sin entidad configurada: vista previa con datos de ejemplo (esto
      // es lo que se ve en el selector de tarjetas de Lovelace).
      atributos = DATOS_DEMO;
    } else {
      const estado = this._hass.states[entityId];
      if (!estado) {
        this._elTexto.textContent = `Entidad no encontrada: ${entityId}`;
        return;
      }
      atributos = estado.attributes || {};
    }

    // textContent en todos los campos que vienen del feed: nunca HTML.
    this._elCarretera.textContent = atributos.carretera || "?";
    this._elKm.textContent = atributos.punto_kilometrico || "?";
    this._elSentido.textContent = atributos.sentido_hacia || "?";

    const urlPictograma = atributos.entity_picture || null;
    if (urlPictograma) {
      this._elPictograma.src = urlPictograma;
      this._elPictograma.hidden = false;
    } else {
      this._elPictograma.removeAttribute("src");
      this._elPictograma.hidden = true;
    }

    // Vaciar y reconstruir las líneas de texto con textContent + <br>
    // reales (elementos DOM, no una cadena con \n insertada en innerHTML).
    this._elTexto.textContent = "";
    const lineas = Array.isArray(atributos.lineas) ? atributos.lineas : [];
    if (lineas.length === 0) {
      const span = document.createElement("span");
      span.className = "dgt-panel-sin-mensaje";
      span.textContent = atributos.apagado === false ? "" : "Sin mensaje";
      this._elTexto.appendChild(span);
      return;
    }

    lineas.forEach((linea, indice) => {
      if (indice > 0) {
        this._elTexto.appendChild(document.createElement("br"));
      }
      this._elTexto.appendChild(document.createTextNode(linea));
    });
  }
}

customElements.define("dgt-panel-card", DgtPanelCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dgt-panel-card",
  name: "DGT Panel Card",
  description:
    "Muestra un panel de mensaje variable de la DGT con el mismo aspecto que el visor oficial.",
});
