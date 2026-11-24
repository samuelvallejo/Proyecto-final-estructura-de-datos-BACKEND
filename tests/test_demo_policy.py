"""Safe demo mode: public demo sessions cannot change shared data or read real people's details."""
import pytest
from sqlalchemy import select
from app import schema as s
from app.demo_policy import DemoPolicy, READ_ONLY_MESSAGE
from test_postgres_api import client  # noqa: F401  (PostgreSQL fixture)
from test_admin_profile import demo, login, register
from test_operator_api import custom_detector, publish  # noqa: F401  (light detector fixture)


@pytest.mark.parametrize('email, masked', [('samuel@gmail.com', 's•••@g•••.com'), ('a@b.co', 'a•••@b•••.co'),
                                           ('ana@campus.edu.co', 'a•••@c•••.co'), ('broken', '•••'), ('', '•••')])
def test_mask_email(email, masked):
    assert DemoPolicy.mask_email(email) == masked


@pytest.fixture
def read_only(client):
    client.app.state.settings.demo_read_only = True
    return client


def promote(client, accounts, email, role):
    login(client, accounts['Administrador']['email'], accounts['Administrador']['password'])
    target = next(user for user in client.get('/api/admin/users').json()['users'] if user['email'] == email)
    assert client.post(f"/api/admin/users/{target['id']}/role", json={'role': role}).status_code == 200
    return target


def test_demo_sessions_are_read_only_for_shared_data(read_only):
    client = read_only
    accounts = demo(client)
    person = register(client, 'Persona Real')
    login(client, person['email'], person['password'])
    real_trip = client.post('/api/trips', json={'name': 'Casa al trabajo', 'pointA': 'Mi casa', 'pointB': 'Oficina',
                                                'position': {'lat': 1.2, 'lng': -77.29, 'accuracy': 5}})
    assert real_trip.status_code == 201, real_trip.text
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    report = publish(client, 1.25, -77.25)  # Demo drivers can still report potholes.
    me = client.get('/api/me').json()
    assert me['isDemo'] is True and me['readOnly'] is True

    login(client, accounts['Administrador']['email'], accounts['Administrador']['password'])
    users = {user['displayName']: user for user in client.get('/api/admin/users').json()['users']}
    assert users['Persona Real']['email'] == DemoPolicy.mask_email(person['email']) != person['email']
    assert users['Operario de vías']['email'] == accounts['Operario']['email']  # Demo addresses are already public.
    trip = next(item for item in client.get('/api/admin/trips').json()['trips'] if item['userName'] == 'Persona Real')
    assert (trip['name'], trip['pointA'], trip['pointB']) == ('Oculto en la demostración',) * 3
    target = users['Persona Real']['id']
    for path, body in [(f'/api/admin/users/{target}/role', {'role': 'Administrador'}),
                       (f'/api/admin/users/{target}/active', {'active': False}),
                       (f"/api/admin/reports/{report['id']}/status", {'status': 'REPAIRED'})]:
        response = client.post(path, json=body)
        assert response.status_code == 403 and response.json()['error'] == READ_ONLY_MESSAGE, path

    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    assert client.get('/api/operator/queue').status_code == 200  # Reading stays available for the demo.
    assert client.post(f"/api/operator/reports/{report['id']}/transition", json={'status': 'CONFIRMED'}).status_code == 403
    assert client.post('/api/operator/duplicates/merge', json={'canonicalReportId': report['id'],
                       'duplicateReportIds': ['00000000-0000-4000-8000-000000000000']}).status_code == 403
    with client.app.state.engine.connect() as conn:
        assert conn.execute(select(s.potholes.c.status).select_from(s.reports.join(s.potholes))
                            .where(s.reports.c.id == report['id'])).scalar_one() == 'UNVERIFIED'


def test_real_accounts_keep_full_access(read_only):
    client = read_only
    accounts = demo(client)
    # Promotion needs a real administrator: switch the mode off only for this setup step.
    client.app.state.settings.demo_read_only = False
    admin = register(client, 'Administradora Real')
    operator = register(client, 'Operario Real')
    promote(client, accounts, admin['email'], 'Administrador')
    client.app.state.settings.demo_read_only = True
    login(client, admin['email'], admin['password'])
    assert client.get('/api/me').json()['readOnly'] is False
    users = {user['displayName']: user for user in client.get('/api/admin/users').json()['users']}
    assert users['Operario Real']['email'] == operator['email']
    assert client.post(f"/api/admin/users/{users['Operario Real']['id']}/role", json={'role': 'Operario'}).status_code == 200
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    report = publish(client, 1.26, -77.26)
    login(client, operator['email'], operator['password'])
    response = client.post(f"/api/operator/reports/{report['id']}/transition", json={'status': 'CONFIRMED'})
    assert response.status_code == 200 and response.json()['report']['status'] == 'CONFIRMED'
