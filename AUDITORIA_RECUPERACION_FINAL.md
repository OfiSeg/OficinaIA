# Auditoría final — OficinaIA recuperada estable

Fecha: 2026-09-11

## Base y referencia

- **Base modificada:** `OficinaIA_GITHUB_FINAL_ESTABLE(1).zip`.
- **Referencia funcional/visual:** `OficinaIA_FAST_FAIL_CLIENTE_FIX.zip`.
- El ZIP descartado se usó únicamente para recuperar implementaciones aisladas aprobadas. No se copiaron su gateway de Gemini, su sistema de retries/fallbacks ni su cancelación X.

## Regla congelada: cédulas

El núcleo actual de cédulas no fue modificado.

Archivos protegidos verificados byte por byte contra la base:

- `cedula_ops.py` — idéntico.
- `ai_gateway.py` — idéntico.
- `document_classifier.py` — idéntico.
- `document_grouping.py` — idéntico.

`cedula_ops.py` SHA-256: `0a05fabb46e078fdbe7bd4338d2b78538d4449774e55651aaa80ea923479f95e`

`ai_gateway.py` SHA-256: `07450cdd7756b2d04b664d95aaf89c5a85ca4fd03793c3ddeb95271818be17c7`

Las validaciones de cédula/documentos existentes continúan pasando. La cédula se trató únicamente como prueba de no regresión.

## Funcionalidades recuperadas / corregidas

### Chat y UX

- Brocha del chat recuperada con iconos aprobados y fondos **Suave / Liso**.
- Persistencia del fondo mediante el mecanismo local existente.
- Composer actual conservado, sin recuperar la X/cancelación rota del ZIP descartado.
- Menú `+`, comandos `/` y dictado por voz conservados/integrados.
- `/cuit` y `/cuil` continúan resolviendo al mismo flujo ARCA.
- Se agregó `/ficha` para ficha operativa determinística de cartera.
- Previews tipo WhatsApp, múltiples adjuntos y lightbox permanecen activos.

### Ciclo de envío de adjuntos

Se corrigió de forma general la separación entre estado del composer y estado de la request:

1. se toma snapshot del texto y archivos;
2. se muestra inmediatamente el mensaje del usuario;
3. se limpia inmediatamente el composer;
4. la request continúa utilizando el snapshot interno;
5. si el envío falla, los archivos/texto pueden restaurarse sin obligar al usuario a buscarlos otra vez, siempre que no haya escrito/adjuntado contenido nuevo mientras tanto.

No existe una excepción especial para cédulas.

### Mensajes internos y presentación

- Los prompts operativos internos como `Procesá estos documentos` ya no se usan como texto visible del usuario cuando sólo se envían adjuntos.
- Se agregó una regla general de presentación para no repetir prosa de éxito cuando una tarjeta estructurada ya contiene la respuesta.
- Advertencias, errores y mensajes realmente útiles siguen siendo visibles.
- No se agregó lógica específica dentro del sistema de cédulas para conseguir esta limpieza visual.

### ATM

Se recuperó un calculador determinístico independiente de Gemini:

- factor de adhesión `5/6`;
- preset Auto `50%`;
- preset Moto `30%`;
- descuento manual `1–50%`, con prioridad sobre el preset;
- disponible desde el chat y desde un modal del menú `+`;
- endpoint autenticado `/api/atm/cotizar`.

### Ficha operativa

Se recuperó un módulo determinístico de consulta de cartera:

- búsqueda por datos disponibles en los libros existentes;
- devuelve coincidencia única, múltiples candidatos o no encontrado;
- no elige arbitrariamente cuando hay múltiples candidatos;
- se integra mediante `/ficha` y el renderer de ficha operativa que ya existía.

No se recuperó `operational_intent.py` del ZIP descartado.

### Funcionalidades que ya existían en la base y se conservaron

- persistencia del chat y metadata;
- R2 para assets históricos cuando está configurado;
- Envíos Masivos Excel/CSV → CSV Envíos Ya;
- ARCA local, búsqueda por DNI/CUIT/CUIL/nombre y soporte de DNI antiguos;
- contexto de cartera con filtro barato antes de consultar Sheets;
- `connect_timeout=3` para Neon;
- prevención existente de la carrera de inicialización del chat;
- alta, tabulados, Envíos Ya, previews, lightbox y múltiples adjuntos.

## Gemini y velocidad

No se importó el gateway de Gemini del ZIP descartado.

