#!/usr/bin/env python3
"""
core.py — Motor del publicador. Sin dependencias externas: solo stdlib.

Contiene todo lo que no es interfaz: configuracion, parser .docx, emparejador
docx<->imagen, traduccion, metadata con IA local, backends de imagen, cliente
de la API del sitio y validacion.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import mimetypes
import os
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

APP_NAME = "client_content_publisher"
VERSION = "2.0.1"

DATA_DIR = Path(os.environ.get("PUBLISHER_HOME") or (Path.home() / f".{APP_NAME}"))
CONFIG_FILE = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "memory.db"
CACHE_DIR = DATA_DIR / "cache"

UA = "Mozilla/5.0 (compatible; ClientContentPublisher/2.0)"


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ────────────────────────── IDIOMAS ──────────────────────────
# Un unico i18n.json para el motor y la interfaz: un texto se corrige en un
# solo sitio y cambia en los dos.

UI_LANGS = ("es", "en", "sl")
LANG = "es"          # idioma activo del programa; lo fija el servidor
_I18N: dict = {}


def load_i18n() -> dict:
    global _I18N
    if _I18N:
        return _I18N
    here = Path(__file__).resolve().parent
    raw = None
    p = here / "i18n.json"
    if p.exists():
        raw = p.read_text("utf-8")
    else:
        # Empaquetado en el .pyz: el archivo vive dentro del zip.
        loader = globals().get("__loader__")
        if hasattr(loader, "get_data"):
            for cand in ("i18n.json", str(here / "i18n.json")):
                try:
                    raw = loader.get_data(cand).decode("utf-8")
                    break
                except (OSError, KeyError):
                    continue
    _I18N = json.loads(raw) if raw else {}
    return _I18N


def set_lang(lang: str) -> None:
    global LANG
    LANG = lang if lang in UI_LANGS else "es"


def t(key: str, lang: str | None = None, **kw) -> str:
    """Texto traducido. Si falta la clave, devuelve la clave: se ve el fallo."""
    data = load_i18n()
    table = data.get(lang or LANG) or data.get("es") or {}
    s = table.get(key) or (data.get("es") or {}).get(key) or key
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return s
    return s


# ────────────────────────── TAXONOMIA DEL SITIO ──────────────────────────
# Valores de la API editorial compatible. Adapta estas constantes a tu backend.

CATEGORIES = ["zgodba", "vodnik", "potovanje", "oprema"]
CONTENT_TYPES = [
    "destination-guide", "best-time-to-visit", "itinerary", "travel-tips",
    "flight-guide", "adventure-guide", "comparison", "seasonal-inspiration",
    "agency-review", "hidden-gems",
]
CONTINENTS = ["Evropa", "Azija", "Afrika", "Severna Amerika", "Južna Amerika",
              "Oceanija", "Antarktika"]
SEARCH_INTENTS = ["informational", "commercial", "affiliate", "inspirational"]

# ── Señales de intención de búsqueda (esloveno) ──
# Patrón de agent-seo-engine: listas de palabras señal por intención,
# acumulación de puntos, gana la que más suma.  Adaptado al contexto
# de viajes eslovenos.
INTENT_SIGNALS = {
    "informational": [
        "kako", "zakaj", "kje", "kaj je", "kaj so", "vodič", "vodnik",
        "navodila", "nasveti", "nasvet", "povzetek", "pregled",
        "popoln vodič", "začetniki", "izkušnje", "izkušnja",
        "koraki", "postopek", "načrt", "itinerarij",
        "najboljši čas", "kdaj", "kam", "koliko",
        "prednosti", "slabosti", "primerjava", "razlike",
        "what", "how", "guide", "tips", "best time",
    ],
    "commercial": [
        "najcenejši", "najboljši", "najlepši", "najvišji", "najnižji",
        "pregled", "primerjava", "alternativa", "alternative",
        "best", "top", "review", "vs", "compare", "comparison",
        "cheapest", "cheapest", "affordable", "budget",
        "najugodnejši", "ugodno", "ugodne", "poceni",
        "najmanj", "največ", "najdlje", "najhitreje",
    ],
    "affiliate": [
        "poceni", "popust", "kupon", "rezerviraj", "ponudba", "ponudbe",
        "po ponudbi", "akcija", "akcijska", "brezplačno",
        "buy", "deal", "discount", "coupon", "booking",
        "naroči", "naročilo", "cena", "cenik", "plačilo",
        "najugodnejši", "ugodno", "ugodne",
    ],
    "inspirational": [
        "skrit", "skrite", "skritega", "čudovit", "čudovita",
        "raziskuj", "odkrij", "odkrijte", "potovanje", "potovanja",
        "avantura", "avanture", "doživetje", "doživetja",
        "inspirational", "inspire", "dream", "wanderlust",
        "najlepši", "najlepša", "najlepše", "prečudovit",
        "nezaboravno", "edinstveno", "posebno",
        "pozabite na", "obeščite", "raziskujte",
    ],
}

# Pais esloveno -> continente. Permite deducir el continente sin preguntar.
COUNTRY_CONTINENT = {
    "Slovenija": "Evropa", "Hrvaška": "Evropa", "Italija": "Evropa",
    "Sicilija": "Evropa", "Avstrija": "Evropa", "Nemčija": "Evropa",
    "Francija": "Evropa", "Španija": "Evropa", "Grčija": "Evropa",
    "Islandija": "Evropa", "Portugalska": "Evropa", "Norveška": "Evropa",
    "Švedska": "Evropa", "Finska": "Evropa", "Danska": "Evropa",
    "Irska": "Evropa", "Škotska": "Evropa", "Anglija": "Evropa",
    "Nizozemska": "Evropa", "Belgija": "Evropa", "Švica": "Evropa",
    "Poljska": "Evropa", "Češka": "Evropa", "Madžarska": "Evropa",
    "Romunija": "Evropa", "Bolgarija": "Evropa", "Srbija": "Evropa",
    "Črna gora": "Evropa", "Albanija": "Evropa", "Malta": "Evropa",
    "Ciper": "Evropa", "Turčija": "Evropa",
    "Kenija": "Afrika", "Tanzanija": "Afrika", "Južna Afrika": "Afrika",
    "Maroko": "Afrika", "Egipt": "Afrika", "Tunizija": "Afrika",
    "Namibija": "Afrika", "Bocvana": "Afrika", "Uganda": "Afrika",
    "Japonska": "Azija", "Koreja": "Azija", "Kitajska": "Azija",
    "Indija": "Azija", "Tajska": "Azija", "Vietnam": "Azija",
    "Indonezija": "Azija", "Bali": "Azija", "Filipini": "Azija",
    "Malezija": "Azija", "Singapur": "Azija", "Sri Lanka": "Azija",
    "Nepal": "Azija", "Jordanija": "Azija", "Gruzija": "Azija",
    "Dubaj": "Azija", "ZAE": "Azija", "Kambodža": "Azija", "Laos": "Azija",
    "ZDA": "Severna Amerika", "Kanada": "Severna Amerika",
    "Mehika": "Severna Amerika", "Kuba": "Severna Amerika",
    "Kostarika": "Severna Amerika",
    "Brazilija": "Južna Amerika", "Argentina": "Južna Amerika",
    "Čile": "Južna Amerika", "Peru": "Južna Amerika",
    "Kolumbija": "Južna Amerika", "Ekvador": "Južna Amerika",
    "Bolivija": "Južna Amerika", "Urugvaj": "Južna Amerika",
    "Avstralija": "Oceanija", "Novi Zeland": "Oceanija", "Fidži": "Oceanija",
}

# Sinonimos y formas flexionadas -> pais canonico. El esloveno declina los
# nombres propios ("na Islandijo", "v Keniji"), asi que buscamos la raiz.
COUNTRY_HINTS = {
    "islandij": "Islandija", "iceland": "Islandija",
    "kenij": "Kenija", "kenya": "Kenija",
    "tajsk": "Tajska", "thailand": "Tajska",
    "bali": "Bali",
    "sicilij": "Sicilija", "sicily": "Sicilija",
    "italij": "Italija", "italy": "Italija",
    "grčij": "Grčija", "grcij": "Grčija", "greece": "Grčija",
    "santorini": "Grčija", "mykonos": "Grčija",
    "španij": "Španija", "spanij": "Španija", "spain": "Španija",
    "hrvašk": "Hrvaška", "hrvask": "Hrvaška", "croatia": "Hrvaška",
    "slovenij": "Slovenija", "slovenia": "Slovenija",
    "japonsk": "Japonska", "japan": "Japonska",
    "portugalsk": "Portugalska", "portugal": "Portugalska",
    "norvešk": "Norveška", "norvesk": "Norveška", "norway": "Norveška",
    "marok": "Maroko", "morocco": "Maroko",
    "egipt": "Egipt", "egypt": "Egipt",
    "vietnam": "Vietnam", "indonezij": "Indonezija",
    "turčij": "Turčija", "turcij": "Turčija", "turkey": "Turčija",
    "mehik": "Mehika", "mexico": "Mehika",
    "peru": "Peru", "brazilij": "Brazilija",
    "kanad": "Kanada", "canada": "Kanada",
    "avstralij": "Avstralija", "australia": "Avstralija",
    "nepal": "Nepal", "indij": "Indija",
    "tanzanij": "Tanzanija", "dubaj": "Dubaj",
}

# Pistas de contentType por palabras del titulo, con peso: "letalske" señala
# el tema, mientras que "kako" o "vodič" salen en casi cualquier titular y no
# deben arrastrar la clasificacion.
CONTENT_TYPE_HINTS = [
    (["letal", "flight", "letov", "lete ", "leti ", "letalsk", "poceni let"],
     "flight-guide", 6),
    (["kdaj", "najboljši čas", "best time", "sezona", "monsun"],
     "best-time-to-visit", 6),
    (["dneh", "dni ", "itinerar", "roadtrip", "road trip", "pot po"],
     "itinerary", 6),
    (["skrit", "hidden", "pozabite", "neodkrit", "namesto", "alternativ"],
     "hidden-gems", 6),
    (["primerjav", "comparison", " vs ", " ali "], "comparison", 6),
    (["agencij", "review", "ocena", "izkušnja z"], "agency-review", 6),
    (["kam potovati", "destinacij", "inspiracij"], "seasonal-inspiration", 5),
    (["oprema", "nahrbtnik", "packing", "kovček"], "travel-tips", 5),
    (["pozimi", "poleti", "jeseni", "spomladi"], "seasonal-inspiration", 3),
    (["nasvet", "tips", "kako", "vodič", "guide"], "travel-tips", 2),
]

# Transliteracion eslovena/croata. El parser anterior BORRABA estos caracteres
# ("najcenejše" -> "najcenej-e"); aqui se convierten al ASCII correcto.
TRANSLIT = {
    "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d", "dž": "dz",
    "ä": "a", "ö": "o", "ü": "u", "ß": "ss", "å": "a", "æ": "ae",
    "ø": "o", "ñ": "n", "ç": "c", "þ": "th", "ð": "d",
}

STOPWORDS_SL = {
    "in", "je", "za", "na", "se", "so", "ki", "z", "s", "v", "do", "od", "po",
    "pri", "kot", "ali", "da", "ne", "bo", "ter", "če", "kaj", "kje", "kdaj",
    "the", "a", "an", "of", "to", "and", "in", "for", "on", "at", "si",
    "avanture", "evergreen", "seasonal", "docx", "final", "draft", "copy",
    "v2", "v1", "novo", "new",
}


# ────────────────────────── UTILIDADES ──────────────────────────

def translit(text: str) -> str:
    """Convierte caracteres eslovenos a ASCII conservando la letra correcta."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in TRANSLIT:
            rep = TRANSLIT[low]
            out.append(rep.upper() if ch.isupper() else rep)
        else:
            out.append(ch)
    s = "".join(out)
    # Cualquier resto acentuado se descompone (é -> e) en vez de perderse.
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def slugify(text: str, max_len: int = 80) -> str:
    """Slug URL-safe con transliteracion eslovena previa."""
    s = translit(text or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rsplit("-", 1)[0] or s[:max_len]
    return s.strip("-")


def tokens(text: str) -> set[str]:
    """Palabras significativas, normalizadas, sin stopwords ni ruido."""
    raw = re.split(r"[^a-z0-9]+", translit(text or "").lower())
    return {t for t in raw if len(t) > 2 and t not in STOPWORDS_SL
            and not t.isdigit()}


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", re.sub(r"[#*\-|`>]", " ", text or ""))
                if w.strip()])


