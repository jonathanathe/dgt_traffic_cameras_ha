# Cámaras de tráfico DGT para Home Assistant

Integración personalizada que añade las cámaras de tráfico y los paneles de mensaje variable (PMV) de la Dirección General de Tráfico (DGT) a Home Assistant, con un selector guiado por provincia y carretera.

> **Proyecto no oficial.** No está afiliado, patrocinado ni respaldado por la DGT. Únicamente consume datos publicados en abierto.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jonathanathe&repository=dgt_traffic_cameras_ha&category=integration)

---

## Qué hace

- Descarga los datos públicos de la DGT (formato DATEX II, sin necesidad de clave de API): inventario de cámaras y ubicación/mensajes de los paneles de mensaje variable.
- Te deja elegir, en tres pasos (**provincia → carretera → dispositivos concretos**), tanto cámaras como paneles.
- Crea una entidad `camera.*` por cada cámara, con su carretera, punto kilométrico, sentido y coordenadas como atributos.
- Crea una entidad `sensor.*` por cada panel, con el mensaje que muestra ahora mismo como estado, y como atributos el texto completo, las líneas por separado, los pictogramas activos y si está apagado.
- Opcionalmente, muestra cámaras y paneles como puntos en el mapa de Home Assistant (ver [Mostrar en el mapa](#mostrar-en-el-mapa)).

La DGT publica **instantáneas fijas** de las cámaras, no vídeo en directo. Cada foto se renueva unas pocas veces por hora en origen. Los mensajes de los paneles se comprueban cada 5 minutos.

## Qué **no** hace

- **No incluye País Vasco ni Cataluña.** No es una limitación de la integración: esas comunidades tienen la gestión de tráfico transferida a sus propias administraciones y sus cámaras no están en el feed de la DGT.
- **No hay vídeo ni grabación.** Solo la última imagen disponible.
- No almacena ni redistribuye imágenes: cada instalación las descarga directamente de los servidores de la DGT.

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

1. **Provincia** — desplegable con las provincias que tienen cámaras disponibles.
2. **Carretera** — las vías de esa provincia.
3. **Cámaras** — lista con casillas, ordenada por punto kilométrico.

Cada combinación de provincia y carretera crea una entrada propia, que agrupa sus cámaras bajo un mismo dispositivo.

Para añadir más cámaras de la misma carretera más adelante, o para quitar alguna que ya no quieras, usa el botón de **Opciones** (el engranaje) de esa entrada: te preguntará si quieres **Añadir cámaras** o **Quitar cámaras**. Para otra carretera distinta, añade una nueva entrada.

Al quitar una cámara, su entidad se elimina por completo de Home Assistant (no se queda como "no disponible"). No se pueden quitar todas las cámaras de una entrada desde aquí: si quieres vaciarla del todo, elimina la entrada entera desde **Dispositivos y servicios**.

### Paneles de mensaje variable

Al añadir la integración, el primer paso pregunta si quieres **Cámaras de tráfico** o **Paneles de mensaje variable**. El resto del asistente (provincia → carretera → selección) funciona igual que con las cámaras, y también tiene su propio **Opciones** para añadir o quitar paneles de una entrada ya creada.

Un panel puede no aparecer en la descarga de mensajes en un momento dado (no todos emiten siempre); en ese caso su entidad muestra "Sin datos" en vez de marcarse como no disponible.

### Mostrar en el mapa

Desde **Opciones** de cualquier entrada (de cámaras o de paneles) hay una tercera opción, **Mostrar en el mapa**, que activa un interruptor. Al activarlo, cada dispositivo de esa entrada aparece también como un punto en el panel de **Mapa** del menú lateral de Home Assistant (además de en cualquier tarjeta que ya tengas), con la distancia a tu ubicación "Casa" como su estado.

**Sobre la etiqueta del pin:** por defecto, Home Assistant pone en cada pin las iniciales del nombre de la entidad (por ejemplo, "PA" para "Panel A-1"). Si prefieres ver directamente el mensaje del panel en el propio pin en vez de esas iniciales, hace falta una tarjeta de Mapa personalizada en un dashboard (esto no se puede aplicar al panel de Mapa por defecto del menú lateral, que no es configurable):

```yaml
type: map
entities:
  - entity: geo_location.panel_dgt_xxxxx
    label_mode: attribute
    attribute: mensaje
```

Ojo: es la entidad `geo_location.*` (la del punto en el mapa), no la `sensor.*` del panel — cada una expone sus propios atributos, y `mensaje` solo existe en la de `geo_location`, pensado exactamente para esto.

---

## Cómo se protege al servidor de la DGT

Este es el punto al que más atención se le ha dedicado. La integración usa un servicio público gratuito, y saturarlo sería un problema tanto para la DGT como para el usuario, que acabaría bloqueado.

| Medida | Efecto |
|---|---|
| **Caché de 10 minutos por cámara** | Aunque el panel refresque la tarjeta cada pocos segundos, solo se pide una foto nueva cada 10 minutos. |
| **Caché condicional** (`ETag` / `If-Modified-Since`) | Al refrescar se pregunta si la imagen ha cambiado. Si no, la respuesta son unos pocos bytes en lugar de la foto completa. |
| **Backoff exponencial ante fallos** | Si la DGT falla, se espera cada vez más antes de reintentar (1, 2, 4, 8... hasta 60 minutos) en lugar de insistir. |
| **Inventario cacheado 15 minutos** | Abrir el diálogo de configuración varias veces no vuelve a descargar el listado completo. |
| **`frame_interval` ajustado** | Se le indica a Home Assistant que no tiene sentido pedir fotogramas más a menudo. |

En un escenario de 28 cámaras con el panel abierto una hora, esto supone unas **168 peticiones** en lugar de las más de 1.100 que generaría un enfoque sin caché — y más de 10.000 si el servidor estuviera fallando.

## Otras medidas técnicas

- **Validación de URLs**: solo se aceptan direcciones HTTPS de dominios de la DGT, para que un feed manipulado no pueda hacer que Home Assistant consulte equipos de la red interna.
- **Verificación de la respuesta**: se comprueba que los bytes recibidos sean realmente una imagen, no una página de error servida con código 200.
- **Límites de tamaño** en descargas, con lectura por bloques que aborta si se superan.
- **Parseo fuera del bucle de eventos**, para que procesar el XML no congele Home Assistant.

---

## Requisitos

- Home Assistant en una versión reciente (la integración usa el flujo de opciones moderno, disponible desde 2024.11).
- Para que se muestre el icono de la integración se necesita **Home Assistant 2026.3 o superior**, que es cuando se añadió el soporte para imágenes de marca locales. En versiones anteriores todo funciona igual, pero se verá el marcador genérico de "icono no disponible".
- No requiere dependencias de Python adicionales.

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

Todo el código de esta integración fue escrito por **Claude** (Anthropic) a lo largo de una sesión de trabajo, incluyendo el diseño inicial, la corrección de errores y dos auditorías completas en busca de fallos, vulnerabilidades y uso abusivo del servidor de origen.

El papel humano consistió en definir los requisitos, ejecutar la integración en una instalación real de Home Assistant y aportar los registros de error que permitieron localizar y corregir los fallos. El icono se generó con una herramienta de IA a partir de una descripción propia y se ajustó después mediante código.

Se documenta aquí por transparencia, no como reclamo: el código está comentado en detalle y cualquiera puede revisarlo y juzgarlo por sí mismo.