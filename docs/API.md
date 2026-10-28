# Publishing adapter contract

The reusable client is `SiteClient` in `core.py`. This repository contains a desktop application, **not the original server or a WordPress integration**. Point it only at a backend you own or are authorized to manage.

## Configuration

A site entry in local `config.json` has `name`, `url`, `api_base`, `username`, `password`, `cookie_name`, `cookie_value`, `default_author`, `language` and `list_key`. The shipped values for URLs and credentials are empty. Set them through Settings, or edit your local configuration. `api_base` is joined with the paths below.

`example.invalid` is a reserved example domain. It is not a working endpoint:

```json
{
  "active_site": "example",
  "sites": {
    "example": {
      "name": "Your site",
      "url": "https://example.invalid",
      "api_base": "https://example.invalid/api/admin",
      "username": "",
      "password": "",
      "cookie_name": "publisher_session",
      "cookie_value": "",
      "default_author": "Editorial team",
      "language": "sl",
      "list_key": "items"
    }
  }
}
```

This is a site-entry illustration, not a replacement for the complete generated configuration. Retain the image, UI, translation and Ollama sections when editing the file.

## Routes

| Method | Path relative to `api_base` | Request / expected response |
|---|---|---|
| POST | `/login/` | JSON `{ "username": "…", "password": "…" }`. HTTP 200 with a session in `Set-Cookie`. |
| GET | `/articles/` | Cookie-authenticated. HTTP 200, normally `{ "items": [article, …] }`. The list key is configurable; several common alternatives are also accepted. |
| POST | `/articles/` | JSON article payload; HTTP 200 or 201 on success. |
| PUT | `/articles/{slug}/` | Updated JSON article payload; HTTP 200 or 201. |
| DELETE | `/articles/{slug}/` | HTTP 200 or 204. |

The session cookie is reused and stored in the user's private local configuration. The adapter reserves a free slug before creating a new article. Editing from the browser preserves the existing article's slug and uses PUT.

## Article shape

`Article` is the definitive model. Core fields include `title`, `slug`, `body` (Markdown), `metaTitle`, `metaDescription`, `excerpt`, `author`, `category`, `contentType`, geographic fields, `articlePath`, `primaryKeyword`, `searchIntent`, `coverImage`, image captions/alt text, `faq`, `quickFacts`, related slugs, publication status/dates and sponsorship fields.

FAQ entries use `{ "q": "Question", "a": "Answer" }`; quick facts use objects with a `label`. The outgoing serializer excludes local file paths, match confidence, notes, word counts and authored-field tracking. It retains boolean false values so a feature can be disabled when editing. Review the exact serializer before integrating a different backend.

`coverImage` is a URL; uploading image bytes is handled separately by the explicitly configured image provider. Default categories and the `/clanki/` article-path convention reflect the original Slovenian travel use case. Adapt `CATEGORIES`, `CONTENT_TYPES`, geographic inference and `build_article_path` if your site uses different rules.

## Integration checks

The repository's tests replace remote HTTP calls with test doubles. No client's API was used to validate this public release. Before production use, test your own adapter against a staging backend: authentication, listing, draft creation, slug collisions, update, image URLs and deletion. A successful local test does not establish compatibility with an arbitrary CMS.