def reading_time(text: str) -> int:
    return max(1, round(word_count(text) / 200))


def truncate_at_word(text: str, limit: int) -> str:
    """Recorta sin partir palabras ni dejar puntuacion colgando."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-–—")


def http_json(url: str, data: dict | None = None, method: str | None = None,
              headers: dict | None = None, cookie: str | None = None,
              timeout: int = 60) -> tuple[int, dict | list | str, dict]:
    """Peticion HTTP que devuelve (status, cuerpo_parseado, headers)."""
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
        return 0, {"error": t("d.site_unconfigured")}, {}
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if cookie:
        hdrs["Cookie"] = cookie
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs,
                                 method=method or ("POST" if body else "GET"))
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return r.status, parsed, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return e.code, parsed, dict(e.headers or {})
    except Exception as e:
        return 0, {"error": str(e)}, {}


def http_multipart(url: str, fields: dict, files: dict,
                   timeout: int = 120) -> tuple[int, str]:
    """POST multipart/form-data con stdlib. files: {campo: (nombre, bytes)}."""
    boundary = "----avanture" + uuid.uuid4().hex
    buf = io.BytesIO()

    def w(s):
        buf.write(s.encode("utf-8") if isinstance(s, str) else s)

    for k, v in fields.items():
        w(f"--{boundary}\r\n")
        w(f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    for k, (fname, content) in files.items():
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        w(f"--{boundary}\r\n")
        w(f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n')
        w(f"Content-Type: {ctype}\r\n\r\n")
        w(content)
        w("\r\n")
    w(f"--{boundary}--\r\n")

    req = urllib.request.Request(
        url, data=buf.getvalue(),
        headers={"User-Agent": UA,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


# ────────────────────────── CONFIGURACION ──────────────────────────

DEFAULT_CONFIG = {'active_site': 'example',
 'sites': {'example': {'name': 'Your site',
                       'url': '',
                       'api_base': '',
                       'username': '',
                       'password': '',
                       'cookie_name': 'publisher_session',
                       'cookie_value': '',
                       'default_author': 'Editorial team',
                       'language': 'sl',
                       'list_key': 'items'}},
 'ollama': {'url': 'http://localhost:11434',
            'model': 'lfm2.5-reasoning:1.2b',
            'vision_model': 'lfm2-vl:latest',
            'enabled': False,
            'timeout': 240},
 'images': {'backend_order': [],
            'cloudinary': {'cloud_name': '',
                           'api_key': '',
                           'api_secret': '',
                           'upload_preset': '',
                           'folder': '',
                           'transform': 'f_auto,q_auto,w_1800'},
            'stock': {'pexels_key': '', 'unsplash_key': '', 'pixabay_key': ''}},
 'translate': {'enabled': False, 'source': 'auto', 'target': 'sl'},
 'publish': {'default_status': 'draft', 'auto_related': True},
 'ui': {'lang': 'en', 'port': 5000}}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    _ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            return _deep_merge(DEFAULT_CONFIG, json.loads(CONFIG_FILE.read_text("utf-8")))
        except Exception:
            pass
    save_config(DEFAULT_CONFIG)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> None:
    _ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)  # contiene credenciales
    except OSError:
        pass


def active_site(cfg: dict) -> dict:
    return cfg["sites"].get(cfg.get("active_site")) or next(iter(cfg["sites"].values()))


# ────────────────────────── MODELO ──────────────────────────

@dataclass
class Article:
    title: str = ""
    slug: str = ""
    body: str = ""
    metaTitle: str = ""
    metaDescription: str = ""
    excerpt: str = ""
    author: str = "Editorial team"
    # Se dejan vacios a proposito: heuristic_metadata solo deduce lo que falta,
    # asi que un valor por defecto aqui le impediria mirar el texto.
    category: str = ""
    contentType: str = ""
    continent: str = ""
    country: str = ""
    region: str = ""
    city: str = ""
    articlePath: str = ""
    primaryKeyword: str = ""
    searchIntent: str = ""
    coverImage: str = ""
    imageAlt: str = ""
    imageCaption: str = ""
    faq: list = field(default_factory=list)
    quickFacts: list = field(default_factory=list)
    pros: list = field(default_factory=list)
    cons: list = field(default_factory=list)
    packingList: list = field(default_factory=list)
    relatedSlugs: list = field(default_factory=list)
    relatedAdventureSlug: str = ""
    featured: bool = False
    status: str = "draft"
    readingTimeMinutes: int = 0
    publishDate: str = ""
    updatedDate: str = ""
    destination: str = ""          # campo antiguo del sitio, se conserva
    # Bloque de patrocinio / afiliación que soporta el sitio.
    affiliateEnabled: bool = False
    affiliateTitle: str = ""
    affiliateDescription: str = ""
    affiliateButtonText: str = ""
    affiliateUrl: str = ""
    affiliatePartnerName: str = ""
    sponsoredToggle: bool = False  # añade rel="sponsored" a los enlaces
    # Campos locales, nunca se envian a la API.
    source_file: str = ""
    image_file: str = ""
    match_score: float = 0.0
    match_reason: str = ""
    word_count: int = 0
    # Avisos del proceso (emparejamiento dudoso, IA caida, imagen subida).
    # Los de validacion NO viven aqui: se recalculan en cada validate().
    notes: list = field(default_factory=list)
    # Campos que venian escritos en el .docx. Sin esta marca no hay forma de
    # distinguir lo que puso el redactor de lo que rellena la heuristica, y la
    # IA nunca podria mejorar un meta title que la heuristica ya habia copiado
    # del titulo.
    authored_fields: list = field(default_factory=list)

    LOCAL_FIELDS = ("source_file", "image_file", "match_score", "match_reason",
                    "word_count", "notes", "authored_fields")

    def api_payload(self) -> dict:
        """Campos que se envian a la API, sin los de uso interno.

        Los booleanos van siempre: en Python False == 0, asi que el filtro de
        vacios se los comeria y no habria forma de *desactivar* el bloque de
        afiliacion al editar un articulo ya publicado.
        """
        d = {k: v for k, v in asdict(self).items() if k not in self.LOCAL_FIELDS}
        out: dict = {}
        for k, v in d.items():
            if isinstance(v, bool) or k in ("status", "body", "title"):
                out[k] = v
            elif v not in ("", None, [], 0):
                out[k] = v
        return out

    def to_dict(self) -> dict:
        return asdict(self)


# ────────────────────────── PARSER .DOCX ──────────────────────────
# Un .docx es un zip con word/document.xml. Leerlo con zipfile+ElementTree
# evita la dependencia python-docx y mantiene el programa portable.

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _runs(p) -> list[tuple[str, bool, bool]]:
    """Runs del parrafo como (texto, negrita, cursiva), ya fusionados.

    Word parte una misma palabra en varios runs (corrector, revisiones), asi
    que "URL slug" en negrita llega como "URL s" + "lug". Sin fusionar, el
    Markdown saldria como **URL s****lug**.
    """
    out: list[tuple[str, bool, bool]] = []
    for r in p.iter(f"{W}r"):
        txt = "".join(t.text or "" for t in r.iter(f"{W}t"))
        if not txt:
            if r.find(f"{W}br") is not None and out:
                out.append(("\n", False, False))
            continue
        rpr = r.find(f"{W}rPr")
        bold = rpr is not None and rpr.find(f"{W}b") is not None
        ital = rpr is not None and rpr.find(f"{W}i") is not None
        if out and out[-1][1] == bold and out[-1][2] == ital:
            out[-1] = (out[-1][0] + txt, bold, ital)
        else:
            out.append((txt, bold, ital))
    return out


def _plain_text(p) -> str:
    """Texto del parrafo sin marcas, para detectar cabeceras con fiabilidad."""
    return "".join(t for t, _, _ in _runs(p)).strip()


def _para_text(p) -> str:
    """Texto de un parrafo preservando negrita/cursiva como Markdown."""
    parts = []
    for txt, bold, ital in _runs(p):
        core_txt = txt.strip()
        if not core_txt:
            parts.append(txt)
            continue
        lead = txt[:len(txt) - len(txt.lstrip())]
        trail = txt[len(txt.rstrip()):]
        if bold:
            core_txt = f"**{core_txt}**"
        elif ital:
            core_txt = f"*{core_txt}*"
        parts.append(lead + core_txt + trail)
    s = "".join(parts).strip()
    # Dos tramos en negrita pegados ("**a****b**") salen de un cambio de
    # formato a mitad de palabra; en Markdown deben ser uno solo.
    s = re.sub(r"\*\*\*\*", "", s)
    s = re.sub(r"(?<!\*)\*\*(?!\*)\s*\*\*(?!\*)", " ", s)
    return s.strip()


def _style_of(p) -> str:
    ppr = p.find(f"{W}pPr")
    if ppr is None:
        return ""
    st = ppr.find(f"{W}pStyle")
    return (st.get(f"{W}val") or "") if st is not None else ""


def _is_list(p) -> bool:
    ppr = p.find(f"{W}pPr")
    return ppr is not None and ppr.find(f"{W}numPr") is not None


def _heading_level(style: str) -> int:
    m = re.match(r"(?:Heading|Naslov|Titre|berschrift)(\d)", style or "", re.I)
    if m:
        return int(m.group(1))
    if re.match(r"^(Title|Naslov)$", style or "", re.I):
        return 1
    return 0


def _table_md(tbl) -> str:
    rows = []
    for tr in tbl.findall(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            cells.append(" ".join(_para_text(p) for p in tc.findall(f"{W}p")).strip())
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "|".join([" --- "] * n) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def parse_docx(path: str | Path) -> Article:
    """Extrae titulo, meta y cuerpo Markdown de un .docx, preservando estructura."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body_el = root.find(f"{W}body")
    if body_el is None:
        raise ValueError("docx sin cuerpo")

    meta = {}
    title = ""
    lines: list[str] = []
    title_is_provisional = False  # tomado de un parrafo suelto, no de un H1

    for el in body_el:
        tag = el.tag
        if tag == f"{W}tbl":
            md = _table_md(el)
            if md:
                lines.extend(["", md, ""])
            continue
        if tag != f"{W}p":
            continue
        text = _para_text(el)
        if not text:
            continue

        # Bloque de cabecera del docx, fuera del cuerpo. Los redactores usan
        # "Meta title:", "Meta description:", "URL slug:", "Focus keyword:".
        # Se busca sobre el texto plano: la negrita de Word no debe estorbar.
        m = re.match(
            r"^\s*(?:seo\s*)?("
            r"meta\s*(?:title|naslov|description|opis)"
            r"|(?:url\s*)?slug"
            r"|url"
            r"|(?:focus|primary|glavna)?\s*keyword"
            r"|ključna\s*beseda|kljucna\s*beseda"
            r")\s*[:：]\s*(.+)$", _plain_text(el), re.I)
        if m:
            key = translit(m.group(1).lower()).replace(" ", "")
            val = m.group(2).strip().strip("*").strip()
            if "description" in key or "opis" in key:
                meta["metaDescription"] = val
            elif "title" in key or "naslov" in key:
                meta["metaTitle"] = val
            elif "slug" in key or key == "url":
                # Puede venir como "/sicilija-10-dni/" o URL completa.
                val = val.rstrip("/").split("/")[-1]
                meta["slug"] = slugify(val)
            else:
                meta["primaryKeyword"] = val
            continue

        style = _style_of(el)
        lvl = _heading_level(style)

        if lvl == 1:
            clean = re.sub(r"[*_]", "", text).strip()
            if not title:
                title = clean
            elif title_is_provisional:
                # El H1 real manda; el parrafo que hacia de titulo vuelve al cuerpo.
                lines.extend(["", title, ""])
                title = clean
            else:
                # Un segundo H1 es una seccion, no el titulo.
                lines.extend(["", "## " + clean, ""])
            title_is_provisional = False
            continue
        if lvl >= 2:
            lines.extend(["", "#" * min(lvl, 4) + " " + re.sub(r"[*_]", "", text), ""])
            continue
        if _is_list(el):
            lines.append("- " + text)
            continue
        if not title and len(text) < 140:
            # Sin estilo Heading: el primer parrafo corto hace de titulo, pero
            # cede si luego aparece un H1 de verdad.
            title = re.sub(r"[*_]", "", text).strip()
            title_is_provisional = True
            continue
        lines.extend(["", text, ""])

    body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    if not title:
        title = re.sub(r"[_-]+", " ", path.stem).strip()

    art = Article(
        title=title,
        metaTitle=meta.get("metaTitle", ""),
        metaDescription=meta.get("metaDescription", ""),
        slug=meta.get("slug", "") or slugify(title),
        primaryKeyword=meta.get("primaryKeyword", ""),
        body=body,
        source_file=str(path),
        word_count=word_count(body),
        # Se anota lo que traia escrito el documento: es lo que la IA no debe tocar.
        authored_fields=[k for k in ("metaTitle", "metaDescription", "slug",
                                     "primaryKeyword") if meta.get(k)],
    )
    art.readingTimeMinutes = reading_time(body)
    return art


