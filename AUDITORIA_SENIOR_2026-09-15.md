# OficinaIA — cierre de auditoría senior (15-09-2026)

## Alcance aplicado
- Se siguió el pipeline documental real hasta DOCX → PDF → JPG/PNG → ZIP.
- Se corrigió la contradicción semántica de exclusiones explícitas (caso Allianz S/GRANIZO).
- Se renderiza el vehículo en la propuesta documental; antes sólo llegaba al nombre de archivo.
- Se flexibilizó la fila exterior de compañía para evitar huecos causados por un bloque excesivamente rígido, conservando indivisible cada cobertura interna.
- Se mantuvo el cierre institucional en la última página, pero anclado al área útil de márgenes para evitar recorte en LibreOffice/PDF/JPG.
- Se agregaron regresiones documentales que verifican vehículo y exclusión de granizo.
- Se ejecutó el pipeline real DOCX → PDF → JPG con un caso Nissan Tiida de regresión y se verificó el contenido final.
- Se consolidó el tamaño óptico de iconos clave de los menús / y + sobre la capa canónica existente, sin crear otra hoja de parches.
- Se añadieron tokens canónicos de iconografía y render vectorial de precisión.

## Regla de mantenimiento
Una corrección documental no se considera cerrada hasta validar el archivo final exportado. Las exclusiones explícitas dominan detecciones textuales contradictorias.

## Validaciones ejecutadas
- `python -m compileall -q .` — OK
- `node --check static/js/app.js` — OK
- `python VALIDACION_NORMALIZACION_SISTEMA.py` — OK
- `python VALIDACION_COTIZACION_DOCUMENTAL.py` — OK
- Regresión real DOCX → PDF → JPG Nissan Tiida — OK: vehículo presente, `S/GRANIZO` sin bullet `Granizo`, cierre único.

## Nota de entorno
No se pudo importar `app.py` en el contenedor de auditoría porque Flask no está instalado en este runtime. No es un error del proyecto; las validaciones estáticas y específicas del proyecto sí se ejecutaron correctamente.
