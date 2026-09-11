# ETAPA 8 — Entrega operativa, diagnóstico local y validación total

Esta etapa no agrega una funcionalidad de negocio nueva. Cierra el paquete para que sea más fácil instalar, probar, validar y subir sin romper la versión acumulada de las etapas anteriores.

## Objetivo

- Evitar que el productor tenga que recordar comandos sueltos.
- Dejar un diagnóstico local simple para detectar problemas de instalación, zona horaria, dependencias, variables de entorno y padrón ARCA.
- Dejar un único comando para correr todos los validadores.
- Documentar comandos exactos de instalación, ARCA, GitHub y Render.
- Mantener fuera del ZIP final bases locales, `__pycache__`, `.pyc` y el padrón pesado.

## Archivos agregados

- `DIAGNOSTICO_OFICINAIA.py`
- `VALIDAR_TODO.py`
- `VALIDACION_ETAPA8_DEPLOY_CHECKS.py`
- `COMANDOS_GITHUB_RENDER.md`
- `ETAPA8_CAMBIOS.md`

## Qué permite hacer

### Diagnóstico local

```cmd
python DIAGNOSTICO_OFICINAIA.py
```

Revisa:

- archivos principales;
- dependencias Python;
- hora de oficina Argentina con fallback local;
- variables de entorno presentes sin mostrar valores;
- estado básico del padrón ARCA;
- exclusiones de `.gitignore` para no subir el padrón.

### Validación total

```cmd
python VALIDAR_TODO.py
```

Ejecuta todos los validadores por etapa y validadores históricos, más `compileall` y `node --check` cuando Node esté disponible.

### Comandos de entrega

Ver:

```txt
COMANDOS_GITHUB_RENDER.md
```

Incluye instalación, arranque local, importación ARCA, pruebas `/cuit`, validación total, GitHub y Render.

## Importante

Esta etapa no modifica la lógica de cédulas, ARCA, retries, Excel, documentos múltiples ni capabilities. Sólo agrega herramientas de operación y control para que la versión sea más fácil de usar y verificar.