# ────────────────────────── EMPAREJADOR docx <-> imagen ──────────────────────────

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".heic", ".tif", ".tiff"}
DOC_EXT = {".docx"}

# Ruido tipico en nombres de archivo que no ayuda a emparejar.
NAME_NOISE = re.compile(
    r"(img|image|photo|foto|slika|dsc|pxl|screenshot|captura|final|copy|copia|"
    r"v\d+|\d{6,}|\(\d+\)|-\d{2,4}x\d{2,4})", re.I)


def _clean_stem(name: str) -> str:
    s = translit(Path(name).stem.lower())
    s = NAME_NOISE.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def root_match(a: str, b: str) -> float:
    """Cuanto se parecen dos palabras por su raiz, 0..1.

    El esloveno declina mucho ("sonce" -> "sončnih", "let" -> "leti"/"letov"),
    asi que comparar palabras enteras pierde coincidencias evidentes. Se exige
    un prefijo comun de al menos 3 letras que cubra >=60% de la palabra corta,
    lo que enlaza sonce/soncnih pero no pozimi/pozabite.
    """
    if a == b:
        return 1.0
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    if n >= 3 and n >= min(len(a), len(b)) * 0.6:
        return n / max(len(a), len(b))
    return 0.0


def doc_profile(doc: Article) -> dict[str, float]:
    """Vocabulario del articulo con su peso segun donde aparece.

    Mirar solo el nombre del fichero no basta: una foto llamada
    "zima-kanari-sonce.jpg" encaja con un articulo cuyo titulo no dice
    "kanari", pero cuyo encabezado si ("Kanarski otoki").
    """
    prof: dict[str, float] = {}

    def add(text: str, weight: float) -> None:
        for t in tokens(text):
            if prof.get(t, 0.0) < weight:
                prof[t] = weight

    if doc.source_file:
        add(Path(doc.source_file).stem, 1.0)
    add(doc.title, 1.0)
    add(doc.slug.replace("-", " "), 0.9)
    heads = " ".join(l.lstrip("# ") for l in (doc.body or "").split("\n")
                     if l.startswith("#"))
    add(heads, 0.6)
    add((doc.body or "")[:4000], 0.3)
    return prof


def pair_score(doc: Article, img_path: Path,
               prof: dict[str, float] | None = None) -> tuple[float, str]:
    """Puntua 0..1 cuanto encaja una imagen con un articulo, y explica por que."""
    d_stem = _clean_stem(doc.source_file or doc.title)
    i_stem = _clean_stem(img_path.name)
    if not i_stem:
        return 0.0, "el nombre de la imagen no da ninguna pista"

    if d_stem and i_stem and d_stem == i_stem:
        return 1.0, "nombre de archivo idéntico"

    prof = prof if prof is not None else doc_profile(doc)
    i_tok = tokens(i_stem)
    if not i_tok:
        return 0.0, "el nombre de la imagen no da ninguna pista"

    # Cada palabra del nombre de la imagen busca su mejor eco en el articulo.
    per_token: list[float] = []
    hits: list[str] = []
    for it in i_tok:
        best, best_word = 0.0, ""
        for pt, w in prof.items():
            r = root_match(it, pt)
            if r:
                s = r * w
                if s > best:
                    best, best_word = s, pt
        per_token.append(best)
        if best >= 0.45:
            hits.append(best_word)

    per_token.sort(reverse=True)
    top = per_token[:3] or [0.0]
    tok_score = sum(top) / len(top)

    fuzzy = difflib.SequenceMatcher(None, d_stem, i_stem).ratio()
    score = min(1.0, tok_score * 0.8 + fuzzy * 0.2)

    # Varias palabras distintas apuntando al mismo articulo es señal fuerte.
    if len(hits) >= 2:
        score = min(1.0, score + 0.15)

    if hits:
        reason = "coincide con: " + ", ".join(sorted(set(hits))[:3])
    elif fuzzy > 0.5:
        reason = f"nombres parecidos ({int(fuzzy * 100)}%)"
    else:
        reason = "sin coincidencia clara"
    return score, reason


def match_pairs(docs: list[Article], images: list[Path]) -> list[Article]:
    """Asigna a cada docx su imagen. Asignacion global: primero los pares mas
    seguros, para que una imagen obvia no se la lleve un articulo equivocado."""
    if not images:
        return docs

    # Caso trivial: uno a uno, sin ambiguedad posible.
    if len(docs) == 1 and len(images) == 1:
        s, why = pair_score(docs[0], images[0])
        docs[0].image_file = str(images[0])
        docs[0].match_score = max(s, 0.99)
        docs[0].match_reason = "único par posible" if s < 0.4 else why
        return docs

    profiles = [doc_profile(d) for d in docs]
    grid = []
    for di, d in enumerate(docs):
        for ii, img in enumerate(images):
            s, why = pair_score(d, img, profiles[di])
            grid.append((s, di, ii, why))
    grid.sort(key=lambda x: -x[0])

    used_d: set[int] = set()
    used_i: set[int] = set()
    for s, di, ii, why in grid:
        if di in used_d or ii in used_i:
            continue
        if s < 0.15:
            continue
        docs[di].image_file = str(images[ii])
        docs[di].match_score = round(s, 3)
        docs[di].match_reason = why
        used_d.add(di)
        used_i.add(ii)

    # Sobrantes: reparto por orden para no dejar articulos sin portada.
    free_d = [i for i in range(len(docs)) if i not in used_d]
    free_i = [i for i in range(len(images)) if i not in used_i]
    for di, ii in zip(free_d, free_i):
        docs[di].image_file = str(images[ii])
        docs[di].match_score = 0.1
        docs[di].match_reason = "asignado por orden (revísalo)"
        docs[di].notes.append(t("n.match_uncertain"))
    return docs


def classify_files(paths: list[str | Path]) -> tuple[list[Path], list[Path], list[Path]]:
    """Separa lo soltado en (docx, imagenes, ignorados)."""
    docs, imgs, other = [], [], []
    for p in paths:
        p = Path(p)
        ext = p.suffix.lower()
        if ext in DOC_EXT:
            docs.append(p)
        elif ext in IMAGE_EXT:
            imgs.append(p)
        else:
            other.append(p)
    return sorted(docs), sorted(imgs), other


# ────────────────────────── TRADUCCION ──────────────────────────

def _split_text(text: str, max_len: int = 4500) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > max_len:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks or [""]


