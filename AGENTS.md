# OficinaIA — instrucciones obligatorias para Codex

## 0. Principio arquitectónico obligatorio: una sola lógica activa

**Una responsabilidad funcional debe tener una sola fuente de verdad ejecutable.**

### Regla de antigüedad y dependencias

**Nunca eliminar una implementación por ser antigua ni conservar una implementación por ser nueva.** La antigüedad del código no determina su validez ni su autoridad.

- Antes de retirar una implementación, identificar qué responsabilidad cumple y mapear todos sus consumidores/dependencias.
- Si una funcionalidad nueva necesita una lógica existente que sigue siendo válida, debe **reutilizarla/consumirla como fuente de verdad**. No duplicarla, reinterpretarla ni eliminarla.
- Una implementación existente sólo se retira cuando otra asume explícitamente **la misma responsabilidad**, existe un contrato equivalente o migrado para sus consumidores y se comprobó que no queda ninguna dependencia necesaria de comportamiento exclusivo de la implementación retirada.
- Agregar una función nueva no implica reemplazar lo anterior. Primero clasificar el cambio como **extensión**, **consumo** o **reemplazo**. Sólo un reemplazo justificado habilita retirar la implementación desplazada.
- Si A es la autoridad válida y B es una función nueva que necesita su resultado, el diseño correcto es `A → resultado canónico → B`. B no vuelve a calcular A y A no se elimina.
- Si C reemplaza justificadamente a A, primero migrar/verificar los consumidores de A para que dependan del contrato canónico de C; recién entonces retirar A.
- Está prohibido borrar código funcional sólo para reducir legacy, duplicación aparente o cantidad de capas sin demostrar antes equivalencia de responsabilidad y seguridad de sus dependencias.

Flujo obligatorio antes de retirar o reemplazar lógica:

`MAPEAR RESPONSABILIDAD → MAPEAR CONSUMIDORES → CLASIFICAR (EXTENDER / CONSUMIR / REEMPLAZAR) → REUTILIZAR O MIGRAR → RETIRAR SÓLO SI CORRESPONDE → BUSCAR RESIDUOS → REGRESIÓN → END-TO-END`

- Antes de agregar o modificar una regla, localizar todas las implementaciones, fallbacks, heurísticas, overrides y transformaciones que puedan decidir el mismo resultado.
- Si la implementación nueva reemplaza a una anterior, retirar la anterior en la misma tarea. No alcanza con darle menos prioridad, envolverla en otro `if` o pisarla después.
- Está prohibido conservar dos caminos activos que reconstruyan nombres comerciales, coberturas, contenidos, routing, estados o presentación canónica del mismo dato.
- Parser/adaptador = extrae hechos de la fuente. Normalizador = decide el modelo canónico. UI = presenta/selecciona. Renderer/exportador = renderiza. Una capa posterior no debe reinterpretar una decisión ya tomada.
- No resolver deuda legacy agregando otra capa de CSS, `!important`, fallback o postprocesado. Si una regla nueva es la canónica, consolidar/eliminar la regla desplazada.
- Código histórico sólo se conserva cuando cumple una responsabilidad distinta y vigente. “Por compatibilidad” no justifica dejar una segunda autoridad sin un contrato explícito y una prueba que lo requiera.
- Una tarea no se considera terminada hasta buscar residuos de la lógica reemplazada y probar el flujo final real.
- Si durante una tarea aparece una contradicción entre lógica aprobada y lógica legacy, preservar la lógica aprobada: no reinventarla ni volver a inferirla desde otra capa.

Flujo obligatorio para cambios de comportamiento:

`MAPEAR → IDENTIFICAR AUTORIDAD → MODIFICAR/REEMPLAZAR → RETIRAR LEGACY → BUSCAR RESIDUOS → REGRESIÓN → END-TO-END`

En el cierre de cada tarea indicar qué fuente de verdad quedó, qué lógica desplazada se retiró y qué validaciones se ejecutaron.

Este repositorio es un sistema existente y funcional. Trabajá de forma incremental.
La prioridad es **preservar comportamiento y UI ya validados**. No uses una tarea puntual como excusa para refactorizar o rediseñar otras áreas.

## 1. Fuente de verdad y alcance

