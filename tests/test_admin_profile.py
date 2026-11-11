"""Modo administrador, cuentas demo, perfil, historial por sesión, pasos por baches y panel."""
import uuid
from sqlalchemy import select, func
from app import schema as s
from app.contracts import Analysis
from test_postgres_api import client  # noqa: F401  (fixture PostgreSQL real)

POSITION = {'lat': 4.6097, 'lng': -74.0817, 'accuracy': 8}


def login(client, email, password):
    client.cookies.clear()
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text


def demo(client):
    data = client.get('/api/auth/demo').json()
    assert data['enabled'] and [item['role'] for item in data['accounts']] == ['Administrador', 'Operario', 'Conductor']
    return {item['role']: item for item in data['accounts']}


def register(client, name='Persona Uno'):
    credentials = {'email': uuid.uuid4().hex + '@example.com', 'password': 'Testing-password!73'}
    assert client.post('/api/auth/register', json={**credentials, 'displayName': name,
                                                    'confirmPassword': credentials['password']}).status_code == 201
    return credentials


def save_pothole(client):
    async def geocode(position):
        return {'cacheKey': f'{position.lat:.4f},{position.lng:.4f}', 'source': 'nominatim', 'street': 'Calle 1',
                'neighborhood': 'Centro', 'city': 'Bogotá', 'region': 'Bogotá DC', 'countryCode': 'co',
                'country': 'Colombia', 'fullAddress': 'Calle 1, Centro, Bogotá'}
    client.app.state.geocoder.resolve = geocode
    response = client.post('/api/community/reports', json={'position': POSITION, 'capturedAt': s.now(),
                                                           'risk': 'HIGH', 'description': 'Hueco profundo en el carril'})
    assert response.status_code == 201, response.text
    return response.json()['report']


def test_demo_accounts_roles_and_admin_access(client):
    accounts = demo(client)
    assert all(len(item['password']) >= 12 and '@' in item['email'] for item in accounts.values())
    # Conductor: no puede entrar al modo administrador.
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    me = client.get('/api/me').json()
    assert me['role'] == 'Conductor' and not me['isAdmin'] and me['initials'] == 'CD'
    assert client.get('/api/admin/overview').status_code == 403
    # Administrador: ve todo.
    login(client, accounts['Administrador']['email'], accounts['Administrador']['password'])
    assert client.get('/api/auth/session').json()['role'] == 'Administrador'
    overview = client.get('/api/admin/overview').json()
    assert overview['roles']['Administrador'] >= 1 and overview['users'] >= 3
    users = client.get('/api/admin/users').json()['users']
    assert {user['email'] for user in users} >= {item['email'] for item in accounts.values()}
    assert all('password' not in user and 'password_hash' not in user for user in users)
    # Muchos inicios de sesión correctos con una cuenta demo compartida no la bloquean.
    for _ in range(12):
        login(client, accounts['Operario']['email'], accounts['Operario']['password'])


def test_admin_manages_roles_accounts_and_status(client):
    accounts = demo(client)
    person = register(client, 'Ana María Pérez')
    login(client, accounts['Administrador']['email'], accounts['Administrador']['password'])
    target = next(user for user in client.get('/api/admin/users').json()['users'] if user['email'] == person['email'])
    assert target['role'] == 'Conductor' and target['initials'] == 'AM'
    assert client.post(f"/api/admin/users/{target['id']}/role", json={'role': 'Operario'}).json()['role'] == 'Operario'
    assert client.post(f"/api/admin/users/{target['id']}/role", json={'role': 'Rey'}).status_code == 422
    me = client.get('/api/me').json()
    assert client.post(f"/api/admin/users/{me['id']}/active", json={'active': False}).status_code == 409
    # Desactivar cierra el acceso de la cuenta.
    assert client.post(f"/api/admin/users/{target['id']}/active", json={'active': False}).json()['active'] is False
    client.cookies.clear()
    assert client.post('/api/auth/login', json=person).status_code == 401
    login(client, accounts['Administrador']['email'], accounts['Administrador']['password'])
    assert client.post(f"/api/admin/users/{target['id']}/active", json={'active': True}).status_code == 200
    report = save_pothole(client)
    changed = client.post(f"/api/admin/reports/{report['id']}/status", json={'status': 'REPAIRED', 'reason': 'Reparado'}).json()
    assert changed['status'] == 'REPAIRED'
    assert client.get('/api/reports').json()['total'] == 0
    assert client.get('/api/admin/reports?status=REPAIRED').json()['total'] == 1
    actions = [event['action'] for event in client.get('/api/admin/audit').json()['events']]
    assert {'admin.report.status', 'admin.user.active', 'admin.user.role', 'auth.login'} <= set(actions)
    sessions = client.get('/api/admin/sessions').json()['sessions']
    assert sessions and all('durationMs' in item and 'userName' in item for item in sessions)