def translate_google(text: str, source: str = "en", target: str = "sl") -> str:
    out = []
    for chunk in _split_text(text):
        params = urllib.parse.urlencode(
            {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": chunk})
        st, data, _ = http_json(
            f"https://translate.googleapis.com/translate_a/single?{params}",
            headers={"Accept": "*/*"}, timeout=45)
        if st == 200 and isinstance(data, list) and data and data[0]:
            out.append("".join(p[0] for p in data[0] if p and p[0]))
        else:
            out.append(chunk)
    return "".join(out)


def translate_mymemory(text: str, source: str = "en", target: str = "sl") -> str:
    out = []
    for chunk in _split_text(text, 480):
        params = urllib.parse.urlencode({"q": chunk, "langpair": f"{source}|{target}"})
        st, data, _ = http_json(
            f"https://api.mymemory.translated.net/get?{params}", timeout=45)
        if st == 200 and isinstance(data, dict):
            out.append(data.get("responseData", {}).get("translatedText", chunk))
        else:
            out.append(chunk)
    return " ".join(out)


def translate(text: str, source: str = "en", target: str = "sl") -> str:
    """Google primero, MyMemory de reserva. Los modelos locales de 1.2B no
    traducen esloveno de forma publicable, por eso no se usan aqui."""
    if not text.strip():
        return text
    r = translate_google(text, source, target)
    if r and r.strip() and r != text:
        return r
    return translate_mymemory(text, source, target)


def translate_markdown(text: str, source: str, target: str) -> str:
    """Traduce conservando el Markdown.

    Los traductores destrozan los `##` y los `-` si se les manda el documento
    entero, asi que cada linea viaja sin su marca y se le devuelve despues.
    """
    out: list[str] = []
    for line in (text or "").split("\n"):
        raw = line.rstrip()
        if not raw.strip() or raw.strip() == "---":
            out.append(raw)
            continue
        m = re.match(r"^(#{1,6}\s+|[-*]\s+|\d+\.\s+)?(.*)$", raw)
        prefix, body = (m.group(1) or ""), m.group(2)
        if not body.strip():
            out.append(raw)
            continue
        # Las marcas de negrita/cursiva se quitan y se reponen alrededor.
        bold = body.startswith("**") and body.endswith("**") and len(body) > 4
        clean = body[2:-2] if bold else body
        tr = translate(clean, source, target).strip()
        if bold:
            tr = f"**{tr}**"
        out.append(prefix + tr)
    return "\n".join(out)


def translate_article(art: Article, target: str, source: str = "") -> Article:
    """Traduce el articulo entero al idioma pedido, con su Markdown y su FAQ."""
    src = source or detect_language(art.body)
    if src == target:
        return art

    art.title = translate(art.title, src, target).strip()
    art.body = translate_markdown(art.body, src, target)
    if art.metaTitle:
        art.metaTitle = truncate_at_word(translate(art.metaTitle, src, target), 60)
    if art.metaDescription:
        art.metaDescription = truncate_at_word(
            translate(art.metaDescription, src, target), 155)
    if art.excerpt:
        art.excerpt = truncate_at_word(translate(art.excerpt, src, target), 300)
    if art.imageAlt:
        art.imageAlt = truncate_at_word(translate(art.imageAlt, src, target), 120)
    art.faq = [{"q": translate(f.get("q", ""), src, target).strip(),
                "a": translate(f.get("a", ""), src, target).strip()}
               for f in (art.faq or [])]
    art.quickFacts = [{"label": translate(f.get("label", ""), src, target).strip()}
                      for f in (art.quickFacts or [])]
    for f in ("pros", "cons", "packingList"):
        vals = getattr(art, f) or []
        setattr(art, f, [translate(v, src, target).strip() for v in vals])

    # El slug se rehace desde el titulo traducido, y la ruta con el.
    art.slug = slugify(art.title)
    art.articlePath = build_article_path(art.continent, art.country, art.slug)
    art.notes.append(t("n.translated", src=src, dst=target))
    return art


def detect_language(text: str) -> str:
    """Detecta sl/en/es por palabras funcionales. Suficiente para decidir si
    hay que traducir; no pretende ser un identificador general."""
    t = " " + re.sub(r"[^a-zčšž ]", " ", (text or "").lower()[:3000]) + " "
    marks = {
        "sl": [" in ", " je ", " za ", " na ", " se ", " ki ", " ne ", " so ",
               " ali ", " tudi ", " lahko ", " kot ", " pri ", " če "],
        "en": [" the ", " and ", " you ", " for ", " with ", " that ", " this ",
               " are ", " from ", " your ", " have ", " what "],
        "es": [" el ", " la ", " los ", " las ", " que ", " para ", " con ",
               " una ", " por ", " del ", " más ", " como "],
    }
    scores = {k: sum(t.count(m) for m in v) for k, v in marks.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 3 else "sl"


# ────────────────────────── IA LOCAL (OLLAMA) ──────────────────────────

def ollama_up(cfg: dict) -> tuple[bool, list[str]]:
    st, data, _ = http_json(cfg["ollama"]["url"].rstrip("/") + "/api/tags", timeout=6)
    if st == 200 and isinstance(data, dict):
        return True, [m["name"] for m in data.get("models", [])]
    return False, []


_READY_CACHE: dict[str, tuple[float, bool, str]] = {}
_READY_TTL = 90.0


def ollama_ready(cfg: dict, budget: int = 20, use_cache: bool = True) -> tuple[bool, str]:
    """Comprueba que el modelo responde *ya*, generando un solo token.

    Que /api/tags conteste solo prueba que el servidor esta vivo, no que pueda
    atender: si otro proceso tiene la GPU o la CPU ocupada, la peticion se queda
    encolada. Sin esta prueba corta, cada articulo esperaria el timeout completo
    antes de rendirse y pareceria que el programa se ha colgado.

    El resultado se cachea unos segundos: al publicar un lote de diez articulos
    no tiene sentido gastar el presupuesto de espera diez veces seguidas.
    """
    key = cfg["ollama"]["url"] + "|" + cfg["ollama"]["model"]
    now = time.time()
    if use_cache:
        hit = _READY_CACHE.get(key)
        if hit and now - hit[0] < _READY_TTL:
            return hit[1], hit[2]

    t0 = time.time()
    payload = {"model": cfg["ollama"]["model"], "prompt": "OK", "stream": False,
               "options": {"num_predict": 1}}
    st, _, _ = http_json(cfg["ollama"]["url"].rstrip("/") + "/api/generate",
                         data=payload, timeout=budget)
    took = time.time() - t0
    if st == 200:
        out = (True, t("d.ai_ready", s=f"{took:.1f}"))
    elif st == 0:
        out = (False, t("d.ai_timeout", s=budget))
    else:
        out = (False, t("d.ai_error", code=st))
    _READY_CACHE[key] = (now, out[0], out[1])
    return out


def ollama_generate(cfg: dict, prompt: str, model: str | None = None,
                    images: list[str] | None = None, fmt: str | None = None) -> str:
    payload = {
        "model": model or cfg["ollama"]["model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 900},
    }
    if images:
        payload["images"] = images
    if fmt:
        payload["format"] = fmt
    st, data, _ = http_json(cfg["ollama"]["url"].rstrip("/") + "/api/generate",
                            data=payload, timeout=cfg["ollama"].get("timeout", 240))
    if st == 200 and isinstance(data, dict):
        return data.get("response", "") or ""
    return ""


def _json_from_text(raw: str) -> dict:
    """Extrae el JSON de una respuesta del modelo, tolerando <think>, vallas
    de codigo y texto suelto alrededor."""
    if not raw:
        return {}
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)
    start = raw.find("{")
    if start < 0:
        return {}
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


# ────────────────────────── METADATA ──────────────────────────

def extract_faq(body: str) -> tuple[list[dict], str]:
    """Saca el FAQ que ya trae el articulo y lo quita del cuerpo.

    Los redactores escriben la pregunta en negrita (a veces sin ella) y la
    respuesta en el parrafo siguiente. Pasarlo al campo `faq` da rich results
    en Google, en vez de dejarlo como texto plano dentro del cuerpo.
    """
    lines = body.split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^#{2,4}\s", l) and re.search(
                r"pogosta\s+vprašanja|pogosto\s+zastavljena|faq|preguntas", l, re.I):
            start = i
            break
    if start is None:
        return [], body

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^#{2,4}\s", lines[j]):
            end = j
            break

    faq: list[dict] = []
    q: str | None = None
    ans: list[str] = []
    for l in lines[start + 1:end]:
        t = l.strip()
        if not t:
            continue
        plain = re.sub(r"[*_]", "", t).strip()
        if plain.endswith("?") and len(plain) < 200:
            if q and ans:
                faq.append({"q": q, "a": " ".join(ans).strip()})
            q, ans = plain, []
        elif q:
            ans.append(plain)
    if q and ans:
        faq.append({"q": q, "a": " ".join(ans).strip()})

    if not faq:
        return [], body
    new_body = "\n".join(lines[:start] + lines[end:])
    return faq, re.sub(r"\n{3,}", "\n\n", new_body).strip()


def _count_countries(text: str) -> dict[str, int]:
    t = translit(text or "").lower()
    counts: dict[str, int] = {}
    for hint, country in COUNTRY_HINTS.items():
        n = t.count(translit(hint).lower())
        if n:
            counts[country] = counts.get(country, 0) + n
    return counts


def extract_quick_facts(body: str) -> tuple[list[dict], str]:
    """Saca los datos rapidos de la seccion «Hitra dejstva» y la quita del cuerpo.

    Devuelve (datos, cuerpo_sin_la_seccion). El sitio ya pinta un bloque propio
    con el campo quickFacts, asi que dejar ademas la lista dentro del texto la
    mostraría dos veces.
    """
    lines = (body or "").split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^#{2,4}\s", l) and re.search(
                r"hitra\s+dejstva|dejstva\s+o\s|datos\s+rápidos|quick\s+facts", l, re.I):
            start = i
            break
    if start is None:
        return [], body

    end = len(lines)
    facts = []
    for j in range(start + 1, len(lines)):
        t = lines[j].strip()
        if re.match(r"^#{2,4}\s", t):
            end = j
            break
        if re.match(r"^[-*]\s+", t):
            fact = re.sub(r"^[-*]\s+", "", t)
            fact = re.sub(r"[*_]", "", fact).strip()
            if 10 <= len(fact) <= 200:
                facts.append({"label": fact})
    if not facts:
        return [], body

    # Fuera la seccion y los separadores que la envolvian.
    rest = lines[:start] + lines[end:]
    new_body = re.sub(r"\n{3,}", "\n\n", "\n".join(rest)).strip()
    new_body = re.sub(r"^-{3,}\s*\n+", "", new_body)
    new_body = re.sub(r"\n-{3,}\s*\n-{3,}\s*\n", "\n---\n", new_body)
    return facts[:6], new_body


def guess_country(title: str, body: str = "") -> str:
    """Pais del articulo, o "" si es multi-destino.

    Devolver siempre "el mas mencionado" es peor que no devolver nada: una guia
    de vuelos que cita Bali de pasada acabaria archivada en /azija/bali/. Por
    eso el titulo manda, y el cuerpo solo decide si un pais domina claramente.
    Eslovenia se ignora salvo que este en el titulo: es el pais del lector y
    aparece en casi todos los articulos ("leti iz Slovenije").
    """
    body_counts = _count_countries(body)
    body_counts.pop("Slovenija", None)
    body_total = sum(body_counts.values())

    in_title = _count_countries(title)
    if in_title:
        cand = max(in_title, key=lambda k: in_title[k])
        # El titulo propone, el cuerpo confirma. "Pozabite na Santorini in
        # Mykonos: obiščite skrite evropske otoke" nombra Grecia justamente
        # para descartarla, y el articulo recorre media Europa.
        if not body_total or body_counts.get(cand, 0) / body_total >= 0.25:
            return cand
        return ""

    if not body_counts:
        return ""
    best = max(body_counts, key=lambda k: body_counts[k])
    # Un solo pais debe llevarse al menos el 45% de las menciones y aparecer
    # varias veces; si no, el articulo habla de muchos destinos.
    if body_counts[best] >= 4 and body_counts[best] / body_total >= 0.45:
        return best
    return ""


CONTINENT_HINTS = {
    "evropsk": "Evropa", "european": "Evropa", "evropi": "Evropa",
    "azijsk": "Azija", "asian": "Azija", "aziji": "Azija",
    "afrišk": "Afrika", "afrisk": "Afrika", "african": "Afrika",
    "afriki": "Afrika", "karib": "Severna Amerika",
    "južna amerika": "Južna Amerika", "latinsk": "Južna Amerika",
    "oceanij": "Oceanija",
}


def guess_continent(title: str, body: str = "", country: str = "") -> str:
    """Continente del articulo. Un reportaje sobre varias islas europeas no
    tiene pais, pero si continente: asi no se queda sin clasificar."""
    if country:
        return COUNTRY_CONTINENT.get(country, "")
    t = translit(f"{title} {title} {body[:3000]}").lower()
    scores: dict[str, int] = {}
    for hint, cont in CONTINENT_HINTS.items():
        n = t.count(translit(hint).lower())
        if n:
            scores[cont] = scores.get(cont, 0) + n
    if scores:
        return max(scores, key=lambda k: scores[k])
    # Sin pistas explicitas: el continente de los paises citados, si coinciden.
    counts = _count_countries(body)
    counts.pop("Slovenija", None)
    conts: dict[str, int] = {}
    for c, n in counts.items():
        cont = COUNTRY_CONTINENT.get(c)
        if cont:
            conts[cont] = conts.get(cont, 0) + n
    if conts:
        total = sum(conts.values())
        best = max(conts, key=lambda k: conts[k])
        if conts[best] / total >= 0.6:
            return best
    return ""


def guess_content_type(title: str, body: str = "") -> str:
    """Tipo de contenido por puntuacion: varias pistas pueden coincidir y gana
    la mas especifica, no la primera de la lista."""
    # La puntuacion se cambia por espacios: en "najcenejše lete:" la pista
    # "lete " no encajaria por culpa de los dos puntos.
    t = " " + re.sub(r"[^\w]+", " ", (title or "").lower()) + " "
    scores: dict[str, float] = {}
    for words, ctype, weight in CONTENT_TYPE_HINTS:
        for w in words:
            if w in t:
                scores[ctype] = scores.get(ctype, 0.0) + weight
    if not scores:
        return "travel-tips"
    return max(scores, key=lambda k: scores[k])


def first_paragraph(body: str) -> str:
    for block in (body or "").split("\n\n"):
        b = re.sub(r"[*_#>-]", "", block).strip()
        if len(b) > 80 and not b.startswith("|"):
            return re.sub(r"\s+", " ", b)
    return ""


def build_article_path(continent: str, country: str, slug: str) -> str:
    """Ruta canonica /continent/country/slug/ como el resto del sitio.

    Sin pais no hay ruta geografica posible (guias globales, listas de varios
    destinos): esos van al listado /clanki/, que ya existe en el sitio.
    """
    if not slug:
        return ""
    if continent and country:
        return f"/{slugify(continent)}/{slugify(country)}/{slug}/"
    # Solo con continente no se usa /evropa/{slug}/: esa forma choca con las
    # paginas de continente del sitio, que esperan /evropa/{pais}/.
    return f"/clanki/{slug}/"


def guess_search_intent(title: str, body: str = "") -> str:
    """Clasifica la intención de búsqueda por keywords en esloveno.

    Patrón de agent-seo-engine: cuenta coincidencias por categoría en
    título + primeros 1000 chars del cuerpo, gana la que más suma.
    Sin dependencias externas, sin IA, solo.matching de palabras señal.
    """
    text = translit(f"{title} {title} {body[:1000]}").lower()
    scores: dict[str, float] = {}
    for intent, signals in INTENT_SIGNALS.items():
        for signal in signals:
            s = translit(signal).lower()
            n = text.count(s)
            if n:
                # Las señales de 1 palabra valen 1, las de 2+ palabras valen 2
                weight = 2 if " " in signal else 1
                scores[intent] = scores.get(intent, 0.0) + n * weight
    if not scores:
        return "informational"
    best = max(scores, key=lambda k: scores[k])
    # Umbral: si el segundo más alto está a menos del 40%, hay ambigüedad
    ordered = sorted(scores.values(), reverse=True)
    if len(ordered) >= 2 and ordered[0] - ordered[1] < ordered[0] * 0.4:
        # Empate técnico: preferir informational para travel content
        return "informational"
    return best


# Patrones de basura para meta description (swarm meta_generator adaptado)
_SKIP_META = [
    re.compile(r"^(to\s+je|v\s+tem\s+clanku|v\s+tem\s+vodniku|here|this|the\s+following|below|note|warning)", re.I),
    re.compile(r"^#{1,6}\s"),
    re.compile(r"^\|"),
    re.compile(r"^```"),
    re.compile(r"^<"),
    re.compile(r"^!\["),
    re.compile(r"^---"),
    re.compile(r"^\*\*?(Opomba|Pozor|Warning|Note|Disclaimer)", re.I),
    re.compile(r"^\s*$"),
]


def _best_meta_description(body: str, title: str = "") -> str:
    """Extrae la mejor meta description del cuerpo, sin IA.

    Patrón de swarm: skip de basura → primer párrafo significativo →
    truncar en frontera de palabra a 155 chars.  Si no hay nada
    útil, devuelve el título truncado.
    """
    text = re.sub(r"<style[\s\S]*?</style>", "", body or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    candidates: list[str] = []
    for block in text.split("\n\n"):
        b = re.sub(r"[*_#>-]", "", block).strip()
        if not b or len(b) < 50:
            continue
        if any(p.match(b) for p in _SKIP_META):
            continue
        if b.startswith("|"):
            continue
        b = re.sub(r"\s+", " ", b)
        candidates.append(b)
        if len(candidates) >= 3:
            break

    desc = candidates[0] if candidates else (title or "")
    if len(desc) > 155:
        cut = desc[:155].rfind(" ")
        if cut > 155 * 0.6:
            desc = desc[:cut]
        desc = desc.rstrip(".,;:- ") + "..."
    return desc


def heuristic_metadata(art: Article) -> Article:
    """Rellena todo lo que se puede deducir del texto sin IA.

    Es la red de seguridad: si Ollama no responde, el articulo sigue siendo
    publicable, porque los .docx ya traen meta title y description escritos.
    """
    art.faq, art.body = extract_faq(art.body) if not art.faq else (art.faq, art.body)
    if not art.quickFacts:
        art.quickFacts, art.body = extract_quick_facts(art.body)

    # El slug se normaliza siempre, venga de donde venga: si se edita a mano y
    # queda "mi-articulo-" o con un acento, se arregla solo en vez de soltar un
    # error que no dice qué hacer.
    art.slug = slugify(art.slug) if art.slug else slugify(art.title)
    if not art.country:
        art.country = guess_country(art.title, art.body)
    if not art.continent:
        art.continent = guess_continent(art.title, art.body, art.country)
    if not art.contentType:
        art.contentType = guess_content_type(art.title, art.body)
    if not art.searchIntent:
        art.searchIntent = guess_search_intent(art.title, art.body)
    if not art.category:
        art.category = "vodnik"
    if not art.metaTitle:
        art.metaTitle = truncate_at_word(art.title, 60)
    if not art.excerpt:
        # 300, no 200: los articulos publicados usan entre 214 y 334 caracteres.
        art.excerpt = truncate_at_word(first_paragraph(art.body), 300)
    if not art.metaDescription:
        # Buscar un párrafo descriptivo mejor que el primero.
        # Patrón de swarm meta_generator: skip basura, primer >50 chars.
        art.metaDescription = _best_meta_description(art.body, art.title)
    if not art.primaryKeyword:
        base = translit(art.metaTitle or art.title).lower()
        kw = [w for w in re.split(r"[^a-z0-9]+", base) if w and w not in STOPWORDS_SL]
        art.primaryKeyword = " ".join(kw[:3])
    if not art.articlePath:
        art.articlePath = build_article_path(art.continent, art.country, art.slug)
    if not art.readingTimeMinutes:
        art.readingTimeMinutes = reading_time(art.body)
    if not art.word_count:
        art.word_count = word_count(art.body)
    # Alt de reserva desde el titulo: sin esto, con la IA apagada el articulo
    # se publicaria con la imagen sin describir, que es justo el fallo de SEO y
    # accesibilidad que ya arrastra un articulo del sitio.
    if not art.imageAlt and (art.coverImage or art.image_file):
        art.imageAlt = truncate_at_word(art.title, 120)
    return art


# ────────────────────────── CONVENCIONES DEL SITIO ──────────────────────────

# Campos que, si valen lo mismo en todos los articulos publicados, se toman
# como norma de la casa y se aplican a los nuevos. Se excluyen a proposito los
# que son propios de cada articulo (titulo, slug, pais, tipo de contenido).
CONVENTION_FIELDS = ("author", "category", "searchIntent", "featured",
                     "affiliateEnabled", "sponsoredToggle", "imageCaption",
                     "relatedAdventureSlug", "destination")

CONVENTIONS_CACHE = CACHE_DIR / "conventions.json"


def learn_site_conventions(articles: list[dict]) -> dict:
    """Deduce como son los articulos de este sitio, mirando los publicados.

    Si los articulos llevan el mismo autor, category "vodnik" y
    featured true, los nuevos salen igual: es lo que significa «los mismos
    anuncios con los mismos parametros». Un campo que varia no es una norma y
    se deja que lo decida el texto de cada articulo.
    """
    conv: dict = {"_sample": len(articles)}
    if not articles:
        return conv

    for f in CONVENTION_FIELDS:
        vals = [a.get(f) for a in articles if f in a]
        if not vals or len(vals) < max(2, len(articles) * 0.75):
            continue
        first = vals[0]
        if all(v == first for v in vals) and first is not None:
            conv[f] = first

    # Cuantos bloques suele llevar un articulo de la casa: sirve para avisar
    # cuando el nuevo se queda corto, no para inventarlos.
    for f in ("faq", "quickFacts"):
        counts = [len(a.get(f) or []) for a in articles]
        used = [c for c in counts if c]
        if used and len(used) >= len(articles) * 0.75:
            conv[f"typical_{f}"] = round(sum(used) / len(used))

    lens = [len(a.get("excerpt") or "") for a in articles if a.get("excerpt")]
    if lens:
        conv["typical_excerpt"] = round(sum(lens) / len(lens))
    return conv


def get_conventions(cfg: dict, client=None, force: bool = False) -> dict:
    """Convenciones del sitio, cacheadas en disco para no pedirlas cada vez."""
    if not force and CONVENTIONS_CACHE.exists():
        try:
            cached = json.loads(CONVENTIONS_CACHE.read_text("utf-8"))
            if time.time() - cached.get("_ts", 0) < 86400:
                return cached
        except Exception:
            pass
    try:
        cli = client or SiteClient(cfg)
        if not cli.ensure_session()[0]:
            return {}
        conv = learn_site_conventions(cli.list_articles())
        conv["_ts"] = time.time()
        _ensure_dirs()
        CONVENTIONS_CACHE.write_text(json.dumps(conv, ensure_ascii=False, indent=2), "utf-8")
        return conv
    except Exception:
        return {}


def apply_conventions(art: Article, conv: dict) -> Article:
    """Pone en el articulo nuevo lo que el sitio hace siempre igual."""
    for f in CONVENTION_FIELDS:
        if f not in conv:
            continue
        current = getattr(art, f, None)
        if f in art.authored_fields:
            continue
        # Solo se rellena lo que esta vacio: nunca se pisa una decision tomada.
        if current in ("", None, False) and conv[f] not in ("", None):
            setattr(art, f, conv[f])
    return art


AI_META_PROMPT = """Si SEO urednik za slovenski potovalni portal.
Preberi članek in vrni SAMO JSON objekt, brez razlage.

Zahteve:
- "metaTitle": največ 58 znakov, vsebuje glavno ključno besedo, privlačen
- "metaDescription": 120-155 znakov, vsebuje ključno besedo, vabi h kliku
- "excerpt": 1-2 stavka, največ 200 znakov
- "primaryKeyword": 2-4 besede, kar bi uporabnik vtipkal v Google
- "quickFacts": 4-5 zanimivih dejstev, vsak {"label": "dejstvo"}
- "searchIntent": informational, commercial, affiliate ali inspirational

Vse v slovenščini. Vrni samo JSON."""


def ai_metadata(cfg: dict, art: Article, examples: list[dict] | None = None) -> dict:
    """Pide a la IA local que mejore los campos SEO. Devuelve solo lo aceptable."""
    ex = ""
    if examples:
        sample = [{"metaTitle": e.get("metaTitle", ""),
                   "metaDescription": e.get("metaDescription", ""),
                   "primaryKeyword": e.get("primaryKeyword", "")}
                  for e in examples[:2] if e.get("metaTitle")]
        if sample:
            ex = ("\n\nPRIMERI IZ TEGA SPLETNEGA MESTA:\n"
                  + json.dumps(sample, ensure_ascii=False, indent=1))

    prompt = (f"{AI_META_PROMPT}{ex}\n\nNASLOV: {art.title}\n\n"
              f"ČLANEK:\n{art.body[:5000]}")
    raw = ollama_generate(cfg, prompt, fmt="json")
    data = _json_from_text(raw)
    if not isinstance(data, dict):
        return {}

    out: dict = {}
    mt = str(data.get("metaTitle") or "").strip()
    if 15 <= len(mt) <= 70:
        out["metaTitle"] = truncate_at_word(mt, 60)
    md = str(data.get("metaDescription") or "").strip()
    if 60 <= len(md) <= 220:
        out["metaDescription"] = truncate_at_word(md, 155)
    exc = str(data.get("excerpt") or "").strip()
    if 40 <= len(exc) <= 400:
        out["excerpt"] = truncate_at_word(exc, 200)
    kw = str(data.get("primaryKeyword") or "").strip()
    if 3 <= len(kw) <= 60:
        out["primaryKeyword"] = kw
    si = str(data.get("searchIntent") or "").strip()
    if si in SEARCH_INTENTS:
        out["searchIntent"] = si
    qf = data.get("quickFacts")
    if isinstance(qf, list):
        facts = []
        for f in qf[:6]:
            if isinstance(f, dict):
                lab = str(f.get("label") or f.get("value") or "").strip()
            else:
                lab = str(f).strip()
            if 15 <= len(lab) <= 160:
                facts.append({"label": lab})
        if len(facts) >= 3:
            out["quickFacts"] = facts
    return out


def vision_alt_text(cfg: dict, image_path: str | Path, title: str = "") -> str:
    """Alt-text describiendo la foto real, con el modelo de vision local."""
    import base64
    try:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    except OSError:
        return ""
    model = cfg["ollama"].get("vision_model") or "lfm2-vl:latest"
    prompt = ("Describe this travel photo in ONE short sentence for an image "
              "alt attribute. Max 100 characters. Only the description, no "
              "quotes, no preamble.")
    if title:
        prompt += f" Context: the article is titled '{title}'."
    raw = ollama_generate(cfg, prompt, model=model, images=[b64])
    alt = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S | re.I)
    alt = alt.strip().strip('"').split("\n")[0].strip()
    return truncate_at_word(alt, 120)


def check_against_conventions(art: Article, conv: dict) -> list[str]:
    """Avisa de en que se aparta el articulo de los ya publicados."""
    out = []
    n = conv.get("typical_quickFacts")
    if n and not art.quickFacts:
        out.append(t("n.few_facts", n=n))
    n = conv.get("typical_faq")
    if n and not art.faq:
        out.append(t("n.few_faq", n=n))
    return out


def process_article(cfg: dict, art: Article, use_ai: bool = True,
                    examples: list[dict] | None = None,
                    conventions: dict | None = None) -> Article:
    """Deja el articulo listo para revisar: heuristica siempre, IA si responde."""
    art = heuristic_metadata(art)
    if conventions:
        art = apply_conventions(art, conventions)
        for msg in check_against_conventions(art, conventions):
            if msg not in art.notes:
                art.notes.append(msg)

    lang = detect_language(art.body)
    target = cfg.get("translate", {}).get("target", "sl")
    if cfg.get("translate", {}).get("enabled") and lang != target:
        art.body = translate(art.body, lang, target)
        art.title = translate(art.title, lang, target)
        art.slug = slugify(art.title)
        art = heuristic_metadata(art)

    ai_on = bool(use_ai and cfg["ollama"].get("enabled"))
    if use_ai and not cfg["ollama"].get("enabled"):
        art.notes.append(t("n.ai_off"))

    if ai_on:
        ready, why = ollama_ready(cfg)
        if not ready:
            ai_on = False
            art.notes.append(t("n.ai_unavailable", why=why))

    if ai_on:
        try:
            improved = ai_metadata(cfg, art, examples)
            for k, v in improved.items():
                # La IA rellena huecos y mejora lo que puso la heuristica, pero
                # jamas reescribe lo que el redactor dejo escrito en el .docx.
                if k in art.authored_fields and getattr(art, k):
                    continue
                setattr(art, k, v)
        except Exception as e:
            art.notes.append(t("n.ai_failed", err=e))

    # La vision mejora el alt de reserva que puso la heuristica, pero no toca
    # el que haya escrito una persona.
    if ai_on and art.image_file and "imageAlt" not in art.authored_fields:
        try:
            alt = vision_alt_text(cfg, art.image_file, art.title)
            if alt:
                art.imageAlt = alt
        except Exception:
            pass

    return heuristic_metadata(art)


# ────────────────────────── BACKENDS DE IMAGEN ──────────────────────────
# La API editorial acepta coverImage como
# solo una URL de texto. Por eso el flujo manual obligaba a subir la foto a
# Cloudinary a mano y pegar la URL. Estos backends automatizan ese paso.

class ImageUploadError(Exception):
    pass


def cloudinary_signed_upload(cfg: dict, path: str | Path,
                             public_id: str = "") -> str:
    """Sube a la cuenta Cloudinary del sitio con api_key + api_secret."""
    cl = cfg["images"]["cloudinary"]
    cloud, key, secret = cl.get("cloud_name"), cl.get("api_key"), cl.get("api_secret")
    if not (cloud and key and secret):
        raise ImageUploadError("faltan cloud_name, api_key o api_secret")

    params = {"timestamp": str(int(time.time()))}
    if public_id:
        params["public_id"] = public_id
    if cl.get("folder"):
        params["folder"] = cl["folder"]
    # Firma: parametros ordenados, k=v unidos por &, + api_secret, en SHA1.
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    params["signature"] = hashlib.sha1((to_sign + secret).encode()).hexdigest()
    params["api_key"] = key

    st, body = http_multipart(
        f"https://api.cloudinary.com/v1_1/{cloud}/image/upload",
        fields=params, files={"file": (Path(path).name, Path(path).read_bytes())})
    data = _json_from_text(body) if body.strip().startswith("{") else {}
    if st == 200 and data.get("secure_url"):
        return _cloudinary_transform(data["secure_url"], cl.get("transform", ""))
    msg = (data.get("error") or {}).get("message") or body[:200]
    raise ImageUploadError(f"Cloudinary ({st}): {msg}")


def cloudinary_unsigned_upload(cfg: dict, path: str | Path,
                               public_id: str = "") -> str:
    """Sube con un upload_preset sin firmar (hay que habilitarlo en Cloudinary)."""
    cl = cfg["images"]["cloudinary"]
    cloud, preset = cl.get("cloud_name"), cl.get("upload_preset")
    if not (cloud and preset):
        raise ImageUploadError("falta upload_preset")
    fields = {"upload_preset": preset}
    if public_id:
        fields["public_id"] = public_id
    if cl.get("folder"):
        fields["folder"] = cl["folder"]
    st, body = http_multipart(
        f"https://api.cloudinary.com/v1_1/{cloud}/image/upload",
        fields=fields, files={"file": (Path(path).name, Path(path).read_bytes())})
    data = _json_from_text(body) if body.strip().startswith("{") else {}
    if st == 200 and data.get("secure_url"):
        return _cloudinary_transform(data["secure_url"], cl.get("transform", ""))
    msg = (data.get("error") or {}).get("message") or body[:200]
    raise ImageUploadError(f"Cloudinary ({st}): {msg}")


def _cloudinary_transform(url: str, transform: str) -> str:
    """Inserta f_auto,q_auto,w_1800 en la URL, como el resto del sitio."""
    if not transform or "/image/upload/" not in url:
        return url
    head, tail = url.split("/image/upload/", 1)
    return f"{head}/image/upload/{transform}/{tail}"


def catbox_upload(cfg: dict, path: str | Path, public_id: str = "",
                  attempts: int = 3) -> str:
    """Sube a catbox.moe: anonimo y sin cuenta. Sirve para trabajar hoy, pero
    no es un CDN del sitio; para produccion conviene Cloudinary.

    Es un servicio gratuito y a veces contesta 200 con el cuerpo vacio en vez
    de la URL. Reintentar basta; sin esto, publicar fallaria de vez en cuando
    sin motivo aparente.
    """
    last = ""
    for i in range(attempts):
        st, body = http_multipart(
            "https://catbox.moe/user/api.php",
            fields={"reqtype": "fileupload"},
            files={"fileToUpload": (Path(path).name, Path(path).read_bytes())})
        body = (body or "").strip()
        if st == 200 and body.startswith("http"):
            return body
        last = f"{st}: {body[:120]}" if body else f"{st}: respuesta vacía"
        if i < attempts - 1:
            time.sleep(1.5 * (i + 1))
    raise ImageUploadError(f"catbox ({last})")


IMAGE_BACKENDS = {
    "cloudinary_signed": cloudinary_signed_upload,
    "cloudinary_unsigned": cloudinary_unsigned_upload,
    "catbox": catbox_upload,
}


def backend_available(cfg: dict, name: str) -> bool:
    cl = cfg["images"]["cloudinary"]
    if name == "cloudinary_signed":
        return bool(cl.get("cloud_name") and cl.get("api_key") and cl.get("api_secret"))
    if name == "cloudinary_unsigned":
        return bool(cl.get("cloud_name") and cl.get("upload_preset"))
    return name in IMAGE_BACKENDS


def upload_image(cfg: dict, path: str | Path, public_id: str = "") -> tuple[str, str]:
    """Sube la imagen por el primer backend configurado que funcione.

    Devuelve (url, backend_usado). Recorrer la lista en orden permite que el
    sitio use Cloudinary en cuanto haya credenciales, sin tocar el codigo.
    """
    # An empty list means uploads are disabled, never an implicit public host.
    order = cfg["images"].get("backend_order", [])
    errors = []
    for name in order:
        if name not in IMAGE_BACKENDS or not backend_available(cfg, name):
            continue
        try:
            return IMAGE_BACKENDS[name](cfg, path, public_id), name
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise ImageUploadError(t("p.upload_failed", errors=" | ".join(errors))
                           if errors else t("p.no_backend"))


def search_wikimedia(query: str, limit: int = 12) -> list[dict]:
    """Busca fotos reales en Wikimedia Commons. No necesita ninguna clave.

    Es la unica fuente que funciona nada mas instalar el programa: Pexels,
    Unsplash y Pixabay exigen registrarse. Las fotos son libres, pero hay que
    citar al autor, asi que el credito viaja en el resultado.
    """
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": limit,
        "gsrnamespace": 6, "prop": "imageinfo",
        "iiprop": "url|extmetadata|size", "iiurlwidth": 1600,
    })
    st, data, _ = http_json(f"https://commons.wikimedia.org/w/api.php?{params}", timeout=25)
    if st != 200 or not isinstance(data, dict):
        return []
    out = []
    for p in (data.get("query", {}).get("pages") or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url or ii.get("width", 0) < 800:
            continue
        meta = ii.get("extmetadata") or {}
        author = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:60]
        out.append({
            "url": url,
            "thumb": re.sub(r"/\d+px-", "/320px-", url) if "/thumb/" in url else url,
            "credit": author.strip() or "Wikimedia Commons",
            "license": (meta.get("LicenseShortName") or {}).get("value", ""),
            "source": "Wikimedia",
            "title": p.get("title", "").replace("File:", "")[:70],
        })
    return out


