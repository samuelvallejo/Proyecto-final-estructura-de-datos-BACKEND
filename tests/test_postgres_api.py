"""Pruebas en un esquema temporal de PostgreSQL real, nunca en SQLite."""
import os
import uuid
import io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.exc import IntegrityError
from app.config import Settings
from app.main import create_app
from app import schema as s
from app.contracts import Analysis
from app.repository import Repository, distance

URL = os.environ.get('TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='Configura TEST_DATABASE_URL para pruebas PostgreSQL reales')
FIXTURE = Path(__file__).parents[2] / 'backend/tests/fixtures/pothole.jpg'


@pytest.fixture
def client(monkeypatch):
    import psycopg
    from alembic.config import Config
    from alembic import command
    from sqlalchemy.engine import make_url
    schema_name = 'test_' + uuid.uuid4().hex
    db_url = make_url(URL)
    admin = create_engine(db_url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema_name}'))
    scoped = db_url.update_query_dict({'options': '-csearch_path=' + schema_name})
    monkeypatch.setenv('DATABASE_URL', scoped.render_as_string(hide_password=False))
    command.upgrade(Config('alembic.ini'), 'head')
    settings = Settings(_env_file=None, database_url=str(scoped), ai_provider='local', scan_interval_seconds=0,
                        local_scan_interval_seconds=0,
                        nominatim_user_agent='', gemini_api_key='', max_scans_per_hour=100)
    # str(URL) oculta contraseñas; render explícito necesario si el servidor usa password.
    settings.database_url = scoped.render_as_string(hide_password=False)
    app = create_app(settings)
    try:
        with TestClient(app) as test:
            test.app = app
            yield test
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema_name} CASCADE'))
        admin.dispose()


def token(client):
    session = client.post('/api/sessions')
    assert session.status_code == 201, session.text
    return {'Authorization': 'Bearer ' + session.json()['token']}


def scan(client, headers, coords=None, data=None):
    return client.post('/api/scan', headers=headers, data=coords or {},
                       files={'frame': ('frame.jpg', data or FIXTURE.read_bytes(), 'image/jpeg')})


def test_migration_scan_persistence_deduplication_and_geography(client):
    assert client.get('/api/health').json()['tables'] == 43
    headers = token(client)
    async def geocode(position):
        return {'cacheKey': f'{position.lat:.4f},{position.lng:.4f}', 'source': 'nominatim',
                'street': 'Calle de prueba', 'neighborhood': 'Centro', 'city': 'Bogotá',
                'region': 'Bogotá DC', 'countryCode': 'co', 'country': 'Colombia', 'fullAddress': 'Calle de prueba, Centro, Bogotá'}
    client.app.state.geocoder.resolve = geocode
    coords = {'lat': '4.65', 'lng': '-74.08', 'accuracy': '10'}
    first = scan(client, headers, coords)
    assert first.status_code == 200, first.text
    report = first.json()['report']
    assert report['zone']['city'] == 'Bogotá' and report['hazardLevel'] in ('HIGH', 'CRITICAL')
    assert first.json()['result']['boundingBox']
    assert report['status'] == 'UNVERIFIED'
    second = scan(client, headers, coords)
    assert second.json()['existing'] is True and second.json()['report']['id'] == report['id']
    assert client.get('/api/reports').json()['total'] == 1
    assert len(client.get('/api/reports/nearby?lat=4.65&lng=-74.08&radiusKm=1').json()['reports']) == 1
    assert not client.get('/api/reports/nearby?lat=0&lng=0&radiusKm=1').json()['reports']
    assert client.get('/api/reports/priority').json()['reports'][0]['id'] == report['id']
    engine = client.app.state.engine
    with engine.connect() as conn:
        for relation in [s.countries, s.regions, s.cities, s.neighborhoods, s.roads, s.zones, s.reports,
                         s.potholes, s.risk_assessments, s.audit_events, s.status_events]:
            assert conn.execute(select(func.count()).select_from(relation)).scalar_one() == 1
        assert conn.execute(select(func.count()).select_from(s.analyses)).scalar_one() == 2
    # Nueva instancia del repositorio: reportes independientes de las estructuras en memoria.
    assert Repository(engine, client.app.state.repo.settings).get_report(report['id']) == report
    stats = client.get('/api/data-structures/stats').json()
    assert stats['singlyLinkedList']['size'] == 2
    assert len(client.get('/api/scans/history', headers=headers).json()['events']) == 2


def test_invalid_or_missing_gps_never_maps_pothole(client):
    headers = token(client)
    for position in ({}, {'lat': '', 'lng': '', 'accuracy': ''}, {'lat': 'nan', 'lng': '0', 'accuracy': '0'},
                     {'lat': '4.65', 'lng': '-74.08', 'accuracy': '101'}):
        response = scan(client, headers, position)
        assert response.status_code == 200, response.text
        assert response.json()['result']['isPothole']
        assert response.json()['report'] is None and response.json()['locationNote']
    assert client.get('/api/reports').json()['total'] == 0


