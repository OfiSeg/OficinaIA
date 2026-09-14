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

## Router conversacional — reglas críticas (13-Sep-2026)

Estas reglas son contrato funcional y NO deben relajarse durante refactors:

1. Mencionar `ATM` en una pregunta documental nunca activa una calculadora textual. La sintaxis legacy con importe sólo abre la UI de Cotizaciones; no calcula en el chat.
2. `su` / `sus` no son señal suficiente para activar un registro de cartera. `sus coberturas`, `sus grúas`, `sus remolques` deben continuar al dominio documental.
3. ARCA/CUIT/CUIL se activa exclusivamente mediante `/cuit` o `/cuil`. Fuera de esos comandos, nombres, DNI, CUIT/CUIL numéricos, la palabra ARCA y cualquier texto natural nunca deben caer al parser de personas/ARCA.
4. Una vez abierto explícitamente `/cuit` o `/cuil`, ese modo puede recibir nombre, DNI o CUIT/CUIL como dato de búsqueda; fuera de ese modo no existe activación implícita por contexto ni por historial.
5. Metadata de una compañía jamás puede reemplazarse con metadata de otra si la compañía pedida no tiene fichas. Responder evidencia insuficiente.
6. Internet sólo debe estar disponible a Gemini cuando el usuario lo pide explícitamente.
7. El historial sirve para resolver continuidad semántica, no para reactivar herramientas o estados operativos.
8. Antes de modificar routing ejecutar `python VALIDACION_ROUTER_CHAT.py`.

## Arquitectura del chat y cotizaciones — no regresar

- `chat_state.py` es el dueño de los contextos operativos efímeros (ARCA/cartera/alta): chat_id + TTL.
- Historial = continuidad semántica; no estado ejecutable.
- Gemini usa tools por allowlist de intención y modelo fijado durante cada turno.
- ARCA se resuelve fuera del toolset general de Gemini.
- Function responses se envían agrupadas con rol `user` y call id cuando sea compatible.
- El documento activo se reutiliza sólo en follow-ups inequívocos y expira.
- El normalizador universal debe preservar todas las alternativas y distinguir Todo Riesgo por franquicia (`D1.5`, `D2`, `D2.5`, `D3`, etc.).
- No convertir una mejora de normalización en rediseño de Cotizaciones.
- Los controles globales tema/Ajustes/Salir son compactos y estructurales; Salir no usa rojo.

Antes de tocar cualquiera de estos puntos ejecutar:

```bash
python VALIDACION_ROUTER_CHAT.py
python VALIDACION_NORMALIZADOR_COTIZACIONES.py
```