def search_stock_image(cfg: dict, query: str) -> list[dict]:
    """Busca una foto de portada en bancos gratuitos cuando no hay imagen propia."""
    keys = cfg["images"].get("stock", {})
    out: list[dict] = []
    q = urllib.parse.quote(query[:80])

    # Wikimedia primero: es la que funciona sin configurar nada.
    out.extend(search_wikimedia(query))

    if keys.get("pexels_key"):
        st, d, _ = http_json(
            f"https://api.pexels.com/v1/search?query={q}&per_page=8&orientation=landscape",
            headers={"Authorization": keys["pexels_key"]}, timeout=25)
        if st == 200 and isinstance(d, dict):
            for p in d.get("photos", []):
                out.append({"url": p["src"]["large2x"], "thumb": p["src"]["tiny"],
                            "credit": p.get("photographer", ""), "source": "Pexels"})
    if keys.get("unsplash_key"):
        st, d, _ = http_json(
            f"https://api.unsplash.com/search/photos?query={q}&per_page=8&orientation=landscape",
            headers={"Authorization": f"Client-ID {keys['unsplash_key']}"}, timeout=25)
        if st == 200 and isinstance(d, dict):
            for p in d.get("results", []):
                out.append({"url": p["urls"]["regular"], "thumb": p["urls"]["thumb"],
                            "credit": p["user"]["name"], "source": "Unsplash"})
    if keys.get("pixabay_key"):
        st, d, _ = http_json(
            f"https://pixabay.com/api/?key={keys['pixabay_key']}&q={q}"
            f"&image_type=photo&orientation=horizontal&per_page=8", timeout=25)
        if st == 200 and isinstance(d, dict):
            for p in d.get("hits", []):
                out.append({"url": p["largeImageURL"], "thumb": p["previewURL"],
                            "credit": p.get("user", ""), "source": "Pixabay"})
    return out


