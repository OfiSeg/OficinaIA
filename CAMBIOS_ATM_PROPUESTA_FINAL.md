# Cotización ATM — cierre de interfaz y propuesta comercial

Base: `OficinaIA_HYBRID_DESKTOP_IOS_FINAL.zip`.

## Cambios funcionales del módulo ATM

- Se eliminó el selector visual Auto/Moto del cotizador. El usuario controla únicamente el descuento comercial manual o mediante presets 30/40/50.
- La fórmula de adhesión queda intacta: `adherido = cuponera / 1,20` (`5/6`).
- La familia B queda en seis alternativas: `B B1 B2 B3 B4 B5`.
- La matriz de desktop queda en una sola fila: `A A1 B B1 B2 B3 B4 B5 C CPr CB TR 3% 6%`.
- 3% y 6% tienen el mismo tamaño visual que el resto. Seleccionarlos activa TR; deseleccionar TR limpia la franquicia.
- C, CPr y CB comparten la misma descripción comercial base, cambiando únicamente el nombre del plan.
- Las variantes `SIN ASISTENCIA` se comunican al asegurado únicamente como `Sin grúa.`
- El área de propuesta es editable antes de copiar.
- Sólo las coberturas seleccionadas ingresan a la propuesta.

## Texto comercial

La propuesta comienza con:

> ¡Hola! Te paso algunas opciones de cobertura para tu vehículo para que puedas compararlas y elegir la que mejor te sirva:

Los códigos internos A/B/C/TR nunca aparecen en el mensaje final. Los precios se muestran como:

`$XX.XXX con cupones · $XX.XXX con CBU o tarjeta adherida`

Todo Riesgo explica en lenguaje simple la franquicia porcentual y mantiene una única aclaración contractual al final.
