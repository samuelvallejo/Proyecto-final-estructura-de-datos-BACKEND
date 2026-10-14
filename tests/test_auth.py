import pytest
from cryptography.fernet import Fernet
from app.auth import Vault, password_hash, password_matches
from sqlalchemy import select
from app import schema as s
from test_postgres_api import client


def test_password_is_salted_and_not_reversible():
    password = 'An-example-password!12'
    first, second = password_hash(password), password_hash(password)
    assert first != second and password not in first
    assert password_matches(password, first)
    assert not password_matches('Wrong-password!12', first)
    assert not password_matches(password, 'invalid')


def test_vault_ciphertext_and_lookup():
    vault = Vault(Fernet.generate_key().decode())
    assert vault.decrypt(vault.encrypt('private@example.com')) == 'private@example.com'
    assert 'private@example.com' not in vault.encrypt('private@example.com')
    assert vault.encrypt('name') != vault.encrypt('name')
    assert vault.lookup('email:test') == vault.lookup('email:test')
    with pytest.raises(RuntimeError):
        Vault('')


def test_registration_login_cookie_and_access_control(client):
    for path in ['/api/reports', '/api/reports/priority', '/api/reports/patrol', '/api/data-structures/stats', '/api/scans/history']:
        assert client.get(path).status_code == 401
    credentials = {'email': 'Private@example.com', 'password': 'Private-password!43'}
    registration = {**credentials, 'displayName': 'Nombre privado', 'confirmPassword': credentials['password']}
    reply = client.post('/api/auth/register', json=registration)
    assert reply.status_code == 201 and reply.json() == {'message': 'Todo se ejecutó correctamente.'}
    with client.app.state.engine.connect() as conn:
        row = conn.execute(select(s.users)).mappings().one()
        assert credentials['email'].lower() not in row['email']
        assert row['display_name'] != registration['displayName']
        assert credentials['password'] not in row['password_hash']
        assert row['email_lookup'] != credentials['email']
    reply = client.post('/api/auth/login', json=credentials)
    assert reply.status_code == 200 and set(reply.json()) == {'message'}
    assert 'httponly' in reply.headers['set-cookie'].lower()
    assert 'samesite=lax' in reply.headers['set-cookie'].lower()
    assert client.get('/api/auth/session').json()['authenticated']
    assert client.get('/api/reports').status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/reports').status_code == 401


@pytest.mark.parametrize('change', [{'password': 'x'}, {'email': 'internal-secret-not-email'}, {'displayName': 'x' * 81}, {'password': 'x' * 129}, {'confirmPassword': 'different'}, {'extra': 'secret'}])
def test_invalid_forms_never_echo_input(client, change):
    payload = {'email': 'hidden@example.com', 'password': 'Hidden-password!12', 'confirmPassword': 'Hidden-password!12', 'displayName': 'Usuario'}
    reply = client.post('/api/auth/register', json={**payload, **change})
    assert reply.status_code in (400, 422)
    assert set(reply.json()) == {'error'}
    assert 'hidden@example.com' not in reply.text and 'Hidden-password' not in reply.text
    assert 'internal-secret' not in reply.text and 'loc' not in reply.json()


def test_csrf_and_auth_throttling(client):
    credentials = {'email': 'missing@example.com', 'password': 'Testing-password!12'}
    assert client.post('/api/auth/login', json=credentials, headers={'Origin': 'https://attacker.example'}).status_code == 403
    for _ in range(10):
        assert client.post('/api/auth/login', json=credentials).status_code == 401
    assert client.post('/api/auth/login', json=credentials).status_code == 429
