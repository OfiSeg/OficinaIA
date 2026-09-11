# OficinaIA — Etapa 1

Base: `OficinaIA_GITHUB_DEFINITIVA_CEDULA_VISUAL_V3(6)/(7)` (ambos ZIP eran idénticos por SHA-256).

## Cambios aplicados

- Se quitó el texto visible **Sofia** del encabezado del chat y se conservó solamente el ícono de carpeta.
- La lectura de cédulas mantiene las lecturas independientes de PATENTE/MOTOR/CHASIS y presenta variantes reales cuando hay discrepancias.
- Las dudas por posición se exponen como, por ejemplo, `Posición 9: 8 / 0`.
- `3/3` sigue siendo evidencia fuerte, pero ya no habilita `verificado` si la calidad visual informada es deficiente.
- La confianza incorpora calidad global/regional y problemas visuales reportados (desenfoque, reflejo, contraste, etc.).
- Se agregó normalización adaptativa de orientación: si la primera mirada detecta 90/180/270°, se rota una copia temporal y se repite la lectura general antes de las lecturas críticas.
- Se mantienen y aprovechan los recortes ampliados de MOTOR y CHASIS.
- Cuando un dato crítico requiere revisión, la UI ya no ofrece `Copiar igualmente`.
- Se muestran lecturas completas realmente observadas y la opción `Ingresar manualmente`.
- El productor debe confirmar el dato mediante `Seleccionar lectura` / `Confirmar dato` antes de usarlo.
- Se diferencia visual y conceptualmente `Verificado` de `Confirmado por productor`.
- Las acciones combinadas de copia quedan bloqueadas mientras exista un dato crítico sin verificar/confirmar.
- Se actualizó manualmente la versión de JS/CSS para evitar que esta etapa quede oculta por caché; el cache-busting automático queda para la etapa correspondiente.

## Validación

Se mantuvieron verdes los validadores existentes:

- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py` — 11 grupos.
- `VALIDACION_V20_DNI_LICENCIA.py` — 13 grupos.
- `VALIDACION_ADJUNTOS_MULTIPLES.py` — 12 grupos.
- `VALIDACION_RESILIENCIA_GLOBAL.py` — 12 grupos.
- `VALIDACION_SALUD_SERVICIOS.py` — 7 grupos.

Se agregó:

- `VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py` — 7 grupos.

No se modificó la lógica de ARCA en esta etapa. El padrón/ZIP de ARCA queda reservado para su etapa específica; no era necesario tocarlo para estas correcciones.
