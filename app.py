#!/usr/bin/env python3
"""
app.py — Servidor local y punto de entrada del publicador.

Sirve la interfaz en el navegador y expone la API que usa. Todo con la
biblioteca estandar: basta con tener Python instalado.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from html import escape as html_escape
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core
from core import (Article, CATEGORIES, CONTENT_TYPES, CONTINENTS, COUNTRY_CONTINENT,
                  SEARCH_INTENTS, SiteClient, load_config, save_config, active_site,
                  parse_docx, match_pairs, classify_files, process_article,
                  heuristic_metadata, validate, seo_score, doctor, init_db,
                  log_publish, save_correction, upload_image_cached, search_stock_image,
                  ollama_up, ImageUploadError)

UPLOAD_DIR = core.DATA_DIR / "uploads"

# Ultima señal de vida del navegador. Si la ventana se cierra, el programa se
# apaga solo: se usa como cualquier aplicacion, sin dejar un servidor colgado.
LAST_PING = [time.time()]
AUTO_QUIT = [True]

# Las miniaturas se sirven por token, nunca por ruta: el navegador no puede
# pedir un archivo arbitrario del disco, solo los que se han subido aqui.
THUMBS: dict[str, Path] = {}


def thumb_token(path: str | Path) -> str:
    import hashlib
    tok = hashlib.sha256(str(path).encode()).hexdigest()[:16]
    THUMBS[tok] = Path(path)
    return tok


def read_asset(name: str) -> bytes:
    """Lee ui.html o app.js tanto desde la carpeta como desde el .pyz.

    Empaquetado con zipapp los archivos viven dentro del zip, donde Path no
    llega. zipimporter.get_data espera la ruta relativa al zip en Python 3.13,
    pero versiones anteriores usaban la absoluta, asi que se prueban ambas.
    """
    p = HERE / name
    if p.exists():
        return p.read_bytes()

    loader = globals().get("__loader__")
    if hasattr(loader, "get_data"):
        for candidate in (name, str(HERE / name)):
            try:
                return loader.get_data(candidate)
            except (OSError, KeyError):
                continue

    # Ultimo recurso: abrir el .pyz como zip corriente.
    import zipfile
    for base in (HERE, Path(sys.argv[0]).resolve()):
        if zipfile.is_zipfile(base):
            with zipfile.ZipFile(base) as z:
                return z.read(name)
    raise FileNotFoundError(f"no se encontró {name}")


# ────────────────────────── AYUDAS ──────────────────────────

DERIVED_KEYS = ("errors", "warnings", "publishable", "seo_score", "image_url",
                "thumb_url")


def art_to_json(a: Article) -> dict:
    """Serializa el articulo y añade lo que la interfaz necesita mostrar.

    Los avisos que se envian son la suma de los del proceso (a.notes) y los que
    la validacion deriva del estado actual, recalculados en cada respuesta para
    que no queden colgando avisos ya resueltos.
    """
    ok, errors, warns = validate(a)
    d = a.to_dict()
    d["errors"] = errors
    d["warnings"] = list(dict.fromkeys(list(a.notes) + warns))
    d["publishable"] = ok
    d["seo_score"] = seo_score(a)
    d["image_url"] = a.coverImage or ""
    d["lang"] = core.detect_language(a.body) if a.body else "sl"
    d["thumb_url"] = ""
    if a.image_file and Path(a.image_file).exists():
        d["thumb_url"] = "/api/thumb?t=" + thumb_token(a.image_file)
    return d


def art_from_json(d: dict) -> Article:
    a = Article()
    for k, v in (d or {}).items():
        if hasattr(a, k) and k not in DERIVED_KEYS:
            setattr(a, k, v)
    return a


def md_to_html(md: str) -> str:
    """Markdown -> HTML, solo lo que usa el sitio. Es para la vista previa."""
    html: list[str] = []
    in_list = False
    in_table = False
    for raw in (md or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                html.append("</ul>")
                in_list = False
            if in_table:
                html.append("</table>")
                in_table = False
            continue
        if line.strip() == "---":
            html.append("<hr>")
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        if h:
            if in_list:
                html.append("</ul>")
                in_list = False
            lvl = len(h.group(1))
            html.append(f"<h{lvl}>{_inline(h.group(2))}</h{lvl}>")
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("- "):
                continue
            if not in_table:
                html.append("<table>")
                in_table = True
            tag = "td"
            html.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if re.match(r"^[-*]\s+", line):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline(re.sub(r'^[-*]\s+', '', line))}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        html.append(f"<p>{_inline(line)}</p>")
    if in_list:
        html.append("</ul>")
    if in_table:
        html.append("</table>")
    return "\n".join(html)


def _safe_url(url: str) -> str:
    """Allow links, never executable URL schemes in document previews."""
    from urllib.parse import urlsplit
    url = str(url or "").strip()
    if urlsplit(url).scheme.lower() not in ("", "http", "https", "mailto"):
        return "#"
    return html_escape(url, quote=True)


def _inline(s: str) -> str:
    s = html_escape(s, quote=True)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", s)
    from html import unescape
    s = re.sub(r"\[(.+?)\]\((.+?)\)",
               lambda m: f'<a href="{_safe_url(unescape(m.group(2)))}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>', s)
    return s


def article_html(a: Article, site_url: str = "") -> str:
    """El articulo como pagina suelta, con la foto dentro.

    Sirve para guardarlo en el ordenador o enviarlo por correo: no depende del
    programa ni de internet, se abre con doble clic.
    """
    lang = core.detect_language(a.body) if a.body else "sl"
    tt = lambda k, **kw: core.t(k, lang=lang, **kw)
    esc = lambda value: html_escape(str(value or ""), quote=True)

    img = ""
    if a.coverImage:
        img = f'<img src="{_safe_url(a.coverImage)}" alt="{esc(a.imageAlt)}">'
    elif a.image_file and Path(a.image_file).exists():
        raw = base64.b64encode(Path(a.image_file).read_bytes()).decode()
        mime = mimetypes.guess_type(a.image_file)[0] or "image/jpeg"
        img = f'<img src="data:{mime};base64,{raw}" alt="{esc(a.imageAlt)}">'

    def ul(items, key):
        if not items:
            return ""
        li = "".join(f"<li>{esc(x)}</li>" for x in items)
        return f"<h2>{tt(key)}</h2><ul>{li}</ul>"

    facts = ul([f.get("label") or f.get("value") or "" for f in a.quickFacts],
               "preview.facts_title")
    faq = ""
    if a.faq:
        faq = f"<h2>{tt('preview.faq_title')}</h2>" + "".join(
            f"<p><strong>{esc(f.get('q',''))}</strong><br>{esc(f.get('a',''))}</p>" for f in a.faq)
    aff = ""
    if a.affiliateEnabled:
        rel = "sponsored nofollow" if a.sponsoredToggle else "nofollow"
        aff = (f'<div class="aff"><h3>{esc(a.affiliateTitle)}</h3><p>{esc(a.affiliateDescription)}</p>'
               f'<a class="btn" href="{_safe_url(a.affiliateUrl)}" rel="{rel} noopener noreferrer" target="_blank">'
               f'{esc(a.affiliateButtonText)}</a></div>')

    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(a.metaTitle or a.title)}</title>
<meta name="description" content="{esc(a.metaDescription)}">
<style>
:root{{--primary:158 64% 22%;--fg:24 10% 10%;--muted:24 6% 45%;--border:24 6% 90%}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,system-ui,sans-serif;color:hsl(var(--fg));line-height:1.65;
  background:hsl(30 10% 96%);padding:2rem 1rem}}
article{{max-width:760px;margin:0 auto;background:#fff;border-radius:.75rem;
  padding:1.5rem;box-shadow:0 10px 30px -12px hsl(24 10% 10%/.18)}}
img{{width:100%;max-height:340px;object-fit:cover;border-radius:.5rem;display:block}}
h1{{font-family:Fraunces,Georgia,serif;font-size:1.9rem;line-height:1.22;margin:1rem 0 .4rem}}
h2{{font-family:Fraunces,Georgia,serif;font-size:1.3rem;margin:1.6rem 0 .5rem}}
h3{{font-family:Fraunces,Georgia,serif;font-size:1.1rem;margin:1.2rem 0 .4rem}}
p{{margin:.7rem 0}} ul{{margin:.7rem 0 .7rem 1.3rem}} hr{{border:0;border-top:1px solid hsl(var(--border));margin:1.5rem 0}}
.meta{{color:hsl(var(--muted));font-size:.85rem;margin-bottom:1rem}}
table{{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.9rem;display:block;overflow-x:auto}}
td{{border-bottom:1px solid hsl(var(--border));padding:.45rem .6rem}}
.aff{{border:1px solid hsl(var(--border));border-radius:.5rem;padding:1rem;margin-top:1.5rem;
  background:hsl(30 10% 97%)}}
.btn{{display:inline-block;background:hsl(var(--primary));color:#fafaf9;padding:.5rem 1rem;
  border-radius:.5rem;text-decoration:none;margin-top:.5rem}}
a{{color:hsl(var(--primary))}}
@media(max-width:640px){{body{{padding:.5rem}}article{{padding:1rem}}h1{{font-size:1.45rem}}}}
</style></head><body><article>
{img}
{f'<div class="meta" style="margin-top:.4rem">{esc(a.imageCaption)}</div>' if a.imageCaption else ''}
<h1>{esc(a.title)}</h1>
<div class="meta">{esc(a.author)} · {tt('preview.min', n=a.readingTimeMinutes or 1)} · {esc(a.category)}
{' · ' + esc(a.country) if a.country else ''}</div>
{facts}
{md_to_html(a.body)}
{ul(a.pros, 'preview.pros')}{ul(a.cons, 'preview.cons')}{ul(a.packingList, 'preview.packing')}
{faq}
{aff}
<hr><div class="meta">{esc(site_url)}{esc(a.articlePath)}</div>
</article></body></html>"""


