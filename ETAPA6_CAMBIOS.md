# ETAPA 6 — ARCA / CUIT

Implementación realizada sobre `OficinaIA_ETAPA5_CAPABILITIES_HOTFIX.zip`.

## Qué quedó implementado

- Importador interno del padrón `apellidoNombreDenominacion.zip`.
- Lectura directa del ZIP sin descomprimirlo manualmente.
- Procesamiento por streaming, línea por línea.
- Extracción fija:
  - primeros 11 caracteres = CUIT/CUIL;
  - siguientes 30 caracteres = apellido/nombre/denominación.
- Filtrado de personas humanas por prefijos compatibles: `20`, `23`, `24`, `27`.
- Indexación del DNI como texto de 8 posiciones internas, preservando DNI históricos menores a 10 millones.
- Presentación del DNI al productor sin ceros artificiales.
- Resolución determinística DNI → CUIT/CUIL.
- Búsqueda determinística de personas reales por apellido/nombre.
- Hasta 10 candidatos reales.
- Separación conceptual entre ARCA y cartera/Excel.
- Comando `/cuit`.
- Detección natural de intención:
  - `CUIT de Ramiro Herrera`;
  - `cuil del DNI 3456789`;
  - `43384856` como DNI probable si no hay contexto contrario;
  - nombre aislado pregunta si corresponde cartera o ARCA cuando no hay contexto suficiente.
- Continuidad conversacional para candidatos: `el segundo`, `el tercero`, etc.
- Integración con tools de IA:
  - `resolver_cuit_por_dni`;
  - `buscar_personas_arca`;
  - `estado_padron_arca`.
- Integración con `CAPABILITIES`, disponible sólo cuando el padrón está cargado.
- `.gitignore` actualizado para no subir el padrón ni bases generadas a GitHub.

## Backend de almacenamiento

- En producción con `DATABASE_URL`: usa PostgreSQL/Neon existente.
- En desarrollo local sin `DATABASE_URL`: usa SQLite local como fallback, siguiendo la arquitectura existente de OficinaIA.

## Comando para importar

Colocar `apellidoNombreDenominacion.zip` dentro de la carpeta del proyecto y ejecutar:

```cmd
cd C:\OficinaIA
python importar_padron_arca.py apellidoNombreDenominacion.zip
```

No hay que descomprimir ni convertir el archivo.

## Cómo probar

```text
/cuit 43384856
/cuit 43.384.856
/cuit 3456789
/cuit 3.456.789
/cuit Ramiro Alejandro Herrera
CUIT de Ramiro Alejandro Herrera
43384856
3456789
```

Si el nombre está aislado y no hay contexto, OficinaIA pregunta si debe buscar en cartera o en ARCA.

## Variables de entorno nuevas

No se agregó ninguna variable nueva obligatoria.

## Validación agregada

- `VALIDACION_ETAPA6_ARCA_CUIT.py`
