# Cambios de interfaz — 04/09/2026

- Sidebar simplificada: se eliminaron etiquetas decorativas y letras C/P/M/X/S.
- Navegación principal con iconos SVG consistentes.
- Se quitaron encabezados y subtítulos genéricos tipo “Bandeja de trabajo”, “Administración”, “Espacio de trabajo”, “Mesa de trabajo” y equivalentes.
- Configuración rediseñada como panel normal con secciones Apariencia, General, Herramientas y Usuarios.
- Apariencia: tamaño general, tamaño del menú lateral y tamaño del chat independientes.
- Herramientas externas ahora son dinámicas: nombre + URL + visible. Ya no existe un catálogo fijo obligatorio.
- Configuraciones antiguas de Gmail/WhatsApp/Datacar/Nosis/ChatGPT/Drive/Envíos Ya se migran automáticamente al formato nuevo para no perder accesos existentes.
- Instalaciones nuevas comienzan sin herramientas precargadas.
- Favicons de herramientas se obtienen automáticamente desde la URL mediante el servicio de favicons de Google; por ejemplo, Datacar mostrará el favicon del sitio en lugar de un PNG inventado por OficinaIA.
- El claro/oscuro existente se conserva.
- Se agregó static/css/ui-clean.css como capa acotada a sidebar/configuración para no rediseñar el chat que ya funcionaba bien.

## Iconografía de navegación — V3
- La barra lateral deja de usar pictogramas SVG para sus módulos principales.
- Excel usa el icono de aplicación de Microsoft Excel en formato PNG desde el CDN de Microsoft/Office.
- Chat IA usa la identidad visual de OficinaIA.
- Pendientes, Manuales y pólizas y Compañías usan iconos raster PNG reconocibles y neutros.
- Configuración usa un icono raster PNG de preferencias.
- Las herramientas agregadas por el usuario siguen tomando automáticamente el favicon de la URL configurada.
