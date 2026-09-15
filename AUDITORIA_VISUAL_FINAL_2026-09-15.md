# OficinaIA — Consolidación visual V1 (15-09-2026)

Alcance: presentación/UX visual. No se modificaron rutas, endpoints, parsers, Gemini, cartera, Excel, ARCA, cálculos, normalizador ni contratos JS.

## Criterio
- Preservar identidad existente y usar como referencia las superficies maduras (login, botones y menús recientes).
- No rediseñar módulos funcionales ni sustituir iconografía propia.
- Unificar ritmo de página, superficies, controles, tabs, tablas, estados e iconografía.
- Reducir deuda visible sin realizar una eliminación masiva de CSS histórico no verificable en navegador.

## Cambios aplicados
- Pendientes: fondo semántico reducido a acento lateral; cards y acciones más sobrias.
- Salud: tabla, filtros, tabs, badges y hover normalizados.
- Manuales: ritmo y cards alineados con el design system.
- Estudio: dropzones menos vacíos, tabs y cards más compactos.
- Excel/Word: shell, tabs, tabla, foco y acciones normalizados conservando densidad.
- Formularios de modales: eliminados estilos inline de Pendientes y Notas del Chat.
- Iconografía: escalas canónicas para comandos, acciones, sidebar y controles globales.
- Dark mode y responsive cubiertos para las reglas nuevas.

## Regla de QA
La validación definitiva requiere comparar el deploy real contra las capturas baseline anteriores, especialmente: Pendientes, Salud, Manuales, Estudio, Excel, Chat `/` y `+`, claro/oscuro.