def test_passes_count_people_per_pothole_and_profile_history(client):
    first = register(client, 'Primera Persona')
    second = register(client, 'Segunda Persona')
    login(client, first['email'], first['password'])
    report = save_pothole(client)
    near = {'lat': POSITION['lat'] + 0.0001, 'lng': POSITION['lng'], 'accuracy': 6}  # ~11 m
    far = {'lat': POSITION['lat'] + 0.01, 'lng': POSITION['lng'], 'accuracy': 6}
    assert client.post('/api/passes', json={'position': far}).json()['passed'] == 0
    assert client.post('/api/passes', json={'position': near}).json()['passed'] == 1
    assert client.post('/api/passes', json={'position': near}).json()['passed'] == 0  # Mismo paso en 10 minutos.
    assert client.post('/api/passes', json={'position': {**near, 'accuracy': 80}}).json()['passed'] == 0
    login(client, second['email'], second['password'])
    assert client.post('/api/passes', json={'position': near}).json()['passed'] == 1
    general = client.get('/api/map/potholes').json()
    pothole = next(item for item in general['potholes'] if item['id'] == report['id'])
    assert pothole['peopleCount'] == 2 and pothole['passCount'] == 2 and general['peopleTotal'] == 2
    history = client.get('/api/me/potholes').json()
    assert history['passed'] == 1 and history['history'][0]['kind'] == 'passed'
    login(client, first['email'], first['password'])
    mine = client.get('/api/me/potholes').json()
    assert mine['detected'] == 1 and {item['kind'] for item in mine['history']} == {'detected', 'passed'}
    profile = client.get('/api/me').json()
    assert profile['stats']['potholesDetected'] == 1 and profile['stats']['potholesPassed'] == 1
    sessions = client.get('/api/me/sessions').json()['sessions']
    assert sessions[0]['current'] and sessions[0]['active']
    assert any(event['action'] == 'auth.login' for event in sessions[0]['events'])
    client.post('/api/auth/logout')
    with client.app.state.engine.connect() as conn:
        ended = conn.execute(select(func.count()).select_from(s.sessions).where(s.sessions.c.ended_at.is_not(None))).scalar_one()
    assert ended >= 1


def test_driving_trip_duration_passes_and_dashboard(client):
    person = register(client, 'Conductora Moto')
    login(client, person['email'], person['password'])
    save_pothole(client)
    trip = client.post('/api/trips', json={'name': 'Sesión en moto', 'pointA': 'Casa', 'pointB': 'Trabajo',
                                            'position': {'lat': POSITION['lat'] - 0.001, 'lng': POSITION['lng'], 'accuracy': 5},
                                            'vehicle': 'moto'})
    assert trip.status_code == 201, trip.text
    trip = trip.json()
    assert trip['vehicle'] == 'moto' and trip['durationMs'] >= 0 and trip['potholeCount'] == 0
    sample = client.post(f"/api/trips/{trip['id']}/samples", json={'position': {**POSITION, 'accuracy': 5}}).json()
    assert sample['passed'] == 1
    finished = client.post(f"/api/trips/{trip['id']}/finish", json={'position': {**POSITION, 'accuracy': 5}}).json()
    assert finished['passCount'] == 1 and finished['potholeCount'] == 1 and finished['distanceMeters'] > 50
    assert client.get('/api/trips').json()['trips'][0]['durationMs'] == finished['durationMs']
    for section in ['totals', 'series', 'risk', 'top', 'pipeline']:
        body = client.get(f'/api/dashboard?section={section}').json()
        assert body['section'] == section and body['serverMs'] >= 0
    totals = client.get('/api/dashboard?section=totals').json()['data']
    assert totals['potholesActive'] >= 1 and totals['people'] >= 1 and totals['trips'] >= 1
    series = client.get('/api/dashboard?section=series&days=7').json()['data']
    assert len(series['days']) == 7 and sum(series['passes']) >= 1
    top = client.get('/api/dashboard?section=top').json()['data']['potholes']
    assert top and top[0]['peopleCount'] >= 1
    assert client.get('/api/dashboard?section=secret').status_code == 422


def test_existing_pothole_scan_adds_pass_instead_of_duplicate(client):
    person = register(client, 'Escáner Uno')
    login(client, person['email'], person['password'])
    report = save_pothole(client)

    async def fake_ai(data, image, live=False):
        return Analysis(isPothole=True, potholeType='BACHE', hazardScore=70, aiDescription='Daño visible',
                        riskFactors=['Bordes rotos']), 'local-yolo', 'test', False
    client.app.state.ai.analyze = fake_ai
    from pathlib import Path
    frame = (Path(__file__).parent / 'fixtures/pothole.jpg').read_bytes()
    response = client.post('/api/scan', files={'frame': ('f.jpg', frame, 'image/jpeg')},
                           data={'lat': str(POSITION['lat']), 'lng': str(POSITION['lng']), 'accuracy': '8'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['existing'] and body['report']['id'] == report['id'] and body['nextScanMs'] >= 250
    assert body['report']['peopleCount'] == 1
    actions = {event['action'] for event in client.get('/api/me/sessions').json()['sessions'][0]['events']}
    assert {'scan.detected', 'pothole.pass'} <= actions
