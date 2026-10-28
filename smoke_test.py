"""Synthetic local regression tests. No real backend, image host or AI is used."""
from __future__ import annotations
import contextlib
import copy
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

TEST_HOME = tempfile.TemporaryDirectory(prefix='publisher-public-test-')
os.environ['PUBLISHER_HOME'] = TEST_HOME.name

import core
import app
from examples.generate_demo import generate


class PublicEditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.set_lang('en')
        cls.docx, cls.photo = generate(Path(TEST_HOME.name) / 'fixtures')

    def config(self):
        return copy.deepcopy(core.DEFAULT_CONFIG)

    def article(self):
        return core.heuristic_metadata(core.parse_docx(self.docx))

    def test_factory_configuration_is_unconnected(self):
        cfg = self.config()
        for site in cfg['sites'].values():
            for key in ('url', 'api_base', 'username', 'password', 'cookie_value'):
                self.assertEqual(site[key], '')
        for key in ('cloud_name', 'api_key', 'api_secret', 'upload_preset'):
            self.assertEqual(cfg['images']['cloudinary'][key], '')
        self.assertEqual(cfg['images']['backend_order'], [])
        self.assertFalse(cfg['ollama']['enabled'])
        self.assertFalse(cfg['translate']['enabled'])
        self.assertEqual(cfg['publish']['default_status'], 'draft')

    def test_private_storage_is_isolated(self):
        self.assertEqual(core.APP_NAME, 'client_content_publisher')
        self.assertEqual(core.DATA_DIR, Path(TEST_HOME.name))
        core.save_config(self.config())
        if os.name != 'nt':
            self.assertEqual(core.CONFIG_FILE.stat().st_mode & 0o777, 0o600)

    def test_default_site_cannot_connect(self):
        client = core.SiteClient(self.config())
        self.assertFalse(client.ensure_session()[0])
        self.assertEqual(client.list_articles(), [])
        self.assertFalse(client.create(self.article())[0])
        self.assertFalse(client.delete('synthetic')[0])

    def test_no_implicit_image_host(self):
        with mock.patch.object(core, 'http_multipart') as upload:
            with self.assertRaises(core.ImageUploadError):
                core.upload_image(self.config(), self.photo)
            upload.assert_not_called()

    def test_explicit_host_has_no_fallback(self):
        cfg = self.config()
        cfg['images']['backend_order'] = ['cloudinary_signed']
        cfg['images']['cloudinary'].update(cloud_name='synthetic', api_key='synthetic', api_secret='synthetic')
        catbox = mock.Mock()
        with mock.patch.dict(core.IMAGE_BACKENDS, {'cloudinary_signed': mock.Mock(side_effect=RuntimeError('test failure')), 'catbox': catbox}):
            with self.assertRaises(core.ImageUploadError):
                core.upload_image(cfg, self.photo)
            catbox.assert_not_called()

    def test_docx_preserves_authored_metadata(self):
        article = core.parse_docx(self.docx)
        self.assertEqual(article.slug, 'demo-lake-trip')
        self.assertEqual(article.metaTitle, 'Lake Example: a fictional weekend guide')
        self.assertIn('metaDescription', article.authored_fields)
        self.assertIn('## A relaxed two-day itinerary', article.body)
        self.assertGreater(article.word_count, 100)

    def test_faq_and_quick_facts_are_extracted_once(self):
        article = self.article()
        self.assertEqual(len(article.faq), 2)
        self.assertEqual(len(article.quickFacts), 2)
        self.assertNotIn('## FAQ', article.body)
        self.assertNotIn('## Quick facts', article.body)
        self.assertTrue(core.validate(article)[0])

    def test_photo_pairing_and_local_export(self):
        article = core.match_pairs([self.article()], [self.photo])[0]
        self.assertEqual(Path(article.image_file), self.photo)
        html = app.article_html(article)
        self.assertIn('data:image/png;base64,', html)
        self.assertNotIn('fonts.googleapis.com', html)

    def test_slug_transliteration(self):
        self.assertEqual(core.slugify('Najcenejše poti ČŠŽ'), 'najcenejse-poti-csz')

    def test_payload_excludes_local_paths_and_keeps_false(self):
        article = self.article()
        article.image_file = '/private/synthetic.png'
        payload = article.api_payload()
        for key in core.Article.LOCAL_FIELDS:
            self.assertNotIn(key, payload)
        self.assertIs(payload['featured'], False)
        self.assertIs(payload['affiliateEnabled'], False)

    def test_translations_have_matching_keys(self):
        translations = core.load_i18n()
        keys = set(translations['en'])
        for language in core.UI_LANGS:
            self.assertEqual(set(translations[language]), keys)
            self.assertIn('Client Content Publisher', translations[language]['app.title'])

    def test_html_metadata_is_escaped(self):
        article = self.article()
        article.title = '<script>alert(1)</script>'
        article.imageAlt = '" onerror="alert(1)'
        article.coverImage = 'javascript:alert(1)'
        article.faq = [{'q': '<script>bad</script>', 'a': '<img onerror=bad>'}]
        html = app.article_html(article)
        self.assertNotIn('<script>', html)
        self.assertNotIn('src="javascript:', html)
        self.assertIn('&lt;script&gt;', html)

    def test_markdown_rejects_executable_links(self):
        self.assertNotIn('href="javascript:', app.md_to_html('[unsafe](javascript:alert(1))'))
        self.assertIn('href="https://example.invalid"', app.md_to_html('[safe](https://example.invalid)'))

    def test_site_adapter_contract_is_mocked(self):
        cfg = self.config()
        cfg['sites']['example'].update(url='https://example.invalid', api_base='https://example.invalid/api/admin', username='synthetic', password='synthetic')
        client = core.SiteClient(cfg)
        calls = []
        def response(url, data=None, method=None, **kwargs):
            calls.append((url, data, method))
            if url.endswith('/login/'):
                return 200, {}, {'Set-Cookie': 'publisher_session=synthetic; HttpOnly'}
            if method == 'DELETE':
                return 204, {}, {}
            if data is not None:
                return 201, {'slug': data['slug']}, {}
            return 200, {'items': [{'slug': 'already-used'}]}, {}
        with mock.patch.object(core, 'http_json', side_effect=response):
            self.assertTrue(client.login()[0])
            self.assertEqual(client.list_articles()[0]['slug'], 'already-used')
            self.assertEqual(client.unique_slug('already-used'), 'already-used-2')
            self.assertTrue(client.create(self.article())[0])
            self.assertTrue(client.update('demo-lake-trip', self.article())[0])
            self.assertTrue(client.delete('demo-lake-trip')[0])
        self.assertTrue(any(method == 'PUT' for _, _, method in calls))
        core.save_config(self.config())

    def test_cli_draft_path_has_no_undefined_variable(self):
        core.save_config(self.config())
        client = mock.Mock()
        client.ensure_session.return_value = (True, 'synthetic')
        client.unique_slug.return_value = 'demo-lake-trip-2'
        client.create.return_value = (True, 'Synthetic draft', {})
        with mock.patch.object(app, 'SiteClient', return_value=client), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.cli_publish([str(self.docx)], 'draft', False), 0)
        article = client.create.call_args.args[0]
        self.assertEqual(article.slug, 'demo-lake-trip-2')
        self.assertEqual(article.status, 'draft')


class LocalHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.save_config(copy.deepcopy(core.DEFAULT_CONFIG))
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        request_headers = {'Content-Type': 'application/json'} if body is not None else {}
        request_headers.update(headers or {})
        connection.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, request_headers)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_ui_and_bootstrap_work_without_services(self):
        status, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'Client Content Publisher', body)
        status, body = self.request('/api/bootstrap')
        self.assertEqual(status, 200)
        cfg = json.loads(body)['config']
        self.assertEqual(cfg['images']['backend_order'], [])
        self.assertEqual(cfg['sites']['example']['api_base'], '')

    def test_http_document_import(self):
        import base64
        docx, photo = generate(Path(TEST_HOME.name) / 'http-fixtures')
        files = [{'name': p.name, 'b64': base64.b64encode(p.read_bytes()).decode()} for p in (docx, photo)]
        status, body = self.request('/api/upload', {'files': files})
        self.assertEqual(status, 200)
        articles = json.loads(body)['articles']
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]['slug'], 'demo-lake-trip')
        self.assertTrue(articles[0]['thumb_url'].startswith('/api/thumb?'))

    def test_cross_origin_config_access_is_rejected(self):
        self.assertEqual(self.request('/api/bootstrap', headers={'Origin': 'https://example.invalid'})[0], 403)
        self.assertEqual(self.request('/api/config', {'config': {}}, {'Origin': 'https://example.invalid'})[0], 403)

    def test_foreign_host_is_rejected(self):
        self.assertEqual(self.request('/api/bootstrap', headers={'Host': 'example.invalid'})[0], 403)

    def test_post_requires_json(self):
        self.assertEqual(self.request('/api/preview', {'article': {}}, {'Content-Type': 'text/plain'})[0], 415)


if __name__ == '__main__':
    # Service clients use urlopen; local HTTP checks use http.client directly.
    with mock.patch('urllib.request.urlopen', side_effect=AssertionError('External HTTP is disabled in this test suite')) as external:
        suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if external.call_count:
            raise SystemExit(f'Unexpected outbound HTTP attempts: {external.call_count}')
    TEST_HOME.cleanup()
    raise SystemExit(0 if result.wasSuccessful() else 1)
