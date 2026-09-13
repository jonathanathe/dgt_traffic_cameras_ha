# Cámaras de tráfico DGT para Home Assistant

Integración personalizada que añade las cámaras de tráfico y los paneles de mensaje variable (PMV) de la Dirección General de Tráfico (DGT) a Home Assistant, con un selector guiado por provincia y carretera.

> **Proyecto no oficial.** No está afiliado, patrocinado ni respaldado por la DGT. Únicamente consume datos publicados en abierto.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jonathanathe&repository=dgt_traffic_cameras_ha&category=integration)

---

## Qué hace

- Descarga los datos públicos de la DGT (formato DATEX II, sin necesidad de clave de API): el inventario de cámaras y, por separado, la ubicación y los mensajes de los paneles de mensaje variable (PMV).
- Te deja elegir, en el mismo asistente guiado, entre **cámaras** o **paneles**, y dentro de cada tipo en varios pasos: **provincia → carretera → dispositivos concretos → mostrar en el mapa**.
- Crea una entidad `camera.*` por cada cámara seleccionada, con su carretera, punto kilométrico y sentido como atributos, más sus coordenadas si has dejado activado "mostrar en el mapa" para esa cámara.
- Crea una entidad `sensor.*` por cada panel seleccionado, con el mensaje que está mostrando ahora mismo como estado, y como atributos el texto completo, sus líneas por separado, los pictogramas activos, si está apagado y la hora del último cambio. Si el panel tiene un pictograma activo (velocidad controlada, obras, etc.), la entidad muestra el icono real de la DGT para ese pictograma en vez de un icono genérico.
- Deja añadir o quitar dispositivos de una entrada ya creada desde **Opciones**, sin tener que volver a montarla desde cero.
- Incluye, como pieza opcional, una tarjeta de Lovelace básica ([`custom_components/dgt_traffic_cameras/frontend/dgt-panel-card.js`](custom_components/dgt_traffic_cameras/frontend/dgt-panel-card.js)) que dibuja el cartel de un panel con el mismo aspecto que el visor oficial de la DGT. Para algo más completo (cámara + panel combinados, con navegación entre varias cámaras), existe también [**camera-card-slide**](https://github.com/jonathanathe/camera-card-slide), en un repositorio aparte.

La DGT publica **instantáneas fijas** de las cámaras, no vídeo en directo: cada foto se renueva unas pocas veces por hora en origen. Los mensajes de los paneles se comprueban cada 5 minutos con una única descarga compartida por todos los paneles configurados, tengas 1 o 100.

## Qué **no** hace

- **No incluye País Vasco ni Cataluña.** No es una limitación de la integración: esas comunidades tienen la gestión de tráfico transferida a sus propias administraciones y ni sus cámaras ni sus paneles están en los feeds de la DGT.
- **No hay vídeo ni grabación.** Solo la última imagen disponible de cada cámara.
- No almacena ni redistribuye imágenes: cada instalación las descarga directamente de los servidores de la DGT.
- **No detecta averías de los paneles.** El feed actual de la DGT no incluye ningún indicador de fallo del propio panel; solo se puede saber si un panel no está emitiendo ningún mensaje ahora mismo (se refleja como "sin mensaje" o "sin datos", no como avería).

---

## Instalación

### Manual

1. Descarga la última versión desde la sección [Releases](../../releases).
2. Copia la carpeta `custom_components/dgt_traffic_cameras` dentro de la carpeta `config/custom_components/` de tu Home Assistant.
3. Reinicia Home Assistant.
4. Ve a **Ajustes → Dispositivos y servicios → Añadir integración** y busca **Cámaras de tráfico DGT**.

### HACS (repositorio personalizado)

1. En HACS, abre el menú de los tres puntos → **Repositorios personalizados**.
2. Añade la URL de este repositorio con la categoría **Integration**.
3. Instálala desde la lista y reinicia Home Assistant.

## Configuración

Todo se hace desde la interfaz, no hace falta tocar YAML.

Al añadir la integración (**Ajustes → Dispositivos y servicios → Añadir integración → Cámaras de tráfico DGT**), lo primero es elegir qué quieres añadir:

- **Cámaras de tráfico (imágenes)**
- **Paneles de mensaje variable (texto)**

A partir de ahí el asistente es igual para los dos tipos:

1. **Provincia** — desplegable con las provincias que tienen dispositivos de ese tipo disponibles.
2. **Carretera** — las vías de esa provincia.
3. **Cámaras** o **Paneles** — lista con casillas, ordenada por punto kilométrico.
4. **Mostrar en el mapa** — si quieres que los dispositivos que acabas de elegir aparezcan en el mapa nativo de Home Assistant (ver [Mostrar en el mapa de Home Assistant](#mostrar-en-el-mapa-de-home-assistant)).

Cada combinación de provincia + carretera + tipo crea una entrada propia, que agrupa sus dispositivos bajo un mismo dispositivo de Home Assistant. Una misma entrada nunca mezcla cámaras y paneles.

**Al añadir una entrada de paneles por primera vez, puede tardar unos segundos (normalmente 5-15s) en terminar de cargar.** Antes de crear las entidades, se descarga y procesa el fichero de mensajes de todos los paneles de España (~4 MB); es intencionado — así, si esa primera descarga fallara, Home Assistant lo detecta y reintenta solo en vez de dejar la entrada creada sin ningún dato. Las siguientes veces no hace falta esperar: esa descarga se comparte entre todas las entradas de paneles y se repite sola cada 5 minutos en segundo plano.

### Añadir o quitar dispositivos de una entrada ya creada

Usa el botón de **Opciones** (el engranaje) de esa entrada. Si es una entrada de cámaras, te ofrece **Añadir cámaras** / **Quitar cámaras**; si es de paneles, **Añadir paneles** / **Quitar paneles** (además de las opciones para el mapa, ver más abajo). Para una carretera o provincia distinta, añade una nueva entrada desde cero.

Al quitar un dispositivo, su entidad se elimina por completo de Home Assistant (no se queda como "no disponible"). No se pueden quitar todos los dispositivos de una entrada desde aquí: si quieres vaciarla del todo, elimina la entrada entera desde **Dispositivos y servicios**.

### Mostrar en el mapa de Home Assistant

Las cámaras y los paneles pueden exponer su ubicación como atributos `latitude`/`longitude`, así que el mapa nativo de Home Assistant (el dashboard "Mapa" por defecto) los pinta como un punto sin necesitar ninguna tarjeta aparte. Es una opción **por dispositivo** (no afecta a toda la integración a la vez) y está **activada por defecto**.

Se pregunta al añadir cada cámara o panel (se aplica a todos los que elijas en ese mismo paso). Para cambiarlo después en dispositivos que ya tengas añadidos, entra en **Opciones** de su entrada:

- **Cambiar qué se ve en el mapa** — lista con casillas, con los que ya se ven en el mapa marcados de entrada, para ajustar dispositivo a dispositivo.
- **Mostrar todos en el mapa** / **Ocultar todos del mapa** — aplica el cambio a todos los dispositivos de esa entrada de golpe, sin formulario.

### Tarjeta del panel (opcional)

La integración incluye una tarjeta de Lovelace personalizada que dibuja el cartel de un panel con el mismo aspecto que el visor oficial de la DGT (fondo del panel, pictograma a la izquierda, texto amarillo monoespaciado), a partir de los atributos de su entidad `sensor.*`. Es opcional: sin ella, la entidad funciona igual, solo que sin esta representación visual.

**Instalación**: ninguna. Desde la versión 1.8.0, la propia integración sirve el `.js` y sus imágenes ([`custom_components/dgt_traffic_cameras/frontend/`](custom_components/dgt_traffic_cameras/frontend/)) sin copiar nada a `config/www/`. Solo falta un paso, una única vez: tras instalar o actualizar, en **Ajustes → Sistema → Reparaciones** aparecerá un aviso con la URL exacta que hay que añadir en **Ajustes → Paneles de control → Recursos** (tipo **Módulo JavaScript**). Es manual y no automático a propósito: automatizarlo del todo tocaría un almacenamiento interno de Home Assistant que tiene un bug conocido (puede borrar tus demás recursos de Lovelace), y ese riesgo no compensa ahorrarte un formulario.

> **Si ya tenías la tarjeta instalada a mano** (versiones anteriores a la 1.8.0): borra la copia vieja en `config/www/dgt-panel-card/` y el recurso antiguo (con URL `/local/dgt-panel-card/dgt-panel-card.js`) antes de añadir el nuevo. Tener los dos a la vez rompe la tarjeta (el navegador se queja de que `dgt-panel-card` ya está definida).

**Uso**: en cualquier dashboard, pulsa "Añadir tarjeta" → "Por tarjeta" → "DGT Panel Card" (o elige por entidad uno de tus paneles, ver más abajo) y selecciona el panel en el desplegable del editor visual. También se puede añadir a mano en YAML:

```yaml
type: custom:dgt-panel-card
entity: sensor.dgt_pmv_xxxxx
```

Si el panel no tiene ningún mensaje activo, la tarjeta muestra el cartel vacío con "Sin mensaje" en vez de inventarse contenido.

En Home Assistant 2026.6 o posterior no hace falta ni buscarla en la lista: al pulsar "Añadir tarjeta" y elegir por entidad una que sea un panel de esta integración, "DGT Panel Card" aparece como sugerencia en la sección "Comunidad", junto a Mosaico y demás. En versiones anteriores de Home Assistant esta sugerencia automática no está disponible, pero el editor visual (el desplegable para elegir la entidad) sí funciona igual.

### Tarjeta combinada de cámara + panel (repositorio aparte)

[**camera-card-slide**](https://github.com/jonathanathe/camera-card-slide) es una tarjeta de Lovelace en un repositorio distinto que muestra tus cámaras de tráfico de una en una, con navegación por flechas entre cámaras y, si tienes esta integración instalada, el panel de mensaje variable más cercano a la cámara que se está viendo, con el mismo aspecto que el cartel real.

<img width="672" height="612" alt="image" src="https://github.com/user-attachments/assets/8689fbb1-2f05-4696-9050-0ce1cf1d0be2" />


No es necesaria para nada de lo que hace esta integración: tiene su propia instalación (HACS o manual) — consulta las instrucciones en su propio README.

## Cómo se protege al servidor de la DGT

Este es el punto al que más atención se le ha dedicado. La integración usa un servicio público gratuito, y saturarlo sería un problema tanto para la DGT como para el usuario, que acabaría bloqueado.

### Cámaras

| Medida | Efecto |
|---|---|
| **Caché de 10 minutos por cámara** | Aunque el dashboard refresque la tarjeta cada pocos segundos, solo se pide una foto nueva cada 10 minutos. |
| **Caché condicional** (`ETag` / `If-Modified-Since`) | Al refrescar se pregunta si la imagen ha cambiado. Si no, la respuesta son unos pocos bytes en lugar de la foto completa. |
| **Backoff exponencial ante fallos** | Si la DGT falla, se espera cada vez más antes de reintentar (1, 2, 4, 8... hasta 60 minutos) en lugar de insistir. |
| **Inventario cacheado 15 minutos** | Abrir el diálogo de configuración varias veces no vuelve a descargar el listado completo. |
| **`frame_interval` ajustado** | Se le indica a Home Assistant que no tiene sentido pedir fotogramas más a menudo. |

En un escenario de 28 cámaras con el dashboard abierto una hora, esto supone unas **168 peticiones** en lugar de las más de 1.100 que generaría un enfoque sin caché — y más de 10.000 si el servidor estuviera fallando.

### Paneles de mensaje variable

Los paneles no funcionan panel a panel: **una única descarga cada 5 minutos trae el mensaje de todos los paneles configurados a la vez**, sea cual sea su número o el de entradas de configuración que los agrupen. Tener 1 panel o 100 genera exactamente el mismo tráfico contra la DGT. Su ubicación (carretera, provincia, coordenadas) cambia muy poco, así que se cachea aparte durante 24 horas en lugar de descargarse en cada paso del asistente.

## Otras medidas técnicas

- **Validación de URLs**: solo se aceptan direcciones HTTPS de dominios de la DGT, para que un feed manipulado no pueda hacer que Home Assistant consulte equipos de la red interna.
- **Verificación de la respuesta**: se comprueba que los bytes recibidos sean realmente una imagen, no una página de error servida con código 200.
- **Detección de la imagen "no disponible" de la propia DGT**: cuando una cámara está averiada, la DGT no da un error, sirve un aviso fijo con el dibujo de un carrete de película. Se detecta por su huella visual (no por su tamaño en bytes, que varía según la compresión) y no se guarda como si fuera una foto real.
- **Límites de tamaño** en descargas, con lectura por bloques que aborta si se superan.
- **Parseo fuera del bucle de eventos**, para que procesar el XML no congele Home Assistant.

---

## Requisitos

- Home Assistant en una versión reciente (la integración usa el flujo de opciones moderno, disponible desde 2024.11).
- Para que se muestre el icono de la integración se necesita **Home Assistant 2026.3 o superior**, que es cuando se añadió el soporte para imágenes de marca locales. En versiones anteriores todo funciona igual, pero se verá el marcador genérico de "icono no disponible".
- Depende de **Pillow** (procesamiento de imágenes) y **defusedxml** (parseo seguro del XML de la DGT), que Home Assistant instala solo al añadir la integración; no requiere nada más por tu parte.

## Resolución de problemas

**Las cámaras aparecen como "No disponible".**
Puede deberse a un fallo real de conexión, pero también a que la propia DGT esté devolviendo su imagen de aviso ("IMAGEN NO DISPONIBLE") para una cámara averiada. La integración detecta esa imagen concreta y no la muestra como si fuera una foto real: en ese caso, la entidad aparece como no disponible en vez de enseñar el aviso genérico.

Para saber cuál de los dos casos es el tuyo, activa el registro detallado añadiendo esto a `configuration.yaml` y reiniciando:

```yaml
logger:
  default: warning
  logs:
    custom_components.dgt_traffic_cameras: debug
```

Después consulta **Ajustes → Sistema → Registros**. Los mensajes indican el motivo concreto (código HTTP, tiempo de espera agotado, respuesta que no es una imagen...).

**La imagen no se actualiza.**
Es el comportamiento esperado: el intervalo mínimo es de 10 minutos. Puede modificarse en `const.py`, en la constante `MIN_SECONDS_BETWEEN_IMAGE_FETCH`, aunque no se recomienda bajarlo mucho.

**Una cámara concreta nunca carga.**
Las cámaras de la DGT se averían o se retiran del servicio con cierta frecuencia. Comprueba si esa cámara se ve en el visor oficial de la DGT antes de dar por hecho que el problema es de la integración.

**Un panel aparece como "Sin datos" o "Sin mensaje".**
Son dos cosas distintas y ninguna es un fallo de la integración:

- **"Sin mensaje"** — el panel está encendido pero no muestra nada ahora mismo (pantalla en blanco). Es su estado real, tal cual lo reporta la DGT.
- **"Sin datos"** — ese panel concreto no venía en la última descarga de mensajes. No todos los paneles emiten siempre; si persiste mucho tiempo, comprueba si el panel existe todavía en el visor oficial de la DGT.

**Los paneles no se actualizan.**
El intervalo es de 5 minutos para todos los paneles a la vez (ver [Cómo se protege al servidor de la DGT](#cómo-se-protege-al-servidor-de-la-dgt)). Puede modificarse en `const.py`, en la constante `VMS_MESSAGES_UPDATE_INTERVAL_SECONDS`.

---

## Fuente de los datos y atribución

Los datos proceden del **Punto de Acceso Nacional de Tráfico y Movilidad** de la Dirección General de Tráfico (<https://nap.dgt.es>), reutilizados conforme a la Ley 37/2007, de 16 de noviembre, sobre reutilización de la información del sector público, y su desarrollo reglamentario.

Este proyecto **no es oficial** y no está afiliado, patrocinado ni respaldado por la Dirección General de Tráfico. Es un desarrollo independiente que únicamente consume información publicada en abierto.

El icono de la integración es un **diseño original** y no reproduce ningún emblema oficial.

Las imágenes de las cámaras son propiedad de sus titulares y **no se almacenan ni redistribuyen** en este repositorio: la integración las descarga directamente desde los servidores de la DGT, en el equipo de cada usuario.

## Licencia

El **código** de este repositorio se publica bajo licencia [MIT](LICENSE).

Esa licencia cubre exclusivamente el software. Los datos y las imágenes obtenidos de la DGT se rigen por sus propias condiciones de reutilización, que cada usuario acepta al ejecutar la integración.

## Aviso

Se ofrece tal cual, sin garantía de ningún tipo. Las imágenes pueden no reflejar el estado actual de la vía. **No la uses como única fuente para tomar decisiones de seguridad vial.** Consulta siempre los canales oficiales de la DGT.

## Créditos

Todo el código de esta integración fue escrito por **Claude** (Anthropic) a lo largo de sesiones de trabajo, incluyendo el diseño inicial, la corrección de errores y dos auditorías completas en busca de fallos, vulnerabilidades y uso abusivo del servidor de origen.

El papel humano consistió en definir los requisitos, ejecutar la integración en una instalación real de Home Assistant y aportar los registros de error que permitieron localizar y corregir los fallos. El icono se generó con una herramienta de IA a partir de una descripción propia y se ajustó después mediante código.

Se documenta aquí por transparencia, no como reclamo: el código está comentado en detalle y cualquiera puede revisarlo y juzgarlo por sí mismo.