def save_upload(name: str, b64: str, session_dir: Path) -> Path:
    """Guarda un archivo subido, con el nombre saneado."""
    session_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[/\\]", "_", name).lstrip(".")[:180] or "archivo"
    path = session_dir / safe
    path.write_bytes(base64.b64decode(b64))
    return path


# ────────────────────────── SERVIDOR ──────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "ClientContentPublisher/" + core.VERSION

    def log_message(self, fmt, *args):
        if os.environ.get("PUBLISHER_DEBUG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- salidas --
    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _err(self, msg, code=400):
        self._json({"error": str(msg)}, code)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > 32 * 1024 * 1024:
            raise ValueError("Request exceeds the 32 MiB upload limit")
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _sync_lang(self):
        core.set_lang((load_config().get("ui") or {}).get("lang", "es"))

    def _local_request(self) -> bool:
        """Keep this personal desktop server inaccessible to other web origins."""
        from urllib.parse import urlsplit
        try:
            host = urlsplit("http://" + self.headers.get("Host", ""))
            if host.hostname not in ("127.0.0.1", "localhost", "::1"):
                return False
            if host.port != self.server.server_port:
                return False
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return False
            return True
        except ValueError:
            return False

    # -- rutas --
    def do_GET(self):
        if not self._local_request():
            return self._err("Only local, same-origin requests are allowed", 403)
        self._sync_lang()
        path = self.path.split("?")[0]
        qs = dict(re.findall(r"(\w+)=([^&]*)", self.path.split("?", 1)[1])
                  if "?" in self.path else [])
        try:
            if path == "/":
                return self._send(200, read_asset("ui.html"), "text/html; charset=utf-8")
            if path == "/app.js":
                return self._send(200, read_asset("app.js"),
                                  "application/javascript; charset=utf-8")
            if path == "/api/ping":
                LAST_PING[0] = time.time()
                return self._json({"ok": True})
            if path == "/api/bootstrap":
                return self.bootstrap()
            if path == "/api/i18n":
                data = core.load_i18n()
                return self._json({"lang": core.LANG,
                                   "langs": {l: (data.get(l) or {}).get("_name", l)
                                             for l in core.UI_LANGS},
                                   "strings": data.get(core.LANG) or {},
                                   "all": {l: data.get(l) or {} for l in core.UI_LANGS}})
            if path == "/api/doctor":
                return self._json({"checks": doctor(load_config())})
            if path == "/api/articles":
                cfg = load_config()
                cli = SiteClient(cfg)
                cli.ensure_session()
                return self._json({"articles": cli.list_articles(),
                                   "site_url": active_site(cfg)["url"].rstrip("/")})
            if path == "/api/thumb":
                return self.thumb(qs)
            return self._err("no encontrado", 404)
        except Exception as e:
            return self._err(e, 500)

    def do_POST(self):
        if not self._local_request():
            return self._err("Only local, same-origin requests are allowed", 403)
        if self.headers.get_content_type() != "application/json":
            return self._err("Content-Type must be application/json", 415)
        self._sync_lang()
        path = self.path.split("?")[0]
        try:
            body = self._read_json()
            if path == "/api/upload":
                return self.upload(body)
            if path == "/api/process":
                return self.process(body)
            if path == "/api/revalidate":
                a = heuristic_metadata(art_from_json(body.get("article")))
                return self._json({"article": art_to_json(a)})
            if path == "/api/preview":
                a = art_from_json(body.get("article"))
                return self._json({"html": md_to_html(a.body)})
            if path == "/api/export":
                return self.export_html(body)
            if path == "/api/delete":
                cfg = load_config()
                cli = SiteClient(cfg)
                cli.ensure_session()
                ok, msg = cli.delete(body.get("slug", ""))
                return self._json({"ok": ok, "message": msg})
            if path == "/api/fetch":
                return self.fetch_one(body)
            if path == "/api/attach":
                return self.attach(body)
            if path == "/api/translate":
                return self.translate_one(body)
            if path == "/api/publish":
                return self.publish(body)
            if path == "/api/stock":
                cfg = load_config()
                return self._json({"images": search_stock_image(cfg, body.get("query", ""))})
            if path == "/api/config":
                cfg = body.get("config") or {}
                cfg.pop("config_path", None)
                cfg.pop("ollama_models", None)
                save_config(cfg)
                return self._json({"ok": True})
            if path == "/api/test-image":
                return self.test_image()
            return self._err("no encontrado", 404)
        except Exception as e:
            import traceback
            if os.environ.get("PUBLISHER_DEBUG"):
                traceback.print_exc()
            return self._err(e, 500)

    # -- handlers --
    def bootstrap(self):
        cfg = load_config()
        up, models = ollama_up(cfg) if cfg["ollama"].get("enabled") else (False, [])
        out = json.loads(json.dumps(cfg))
        out["config_path"] = str(core.CONFIG_FILE)
        out["ollama_models"] = [m for m in models
                                if not any(x in m for x in ("embed", "bge-"))]
        countries = sorted(COUNTRY_CONTINENT.keys())
        return self._json({
            "config": out,
            "conventions": core.get_conventions(cfg),
            "ui_langs": list(core.UI_LANGS),
            "taxonomy": {
                "categories": CATEGORIES, "content_types": CONTENT_TYPES,
                "continents": CONTINENTS, "countries": countries,
                "search_intents": SEARCH_INTENTS,
            },
        })

    def upload(self, body):
        files = body.get("files") or []
        if not files:
            return self._err("no se recibió ningún archivo")
        session_dir = UPLOAD_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
        paths = [save_upload(f["name"], f["b64"], session_dir) for f in files]
        docs, imgs, other = classify_files(paths)
        if not docs:
            return self._err("no hay ningún .docx entre los archivos")

        cfg = load_config()
        # Cómo son los artículos de este sitio, para que los nuevos salgan igual.
        conv = core.get_conventions(cfg)
        arts = []
        for d in docs:
            try:
                arts.append(heuristic_metadata(parse_docx(d)))
            except Exception as e:
                a = Article(title=d.name, source_file=str(d))
                a.notes.append(f"No se pudo leer el documento: {e}")
                arts.append(a)
        arts = match_pairs(arts, imgs)
        tr = cfg.get("translate") or {}
        for a in arts:
            if tr.get("enabled") and a.body:
                target = tr.get("target", "sl")
                if core.detect_language(a.body) != target:
                    a = core.translate_article(a, target)
            core.apply_conventions(a, conv)
            for msg in core.check_against_conventions(a, conv):
                a.notes.append(msg)
            a.author = a.author or active_site(cfg).get("default_author", "")
            # Otra pasada ahora que ya tiene foto: el texto alternativo depende
            # de ella y antes del emparejamiento no había nada que describir.
            heuristic_metadata(a)
        return self._json({"articles": [art_to_json(a) for a in arts],
                           "conventions": conv,
                           "ignored": [p.name for p in other]})

    def process(self, body):
        cfg = load_config()
        a = art_from_json(body.get("article"))
        if body.get("force"):
            # Regenerar de verdad: se vacian los campos que la IA debe rehacer.
            a.metaTitle = a.metaDescription = a.excerpt = ""
            a.primaryKeyword = ""
            a.quickFacts = []
        examples = []
        try:
            cli = SiteClient(cfg)
            if cli.ensure_session()[0]:
                examples = cli.list_articles()
        except Exception:
            pass
        a = process_article(cfg, a, use_ai=body.get("use_ai", True), examples=examples)
        return self._json({"article": art_to_json(a)})

    def fetch_one(self, body):
        """Trae un artículo ya publicado para reeditarlo tal cual está."""
        cfg = load_config()
        cli = SiteClient(cfg)
        cli.ensure_session()
        found = [x for x in cli.list_articles() if x.get("slug") == body.get("slug")]
        if not found:
            return self._err("no encontrado", 404)
        a = art_from_json(found[0])
        a = heuristic_metadata(a)   # recalcula palabras, minutos y ruta
        # Lo que ya está en la web lo escribió una persona: la IA no debe tocarlo.
        a.authored_fields = ["metaTitle", "metaDescription", "slug", "primaryKeyword",
                             "excerpt", "imageAlt"]
        d = art_to_json(a)
        d["existing"] = True          # al publicar se actualiza, no se duplica
        return self._json({"article": d})

    def export_html(self, body):
        """Guarda el artículo como página suelta en el ordenador."""
        cfg = load_config()
        a = art_from_json(body.get("article"))
        html = article_html(a, active_site(cfg)["url"].rstrip("/"))
        out = Path.home() / "Documentos" / "publisher_articles"
        if not out.parent.exists():                 # Documents en inglés
            out = Path.home() / "Documents" / "publisher_articles"
        if not out.parent.exists():                 # último recurso: la home
            out = Path.home() / "publisher_articles"
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{core.slugify(a.slug or a.title)[:120] or 'article'}.html"
        f.write_text(html, "utf-8")
        return self._json({"file": str(f), "bytes": f.stat().st_size})

    def translate_one(self, body):
        """Traduce un artículo al idioma pedido, a demanda desde la interfaz."""
        a = art_from_json(body.get("article"))
        target = body.get("target") or "sl"
        source = body.get("source") or ""
        detected = core.detect_language(a.body)
        if (source or detected) == target:
            return self._json({"article": art_to_json(a),
                               "message": f"Ya está en {target}, no se ha tocado."})
        a = core.translate_article(a, target, source)
        a = heuristic_metadata(a)
        return self._json({"article": art_to_json(a),
                           "message": f"Traducido de {source or detected} a {target}."})

    def attach(self, body):
        a = art_from_json(body.get("article"))
        session_dir = UPLOAD_DIR / "manual"
        p = save_upload(body["name"], body["b64"], session_dir)
        a.image_file = str(p)
        a.coverImage = ""
        a.match_score = 1.0
        a.match_reason = "elegida a mano"
        return self._json({"article": art_to_json(a)})

    def thumb(self, qs):
        p = THUMBS.get(qs.get("t", ""))
        if not p or not p.exists():
            return self._err("no encontrado", 404)
        ctype = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        return self._send(200, p.read_bytes(), ctype)

    def test_image(self):
        cfg = load_config()
        # PNG 1x1 en el verde del sitio, suficiente para validar credenciales.
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
        tmp = Path(tempfile.gettempdir()) / "publisher-test.png"
        tmp.write_bytes(png)
        try:
            url, backend = core.upload_image(cfg, tmp, "publisher-test")
            return self._json({"url": url, "backend": backend})
        except ImageUploadError as e:
            return self._err(e)
        finally:
            tmp.unlink(missing_ok=True)

    def publish(self, body):
        cfg = load_config()
        a = art_from_json(body.get("article"))
        status = body.get("status", "draft")
        original = json.loads(json.dumps(a.to_dict()))

        # 1. Completar lo que falte (y mejorar SEO si se pidió). La heuristica
        #    corre siempre y es idempotente: si se cambió el país o el slug en
        #    la interfaz, la ruta y el alt tienen que rehacerse antes de enviar.
        a = heuristic_metadata(a)
        conv = core.get_conventions(cfg)
        core.apply_conventions(a, conv)
        if not a.metaTitle or not a.slug or body.get("use_ai"):
            examples = []
            try:
                cli0 = SiteClient(cfg)
                if cli0.ensure_session()[0]:
                    examples = cli0.list_articles()
            except Exception:
                pass
            a = process_article(cfg, a, use_ai=body.get("use_ai", True),
                                examples=examples, conventions=conv)

        # 2. Registrar los retoques manuales: sirven para afinar los prompts.
        for k in ("metaTitle", "metaDescription", "title", "slug", "excerpt", "imageAlt"):
            save_correction(a.slug, k, original.get(k, ""), getattr(a, k, ""))

        # 3. Subir la imagen. El panel del sitio solo acepta una URL, asi que
        #    este paso es el que convierte el archivo local en algo publicable.
        if a.image_file and not a.coverImage:
            try:
                url, backend = upload_image_cached(cfg, a.image_file, a.slug)
                a.coverImage = url
                a.notes.append(f"Imagen subida vía {backend}.")
            except ImageUploadError as e:
                return self._json({"ok": False, "message": f"No se pudo subir la imagen: {e}",
                                   "article": art_to_json(a)})

        # 4. Validar antes de tocar el sitio.
        ok, errors, warns = validate(a)
        if not ok:
            return self._json({"ok": False, "message": "; ".join(errors),
                               "article": art_to_json(a)})

        # 5. Publicar.
        cli = SiteClient(cfg)
        sok, smsg = cli.ensure_session()
        if not sok:
            return self._json({"ok": False, "message": smsg, "article": art_to_json(a)})

        a.status = status
        # Editing a fetched article updates it; new documents get a free slug.
        existing = bool(body.get("article", {}).get("existing"))
        if not existing:
            a.slug = cli.unique_slug(a.slug)
        a.articlePath = core.build_article_path(a.continent, a.country, a.slug)
        if not a.publishDate:
            a.publishDate = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if cfg["publish"].get("auto_related") and not a.relatedSlugs:
            try:
                a.relatedSlugs = cli.related_slugs(a)
            except Exception:
                pass

        ok2, msg, data = cli.update(a.slug, a) if existing else cli.create(a)
        site_url = active_site(cfg)["url"].rstrip("/")
        url = site_url + (a.articlePath or f"/clanki/{a.slug}/")
        log_publish(a.slug, cfg["active_site"], "ok" if ok2 else "error", msg, url)
        return self._json({"ok": ok2, "message": msg if not ok2 else
                           ("Publicado" if status == "published" else "Guardado como borrador"),
                           "url": url if ok2 else "", "article": art_to_json(a)})


# ────────────────────────── ARRANQUE ──────────────────────────

def free_port(preferred: int) -> int:
    for p in [preferred] + list(range(preferred + 1, preferred + 40)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 0


def watch_browser(srv, grace: int = 25) -> None:
    """Apaga el programa cuando se cierra la ventana del navegador.

    La interfaz manda una señal cada 5 segundos. Sin señales durante un rato,
    ya no hay nadie mirando y no tiene sentido seguir ocupando el puerto.
    """
    while True:
        time.sleep(5)
        if not AUTO_QUIT[0]:
            continue
        if time.time() - LAST_PING[0] > grace:
            print("\n  Ventana cerrada: hasta luego.", flush=True)
            threading.Thread(target=srv.shutdown, daemon=True).start()
            return


def serve(host: str, port: int, open_browser: bool = True) -> None:
    init_db()
    cfg = load_config()
    port = free_port(port) or port
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"
    # flush explicito: si la salida va a un archivo o a un pipe, Python usa
    # buffer de bloque y la URL no aparaceria hasta cerrar el programa.
    print(f"\n  Client Content Publisher {core.VERSION}", flush=True)
    print(f"  → {url}", flush=True)
    print(f"  Configuración: {core.CONFIG_FILE}", flush=True)
    print("  Ctrl+C para salir\n", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        # Margen para que dé tiempo a abrirse antes de empezar a vigilar.
        LAST_PING[0] = time.time() + 30
        threading.Thread(target=watch_browser, args=(srv,), daemon=True).start()
    else:
        AUTO_QUIT[0] = False   # sin navegador (pruebas, terminal) no se apaga
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cerrado.")


def cli_publish(paths: list[str], status: str, use_ai: bool) -> int:
    """Publicar desde la terminal, sin abrir el navegador."""
    cfg = load_config()
    init_db()
    docs, imgs, _ = classify_files([Path(p) for p in paths])
    if not docs:
        print("No hay ningún .docx en los archivos indicados.")
        return 1
    arts = match_pairs([heuristic_metadata(parse_docx(d)) for d in docs], imgs)
    conv = core.get_conventions(cfg)
    rc = 0
    for a in arts:
        print(f"\n▸ {a.title}")
        a = process_article(cfg, a, use_ai=use_ai, conventions=conv)
        if a.image_file and not a.coverImage:
            try:
                a.coverImage, backend = upload_image_cached(cfg, a.image_file, a.slug)
                print(f"  imagen subida ({backend})")
            except ImageUploadError as e:
                print(f"  ! imagen: {e}")
        ok, errors, warns = validate(a)
        for w in warns:
            print(f"  · {w}")
        if not ok:
            print("  ✗ " + "; ".join(errors))
            rc = 1
            continue
        cli = SiteClient(cfg)
        if not cli.ensure_session()[0]:
            print("  ✗ sin sesión en el panel")
            return 1
        a.status = status
        # CLI inputs are local documents, so always reserve a new slug.
        a.slug = cli.unique_slug(a.slug)
        a.articlePath = core.build_article_path(a.continent, a.country, a.slug)
        ok2, msg, _ = cli.create(a)
        print(("  ✓ " if ok2 else "  ✗ ") + msg + f"  [SEO {seo_score(a)}/100]")
        rc = rc or (0 if ok2 else 1)
    return rc


def main() -> int:
    p = argparse.ArgumentParser(
        prog="client-content-publisher",
        description="Prepara artículos DOCX y publícalos en una API editorial compatible")
    p.add_argument("files", nargs="*", help=".docx e imágenes (modo terminal)")
    p.add_argument("--port", type=int, default=0, help="puerto (por defecto 5000)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    p.add_argument("--doctor", action="store_true", help="diagnóstico y salir")
    p.add_argument("--parse", metavar="FILE", help="leer un .docx y mostrar el resultado")
    p.add_argument("--status", default="draft", choices=["draft", "published"])
    p.add_argument("--no-ai", action="store_true", help="no usar la IA local")
    args = p.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        p.error("This desktop tool must bind to a loopback address")

    if args.doctor:
        for c in doctor(load_config()):
            print(f"[{'ok ' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}")
            if c["fix"]:
                print(f"        → {c['fix']}")
        return 0

    if args.parse:
        a = heuristic_metadata(parse_docx(args.parse))
        print(json.dumps(art_to_json(a), ensure_ascii=False, indent=2))
        return 0

    if args.files:
        return cli_publish(args.files, args.status, not args.no_ai)

    cfg = load_config()
    port = args.port or cfg["ui"].get("port", 5000)
    serve(args.host, port, not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
