# OficinaIA Plus — versión hipermejorada

Sobre la base UX (tandas 1–5) se agrega capa operativa de alto ROI.

## Nuevas capacidades

### 1. Bandeja de Pendientes (`/pendientes`)
- Cola global de trabajo fuera del chat
- Estados: pendiente / hecho / descartado
- Badge en el menú lateral con cantidad
- API: GET/POST/PATCH/DELETE `/api/pendientes`

### 2. Acciones bajo cada respuesta de Sofia
- **Guardar ficha** → crea metadato reutilizable
- **A pendientes** → manda a la bandeja
- **WhatsApp** → prepara prompt de mensaje al cliente (San José Seguros)

### 3. Workflows en el welcome del chat
Atajos: alta asegurado, flota, coti, remolque, WhatsApp, Envíos Ya.

### 4. Plantillas de metadatos
En Biblioteca → Metadatos: remolque, cobertura, procedimiento, contacto.

### 5. Validación de filas Excel
`POST /api/validar-excel-fila` — patente, campos mínimos, avisos.

### 6. Tags en historial
Flota, Coti, WA, Remolque, Cobertura, Alta, Envío según el título.

### 7. Propuestas Excel → “Dejar pendiente”
No se pierde la carga si no se confirma al instante.

## Archivos nuevos
- `pendientes_ops.py`
- `static/js/oficina_plus.js`
- `templates/pendientes.html`
- `CAMBIOS_PLUS.md`

## Filosofía
Menos tipeo, más confirmación. El conocimiento que se pregunta dos veces se convierte en ficha. El trabajo a medias vive en Pendientes, no en la memoria de quien atendió.