- Trabajá siempre sobre el estado actual del repositorio. No reconstruyas desde ZIPs viejos ni copies módulos de versiones anteriores.
- Antes de modificar, inspeccioná los archivos realmente implicados y el diff actual.
- Cambiá solamente lo necesario para la tarea pedida.
- Si una tarea es ambigua y tocar una decisión puede romper otra parte, conservá el comportamiento existente.
- No hagas "limpieza general", migraciones, cambios de nombres masivos ni reorganización de carpetas salvo pedido explícito.

## 2. Regla crítica: lógica y UI son capas separadas

**Normalizar datos NO autoriza a rediseñar la interfaz.**

- La UI actual se considera contrato visual.
- Una mejora de arquitectura/datos debe alimentar los componentes existentes mediante adaptadores o configuración, sin cambiar su estructura visual.
- Una mejora visual no debe cambiar parsers, cálculos, reglas comerciales, almacenamiento ni rutas salvo que la tarea lo requiera explícitamente.
- No mezcles en una misma tarea refactor de arquitectura + rediseño global + nuevas funciones.

## 3. No tocar salvo pedido explícito

Preservar especialmente:

- Gemini / gateway de IA / reintentos.
- Cartera y Excel interno.
- ARCA / CUIT / CUIL.
- Mail y Envíos Ya.
- Cédulas, extracción y validación documental.
- Salud y Estudio.
- Login/autenticación, roles y seguridad.
- Base de datos y migraciones.
- Parsers ATM, Mercantil Andina y Federación Patronal.
- Normalizador universal de cotizaciones.
- Fórmulas de descuentos/bonificaciones y redondeo comercial.
- Mensajes comerciales determinísticos.
- Scroll interno validado de Cotizaciones.
- Visor premium de imágenes.
- Ficha operativa de `/patente`.
- Sistema global de toast/feedback, salvo pedido específico.

No cambies rutas, nombres de endpoints ni contratos JSON existentes sin necesidad real.

## 4. Cotizaciones — reglas permanentes

- Múltiples compañías deben coexistir; una nueva fuente no borra las anteriores.
- La fuente agregada más recientemente aparece arriba.
- Mantener selecciones previas al agregar otra compañía.
- Cada fuente conserva compañía, código/nombre original y datos fuente.
- La marca de compañía puede aportar favicon y acento cromático, pero no debe rediseñar la card.
- Color de compañía = identificación, no decoración. Nada chillón.
- Si una compañía no tiene branding configurado, usar presentación neutra.
- Nunca inferir una cobertura de una compañía desconocida sólo por el código.
- Normalizar por contenido explícito cuando exista evidencia suficiente.

Perfiles comerciales normalizados actuales:

- RC = Responsabilidad Civil.
- B = Robo, Incendio y Accidente Total.
- B1 = Robo e Incendio Total.
- C = Terceros Completo.
- C_PLUS = Terceros Completo Plus / equivalente confirmado.
- LB / LB1 = perfiles específicos con Robo Parcial al amparo del Robo Total.
- TODO_RIESGO = Todo Riesgo, preservando franquicia real del documento.

No inventar equivalencias, adicionales, franquicias, asistencia o límites.

## 5. Branding configurable

Compañías y herramientas usan una capa de configuración separada de la UI:

- nombre visible;
- link de acceso;
- link/fuente de logo o favicon;
- color de marca;
- aliases de detección;
- visible/oculto.

El link de acceso y la fuente de favicon son independientes. Ejemplo: ATM puede abrir su extranet y tomar su identidad del sitio oficial.

No hardcodees nuevos favicons directamente en componentes si pueden entrar por esta configuración.

## 6. Sidebar y branding interno

- El sidebar **NO** debe mostrar el bloque redundante `logo + ofi/nombre de oficina` arriba.
- El sidebar empieza con la navegación.
- Conservar el favicon del navegador, el logo superior interno del chat y el logo grande del welcome.
- Los iconos propios de OficinaIA ya tienen una familia canónica: no sustituir por una librería genérica.
- Los logos/favicons de compañías y herramientas externas se preservan como marcas externas.

## 7. Welcome del chat

