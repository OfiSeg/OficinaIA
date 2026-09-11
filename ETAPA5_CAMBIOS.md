# ETAPA 5 — Capabilities + hotfix zona horaria local

## Base

Esta etapa parte de `OficinaIA_ETAPA4_DOCUMENTOS_MULTIPLES.zip`.

## Qué se corrigió además

Se incorporó el hotfix de zona horaria local/Windows:

- `requirements.txt` incluye `tzdata`.
- `office_time.py` mantiene `America/Argentina/Buenos_Aires` como zona preferida.
- Si el runtime local no dispone de base IANA, usa fallback fijo UTC-3 (`ART`) sin romper el chat.

## Manifiesto central de capacidades

Se creó `capabilities.py` como fuente simple y central de capacidades actuales.

El objetivo es que el asistente explique OficinaIA como sistema operativo real y no como una versión vieja limitada a Excel/manuales.

Capacidades registradas:

- consultas de cartera;
- conteos y fechas;
- estadísticas;
- análisis de archivos;
- documentos múltiples;
- lectura de cédulas;
- ambigüedad en cédulas;
- lectura de DNI/licencias;
- lectura de pólizas;
- alta desde póliza;
- guardado en planilla;
- Envíos Ya;
- manuales/metadatos;
- comparación de compañías;
- Estudio;
- redacción de comunicaciones;
- envío de mails si Gmail está configurado;
- Salud del sistema.

## Qué NO se hizo

- No se implementó ARCA todavía.
- No se agregó `/cuit`.
- No se cargó `apellidoNombreDenominacion.zip`.
- No se marcó ARCA como capacidad disponible.
- No se reescribieron herramientas ni flujos operativos.

## Prompt

`sofia_prompt.py` ahora inyecta las capacidades habilitadas en el contexto del modelo.

También se eliminó la obligación de autodenominarse “Sofia” ante el usuario. El prompt ahora indica que es el asistente interno de OficinaIA sin nombre propio visible.

## Salud / textos visibles

Se corrigieron textos visibles futuros que todavía podían mostrar “Sofia”.

Además `system_health.listar_eventos` normaliza mensajes históricos antes de mostrarlos, para que entradas viejas como “Sofia no pudo responder” no sigan apareciendo en Salud.

## Validación nueva

Se agregó `VALIDACION_ETAPA5_CAPABILITIES.py`.
