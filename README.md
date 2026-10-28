# Client Content Publisher

**A local editorial automation tool developed by Ema Curk for Martin Miklavčič in Slovenia, for one of his clients.** Martin is the founder of [Miklavčič marketing](https://digitalnimarketing.si/pospesevanje-prodaje-na-spletu/). This repository makes a reusable public edition of that work available under the MIT license.

The program turns **Word documents and photographs into structured articles**: it reads DOCX, preserves the document's SEO fields, matches photos, prepares Markdown and metadata, and provides a browser interface for reviewing the result. A configured compatible backend can receive drafts or published articles.

[Español](README.es.md) · [API contract](docs/API.md) · [Public edition changes](CHANGELOG.md)

## Try it locally

Requires **Python 3.10 or newer**. The application and tests use the Python standard library; no `pip install` is needed.

```bash
git clone https://github.com/arku75/martin-client-automation.git
cd martin-client-automation
python3 app.py
```

The application opens a local browser page, normally `http://127.0.0.1:5000`. Import the synthetic files in `examples/` to try document parsing, photo pairing, editing and preview. **No website account is needed for local preparation.** The UI is available in English, Slovenian and Spanish.

For a completely offline demonstration that exports an article with its image embedded:

```bash
python3 demo.py
```

Open `demo-output/demo-article.html` in a browser. This demonstration uses invented content and a generated test image. It does not log in, upload, publish, or contact an external service.

Read a DOCX from the command line:

```bash
python3 app.py --parse examples/demo-lake-trip.docx
```

## What it does

| Step | Implemented behavior |
|---|---|
| Read documents | Parses DOCX directly from its XML; retains headings, lists, tables, emphasis, and an optional SEO header. |
| Pair photographs | Scores filenames against document names, titles, headings and body text, including Slovenian word roots. Low-confidence matches remain reviewable. |
| Prepare metadata | Generates a slug, reading time and excerpt; infers travel taxonomy; extracts FAQ and quick facts when present in the document. |
| Review | Provides simple and advanced editing, validation messages, an internal SEO completeness score and article preview. The score is a local heuristic, not a search-ranking measurement. |
| Export | Saves standalone HTML; local images can be embedded without uploading them. |
| Publish | With your own compatible API: logs in, lists articles, saves drafts, publishes, edits and deletes. Draft is the default. |
| Remember | Keeps local publishing history, corrections and an image-upload cache. Site conventions can be inferred from articles in your configured backend. |
| Optional services | Local Ollama can help with missing SEO fields and alt text. Translation, stock-image search and image hosting are optional network features. |

The application preserves explicitly authored SEO fields. Travel metadata is heuristic: review country, category, image attribution and all generated suggestions before publishing.

## Connect your own backend

Open **Settings → Site** and supply your own website URL, API base URL and login. The public defaults contain **no website endpoint, account, password, session cookie, Cloudinary account or API key**.

This is an adapter for a **specific cookie-authenticated JSON API**, documented in [docs/API.md](docs/API.md). It expects routes such as `POST /login/` and CRUD operations under `/articles/`. **It is not a general WordPress plugin.** A different CMS needs a compatible server adapter or changes to `SiteClient` in `core.py`. No backend server is bundled.

The original taxonomy and inference rules focus on Slovenian travel articles. Modify the constants and mapping rules in `core.py` when adapting the application to another editorial domain.

### Image hosting

Uploads are **disabled by default**. In Advanced mode, Settings → Images lets you explicitly select one provider:

- Cloudinary signed upload, using your own account credentials.
- Cloudinary unsigned upload, using your own upload preset.
- catbox.moe, a public hosting service, only for images you intend to make public.

Selecting a provider does not enable a silent fallback to another host. A failed upload is reported. Existing remote image URLs can also be entered directly.

### Optional network features

Ollama and automatic translation ship disabled. When enabled or explicitly requested:

- Ollama receives the article and, for vision, its image at the configured endpoint. The default endpoint is local.
- Translation sends text to Google Translate's public endpoint, with MyMemory as fallback. Availability and service limits may change.
- Image search contacts Wikimedia Commons, or configured stock providers. Review each image's license and attribution.
- An image upload sends the selected image to the provider you chose.
- Publishing and site-convention learning contact only your configured backend.

The local UI and exported HTML use system fonts and do not load a font CDN. An article containing an external image still loads that image when viewed.

## Local data and privacy

The public edition uses `~/.client_content_publisher/`, separate from the client's original application directory. Set `PUBLISHER_HOME` before launch to choose another location. The folder contains configuration, imports, cache and a SQLite history database. The configuration can contain **your own** credentials once entered; it is written with mode `0600` where supported. Keep the entire folder private. HTML exports go to a `publisher_articles` folder under your Documents directory or home directory.

The server binds to loopback and rejects cross-origin requests. This is a personal desktop tool, not a hosted multi-user service. Do not expose it through a public tunnel or deploy it as a public server without adding a proper authentication model.

Client documents, photographs, private configuration, access material, logs, old builds and the original archive are excluded from this repository. All bundled examples are synthetic.

## Tests and portable build

```bash
python3 smoke_test.py
python3 test_logica.py
python3 build.py
```

`smoke_test.py` runs local, synthetic tests, including the HTTP interface and a mocked publishing adapter. It never publishes or deletes an article on a real website. `test_logica.py` checks parsing of model responses and preservation of authored metadata with the model replaced by test doubles.

`build.py` rebuilds `dist/client_content_publisher.pyz` and launchers for Windows, macOS and Linux, plus `ClientContentPublisher.zip`. Only the allowlisted public source files are packaged. The runtime still requires Python 3.10+. This public edition was tested on Linux; the generated Windows and macOS launchers have not been exercised here.

## Source map

| File | Purpose |
|---|---|
| `core.py` | DOCX parser, pairing, metadata, validation, services and site adapter |
| `app.py` | Local HTTP server, preview/export and command line |
| `ui.html`, `app.js`, `i18n.json` | Browser interface and translations |
| `examples/` | Synthetic document and image, plus their reproducible generator |
| `demo.py` | Offline HTML demonstration |
| `smoke_test.py`, `test_logica.py` | Offline checks |
| `build.py` | Portable packaging from the public source |

## Reuse and attribution

Copyright © 2026 Ema Curk. Code is available under the [MIT License](LICENSE). You may use, modify and redistribute it under those terms. Third-party services and any images obtained from them keep their own terms and licenses.

The collaboration statement describes the author's work for Martin Miklavčič's client. It does not grant access to that client or imply endorsement of this public edition.
