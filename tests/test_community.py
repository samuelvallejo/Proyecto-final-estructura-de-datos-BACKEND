from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, update
from app import schema as s
from app.repository import Repository
from test_postgres_api import client, token


def payload(lat=3.45, lng=-76.53, **changes):
    return {'position': {'lat': lat, 'lng': lng, 'accuracy': 8}, 'capturedAt': s.now(),
            'risk': 'HIGH', 'description': 'Hueco peligroso junto al cruce del carril derecho.', **changes}


def test_shared_report_persistence_identity_and_source(client):
    assert client.post('/api/community/reports', json=payload()).status_code == 401
    token(client)
    response = client.post('/api/community/reports', json=payload())
    assert response.status_code == 201, response.text
    saved = response.json()['report']
    assert saved['source'] == 'COMMUNITY' and saved['hazardLevel'] == 'HIGH'
    assert saved['location'] == {'lat': 3.45, 'lng': -76.53, 'accuracy': 8}
    assert saved['status'] == 'UNVERIFIED' and saved.get('boundingBox') is None
    assert not {'user_id', 'session_id', 'email', 'password_hash', 'token_hash'} & saved.keys()
    assert Repository(client.app.state.engine, client.app.state.settings).get_report(saved['id']) == saved
    token(client)  # Independent account sees the original user's notice.
    assert client.get('/api/reports').json()['reports'] == [saved]
    nearby = client.get('/api/reports/nearby?lat=3.4505&lng=-76.53&radiusKm=.2').json()
    assert nearby['reports'] == [saved]
    assert client.get('/api/reports/priority').json()['reports'] == [saved]
    assert client.get('/api/reports/patrol').json()['report'] == saved
    with client.app.state.engine.connect() as conn:
        assert conn.execute(select(s.reports.c.detection_id)).scalar_one() is None
        assert conn.execute(select(s.risk_assessments.c.method)).scalar_one() == 'community'


def test_community_validation_csrf_and_precision(client):
    token(client)
    assert client.post('/api/community/reports', json=payload(), headers={'Origin': 'https://evil.invalid'}).status_code == 403
    for changes in [dict(description='x'), dict(description='sensitive-value' * 100),
                    dict(risk='INVALID'), dict(position={'lat': 3.4, 'lng': -76.5, 'accuracy': 101}),
                    dict(position={'lat': 91, 'lng': 1, 'accuracy': 10}), dict(internal='sensitive-value')]:
        response = client.post('/api/community/reports', json=payload(**changes))
        assert response.status_code == 422 and 'sensitive-value' not in response.text
    for timestamp in [s.now() - 31000, s.now() + 10000]:
        assert client.post('/api/community/reports', json=payload(capturedAt=timestamp)).status_code == 400
    assert client.post('/api/community/reports', content='x' * 9000,
                       headers={'Content-Type': 'application/json'}).status_code == 413
    assert client.get('/api/reports').json()['total'] == 0


def test_duplicates_concurrent_requests_and_account_rate_limit(client):
    token(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/api/community/reports', json=payload()).json(), range(2)))
    assert len({result['report']['id'] for result in results}) == 1
    assert sorted(result['existing'] for result in results) == [False, True]
    for number in range(1, 10):
        assert client.post('/api/community/reports', json=payload(lat=3.45 + number * .001)).status_code == 201
    # Signing in again must not reset the per-user publication limit.
    assert client.post('/api/community/reports', json=payload(lat=3.48)).status_code == 429


def test_nearby_order_pagination_repaired_and_antimeridian(client):
    token(client)
    first = client.post('/api/community/reports', json=payload(lat=0, lng=179.9998)).json()['report']
    client.post('/api/community/reports', json=payload(lat=.01, lng=-179.9998))
    query = '/api/reports/nearby?lat=0&lng=-179.9998&radiusKm=5&limit=1'
    page = client.get(query).json()
    assert page['reports'][0]['id'] == first['id'] and page['total'] == 2 and page['hasMore']
    assert client.get(query + '&offset=1').json()['reports'][0]['id'] != first['id']
    with client.app.state.engine.begin() as conn:
        pothole = conn.execute(select(s.reports.c.pothole_id).where(s.reports.c.id == first['id'])).scalar_one()
        conn.execute(update(s.potholes).where(s.potholes.c.id == pothole).values(status='REPAIRED'))
    assert client.get(query).json()['total'] == 1
    assert client.get('/api/reports').json()['total'] == 1
