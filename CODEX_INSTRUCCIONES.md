# Cómo trabajar este repo con Codex

Codex debe leer `AGENTS.md` antes de tocar código. Ese archivo contiene las reglas obligatorias del proyecto.

Flujo recomendado para cada tarea:

1. Partir siempre del último commit del repositorio.
2. Pedir una tarea concreta (ej. “corregí sólo el control de tema; no tocar Cotizaciones”).
3. Dejar que Codex inspeccione primero el código relevante.
4. Implementar el cambio mínimo.
5. Ejecutar validaciones locales.
6. Revisar el diff.
7. Commit/PR pequeño y descriptivo.
8. Merge sólo después de revisar visualmente la aplicación.

No usar Codex para “mejorar todo” sin un alcance concreto. En OficinaIA la UI y la lógica comercial ya contienen decisiones validadas que deben preservarse.
