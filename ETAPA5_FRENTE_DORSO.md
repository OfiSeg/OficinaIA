# ETAPA 5 — Frente + dorso / documentos múltiples

Base: `OficinaIA_GITHUB_ETAPA4_CEDULA_MOTOR_CHASIS.zip`.

Esta etapa no reimplementa el pipeline documental: la base ya conservaba el agrupamiento seguro de dos caras. Se validó y congeló ese comportamiento.

## Comportamiento preservado

- hasta 5 adjuntos por mensaje, conservando orden;
- selección acumulativa en el compositor;
- DNI/licencia/cédula: dos imágenes compatibles se procesan como un único documento;
- una cara ambigua (`otro`) puede acompañar a otra cara ya reconocida;
- frente en un turno + dorso en el turno inmediato siguiente se usa sólo como candidato y el extractor confirma compatibilidad;
- PDF multipágina puede tratarse como documento multicara cuando el extractor confirma las caras;
- documentos incompatibles no se fusionan;
- colecciones de más de dos archivos no se recortan silenciosamente: siguen al flujo general con todos los adjuntos.

## Cambio mínimo de esta etapa

Para cédula, el resultado ahora expone `caras_combinadas` y la tarjeta muestra `Cédula detectada · frente + dorso` cuando corresponde. No genera ninguna llamada adicional a IA.

## No tocado

- `ai_gateway.py`;
- retries, timeouts o modelos Gemini;
- flujo de envío / X / AbortController;
- Neon;
- persistencia general;
- Excel / Envíos Ya;
- barra/composer;
- lógica de MOTOR/CHASIS de Etapa 4.
