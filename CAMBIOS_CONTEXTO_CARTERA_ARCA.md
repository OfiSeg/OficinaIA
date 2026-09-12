# Corrección de contexto Cartera / ARCA

## Problema reproducido
Después de consultar un conjunto de asegurados de cartera, expresiones como `el último` o un nombre exacto (por ejemplo `BAO GABRIEL ROBERTO`) podían no resolverse localmente y terminar en el flujo genérico/Gemini. Además, un contexto ARCA previo podía quedar activo más tiempo del debido.

## Correcciones
- `el último` / `la última` ahora seleccionan el último registro del conjunto activo de cartera sin Gemini.
- Se ampliaron ordinales locales hasta décimo.
- Un nombre completo o patente exactos dentro del conjunto activo seleccionan ese registro de forma determinística, sin fuzzy matching agresivo.
- Cuando cartera pasa a ser la fuente activa, se elimina `arca_context` anterior.
- Cuando ARCA pasa a ser la fuente activa, se invalida el conjunto conversacional de cartera.
- `arca_context` queda limitado al `chat_id` actual para evitar contaminación entre conversaciones.
- El historial ya no considera cualquier mención vieja a ARCA/CUIT: decide según la fuente relevante más reciente.
- ARCA también entiende `el último` dentro de su propio conjunto de candidatos.

## Archivos modificados
- `excel_conversation_context.py`
- `chat_commands.py`
- `app.py`
- `VALIDACION_ETAPA2_CONTEXTO_CARTERA.py`
- `VALIDACION_ETAPA6_ARCA_CUIT.py`

## Validación
`python VALIDAR_TODO.py` finaliza con `TODO OK`, incluyendo `compileall` y `node --check static/js/app.js`.