# ────────────────────────── CLIENTE DE LA API ──────────────────────────

class SiteClient:
    """Adaptador de API editorial basada en cookies. Multi-sitio via config.json."""

    def __init__(self, cfg: dict, site_key: str | None = None):
        self.cfg = cfg
        self.key = site_key or cfg.get("active_site")
        self.site = cfg["sites"].get(self.key) or active_site(cfg)
        self.api = self.site["api_base"].rstrip("/")
        self._cookie = ""
        cv = self.site.get("cookie_value")
        if cv:
            self._cookie = f"{self.site.get('cookie_name', 'session')}={cv}"

    # -- sesion --
    def login(self, username: str = "", password: str = "") -> tuple[bool, str]:
        if not self.api:
            return False, t("d.site_unconfigured")
        u = username or self.site.get("username", "")
        p = password or self.site.get("password", "")
        if not (u and p):
            return False, t("d.session_nocreds")
        st, data, headers = http_json(f"{self.api}/login/",
                                      data={"username": u, "password": p})
        if st != 200:
            msg = data.get("error") if isinstance(data, dict) else str(data)[:120]
            return False, t("d.session_rejected", code=st, msg=msg)
        raw = headers.get("Set-Cookie", "")
        m = re.search(r"([A-Za-z0-9_\-]+)=([^;]+)", raw)
        if m:
            self._cookie = f"{m.group(1)}={m.group(2)}"
            self.site["cookie_name"], self.site["cookie_value"] = m.group(1), m.group(2)
            save_config(self.cfg)
            return True, t("d.session_ok")
        return bool(self._cookie), t("d.session_nocookie")

    def ensure_session(self) -> tuple[bool, str]:
        if self._cookie:
            st, _, _ = http_json(f"{self.api}/articles/", cookie=self._cookie, timeout=20)
            if st == 200:
                return True, t("d.session_valid")
        return self.login()

    # -- articulos --
    def list_articles(self) -> list[dict]:
        """Lista los articulos. La API responde {"items": [...]}, no
        {"articles": [...]} — el codigo anterior leia la clave equivocada y
        por eso el listado siempre salia vacio."""
        st, data, _ = http_json(f"{self.api}/articles/", cookie=self._cookie)
        if st != 200 or not isinstance(data, dict):
            return []
        key = self.site.get("list_key", "items")
        items = data.get(key)
        if items is None:
            for alt in ("items", "articles", "data", "results"):
                if isinstance(data.get(alt), list):
                    items = data[alt]
                    break
        return items if isinstance(items, list) else []

    def create(self, art: Article) -> tuple[bool, str, dict]:
        st, data, _ = http_json(f"{self.api}/articles/", data=art.api_payload(),
                                cookie=self._cookie, timeout=90)
        if st in (200, 201):
            return True, t("p.published"), data if isinstance(data, dict) else {}
        msg = data.get("error") if isinstance(data, dict) else str(data)[:200]
        return False, t("p.error", code=st, msg=msg), {}

    def update(self, slug: str, art: Article) -> tuple[bool, str, dict]:
        st, data, _ = http_json(f"{self.api}/articles/{slug}/", data=art.api_payload(),
                                method="PUT", cookie=self._cookie, timeout=90)
        if st in (200, 201):
            return True, t("p.updated"), data if isinstance(data, dict) else {}
        msg = data.get("error") if isinstance(data, dict) else str(data)[:200]
        return False, t("p.error", code=st, msg=msg), {}

    def delete(self, slug: str) -> tuple[bool, str]:
        st, data, _ = http_json(f"{self.api}/articles/{slug}/", method="DELETE",
                                cookie=self._cookie)
        return (st in (200, 204)), (t("p.error", code=st, msg="") if st not in (200, 204) else t("p.deleted"))

    def slug_exists(self, slug: str) -> bool:
        return any(a.get("slug") == slug for a in self.list_articles())

    def unique_slug(self, slug: str) -> str:
        existing = {a.get("slug") for a in self.list_articles()}
        if slug not in existing:
            return slug
        for i in range(2, 60):
            cand = f"{slug}-{i}"
            if cand not in existing:
                return cand
        return f"{slug}-{uuid.uuid4().hex[:6]}"

    def related_slugs(self, art: Article, limit: int = 3) -> list[str]:
        """Sugiere articulos relacionados por continente/pais y palabras comunes."""
        arts = [a for a in self.list_articles() if a.get("slug") != art.slug]
        prof = tokens(f"{art.title} {art.primaryKeyword}")
        scored = []
        for a in arts:
            s = 0.0
            if a.get("country") and a["country"] == art.country:
                s += 2
            if a.get("continent") and a["continent"] == art.continent:
                s += 1
            if a.get("contentType") == art.contentType:
                s += 0.5
            s += len(prof & tokens(a.get("title", ""))) * 0.4
            scored.append((s, a.get("slug", "")))
        scored.sort(reverse=True)
        return [s for sc, s in scored if s and sc > 0][:limit]


