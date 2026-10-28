"""Tests de la lógica que no depende de la red. Ejecutar: python3 test_logica.py

Verifica el manejo de las respuestas de la IA sin depender de Ollama:
JSON envuelto en <think>, vallas de código, campos basura y modelo caído."""
import sys
import os
import tempfile
_test_home = tempfile.TemporaryDirectory(prefix="publisher-test-")
os.environ["PUBLISHER_HOME"] = _test_home.name
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
from core import _json_from_text, ai_metadata, Article, load_config, process_article

cfg = load_config()
ok = fail = 0


def check(name, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1; print(f'  ok   {name}')
    else:
        fail += 1; print(f'  FALLA {name} {extra}')


print('=== _json_from_text: formas reales que devuelven los modelos pequeños')
cases = [
    ('limpio', '{"metaTitle":"Sicilija"}', 'Sicilija'),
    ('con think', '<think>Hmm, dejame pensar...</think>\n{"metaTitle":"Sicilija"}', 'Sicilija'),
    ('valla de codigo', '```json\n{"metaTitle":"Sicilija"}\n```', 'Sicilija'),
    ('texto alrededor', 'Aqui tienes:\n{"metaTitle":"Sicilija"}\nEspero que sirva', 'Sicilija'),
    ('llaves anidadas', '{"a":{"b":1},"metaTitle":"Sicilija"}', 'Sicilija'),
    ('llave en string', '{"metaTitle":"Sicilija {10 dni}"}', 'Sicilija {10 dni}'),
    ('comilla escapada', r'{"metaTitle":"Sicilija \"top\""}', 'Sicilija "top"'),
]
for name, raw, want in cases:
    got = _json_from_text(raw).get('metaTitle')
    check(name, got == want, f'-> {got!r}')
check('basura devuelve {}', _json_from_text('no hay json aqui') == {})
check('vacio devuelve {}', _json_from_text('') == {})
check('json roto devuelve {}', _json_from_text('{"a": ') == {})

print('\n=== ai_metadata: filtra lo que el modelo devuelve mal')
art = Article(title='Sicilija v 10 dneh', body='x ' * 500)

def fake(resp):
    core.ollama_generate = lambda *a, **k: resp

fake('{"metaTitle":"Sicilija v 10 dneh: kam iti, najem avta","metaDescription":"Nacrt za 10 dni na Siciliji. Kje najeti avto, katere avtoceste so brezplacne in koliko stane parkiranje v mestih.","primaryKeyword":"sicilija 10 dni","searchIntent":"informational","quickFacts":[{"label":"Etna je najvisji aktivni vulkan v Evropi"},{"label":"Sicilija ima pet Unescovih spomenikov"},{"label":"ZTL cone nadzorujejo kamere"}]}')
out = ai_metadata(cfg, art)
check('acepta metaTitle bueno', out.get('metaTitle', '').startswith('Sicilija'))
check('acepta quickFacts (3)', len(out.get('quickFacts', [])) == 3)
check('acepta searchIntent', out.get('searchIntent') == 'informational')

fake('{"metaTitle":"x","metaDescription":"corta","searchIntent":"inventado","quickFacts":[{"label":"ab"}]}')
out = ai_metadata(cfg, art)
check('rechaza metaTitle de 1 char', 'metaTitle' not in out)
check('rechaza description corta', 'metaDescription' not in out)
check('rechaza searchIntent invalido', 'searchIntent' not in out)
check('rechaza quickFacts basura', 'quickFacts' not in out)

fake('el modelo se fue por las ramas y no devolvio json')
check('respuesta sin json -> {}', ai_metadata(cfg, art) == {})

print('\n=== process_article: la IA nunca pisa lo que escribio el redactor')
core.ollama_ready = lambda *a, **k: (True, 'ok')
fake('{"metaTitle":"TITULO DE LA IA","metaDescription":"Descripcion inventada por la IA que es suficientemente larga para pasar la validacion de longitud minima."}')
a = Article(title='Sicilija v 10 dneh: kam iti', body='palabra ' * 400,
            metaTitle='Meta del redactor',
            metaDescription='Description escrita a mano por el redactor en el documento word.',
            # como lo deja parse_docx cuando el .docx trae el bloque de cabecera
            authored_fields=['metaTitle', 'metaDescription'])
cfg['ollama']['enabled'] = True
a = process_article(cfg, a, use_ai=True)
check('respeta metaTitle del docx', a.metaTitle == 'Meta del redactor', f'-> {a.metaTitle!r}')
check('respeta metaDescription del docx', a.metaDescription.startswith('Description escrita'))

b = Article(title='Sicilija v 10 dneh: kam iti', body='palabra ' * 400)
b = process_article(cfg, b, use_ai=True)
check('rellena metaTitle si falta', b.metaTitle == 'TITULO DE LA IA', f'-> {b.metaTitle!r}')

print('\n=== IA caida: el articulo sigue siendo publicable')
core.ollama_ready = lambda *a, **k: (False, 'no respondió en 20s')
c = Article(title='Sicilija v 10 dneh: kam iti, najem avta',
            body='palabra ' * 400, metaTitle='Meta del redactor',
            metaDescription='Description del documento, bastante larga para valer.',
            coverImage='https://ejemplo.test/foto.jpg')
c = process_article(cfg, c, use_ai=True)
from core import validate
okc, errs, warns = validate(c)
check('publicable sin IA', okc, f'-> {errs}')
check('avisa de que la IA no estaba', any('IA local' in n for n in c.notes), f'-> {c.notes}')
check('alt-text de reserva con foto', bool(c.imageAlt), f'-> {c.imageAlt!r}')

# Sin foto no hay nada que describir: el alt debe quedarse vacío.
d = Article(title='Guia sin foto', body='palabra ' * 400, metaTitle='Meta')
d = process_article(cfg, d, use_ai=False)
check('sin foto no inventa alt', d.imageAlt == '', f'-> {d.imageAlt!r}')

print(f'\n{ok} ok, {fail} fallos')
sys.exit(1 if fail else 0)
