import os
import pytest
from sqlalchemy import select, func, update
from app import schema as s
from test_postgres_api import client, token
from tree_helpers import seed_reports

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='PostgreSQL temporal requerido')
URL = '/api/data-structures/trees/reports'


def test_tree_api_requires_authentication(client):
    assert client.get(URL).status_code == 401


def test_tree_api_empty(client):
    token(client); response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body['scope']['loaded'] == 0 and body['binary']['rootId'] is None
    assert body['binary']['metrics']['height'] == -1 and body['geography']['metrics']['reports'] == 0
