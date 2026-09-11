# Auditoría — OficinaIA GitHub definitiva + Cédula reforzada + Envíos Ya

Fecha: 2026-09-10

## Base utilizada

Esta entrega parte de `OficinaIA-main(3).zip`, identificado por el usuario como el ZIP original del repositorio GitHub que corresponde a la interfaz actualmente desplegada en Render.

No se utilizó como base ninguna de las cadenas anteriores `V20_REFACTOR_ETAPA*` ni `V20_LIMPIA`. La interfaz general de la base GitHub se conserva; no se reemplazaron las plantillas por la UI antigua.

## Objetivos implementados

Se integraron en una sola base las dos instrucciones solicitadas:

1. Flujo documental automático: el adjunto define la intención (`cedula`, `poliza`, `otro`), con póliza -> alta administrativa y salida de Envíos Ya sin comandos obligatorios.
2. Lector reforzado de cédulas, priorizando precisión de MOTOR y CHASIS, con lectura multimodal, verificación independiente y exposición de discrepancias en vez de inventar caracteres.

## Envíos Ya

- Se centralizó la normalización en `envios_ya_utils.py`.
- Se normalizan teléfonos argentinos mediante código determinístico.
- Se normaliza patente mediante código determinístico.
- La fila copiable usa tabs reales y no incluye etiquetas.
- Orden canónico: ASEGURADO, PÓLIZA, TELÉFONO, PATENTE, VEHÍCULO, COMPAÑÍA.
- `Copiar Envíos Ya` usa los valores actuales del formulario de alta, incluso antes de guardar en Excel.
- Se preserva el comando histórico `/envios ya PATENTE`.
- Se preserva la semántica histórica del campo Excel `NUMERO`: no se reutilizó silenciosamente como número de póliza.

## Cédula — arquitectura de lectura

El pipeline especializado está en `cedula_ops.py` y utiliza la infraestructura central de IA existente.

Flujo:

1. clasificación del adjunto;
2. lectura general estructurada;
3. localización visual de MOTOR/CHASIS;
4. recorte con margen;
5. orientación EXIF correcta;
6. mejora no destructiva / upscale adaptativo;
7. lectura focalizada de cada campo;
8. verificación independiente sin suministrar como pista la lectura previa;
9. incorporación de evidencia del texto digital del PDF, cuando existe;
10. comparación determinística de evidencias;
11. estados `verificado`, `revisar` y `no_legible`.

No se realizan sustituciones silenciosas del tipo O/0, I/1, B/8, etc.

Para marcar un dato como `verificado` se exige evidencia independiente suficiente y sin conflicto. Una evidencia completa que contradiga a las demás fuerza revisión.

## Correcciones específicas al fallo observado con cédulas

El usuario reportó dos fallos en el sistema previo: una imagen de cédula no pudo clasificarse visualmente y otro intento reconoció la cédula pero no consiguió completar una lectura confiable.

Se corrigieron varios puntos relacionados:

### 1. El clasificador ya no es un punto único de fallo

Una imagen enviada con el mensaje automático del adjunto recibe una oportunidad de rescate por el lector especializado de cédulas aun cuando el clasificador devuelva `otro` con confianza alta.

También se permite rescate para PDFs escaneados y para PDFs digitales que contengan señales textuales suficientes de cédula vehicular.

Un manual PDF largo sin señales de cédula no se deriva al lector especializado.

### 2. PDFs escaneados

`chat_pdf.py` ya no corta el flujo sólo porque `page.get_text()` no devuelve contenido. Un PDF escaneado puede renderizarse a imagen y continuar por visión.

### 3. Evidencia del PDF digital

Cuando el PDF sí tiene capa de texto, MOTOR y CHASIS adyacentes a sus etiquetas se incorporan como evidencia independiente. El texto no se usa para inventar caracteres ni para forzar consenso ante una contradicción.

### 4. Orientación de fotos de celular

Se corrigió un borde donde `exif_transpose()` podía ejecutarse en memoria pero terminar enviándose el byte original, perdiendo la rotación EXIF. Ahora la orientación corregida se conserva para la lectura visual.

