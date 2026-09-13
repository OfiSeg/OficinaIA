# OficinaIA — instrucciones obligatorias para Codex

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