# ────────────────────────── VALIDACION ──────────────────────────

def validate(art: Article) -> tuple[bool, list[str], list[str]]:
    """Devuelve (publicable, errores, avisos).

    Los errores impiden publicar; los avisos solo restan calidad SEO.
    """
    errors: list[str] = []
    warns: list[str] = []

    if len((art.title or "").strip()) < 10:
        errors.append(t("v.title_short"))
    if not art.slug:
        errors.append(t("v.slug_missing"))
    elif not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", art.slug):
        errors.append(t("v.slug_invalid", slug=art.slug))
    if word_count(art.body) < 100:
        errors.append(t("v.body_short", n=word_count(art.body)))
    if art.category and art.category not in CATEGORIES:
        errors.append(t("v.category_invalid", v=art.category))
    if art.contentType and art.contentType not in CONTENT_TYPES:
        errors.append(t("v.contenttype_invalid", v=art.contentType))
    if art.continent and art.continent not in CONTINENTS:
        errors.append(t("v.continent_invalid", v=art.continent))
    if art.searchIntent and art.searchIntent not in SEARCH_INTENTS:
        errors.append(t("v.intent_invalid", v=art.searchIntent))

    mt = art.metaTitle or ""
    if not mt:
        warns.append(t("w.no_metatitle"))
    elif len(mt) > 60:
        warns.append(t("w.metatitle_long", n=len(mt)))
    md = art.metaDescription or ""
    if not md:
        warns.append(t("w.no_metadesc"))
    elif len(md) > 160:
        warns.append(t("w.metadesc_long", n=len(md)))
    elif len(md) < 70:
        warns.append(t("w.metadesc_short", n=len(md)))
    # Tener la foto emparejada basta: la URL de portada aparece al publicar,
    # que es cuando se sube. Avisar antes seria confundir al que ya la ve puesta.
    if not art.coverImage and not art.image_file:
        warns.append(t("w.no_cover"))
    if not art.imageAlt and (art.coverImage or art.image_file):
        warns.append(t("w.no_alt"))
    if art.primaryKeyword and md and translit(art.primaryKeyword.split()[0]).lower() \
            not in translit(md).lower():
        warns.append(t("w.kw_not_in_desc"))
    if not art.faq:
        warns.append(t("w.no_faq"))
    if not art.country:
        warns.append(t("w.no_country"))

    if art.affiliateEnabled:
        if not art.affiliateUrl:
            errors.append(t("v.affiliate_no_url"))
        elif not re.match(r"^https?://", art.affiliateUrl):
            errors.append(t("v.affiliate_bad_url"))
        if not art.affiliateTitle:
            warns.append(t("w.affiliate_no_title"))
        if not art.affiliateButtonText:
            warns.append(t("w.affiliate_no_button"))
        if not art.sponsoredToggle:
            warns.append(t("w.affiliate_not_sponsored"))

    return (not errors), errors, warns


