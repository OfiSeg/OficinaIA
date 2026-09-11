# COMANDOS — GitHub, Render, ARCA y validación final

Estos comandos son para usar después de descomprimir el ZIP final en `C:\OficinaIA`.

## 1. Instalar dependencias

```cmd
cd C:\OficinaIA
python -m pip install -r requirements.txt
```

## 2. Diagnóstico local

```cmd
python DIAGNOSTICO_OFICINAIA.py
```

Este diagnóstico no muestra claves ni secretos. Solamente indica qué está configurado y qué falta.

## 3. Levantar OficinaIA local

```cmd
python app.py
```

Abrir:

```txt
http://127.0.0.1:5000
```

## 4. Importar padrón ARCA

Colocar el archivo pesado en la carpeta raíz:

```txt
C:\OficinaIA\apellidoNombreDenominacion.zip
```

Ejecutar:

```cmd
cd C:\OficinaIA
python importar_padron_arca.py apellidoNombreDenominacion.zip
```

No hay que descomprimirlo, convertirlo ni abrirlo manualmente.

## 5. Probar ARCA en el chat

```txt
/cuit 43384856
/cuit 43.384.856
/cuit 3456789
/cuit 3.456.789
/cuit Ramiro Alejandro Herrera
CUIT de Ramiro Alejandro Herrera
43384856
3456789
```

## 6. Validar todo antes de subir

```cmd
python VALIDAR_TODO.py
```

Debe terminar en:

```txt
TODO OK
```

## 7. Subir a GitHub

Antes de subir, confirmar que el padrón pesado NO aparece en Git:

```cmd
git status --short
```

Si aparece `apellidoNombreDenominacion.zip`, NO hagas commit. Ese archivo debe quedar fuera del repositorio.

Comandos normales:

```cmd
cd C:\OficinaIA
git status
git add .
git status
git commit -m "Etapas OficinaIA: cédulas, contexto, frontend, documentos, capabilities y ARCA"
git push origin main
```

## 8. Variables importantes en Render

No pegarlas en chats ni en GitHub. Cargarlas desde el panel de Render.

```txt
FLASK_SECRET_KEY
GEMINI_API_KEY
DATABASE_URL
GOOGLE_SHEET_ID
GMAIL_SENDER_EMAIL
GMAIL_OAUTH_CLIENT_ID
GMAIL_OAUTH_CLIENT_SECRET
GMAIL_OAUTH_REFRESH_TOKEN
R2_ENDPOINT_URL
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
OFFICE_TIMEZONE=America/Argentina/Buenos_Aires
```

`OFFICE_TIMEZONE` puede omitirse porque el default ya es Argentina, pero dejarlo explícito en Render ayuda a evitar dudas.

## 9. Build / start de Render

Build command sugerido:

```txt
pip install -r requirements.txt
```

Start command actual:

```txt
gunicorn --workers 1 --threads 1 --timeout 180 app:app
```

El proyecto ya incluye `render-start.txt` con el start command documentado.

---

## Accesos rápidos de Windows

La Etapa 9 agrega archivos `.bat` para evitar escribir comandos largos cada vez.
Ejecutalos haciendo doble clic desde la carpeta del proyecto:

- `INSTALAR_LOCAL.bat` instala dependencias y corre el diagnóstico.
- `INICIAR_LOCAL.bat` levanta OficinaIA con `python app.py`.
- `IMPORTAR_ARCA.bat` busca automáticamente `apellidoNombreDenominacion*.zip` e importa el padrón.
- `VALIDAR_TODO.bat` ejecuta toda la batería de validación.
- `DIAGNOSTICO_LOCAL.bat` muestra el diagnóstico sin instalar nada.

Estos accesos no suben nada a GitHub, no muestran secretos y no incluyen el padrón dentro del repositorio.
