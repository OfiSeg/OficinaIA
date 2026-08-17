# Integración R2 + Neon de OficinaIA

La sección Manuales utiliza:

- Cloudflare R2 para almacenar físicamente los PDFs privados.
- Neon PostgreSQL para los metadatos.
- SQLite existente para usuarios, chats y configuración.
- La lógica existente de extracción/chunks/ranking de PDF se conserva.

## Variables de entorno

El archivo `.env` local debe contener:

```env
DATABASE_URL=...
R2_ENDPOINT_URL=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=oficinaia-manuales
```

Nunca subas `.env` a GitHub.

## Dependencias

```bat
pip install -r requirements.txt
```

## Inicio local

```bat
python app.py
```

Al iniciar, OficinaIA verifica/crea la tabla `manuales` en Neon.

## Almacenamiento

Los manuales quedan en R2 con claves de la forma:

```text
manuales/<slug-compania>/<uuid>__<nombre>.pdf
```

Neon guarda:

- `id`
- `nombre`
- `r2_key`
- `tamaño`
- `fecha_subida`

Los PDFs no se sirven públicamente. Las rutas de visualización requieren login y el backend obtiene el objeto desde R2.

Para la IA, los PDFs de manuales se descargan únicamente a una caché temporal del sistema y se procesan con la lógica de `pypdf` ya existente. No se almacenan permanentemente dentro del proyecto.

## Límite

Los PDFs individuales tienen un máximo de 20 MB. El almacenamiento objetivo de la sección Manuales es aproximadamente 30–40 MB en total.

## Prueba recomendada

1. Iniciar OficinaIA.
2. Entrar como administrador.
3. Abrir Biblioteca/Manuales.
4. Subir un PDF real.
5. Confirmar que aparece en la interfaz.
6. Confirmar en Cloudflare R2 que existe el objeto.
7. Ejecutar en Neon:

```sql
SELECT * FROM manuales ORDER BY id DESC;
```

8. Preguntar al chat algo que esté explícitamente dentro del manual.
9. Eliminar el manual y comprobar que desaparece de R2 y de Neon.
