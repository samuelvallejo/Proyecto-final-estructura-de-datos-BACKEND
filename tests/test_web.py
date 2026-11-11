import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.web import mount_frontend


def test_frontend_and_api_share_origin_without_intercepting_api(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>BacheScan AI</h1>')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'bundle.js').write_text('/* public compiled bundle */')
    (tmp_path / 'sw.js').write_text('/* worker */')
    app = FastAPI()
    @app.get('/api/health')
    def health(): return {'status': 'ok'}
    mount_frontend(app, str(tmp_path))
    with TestClient(app) as client:
        root = client.get('/')
        assert root.status_code == 200 and 'BacheScan AI' in root.text
        assert root.headers['cache-control'] == 'no-cache'
        assert 'geolocation=(self)' in root.headers['permissions-policy']
        assert root.headers['x-frame-options'] == 'DENY'
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/api/missing').status_code == 404
        assert client.get('/api/missing').headers['content-type'].startswith('application/json')
        assert client.get('/assets/bundle.js').headers['cache-control'].endswith('immutable')
        assert client.get('/sw.js').headers['cache-control'] == 'no-cache'
        assert client.get('/assets/missing.js').status_code == 404
        assert client.get('/../.env').status_code == 404


def test_frontend_mount_requires_compiled_entry_and_is_disabled_by_default(tmp_path):
    app = FastAPI()
    mount_frontend(app, '')
    with TestClient(app) as client: assert client.get('/').status_code == 404
    with pytest.raises(RuntimeError): mount_frontend(FastAPI(), str(tmp_path))