### 5. Recortes más tolerantes

La lectura focalizada recibe el recorte original, su versión mejorada y una copia contextual de la página correspondiente. Una caja delimitadora imperfecta de Gemini deja de ser un fallo fatal por sí sola.

### 6. Presupuesto de IA para documentos

Los adjuntos tienen un presupuesto de solicitud mayor, configurable mediante `GEMINI_DOCUMENT_BUDGET_SECONDS` (default 125 s), para evitar que clasificación + lecturas independientes agoten prematuramente el presupuesto general de 75 s. Se mantiene por debajo del timeout de Gunicorn de la base (180 s).

## UX

Para cédulas, la salida está orientada a la operatoria:

- MOTOR + estado + botón copiar;
- CHASIS + estado + botón copiar;
- los detalles técnicos internos no se muestran cuando todo está verificado;
- ante discrepancia se muestra la posición dudosa y, cuando hay crop disponible, `Ver ampliado`;
- un dato en revisión requiere confirmación para copiar igualmente.

La intención es que una cédula razonablemente legible no requiera volver a tipear manualmente motor/chasis.

## Estado de alta contextual

- Se mantiene un alta activa efímera asociada al chat actual.
- Un nuevo adjunto invalida el alta activa anterior para evitar aplicar una corrección sobre una póliza vieja.
- Correcciones contextuales inequívocas pueden actualizar los datos activos y reconstruir la tarjeta.
- El teléfono corregido por conversación no se pierde al volver a renderizar el formulario.

## Archivos nuevos

- `alta_context.py`
- `attachment_vision.py`
- `cedula_ops.py`
- `document_classifier.py`
- `envios_ya_utils.py`
- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py`
- `AUDITORIA_GITHUB_DEFINITIVA_CEDULA_ENVIOSYA.md`

## Archivos modificados respecto de OficinaIA-main(3)

- `alta_ops.py`
- `app.py`
- `chat_commands.py`
- `chat_pdf.py`
- `chat_request.py`
- `chat_special.py`
- `domain_prompts.py`
- `envios_masivos.py`
- `requirements.txt`
- `servicios_ia.py`
- `static/css/estilo.css`
- `static/js/app.js`

## Dependencia nueva

`requirements.txt` incluye:

`Pillow>=10.0.0`

Después de reemplazar el proyecto local se debe ejecutar `python -m pip install -r requirements.txt` antes de levantar la aplicación si esa dependencia todavía no está instalada.

## Validaciones ejecutadas

En esta entrega se ejecutaron correctamente:

- `python -m py_compile *.py`
- `python VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py`
- `python -m compileall -q .`
- `node --check static/js/app.js`

La validación específica informó `OK TOTAL: 11 grupos`, incluyendo:

- normalización de teléfonos;
- patente y Envíos Ya;
- clasificación textual;
- consenso de cédula;
- evidencia de PDF digital;
- rescate de cédula cuando el clasificador devuelve `otro`;
- PDF escaneado no rechazado;
- aplicación real de orientación EXIF;
- render de scan para visión;
- fallo 503 simulado del clasificador sin matar el rescate;
- preservación de semántica Excel/número de póliza.

## Limitaciones / validación pendiente real

Este entorno no dispone del stack completo para levantar la aplicación Flask como servidor (`flask` no está instalado aquí), por lo que no se afirma una prueba end-to-end real del servidor/browser.

Tampoco se dispone aquí de la `GEMINI_API_KEY` del despliegue ni de los dos archivos originales exactos de cédula que fallaron; sólo se contó con la captura de pantalla del comportamiento. Por eso no sería correcto afirmar que esas dos cédulas concretas ya fueron reconocidas exitosamente por Gemini.

La prueba final recomendada en el entorno real es subir exactamente:

1. la cédula digital que falló;
2. la foto de la cédula que falló;

confirmando que:

- ambas se enrutan al lector de cédula;
- MOTOR y CHASIS salen verificados cuando la evidencia es suficiente;
- si existe una ambigüedad real, el sistema la muestra en vez de inventarla;
- pólizas, Envíos Ya, Excel, Tabulado, Estudio y UI actual continúan funcionando.
