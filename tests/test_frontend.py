import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from starlette.testclient import TestClient
from nse.service import create_app


class FrontendTests(unittest.TestCase):
    def test_built_ui_assets_and_api_coexist_without_exposing_repo_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'assets').mkdir()
            (root / 'index.html').write_text('<!doctype html><title>NSE test</title>', encoding='utf-8')
            (root / 'assets' / 'app.js').write_text('console.log("test")', encoding='utf-8')
            (root / 'favicon.svg').write_text('<svg/>', encoding='utf-8')
            with TestClient(create_app(pipeline_factory=Mock, answer_factory=Mock, frontend_dir=root)) as client:
                response = client.get('/')
                self.assertEqual(response.status_code, 200)
                self.assertIn('NSE test', response.text)
                self.assertIn('text/html', response.headers['content-type'])
                self.assertEqual(client.get('/assets/app.js').status_code, 200)
                self.assertEqual(client.get('/favicon.svg').status_code, 200)
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertEqual(client.get('/.env').status_code, 404)
                self.assertEqual(client.get('/nse/answers.py').status_code, 404)

    def test_unbuilt_ui_explains_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(pipeline_factory=Mock, answer_factory=Mock, frontend_dir=folder)) as client:
                self.assertIn('Build the frontend', client.get('/').json()['message'])


if __name__ == '__main__':
    unittest.main()
