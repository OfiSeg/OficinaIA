# ETAPA 7 — Cierre de integración, hardening y validación final

Esta etapa no agrega una funcionalidad nueva grande. Cierra la integración de las etapas 1 a 6 para que la entrega sea segura y mantenible.

## Objetivo

- Confirmar que el ZIP final parte de la Etapa 6.
- Mantener las correcciones de cédulas, UI, contexto, fecha Argentina, frontend, resiliencia, documentos múltiples, capabilities y ARCA.
- Blindar la distribución contra errores locales ya detectados, especialmente zona horaria en Windows.
- Evitar que el paquete final incluya bases locales, cachés, pycache o el padrón pesado.
- Dejar un validador final que revise integración general, sin reemplazar los validadores específicos de cada etapa.

## Qué se agregó

- `VALIDACION_ETAPA7_INTEGRACION_FINAL.py`
- Este documento de cierre.

## Qué valida la Etapa 7

1. Que no haya referencias visibles a `Sofia` / `Sofía` en templates ni JavaScript servidos al usuario.
2. Que `requirements.txt` incluya `tzdata`.
3. Que `office_time.py` tenga fallback a UTC-3 si Windows/local no encuentra `America/Argentina/Buenos_Aires`.
4. Que `office_now()` devuelva un `datetime` con zona horaria.
5. Que el manifiesto central de capabilities esté disponible y se inyecte en lenguaje natural.
6. Que ARCA conserve reglas críticas:
   - DNI bajo con padding interno;
   - CUIT formateado para el productor;
   - comando `/cuit` disponible.
7. Que sigan presentes todos los validadores por etapa.
8. Que `.gitignore` excluya el padrón y bases generadas.
9. Que el proyecto no incluya `__pycache__`, `.pyc`, `oficina.db` ni archivos pesados del padrón.

## Importante

Las apariciones internas del nombre `Sofia` en módulos, comentarios o archivos históricos no se renombraron masivamente porque no son visibles al usuario y cambiarlas por estética aumenta el riesgo de romper referencias internas.

El criterio aplicado sigue siendo el definido desde la Etapa 1:

- interfaz visible sin personaje llamado Sofia;
- sistema percibido como OficinaIA;
- código interno estable y sin refactor innecesario.

## Comandos útiles

Instalar dependencias:

```cmd
pip install -r requirements.txt
```

Levantar local:

```cmd
python app.py
```

Importar padrón ARCA:

```cmd
python importar_padron_arca.py apellidoNombreDenominacion.zip
```

Probar ARCA en el chat:

```txt
/cuit 43384856
/cuit 3.456.789
/cuit Ramiro Alejandro Herrera
CUIT de Ramiro Alejandro Herrera
43384856
3456789
```

Correr validación final:

```cmd
python VALIDACION_ETAPA7_INTEGRACION_FINAL.py
```
