# ETAPA 9 — Primer arranque local, Salud sin ruido y accesos rápidos Windows

## Objetivo

Cerrar detalles de uso real después de las etapas funcionales: que una instalación local recién descomprimida no pierda eventos de Salud si todavía no existe `oficina.db`, que el diagnóstico sea más cómodo y que el productor pueda iniciar, validar e importar ARCA sin recordar comandos largos.

## Cambios técnicos

### Salud / eventos del sistema

`system_health.py` ahora puede crear/migrar la tabla `eventos_sistema` de forma perezosa antes de insertar, listar o limpiar eventos.

Esto evita warnings como:

```txt
no such table: eventos_sistema
```

cuando un validador, retry o servicio intenta registrar un evento antes de que `app.py` haya inicializado toda la base local.

La regla se mantiene: si Salud falla, nunca rompe la operación principal.

### Accesos rápidos Windows

Se agregaron:

- `INSTALAR_LOCAL.bat`
- `INICIAR_LOCAL.bat`
- `IMPORTAR_ARCA.bat`
- `VALIDAR_TODO.bat`
- `DIAGNOSTICO_LOCAL.bat`

`IMPORTAR_ARCA.bat` acepta `apellidoNombreDenominacion.zip`, `apellidoNombreDenominacion(1).zip` o cualquier variante `apellidoNombreDenominacion*.zip` que Windows genere al descargar varias veces.

## Archivos modificados

- `system_health.py`
- `VALIDAR_TODO.py`
- `COMANDOS_GITHUB_RENDER.md`

## Archivos agregados

- `VALIDACION_ETAPA9_PRIMER_ARRANQUE.py`
- `ETAPA9_CAMBIOS.md`
- `INSTALAR_LOCAL.bat`
- `INICIAR_LOCAL.bat`
- `IMPORTAR_ARCA.bat`
- `VALIDAR_TODO.bat`
- `DIAGNOSTICO_LOCAL.bat`

## Qué NO cambia

- No se toca ARCA funcionalmente.
- No se cambia cédulas.
- No se cambia cartera/contexto.
- No se cambia Gemini.
- No se cambia el sistema de retries.
- No se agrega el padrón al ZIP.
