# OficinaIA — Pulido UI / Excel → Envíos Ya / ATM / Gemini

Fecha: 2026-09-12
Base: último ZIP entregado en el chat antes de esta etapa: `OficinaIA_CEDULA_ALTA_GEMINI_DIAGNOSTICADA.zip`.

## Cambios aplicados

### Menú + y composer
- Se eliminó **solamente el botón físico `/`** del composer.
- Los comandos escritos manualmente siguen disponibles por compatibilidad.
- El menú `+` sigue compacto, gana unos píxeles útiles y no muestra scrollbar visible.
- En pantallas muy bajas puede conservar scroll con rueda/touch, pero la barra queda oculta.
- No se habilita scroll horizontal.

### Visor de imágenes
- El lightbox se mueve al `body` cuando se abre para no quedar recortado por el contenedor del chat.
- El overlay cubre todo el viewport, incluida la barra superior, sidebar, conversaciones y composer.
- Fondo oscurecido + blur uniforme, imagen centrada y sin deformación.

### Conversaciones / ancho útil
- Se redujo moderadamente el ancho de la lista de conversaciones y algunos paddings.
- Se preservó el comportamiento existente de colapsado y responsive.
- No se creó una nueva sidebar ni se hizo un rediseño general.

### Excel → CSV Envíos Ya
- Excel (`.xlsx` / `.xlsm`) queda presentado como entrada principal del flujo.
- CSV continúa aceptado como entrada secundaria por compatibilidad.
- El resultado confirmado continúa siendo el CSV rígido de Envíos Ya.
- El backend no finge compatibilidad con `.xls` viejo: ese formato no estaba soportado por el lector actual.
- Se agregó una validación real con un XLSX creado en memoria: detecta nombre/apellido/celular/fecha y genera filas de 10 campos en el CSV final.

### Cotización ATM
- Las coberturas detectadas ya **no aparecen seleccionadas todas por defecto**.
- La selección del productor se conserva aunque se recalculen precios.
- La propuesta sólo contiene coberturas efectivamente seleccionadas.
- Se eliminan descripciones repetitivas por cada plan.
- Formato comercial corto, por ejemplo:

  `TC Premium`
  `$119.000 efectivo · $99.000 adherido`

- Una sola aclaración general al final.
- Se acortaron nombres de presentación sin inventar coberturas.

### Redondeo comercial
- Se agregó redondeo al millar más cercano con mitad hacia arriba, **sólo para presentación**.
- Ejemplos validados:
  - 94.450 → 94.000
  - 94.499 → 94.000
  - 94.500 → 95.000
  - 94.748 → 95.000
  - 119.026 → 119.000
  - 377.820 → 378.000
- Los valores exactos siguen existiendo internamente y son los que alimentan la matemática.

### Fórmula ATM adherido
- **NO fue modificada.**
- Continúa siendo `5 / 6`, matemáticamente equivalente a `precio / 1,20`.
- No se cambió por un 16% fijo porque no son operaciones equivalentes.
- Queda pendiente contrastarla contra varias cotizaciones reales de ATM antes de tocarla.

### Gemini
- Small talk prioriza `gemini-3.5-flash-lite` y usa `gemini-3.8-flash` como segundo intento controlado.
- Small talk: 5,5 s por intento, máximo 2 intentos y fallback local mínimo al final.
- Chat general conserva 10 s por llamada, presupuesto lógico 35 s y `thinking_level=low`.
- Documentos/cédulas mantienen sus rutas y presupuestos más largos.
- Se conserva logging técnico y clasificación de errores sin exponer claves ni contenido sensible.
- No se pudo realizar una llamada real en este entorno porque no están presentes la API key ni el runtime `google-genai`/Flask.

## Archivos modificados en esta etapa

- `templates/documentos.html`
- `static/js/app.js`
- `static/css/estilo.css`
- `atm_cotizador.py`
- `atm_coberturas.py`
- `servicios_ia.py`
- `chat_request.py`
- `app.py`
- `ENVIRONMENT_VARIABLES.md`
- `DIAGNOSTICO_CEDULA_ALTA_GEMINI.md`
- `VALIDACION_CEDULA_ALTA_GEMINI.py`
- `VALIDACION_PULIDO_UI_ATM_GEMINI.py`
- `VALIDAR_TODO.py`

## Validaciones

- Suite completa `VALIDAR_TODO.py`: TODO OK.
- 18 validadores funcionales.
- Validador específico de esta etapa: 9/9 OK.
- XLSX real → análisis → confirmación pendiente → CSV Envíos Ya: OK.
- `compileall`: OK.
- `node --check static/js/app.js`: OK.

## Pendiente externo

Sólo queda validar Gemini contra la API real del deploy para saber si además existe un problema externo de cuota, credenciales, rate limit o red de Render. El código ahora deja trazas suficientes para distinguir esos casos.
