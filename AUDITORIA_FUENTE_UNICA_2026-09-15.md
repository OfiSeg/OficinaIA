# Auditoría de fuente única — OficinaIA — 2026-09-15

## Objetivo

Revisar la base actual con el criterio acordado: una responsabilidad funcional debe tener una sola autoridad activa. No agregar prioridad, overrides o fallbacks para tapar una implementación anterior.

## Cambios realizados

### 1. Regla permanente en AGENTS.md
Se incorporó como principio obligatorio el flujo `MAPEAR → IDENTIFICAR AUTORIDAD → MODIFICAR/REEMPLAZAR → RETIRAR LEGACY → BUSCAR RESIDUOS → REGRESIÓN → END-TO-END`.

### 2. Cotizaciones: frontend
Se retiraron dos tablas semánticas paralelas que podían volver a reconstruir una cobertura después de que la fuente/normalizador ya la hubiera resuelto:

- `QUOTE_PROFILE_COMMERCIAL_NAMES`
- `QUOTE_CORE_BENEFIT`

También se retiró la inferencia de nombre comercial por códigos/riesgos dentro de `nombreBaseComercialOpcion()`.

Ahora el frontend preserva `nombre_comercial` / `nombre_cliente` / datos fuente ya resueltos. `contenidosCanonicosCotizacion()` dejó de reconstruir el núcleo desde `familia` o `riesgos_detectados`; sanea presentación y atributos explícitos.

### 3. Cotizaciones: renderer DOCX/PDF/JPG
`cotizacion_document_service.py` dejó de ser un segundo normalizador comercial. Se retiraron:

- `PERFIL_NOMBRE_COMERCIAL`
- `PERFIL_BENEFICIO_BASE`
- `_contenido_canonico_por_familia()`
- inferencia de nombres por flags/riesgos
- reordenamiento comercial reconstruido por el renderer

El renderer ahora conserva el contrato canónico recibido, deduplica texto y genera la nota de franquicia documental. Si recibe una contradicción explícita (por ejemplo `S/GRANIZO` + bullet `Granizo`, o `SIN GRÚA` + `Incluye grúa`) falla en vez de corregir silenciosamente. El error debe arreglarse en la autoridad aguas arriba.

### 4. Capa visual agregada hoy
Se retiró por completo `OFICINAIA · VISUAL CONSOLIDATION V1 · 2026-09-15`, porque era otra capa final de `!important` sobre reglas históricas. También se revirtieron los dos cambios de templates que dependían de esa capa. Esto devuelve la UI al estado visual senior anterior en vez de conservar un override nuevo.

No se hizo otra “capa correctora” para reemplazarla.

## Qué NO se borró indiscriminadamente

- Parsers ATM, Mercantil y Federación: extraen/adaptan fuentes distintas; no son duplicación por sí mismos.
- `quote_normalizer.py`: conserva la responsabilidad de normalización universal.
- Lógica de precios, descuentos, franquicias, router, ARCA, Excel, Gemini, Salud, Estudio, alta y envíos: no se reescribieron porque no se demostró una autoridad duplicada dentro del alcance revisado.
- `servicioGruaOpcion()` conserva un fallback de lectura cuando una fuente antigua no entrega booleano estructurado. Es compatibilidad de entrada, no una tabla comercial paralela. Conviene retirarlo sólo cuando todas las fuentes garanticen `servicio_grua` estructurado.
- `lineasCoberturaCotizacion()` todavía limpia frases de descripciones fuente para presentación. No decide perfiles/nombres, pero sigue siendo un adaptador de texto de frontend. No se eliminó porque ATM aún expone algunas `descripcion_cliente` como frases y retirarlo sin migrar primero esas fuentes perdería información.

## Riesgos residuales detectados

La deuda histórica CSS anterior a esta auditoría sigue existiendo. No se intentó una purga masiva porque mezclar una limpieza global de miles de reglas con esta corrección funcional violaría el mismo principio quirúrgico. La capa visual nueva de hoy sí fue retirada porque se podía identificar exactamente y revertir sin ambigüedad.

En cotizaciones queda una frontera a seguir endureciendo: las fuentes específicas deben tender a entregar siempre hechos estructurados + descripción canónica, para poder retirar gradualmente fallbacks textuales del frontend. Esa migración debe hacerse fuente por fuente con regresiones, no borrando heurísticas a ciegas.

## Validaciones ejecutadas

Pasaron:

- `python -m compileall -q .`
- `node --check static/js/app.js`
- `VALIDACION_MARCAS_CONFIG.py`
- `VALIDACION_NAVEGACION_NORMAL.py`
- `VALIDACION_NORMALIZACION_SISTEMA.py`
- `VALIDACION_NORMALIZADOR_COTIZACIONES.py`
- `VALIDACION_ROUTER_CHAT.py`
- `VALIDACION_FICHA_PERSISTENTE.py`
- `VALIDACION_COTIZADOR_UNIVERSAL.py`
- `VALIDACION_COTIZACION_DOCUMENTAL.py`
- `VALIDACION_PULIDO_VISUAL.py`
- `VALIDACION_COTIZADOR_UNIVERSAL.js`
- `VALIDACION_FUENTE_UNICA.py`

## Criterio de cierre

Esta auditoría no declara que todo código legacy del repositorio haya desaparecido. Declara algo más verificable: las duplicaciones comerciales y la capa visual superpuesta identificadas en el trabajo reciente fueron retiradas, se agregó una barrera de regresión y no se tocaron áreas sin evidencia suficiente de conflicto.