`ai_gateway.py` es byte-identical a la base estable.

Se agregó un presupuesto separado para **chat general de texto**:

- variable: `GEMINI_CHAT_BUDGET_SECONDS`;
- default: `20.0` segundos.

Cuando existen adjuntos/documentos, el código existente conserva inmediatamente su presupuesto documental actual. Esto evita cambiar el flujo de cédulas.

### Limitación explícita

El timeout individual del SDK/gateway compartido no se modificó porque `ai_gateway.py` quedó congelado para no introducir una regresión en el sistema documental/cédulas. Por lo tanto, el presupuesto general reduce cadenas/reintentos posteriores, pero **no constituye por sí solo una garantía dura de corte exacto a los 20 segundos si una llamada SDK individual queda bloqueada hasta su timeout actual**.

## Código del ZIP descartado rechazado a propósito

No se recuperó:

- `ai_gateway.py` del ZIP roto;
- cascadas de retries/fallbacks;
- múltiples modelos encadenados sin límite útil;
- X/cancelación frontend que no cancelaba necesariamente el backend;
- `operational_intent.py`;
- `Copiar vehículo` / `copiar_datos_vehiculo` / `copy_vehicle`;
- cambios de cédula;
- cambios de clasificación documental;
- refactors generales no necesarios.

Una búsqueda final no encontró ninguna de las cadenas `Copiar vehículo`, `copiar_datos_vehiculo` o `copy_vehicle` en el proyecto resultante.

## Archivos funcionales modificados

- `app.py`
- `chat_commands.py`
- `chat_special.py`
- `static/css/estilo.css`
- `static/js/app.js`
- `templates/documentos.html`

## Archivos funcionales nuevos

- `atm_cotizador.py`
- `insured_profile.py`
- `static/img/ui/brush.png`
- `static/img/ui/trash.png`

## Validadores actualizados

Se actualizaron únicamente aserciones de tests que todavía exigían comportamientos deliberadamente reemplazados (por ejemplo: prompt operativo visible, adjuntos permaneciendo en composer, wallpaper antiguo o `/cuit` literal sin alias `/cuil`).

- `VALIDACION_ADJUNTOS_MULTIPLES.py`
- `VALIDACION_ETAPA10_1_PREVIEWS_WHATSAPP.py`
- `VALIDACION_ETAPA10_WHATSAPP_VISUAL.py`
- `VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py`
- `VALIDACION_ETAPA7_INTEGRACION_FINAL.py`

Nuevo:

- `VALIDACION_RECUPERACION_FINAL.py`

## Validaciones realizadas

### Estáticas / automatizadas

- 83 archivos Python compilados desde source: **0 errores**.
- `node --check static/js/app.js`: **OK**.
- `node --check static/js/envios_masivos.js`: **OK**.
- Todos los `VALIDACION*.py`: **exit 0**.
- `VALIDAR_TODO.py`: **TODO OK**.
- `VALIDACION_RECUPERACION_FINAL.py`: **OK**.
- Tests determinísticos ATM: preset Auto y porcentaje manual: **OK**.
- Test determinístico de ficha por patente con libro simulado: **OK**.
- Hashes de módulos congelados: **OK**.

### Servicios reales que NO pudieron probarse en este entorno

No se realizó una prueba navegador → Flask → servicios externos real porque este entorno de auditoría no tiene instalados todos los paquetes/runtime del proyecto ni credenciales externas. Faltan en el sandbox, entre otros:

- Flask;
- `google.auth`;
- `psycopg2`.

Tampoco se validaron contra servicios reales:

- Gemini;
- Neon;
- Google Sheets;
- R2;
- Gmail/Google;
- ARCA con un padrón real cargado en este sandbox.

Los tests automatizados simulan/cubren varios de esos caminos, pero eso no equivale a una prueba end-to-end en producción.

## Archivos eliminados del paquete de entrega

Antes de empaquetar se eliminaron artefactos generados durante las pruebas:

- `__pycache__/`;
- `*.pyc`;
- `oficina.db` de prueba;
- logs/temporales de ejecución.

## Criterio de instalación

Este ZIP está preparado como candidato de instalación sobre la base estable y respeta el alcance pedido. La primera ejecución real debe considerarse una prueba funcional final del entorno propio (credenciales, Render, Neon, Gemini, Google y R2). Si aparece un error, el diagnóstico debe hacerse sobre ese fallo concreto y no mediante un refactor general.