def seo_score(art: Article) -> int:
    """Nota 0-100 orientativa, con el mismo criterio que la auditoria del sitio."""
    score = 0
    if art.title and len(art.title) >= 10:
        score += 10
    if art.metaTitle and 30 <= len(art.metaTitle) <= 60:
        score += 15
    elif art.metaTitle:
        score += 7
    if art.metaDescription and 120 <= len(art.metaDescription) <= 160:
        score += 15
    elif art.metaDescription:
        score += 7
    if art.slug and re.match(r"^[a-z0-9-]+$", art.slug):
        score += 10
    if word_count(art.body) >= 800:
        score += 10
    elif word_count(art.body) >= 300:
        score += 5
    if art.coverImage:
        score += 10
    if art.imageAlt:
        score += 5
    if art.faq:
        score += 10
    if art.country and art.continent:
        score += 5
    if art.primaryKeyword:
        score += 5
    if art.excerpt:
        score += 5
    return min(100, score)


# ────────────────────────── MEMORIA ──────────────────────────

SCHEMA = {
    "publish_log": ("""CREATE TABLE publish_log (
        id INTEGER PRIMARY KEY, slug TEXT, site TEXT, status TEXT,
        message TEXT, url TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        ["id", "slug", "site", "status", "message", "url", "created_at"]),
    "corrections": ("""CREATE TABLE corrections (
        id INTEGER PRIMARY KEY, slug TEXT, field TEXT, old_value TEXT,
        new_value TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        ["id", "slug", "field", "old_value", "new_value", "created_at"]),
    "image_cache": ("""CREATE TABLE image_cache (
        file_hash TEXT PRIMARY KEY, url TEXT, backend TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        ["file_hash", "url", "backend", "created_at"]),
}


def init_db() -> None:
    """Crea las tablas y migra las de versiones anteriores.

    La version 1 guardaba el log con otras columnas (article_slug en vez de
    slug). CREATE TABLE IF NOT EXISTS no habria migrado nada y cada intento de
    publicar fallaria en una instalacion antigua, asi que la tabla obsoleta se
    aparta con un nombre de respaldo y se recrea.
    """
    _ensure_dirs()
    with sqlite3.connect(str(DB_PATH)) as c:
        for table, (ddl, want) in SCHEMA.items():
            rows = c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                             "AND name=?", (table,)).fetchall()
            if rows:
                have = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
                if all(col in have for col in want):
                    continue
                backup = f"{table}_v1_backup"
                c.execute(f"DROP TABLE IF EXISTS {backup}")
                c.execute(f"ALTER TABLE {table} RENAME TO {backup}")
            c.execute(ddl)


def log_publish(slug: str, site: str, status: str, message: str, url: str = "") -> None:
    with sqlite3.connect(str(DB_PATH)) as c:
        c.execute("INSERT INTO publish_log (slug, site, status, message, url) "
                  "VALUES (?,?,?,?,?)", (slug, site, status, message, url))


def get_publish_log(limit: int = 60) -> list[dict]:
    with sqlite3.connect(str(DB_PATH)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT * FROM publish_log ORDER BY id DESC LIMIT ?", (limit,))]


def save_correction(slug: str, field: str, old: str, new: str) -> None:
    """Guarda cada retoque manual. Es la base para afinar los prompts."""
    if (old or "") == (new or ""):
        return
    with sqlite3.connect(str(DB_PATH)) as c:
        c.execute("INSERT INTO corrections (slug, field, old_value, new_value) "
                  "VALUES (?,?,?,?)", (slug, field, str(old)[:2000], str(new)[:2000]))


def get_corrections(limit: int = 100) -> list[dict]:
    with sqlite3.connect(str(DB_PATH)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT * FROM corrections ORDER BY id DESC LIMIT ?", (limit,))]


def _file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def cached_image_url(path: str | Path) -> tuple[str, str] | None:
    """Evita volver a subir una imagen ya subida (mismo contenido)."""
    try:
        fh = _file_hash(path)
    except OSError:
        return None
    with sqlite3.connect(str(DB_PATH)) as c:
        r = c.execute("SELECT url, backend FROM image_cache WHERE file_hash=?",
                      (fh,)).fetchone()
        return (r[0], r[1]) if r else None


def cache_image_url(path: str | Path, url: str, backend: str) -> None:
    try:
        fh = _file_hash(path)
    except OSError:
        return
    with sqlite3.connect(str(DB_PATH)) as c:
        c.execute("INSERT OR REPLACE INTO image_cache (file_hash, url, backend) "
                  "VALUES (?,?,?)", (fh, url, backend))


def upload_image_cached(cfg: dict, path: str | Path,
                        public_id: str = "") -> tuple[str, str]:
    hit = cached_image_url(path)
    if hit:
        return hit[0], hit[1] + " (ya subida)"
    url, backend = upload_image(cfg, path, public_id)
    cache_image_url(path, url, backend)
    return url, backend


# ────────────────────────── DIAGNOSTICO ──────────────────────────

def doctor(cfg: dict) -> list[dict]:
    """Comprueba todo lo que hace falta para publicar y explica como arreglarlo."""
    out: list[dict] = []

    def add(name, ok, detail, fix=""):
        out.append({"check": name, "ok": bool(ok), "detail": detail, "fix": fix})

    add(t("d.python"), True, t("d.python_ok", v=sys.version.split()[0]))

    up, models = ollama_up(cfg) if cfg["ollama"].get("enabled") else (True, [])
    if not up:
        add(t("d.ai"), False, t("d.ai_down", url=cfg["ollama"]["url"]),
            t("d.ai_down_fix"))
    elif not cfg["ollama"].get("enabled"):
        add(t("d.ai"), True, t("d.ai_off", n=len(models)))
    else:
        want = cfg["ollama"]["model"]
        has = any(m.startswith(want.split(":")[0]) for m in models)
        if not has:
            add(t("d.ai"), False, t("d.ai_missing", model=want),
                t("d.ai_missing_fix", model=want))
        else:
            # Que el servidor conteste no significa que pueda atender: se mide
            # generando un token de verdad. Sin cache: el diagnostico debe
            # reflejar el estado de este momento, no el de hace un minuto.
            ready, why = ollama_ready(cfg, use_cache=False)
            add(t("d.ai"), ready, t("d.ai_status", model=want, why=why),
                "" if ready else t("d.ai_busy_fix"))

    site = active_site(cfg)
    st, _, _ = http_json(site["url"], timeout=15)
    add(t("d.site"), st == 200, t("d.site_ok", url=site["url"], code=st))

    cli = SiteClient(cfg)
    ok, msg = cli.ensure_session()
    add(t("d.session"), ok, msg, "" if ok else t("d.session_fix"))
    if ok:
        arts = cli.list_articles()
        add(t("d.api"), True, t("d.api_ok", n=len(arts)))

    order = cfg["images"].get("backend_order", [])
    ready = [b for b in order if backend_available(cfg, b)]
    first = ready[0] if ready else None
    add(t("d.images"), bool(ready),
        t("d.images_use", backend=first) if first else t("d.images_none"),
        "" if first and first.startswith("cloudinary") else t("d.images_fix"))

    if str(site.get("cookie_value", "")).lower().startswith(("change-me", "changeme")):
        add(t("d.security"), False, t("d.security_bad"),
            t("d.security_fix", site=site.get("name") or site["url"]))
    return out