def test_auth_image_limits_cors_and_no_damage(client):
    assert scan(client, {}).status_code == 401
    assert scan(client, {'Authorization': 'Bearer invalid'}).status_code == 401
    headers = token(client)
    assert scan(client, headers, data=b'invalid jpeg').status_code == 400
    assert scan(client, headers, data=b'x' * 950000).status_code == 413
    buffer = io.BytesIO()
    Image.new('RGB', (640, 480), '#888888').save(buffer, 'JPEG')
    response = scan(client, headers, {'lat': '0', 'lng': '0', 'accuracy': '5'}, buffer.getvalue())
    assert response.status_code == 200 and not response.json()['result']['isPothole']
    assert response.json()['report'] is None
    options = client.options('/api/scan', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization'})
    assert options.status_code == 200
    assert 'access-control-allow-origin' not in client.get('/api/health', headers={'Origin': 'https://unknown.example'}).headers


def test_rate_limit_and_concurrent_registration(client):
    client.app.state.repo.settings.local_scan_interval_seconds = 60
    headers = token(client)
    assert scan(client, headers).status_code == 200
    assert scan(client, headers).status_code == 429
    client.app.state.repo.settings.local_scan_interval_seconds = 0
    with ThreadPoolExecutor(2) as executor:
        responses = list(executor.map(lambda _: scan(client, headers, {'lat': '4.65', 'lng': '-74.08', 'accuracy': '5'}), range(2)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    assert sum(not response.json()['existing'] for response in responses) == 1
    assert client.get('/api/reports').json()['total'] == 1


def test_priority_pagination_and_bidirectional_patrol(client):
    headers = token(client)
    scores = iter([25, 90, 65])
    async def fake_ai(data, image):
        result = Analysis(isPothole=True, potholeType='BACHE', hazardScore=next(scores),
                          aiDescription='Daño visible', riskFactors=['Bordes irregulares'])
        return result, 'gemini', 'test-model', False
    client.app.state.ai.analyze = fake_ai
    for lat in [4.65, 4.66, 4.67]:
        assert scan(client, headers, {'lat': str(lat), 'lng': '-74.08', 'accuracy': '5'}).status_code == 200
    page = client.get('/api/reports/priority?limit=2').json()
    assert [item['hazardScore'] for item in page['reports']] == [90, 65]
    assert page['total'] == 3 and page['hasMore']
    assert client.get('/api/reports/priority?limit=2&offset=2').json()['reports'][0]['hazardScore'] == 25
    current = client.get('/api/reports/patrol').json()['report']
    assert current['hazardScore'] == 90
    previous = client.get('/api/reports/patrol', params={'current': current['id'], 'direction': 'previous'}).json()['report']
    assert previous['hazardScore'] == 25
    following = client.get('/api/reports/patrol', params={'current': previous['id'], 'direction': 'next'}).json()['report']
    assert following['id'] == current['id']


def test_database_constraints_and_geodesic_edges(client):
    assert distance({'lat': 0, 'lng': 179.99999}, {'lat': 0, 'lng': -179.99999}) < 3
    with pytest.raises(IntegrityError):
        with client.app.state.engine.begin() as conn:
            conn.execute(s.potholes.insert().values(lat=95, lng=0, kind='BACHE', status='UNVERIFIED'))
    with pytest.raises(IntegrityError):
        with client.app.state.engine.begin() as conn:
            conn.execute(s.reports.insert().values(pothole_id=s.uid(), session_id=s.uid(), accuracy=1, description='FK inexistente'))


def test_import_preserves_id_timestamp_address_and_is_idempotent(client, tmp_path):
    import sqlite3
    import json
    from scripts.import_sqlite import import_records
    report_id = s.uid()
    original = {
        'id': report_id, 'timestamp': 1700000000000, 'isPothole': True, 'potholeType': 'BACHE',
        'hazardScore': 62, 'aiDescription': 'Reporte histórico', 'riskFactors': ['Bordes rotos'],
        'location': {'lat': 4.65, 'lng': -74.08, 'accuracy': 10},
        'zone': {'street': 'Vía original', 'city': 'Ciudad original', 'neighborhood': 'Barrio original', 'fullAddress': None},
    }
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE reports (created_at INTEGER, data TEXT)')
        conn.execute('INSERT INTO reports VALUES (?, ?)', (original['timestamp'], json.dumps(original)))
    assert import_records(client.app.state.engine, source) == 1
    assert import_records(client.app.state.engine, source) == 0
    report = client.get('/api/reports').json()['reports'][0]
    assert report['id'] == report_id and report['timestamp'] == original['timestamp']
    assert report['zone']['city'] == original['zone']['city']
    assert report['zone']['street'] == original['zone']['street']
    with sqlite3.connect(source) as conn:
        assert json.loads(conn.execute('SELECT data FROM reports').fetchone()[0]) == original
