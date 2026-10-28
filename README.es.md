# Client Content Publisher — automatización editorial

Programa desarrollado por **Ema Curk para Martin Miklavčič, de Eslovenia, para uno de sus clientes**. Martin es fundador de [Miklavčič marketing](https://digitalnimarketing.si/pospesevanje-prodaje-na-spletu/). Esta edición pública permite reutilizar el código con licencia MIT.

## Qué hace

Convierte documentos Word y fotografías en artículos listos para revisar. Extrae el texto del DOCX, conserva títulos y metadatos escritos por el autor, genera Markdown, empareja imágenes y prepara slug, resumen, tiempo de lectura, FAQ, datos rápidos y clasificación de viajes. Una interfaz local permite revisar, editar, previsualizar y exportar a HTML.

Con una API compatible configurada por ti puede iniciar sesión, listar artículos, guardar borradores, publicar, editar y eliminar. El estado inicial es **borrador**. El motor conserva el enfoque original en artículos de viajes en esloveno; sus reglas y categorías se pueden adaptar en `core.py`.

## Probar sin cuentas ni servicios

Necesitas **Python 3.10 o posterior**. No hay dependencias externas del runtime.

```bash
git clone https://github.com/arku75/martin-client-automation.git
cd martin-client-automation
python3 app.py
```

Se abre una interfaz en tu navegador, normalmente en `http://127.0.0.1:5000`. Arrastra los archivos sintéticos de `examples/`. Puedes preparar y previsualizar artículos sin conectar ningún sitio. La interfaz está en inglés, esloveno y español.

Para generar un ejemplo HTML completamente local:

```bash
python3 demo.py
```

Abre `demo-output/demo-article.html`. El documento y la imagen son inventados para la demostración. Esta prueba no inicia sesión, no sube archivos y no publica nada.

## Publicar en tu propio sitio

En **Configuración → Sitio**, introduce tus propias URLs y credenciales. La edición pública no incluye endpoint del cliente, usuario, contraseña, cookie, cuenta de Cloudinary ni claves.

**No es un plugin universal de WordPress.** El adaptador espera una API JSON con sesión por cookie y rutas `/login/` y `/articles/`. El contrato está descrito en [docs/API.md](docs/API.md). Si tu CMS utiliza otro protocolo, debes implementar un adaptador o modificar `SiteClient`. El servidor del cliente no se distribuye.

Las subidas de imágenes están **desactivadas inicialmente**. En modo avanzado puedes seleccionar tu cuenta de Cloudinary o, de forma expresa, catbox.moe. No hay cambio silencioso de proveedor si uno falla. Revisa derechos y atribución de las imágenes antes de publicarlas.

La IA local con Ollama y la traducción automática son opcionales y vienen desactivadas. La búsqueda de imágenes y la traducción usan servicios externos cuando se solicitan; la traducción envía el texto a Google Translate o MyMemory. La IA envía el contenido al endpoint de Ollama configurado. El índice SEO es una comprobación interna de completitud, no una garantía de posicionamiento.

## Datos privados

Tu configuración, historial SQLite, importaciones y caché se guardan en `~/.client_content_publisher/`. Puedes cambiar la carpeta con `PUBLISHER_HOME`. La edición pública usa un directorio distinto al del programa original para no cargar sus datos privados. Las credenciales que introduzcas se guardan localmente; conserva esa carpeta fuera de GitHub. El servidor es solo para uso local.

No se incluyen documentos, fotografías, claves, sesiones, registros, archivos antiguos ni el ZIP original del cliente. Los ejemplos distribuidos son sintéticos.

## Verificación y paquete portable

```bash
python3 smoke_test.py
python3 test_logica.py
python3 build.py
```

Las pruebas son locales y usan datos inventados y dobles de prueba. No publican ni borran nada en una web real. La compilación genera un `.pyz` y lanzadores para Windows, macOS y Linux a partir del código saneado. Python sigue siendo necesario. Esta edición se ha probado en Linux; los lanzadores de Windows y macOS no se han ejecutado aquí.

Consulta el [README completo en inglés](README.md) para el mapa de archivos, las funciones opcionales y los detalles del almacenamiento. Código MIT © 2026 Ema Curk.
