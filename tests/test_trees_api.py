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


def test_tree_api_filters(client):
    token(client); seed_reports(client,[0,20,60,70,90,100])
    body = client.get(URL+'?minScore=60&maxScore=90').json()
    assert [r['hazardScore'] for r in body['reports']] == [60,70,90]
    assert body['scope']['totalReports'] == 6 and body['scope']['totalMatched'] == 3


def test_tree_api_invalid_parameters(client):
    token(client)
    for query in ['minScore=-1','maxScore=101','minScore=90&maxScore=20','limit=201','limit=0','order=internal-secret-value']:
        response = client.get(URL+'?'+query)
        assert response.status_code == 422 and 'internal-secret-value' not in response.text


def test_tree_api_bounded_sample(client):
    token(client); seed_reports(client,[i%101 for i in range(205)])
    body = client.get(URL).json()
    assert body['scope']['loaded'] == len(body['binary']['nodes']) == 200
    assert body['scope']['totalMatched'] == 205 and body['scope']['hasMore']
    assert len(body['geography']['nodes']) <= 801 and body['binary']['metrics']['height'] <= 7