- Los accesos visibles se configuran únicamente desde **Configuración → Personalización**.
- En el chat son accesos operativos, no un editor.
- NO mostrar handles de drag, botones de editar ni reordenamiento in-place.
- El orden y selección guardados en Personalización son los que debe renderizar el welcome.
- El welcome usa el logo grande bueno de OficinaIA desde el primer frame; no crear un segundo estado visual que lo reemplace.

## 8. Header / shell global

Tema, Ajustes y Salir pertenecen al header/barra correspondiente. No son controles flotantes.

- En Chat IA forman parte estructural de la misma barra de `Conversaciones`.
- En páginas internas forman parte de la barra global del shell.
- No usar `position: fixed` o offsets mágicos para que sigan el viewport.
- Al hacer scroll en Word/Excel/Pendientes/etc. no deben bajar sobre el contenido.
- El control de tema es icon-only: sol/luna según estado, sin cápsula grande ni switch dibujado.
- Ajustes: icono limpio.
- Salir: icono limpio con acento rojo discreto.
- Área clickeable cómoda, pero visualmente sin grandes cajas.

## 9. Personalización

La solapa de Personalización es el lugar de edición de interfaz:

- ordenar módulos;
- ordenar compañías;
- ordenar herramientas;
- elegir/ordenar accesos del chat;
- editar branding de compañías/herramientas.

La sola existencia de Personalización no debe cambiar ningún orden automáticamente. Aplicar cambios sólo después de guardar una preferencia.

## 10. Excel / Word

Excel:

- La lógica histórica de +Fila/-Fila/+Columna/-Columna/limpieza puede permanecer detrás, pero no debe ocupar la UI normal.
- Un único control de exportación ofrece XLSX y CSV.

Word:

- Preservar editor enriquecido y exportación DOCX con formato básico.
- No volver a convertirlo en textarea plano.

## 11. Estilo visual

No crear un template SaaS genérico.

- Premium = consistencia, jerarquía, proporción y detalle.
- No usar blur, glass, gradientes, glow, scale o animaciones porque sí.
- El visor de imágenes es referencia positiva de terminación.
- La ficha operativa de `/patente` es referencia positiva de presentación de datos.
- No miniaturizar tipografía/iconos sólo para hacer entrar más contenido.
- Responsive debe preferir reflow/wrap/stack antes que texto microscópico.

## 12. Archivos y código

- No agregar dependencias nuevas si la tarea puede resolverse con las existentes.
- No guardar secretos, tokens, contraseñas ni credenciales en el repo.
- No editar `oficina.db`, planillas reales o archivos de datos salvo pedido explícito.
- Mantener compatibilidad con Render y ejecución local.
- Evitar `!important` nuevo salvo que sea imprescindible por CSS legado; preferir arreglar el selector/regla fuente.
- No sumar overrides al final indefinidamente: si una regla vieja contradice el comportamiento canónico y el alcance lo permite, consolidarla.

## 13. Flujo de trabajo obligatorio

Antes de cambiar:

1. Leer esta guía.
2. Inspeccionar los archivos implicados.
3. Identificar dependencias y comportamiento actual.
4. Mantener el scope de la tarea.

Después de cambiar, ejecutar como mínimo:

```bash
python -m compileall .
```

Validar JavaScript disponible con Node (`node --check`) y parsear/renderizar templates cuando el entorno lo permita.
Si tocaste un módulo con validaciones propias (`VALIDACION_*.py`), ejecutarlas cuando no requieran credenciales/servicios externos.

Revisar el diff y comprobar que no haya archivos no relacionados modificados.

## 14. Git / GitHub

- No hacer `push --force`.
- No reescribir historia.
- No borrar ramas ni tags.
- No hacer merge a `main` sin pedido explícito.
- Preferir una rama/tarea pequeña, diff revisable y commit descriptivo.
- Si el usuario pide sólo implementar, dejar cambios listos para revisión; no publicar/desplegar por iniciativa propia.

## 15. Criterio final

Si una tarea puntual hace que otra pantalla cambie sin que el usuario lo haya pedido, eso es una regresión.

**OficinaIA se modifica de manera incremental: preservar lo bueno, cambiar sólo lo solicitado y validar antes de entregar.**

## Router conversacional — invariantes obligatorias

