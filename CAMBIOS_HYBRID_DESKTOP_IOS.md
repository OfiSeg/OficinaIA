# OficinaIA — refinamiento híbrido desktop + principios iOS

## Base utilizada
`OficinaIA_CONTEXTO_CARTERA_ARCA_CORREGIDO.zip`

No se utilizó `OficinaIA_IOS_DESIGN_SYSTEM_FINAL.zip` como base.

## Alcance
Etapa visual. No se modificó lógica de Gemini, routing, contexto de cartera/ARCA, lectura documental, alta, Excel, fórmula/cotizador ATM, mails, Estudio, Salud ni endpoints.

## Implementación
- Nuevo `static/css/design-system.css`, cargado después de `estilo.css`.
- Se conserva la estructura desktop y la identidad azul de OficinaIA.
- Sidebar expandida vuelve a tener presencia y texto visible; rail colapsado sigue disponible.
- Chat gana protagonismo con lista de conversaciones de ancho útil, empty state operativo y composer de escala cómoda.
- Menú `+` conserva su estructura aprobada y recibe un pulido de color, spacing, radios y sombra.
- Settings queda acotado al contenido y elimina el exceso de vacío.
- Pendientes usa ancho contenido, cards compactas y botones legibles.
- Modales/popovers reciben la mayor influencia iOS: radios, overlay blur funcional, sombras suaves y controles consistentes.
- Cotización ATM conserva exactamente su lógica y matriz; sólo se ajusta la escala visual para evitar controles microscópicos.
- Dark mode mantiene superficies y contraste equivalentes.

## Decisiones descartadas de la prueba iOS anterior
- Mini-sidebar de sólo iconos.
- Escala tipográfica excesivamente pequeña.
- Controles microscópicos.
- Grandes superficies blancas sin función.
- Layouts estirados con poco contenido.
- Transformación integral de OficinaIA en una imitación de iOS.

## Ideas recuperadas
- Tokens visuales centralizados.
- Segmented controls.
- Switches.
- Radios coherentes.
- Sombras sólo para capas elevadas.
- Blur funcional en overlays.
- Estados hover/focus suaves.
- Sistema reducido de botones.
