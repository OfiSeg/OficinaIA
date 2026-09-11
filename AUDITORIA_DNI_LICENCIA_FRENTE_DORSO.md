# Auditoría — DNI, licencia y frente/dorso

## Base real utilizada

Esta etapa se implementó **sobre `OficinaIA_GITHUB_DEFINITIVA_SALUD_SERVICIOS.zip`**, conservando las mejoras anteriores de:

- UI actual de OficinaIA/GitHub;
- cédula multimodal reforzada;
- póliza/alta automática;
- Tabulado / Excel / Envíos Ya;
- Salud → Servicios y autodiagnóstico.

No se utilizó una V20 antigua como base.

## Objetivo

Extender el lector documental operativo para reconocer de forma automática:

- cédula vehicular;
- DNI;
- licencia/registro de conducir;
- póliza;
- otro documento.

Además, permitir **frente + dorso** en el mismo turno o en dos turnos consecutivos, sin fusionar silenciosamente documentos incompatibles.

## Arquitectura implementada

### Clasificador único

`document_classifier.py` continúa siendo la única capa de clasificación documental. Se amplió el contrato existente a:

`cedula | dni | licencia | poliza | otro`

Se agregaron heurísticas textuales para DNI/licencia y visión multimodal con el mismo gateway Gemini. Si dos caras juntas quedaron como `otro` individualmente, existe un rescate que vuelve a usar **el mismo clasificador** mirando el conjunto; no se creó un segundo sistema paralelo.

### Agrupamiento

Nuevo `document_grouping.py`.

Su responsabilidad es únicamente proponer si dos adjuntos pueden ser frente/dorso. La identidad real la confirma el extractor especializado. No fusiona póliza con DNI/licencia/cédula ni DNI con licencia.

### Datos personales

Nuevo `personal_document_ops.py`.

DNI y licencia comparten el mismo motor de extracción. Campos principales:

- DNI;
- fecha de nacimiento;
- CUIL sólo si está impreso;
- domicilio;
- localidad;
- nombre/apellido como referencia visual.

DNI, fecha y CUIL usan tres lecturas independientes. La UI distingue:

- `Alta confianza — 3/3 lecturas coincidentes`;
- `Confianza media — revisar`;
- `Revisar`;
- `No disponible`.

No se calcula CUIL a partir de DNI/sexo.

### Frente + dorso

El frontend permite hasta dos archivos por mensaje. También se conserva el último adjunto de forma efímera para intentar combinar la cara enviada en el turno inmediatamente siguiente.

Se corrigió un borde importante: si el segundo archivo es un **dorso** y por sí solo el clasificador lo marca como `otro`, igualmente puede combinarse con el frente anterior ya reconocido. Antes esa condición impedía el agrupamiento.

La aplicación corre con un único worker según `render-start.txt`, coherente con el caché efímero de adjuntos ya existente.

También se contempla un PDF único de varias páginas: si Gemini reporta dos caras, se trata como documento multicara aunque haya llegado como un solo archivo.

### Contradicciones

No se resuelven por mayoría de forma silenciosa.

- DNI distinto entre caras: no se fusiona.
- Fecha/CUIL/domicilio/localidad contradictorios: se marcan para revisión y el valor conflictivo no se copia como si fuera seguro.
- Un nombre diferente por sí solo no se usa como única prueba de identidad; se exigen señales adicionales.

## Cédula — cambios complementarios

Se preservó el lector reforzado existente y se agregó:

- botón directo para patente;
- patente incluida en las tres lecturas críticas;
- estado de coincidencia también para patente;
- UI con `Alta confianza — 3/3 lecturas coincidentes` en lugar de presentar la lectura como una validación oficial;
- `Copiar patente`;
- `Copiar motor`;
- `Copiar chasis`;
- `Copiar motor y chasis`;
- `Copiar todos los datos`.

### Bug detectado y corregido

La normalización operativa de patente de Envíos Ya elimina caracteres no alfanuméricos, lo cual es correcto para una patente ya confirmada, pero era peligroso reutilizarla durante OCR/visión: una lectura como `AB?23CD` podía terminar convertida en `AB23CD`, ocultando la duda.

El lector de cédula ahora utiliza una normalización visual propia que **conserva `?`** y nunca elimina silenciosamente una incertidumbre.

## UI

Se extendió la tarjeta de cédula existente. No se agregó dashboard ni framework nuevo.

DNI/licencia reutilizan:

- tarjetas;
- tipografía;
- botones;
- bordes;
- variables de tema;
- responsive;
- modo claro/oscuro.

No se rediseñó OficinaIA.

## Archivos nuevos

- `document_grouping.py`
- `personal_document_ops.py`
- `VALIDACION_V20_DNI_LICENCIA.py`
- `AUDITORIA_DNI_LICENCIA_FRENTE_DORSO.md`

## Archivos modificados

- `app.py`
- `attachment_vision.py`
- `cedula_ops.py`
- `chat_request.py`
- `chat_special.py`
- `document_classifier.py`
- `static/js/app.js`
- `static/css/estilo.css`
- `templates/documentos.html`

## Dependencias

`requirements.txt` **no fue modificado**. La implementación reutiliza dependencias que ya formaban parte de la versión base.

## Pruebas ejecutadas

### `VALIDACION_SALUD_SERVICIOS.py`

7/7 grupos OK.

Esto verifica que la etapa nueva no rompió Salud → Servicios, configuración ni health checks.

### `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py`

11/11 grupos OK.

Incluye Envíos Ya, normalización, cédula, PDF escaneado, orientación EXIF, rescate ante fallo del clasificador y regresión de póliza/Excel.

### `VALIDACION_V20_DNI_LICENCIA.py`

13/13 grupos OK.

Valida offline:

- clasificación DNI;
- clasificación licencia;
- póliza conservada;
- agrupamiento frente/dorso;
- DNI + licencia no se fusionan;
- normalización DNI/CUIL/fecha;
- 3/3 y 2/3 lecturas;
- CUIL ausente no inventado;
- DNI frente+dorso;
- PDF multicara;
- dos personas distintas no se fusionan;
- fecha contradictoria no se elige arbitrariamente;
- licencia sin CUIL;
- patente ambigua conserva `?`;
- UI de copia y carga múltiple.

### Sintaxis

- `python -m py_compile *.py`: OK
- `python -m compileall -q .`: OK
- `node --check static/js/app.js`: OK

Total de grupos de validación funcional ejecutados: **31**, todos OK.

## Prueba pendiente obligatoria en producción

Este entorno no dispone de la `GEMINI_API_KEY` real de OficinaIA, por lo que no se puede afirmar que se probaron físicamente contra Gemini fotografías reales de DNI/licencias/cédulas.

Después del deploy se recomienda probar como mínimo:

1. foto clara de cédula;
2. DNI frente;
3. DNI frente + dorso seleccionados juntos;
4. DNI frente y luego dorso en el siguiente mensaje;
5. licencia;
6. licencia sin CUIL;
7. dos DNI de personas distintas para confirmar que no se fusionen;
8. una póliza para confirmar que el alta automática sigue igual.

## Deploy

Sí: al reemplazar el código en GitHub/Render hay que realizar el deploy normal para que el nuevo backend y JavaScript entren en funcionamiento.

No es necesario modificar variables de Render por esta etapa.