- La calculadora textual ATM está desactivada en el chat. La única calculadora ATM autorizada es la UI de Cotizaciones (`/api/atm/cotizar`). Mencionar `ATM` en lenguaje natural nunca debe disparar cálculo de precios.
- `su` / `sus` no activan por sí solos un registro de cartera. Frases como `sus coberturas`, `sus grúas` o `sus remolques` pertenecen al dominio documental/compañías.
- ARCA/CUIT/CUIL se activa exclusivamente con los comandos `/cuit` o `/cuil`. Nombres, DNI, CUIT/CUIL numéricos, la palabra ARCA y cualquier texto natural deben seguir el router normal y jamás activar ARCA por heurística.
- Fuera de `/cuit` o `/cuil` no existe activación implícita de ARCA ni selección automática de esa fuente; dentro del modo abierto por esos comandos sí se aceptan nombre, DNI o CUIT/CUIL como dato de búsqueda.
- Si una consulta nombra una compañía y no hay metadata interna de esa compañía, devolver evidencia insuficiente. Nunca usar metadata de otra compañía como fallback.
- Internet no se ofrece a Gemini salvo pedido explícito del usuario (`internet`, `web`, `Google`, etc.). Consultas internas de compañía deben priorizar metadata/manuales y reconocer ausencia de evidencia.
- El historial conversacional se conserva para entender el hilo, pero nunca debe reactivar calculadoras, ARCA, alta u otra acción por una palabra ambigua.
- Corregir routing no autoriza a rediseñar la UI ni tocar Cotizaciones, parsers de documentos, Excel, alta, mail o branding salvo pedido explícito.

## 16. Cerebro del chat — estado y tools

Estas reglas son arquitectura estable, no detalles de implementación:

- El historial es memoria lingüística. **Nunca** reactiva por sí solo ARCA, cartera, alta, calculadoras, envíos ni otra acción.
- Los contextos operativos viven en `chat_state.py`, están ligados a `chat_id` y tienen TTL. No volver a crear claves de `session` sin expiración para esas funciones.
- ARCA permanece determinístico antes de Gemini; no exponer sus tools al modelo general.
- Gemini recibe una **allowlist mínima de tools según la intención del turno**. No volver a ofrecer todas las tools juntas.
- Internet sólo se habilita por pedido explícito del usuario.
- Una vez que una llamada del turno eligió modelo, el resto del tool-loop usa ese mismo modelo. No mezclar modelos dentro de una respuesta lógica.
- Las function responses deben volver como `Content(role="user", parts=[function_response...])` y conservar `call.id` cuando el SDK lo admita.
- El último adjunto puede actuar como documento activo efímero sólo en follow-ups documentales claros; nunca heredarlo indiscriminadamente a mensajes no relacionados.
- Metadata de compañías está aislada por compañía. Ausencia de fichas = evidencia insuficiente, no fallback a otra aseguradora.

## 17. Normalizador universal de cotizaciones

- Primero preservar **dato original**; después normalizar. Nunca descartar código/nombre/franquicia/precio fuente por simplificar la UI.
- Compañías equivalentes por alias/acentos/sufijos deben canonicalizar a una sola identidad (`San Cristobal`, `San Cristóbal Seguros`, etc.).
- Una cotización desconocida puede normalizarse por descripción explícita aunque no exista parser específico de esa compañía.
- Tablas PDF deben recorrer todas las filas de cobertura; no detenerse en la primera alternativa.
- Variantes Todo Riesgo con el mismo código original pero distinta franquicia son alternativas distintas y no se deduplican.
- Todo Riesgo se presenta visualmente como `D<porcentaje>` cuando el porcentaje está explícito: 1.5% → `D1.5`, 2% → `D2`, 2.5% → `D2.5`, 3% → `D3`.
- Ordenar ese grupo por porcentaje ascendente, preservando importes concretos de franquicia y precio.
- Si el documento no aporta información suficiente, dejar `SIN_CLASIFICAR`; no inferir por un código de compañía desconocida.

## 18. Controles globales

- Tema debe ser compacto e icon-only: mostrar sólo sol o luna, sin cápsula/switch ancho ni área visual invisible.
- Tema, Ajustes y Salir forman parte de la barra; no flotan ni siguen el scroll.
- Salir usa el mismo lenguaje cromático que Ajustes. **No rojo** en estado normal ni hover.
