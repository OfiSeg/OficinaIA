# Corrección: error 500/502 en el chat + usuarios que se borraban

## 1) Error 500 / 502 en preguntas tipo "cuántas grúas tiene mercantil"

**Causa real:** no era información ni tokens. El prompt de `consultar_gemini()`
obligaba a la IA a reintentar la búsqueda cuando el primer intento devolvía 0
resultados (por ejemplo, buscar "grúa" en una planilla que dice "remolque").
Eso podía encadenar hasta 6 vueltas x 3 modelos = hasta 18 llamadas a Gemini
en un mismo request. Con gunicorn en modo 1 worker / 1 thread / timeout 180s,
esa cadena larga terminaba en timeout (502) o en una excepción intermedia (500).

**Cambios en `servicios_ia.py`:**
- Se agregó un diccionario de sinónimos de dominio (`_SINONIMOS_DOMINIO`):
  grúa/remolque/auxilio/traslado, choque/colisión/siniestro, robo/hurto,
  cristales/vidrios/parabrisas, franquicia/deducible, vehículo/auto/unidad, etc.
- La consulta del usuario se expande con esos sinónimos ANTES de buscar en
  `_buscar_en_registros`, `_puntuar_metadato` y el filtro de tipo de
  `buscar_vehiculos`. Así "cuántas grúas" también encuentra filas que dicen
  "remolque" en la primera pasada, sin necesitar reintento.
- Se bajó el límite de vueltas del bucle de herramientas de 6 a 3
  (`LIMITE_VUELTAS`), así nunca se puede encadenar una secuencia tan larga
  que exceda el timeout del servidor, incluso en el peor caso.

No se tocó `render-start.txt` (1 worker/1 thread) a propósito: ese valor ya
había sido bajado antes para evitar picos de memoria al procesar varios PDFs
en simultáneo (ver `CAMBIO_RENDER_ESTABILIDAD.md`). El problema de esta vuelta
era de tiempo por reintentos, no de concurrencia, así que se resolvió ahí.

## 2) Los usuarios (login) se borraban solos

**Causa real:** la tabla `usuarios` vivía únicamente en el SQLite local
(`oficina.db`). Render no tiene disco persistente en el plan usado: cada
redeploy o reinicio del contenedor devuelve ese archivo a la versión que
viene en el zip, borrando cualquier usuario creado después.

**Cambios:**
- `database_pg.py`: nueva tabla `usuarios` en Neon Postgres + funciones
  `listar_usuarios`, `obtener_usuario`, `obtener_usuario_por_id`,
  `usuario_existe`, `crear_usuario`, `actualizar_usuario`, `eliminar_usuario`.
  El admin principal (`admin` / rol protegido) se bootstrapea automáticamente
  en Neon la primera vez que corre `inicializar_postgres()`.
- `app.py`: todas las rutas de login y de gestión de usuarios
  (`/login`, `/configuracion`, `/api/usuarios` POST/PUT/DELETE) ahora usan
  Neon cuando `DATABASE_URL` está configurada (ya lo está en tu `.env`).
  El SQLite local queda solo como respaldo para correr el proyecto sin Neon
  (por ejemplo en tu compu, sin variables de entorno).

Con esto, los usuarios y contraseñas quedan en la misma nube que ya usás
para manuales y metadatos, y sobreviven a redeploys y reinicios.

## Qué probar después de desplegar
1. Preguntar "cuántas grúas tiene mercantil" y variantes con sinónimos.
2. Crear un usuario nuevo desde Configuración, forzar un redeploy en Render
   (o esperar a que el contenedor se reinicie) y confirmar que el usuario
   sigue pudiendo loguearse.
