"""Operator workspace on real PostgreSQL: role matrix, queue, day plan and workflow."""
import pytest
from sqlalchemy import select
from app import schema as s
from app.config import Settings
from app.pothole_detector import PotholeDetector
from test_postgres_api import client  # noqa: F401  (PostgreSQL fixture)
from test_admin_profile import demo, login, register

OPERATOR_ROUTES = ['/api/operator/queue', '/api/operator/plan']


@pytest.fixture
def custom_detector():
    # These endpoints never run inference; an unavailable model keeps the tests light.
    return PotholeDetector(Settings(_env_file=None, pothole_model_path='models/not-present.pt'))


def publish(client, lat, lng, risk='HIGH'):
    async def geocode(position):
        return {'cacheKey': f'{position.lat:.5f},{position.lng:.5f}', 'source': 'nominatim', 'street': 'Calle 18',
                'neighborhood': 'Centro', 'city': 'Pasto', 'region': 'Nariño', 'countryCode': 'co',
                'country': 'Colombia', 'fullAddress': 'Calle 18, Centro, Pasto'}
    client.app.state.geocoder.resolve = geocode
    response = client.post('/api/community/reports', json={
        'position': {'lat': lat, 'lng': lng, 'accuracy': 6}, 'capturedAt': s.Clock.now(), 'risk': risk,
        'description': 'Hueco profundo en el carril derecho'})
    assert response.status_code == 201, response.text
    return response.json()['report']


def test_role_matrix_for_operator_routes(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    for route in OPERATOR_ROUTES:
        assert client.get(route).status_code == 403
    for role in ('Operario', 'Administrador'):
        login(client, accounts[role]['email'], accounts[role]['password'])
        for route in OPERATOR_ROUTES:
            assert client.get(route).status_code == 200, (role, route)
    client.cookies.clear()
    assert client.get('/api/operator/queue').status_code == 401


def test_queue_orders_by_priority_and_explains_the_score(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    medium = publish(client, 1.2100, -77.2900, 'MEDIUM')
    critical = publish(client, 1.2200, -77.2800, 'CRITICAL')
    high = publish(client, 1.2300, -77.2700, 'HIGH')
    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    data = client.get('/api/operator/queue?limit=2').json()
    assert data['total'] == 3 and [item['rank'] for item in data['items']] == [1, 2]
    assert [item['report']['id'] for item in data['items']] == [critical['id'], high['id']]
    first = data['items'][0]
    assert first['priority']['score'] == round(sum(first['priority']['components'].values()), 2)
    assert first['allowedTransitions'] == ['CONFIRMED', 'REJECTED']
    assert data['structure']['name'] == 'indexed-binary-max-heap' and data['structure']['size'] == 3
    assert medium['id'] not in [item['report']['id'] for item in data['items']]


def test_day_plan_visits_every_selected_stop(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    ids = {publish(client, 1.2 + offset, -77.29, 'HIGH')['id'] for offset in (0.0, 0.004, 0.001, 0.003, 0.002)}
    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    plan = client.get('/api/operator/plan?limit=5&lat=1.1995&lng=-77.29').json()
    assert {stop['report']['id'] for stop in plan['stops']} == ids
    assert [stop['step'] for stop in plan['stops']] == [1, 2, 3, 4, 5]
    assert plan['totalMeters'] <= plan['priorityOrderMeters']
    lats = [stop['report']['location']['lat'] for stop in plan['stops']]
    assert lats == sorted(lats)  # A straight street is walked in order from the start point.
    assert plan['algorithm'] == 'two-opt' and plan['algorithms'] == ['two-opt', 'nearest-neighbour', 'priority']
    baseline = client.get('/api/operator/plan?limit=5&lat=1.1995&lng=-77.29&algorithm=priority').json()
    assert baseline['savedPercent'] == 0 and baseline['totalMeters'] >= plan['totalMeters']
    assert client.get('/api/operator/plan?algorithm=genetic').status_code == 422
    assert client.get('/api/operator/plan?lat=1.2').status_code == 422
    assert client.get('/api/operator/plan').json()['stops'][0]['legMeters'] is None


def test_workflow_transitions_are_validated_and_audited(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    report = publish(client, 1.25, -77.25)
    route = f"/api/operator/reports/{report['id']}/transition"
    assert client.post(route, json={'status': 'CONFIRMED'}).status_code == 403
    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    assert client.post(route, json={'status': 'REPAIRED'}).status_code == 409
    assert client.post(route, json={'status': 'UNVERIFIED'}).status_code == 422
    for status in ('CONFIRMED', 'IN_PROGRESS', 'REPAIRED'):
        response = client.post(route, json={'status': status, 'reason': f'Paso {status}'})
        assert response.status_code == 200, response.text
        assert response.json()['report']['status'] == status
    assert response.json()['allowedTransitions'] == []
    assert client.post(route, json={'status': 'CONFIRMED'}).status_code == 409
    events = client.get(f"/api/operator/reports/{report['id']}/timeline").json()['events']
    assert [(event['from'], event['to']) for event in events] == [
        ('NEW', 'UNVERIFIED'), ('UNVERIFIED', 'CONFIRMED'), ('CONFIRMED', 'IN_PROGRESS'), ('IN_PROGRESS', 'REPAIRED')]
    assert events[0]['actorName'] == 'Sistema' and events[-1]['actorName'] == 'Operario de vías'
    assert report['id'] not in [item['report']['id'] for item in client.get('/api/operator/queue').json()['items']]
    with client.app.state.engine.connect() as conn:
        actions = conn.execute(select(s.audit_events.c.action).where(s.audit_events.c.entity_id == report['id'])).scalars().all()
    assert actions.count('operator.report.status') == 3
    missing = '/api/operator/reports/00000000-0000-4000-8000-000000000000'
    assert client.post(missing + '/transition', json={'status': 'CONFIRMED'}).status_code == 404
    assert client.get(missing + '/timeline').status_code == 404


def test_registered_operator_gets_access_after_promotion(client):
    accounts = demo(client)
    person = register(client, 'Laura Operaria')
    login(client, person['email'], person['password'])
    assert client.get('/api/operator/queue').status_code == 403
    login(client, accounts['Administrador']['email'], accounts['Administrador']['password'])
    target = next(user for user in client.get('/api/admin/users').json()['users'] if user['email'] == person['email'])
    assert client.post(f"/api/admin/users/{target['id']}/role", json={'role': 'Operario'}).status_code == 200
    login(client, person['email'], person['password'])
    assert client.get('/api/operator/queue').status_code == 200
