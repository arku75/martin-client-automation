# Public edition

## 2.0.1 — 2026-10-28

Based on the existing version 2.0.0 application from the author's client project.

- Retained the DOCX parser, Slovenian photo pairing, editorial metadata, browser editor, HTML export and compatible API adapter.
- Removed client endpoints, account defaults, access material and client-specific operational notes.
- Isolated public-edition storage under `.client_content_publisher` / `PUBLISHER_HOME`.
- Disabled image uploads by default; selecting a provider no longer falls back silently to another host.
- Kept AI and automatic translation disabled by default and removed the font CDN.
- Fixed an undefined variable in the command-line publishing path.
- Escaped document metadata and restricted unsafe URL schemes in HTML previews.
- Restricted the desktop server to loopback and same-origin requests; added a 32 MiB request limit and safe export filenames.
- Replaced the client-connected smoke test with synthetic local tests and documented the actual backend contract.
- Added a reproducible offline example and the MIT license.
