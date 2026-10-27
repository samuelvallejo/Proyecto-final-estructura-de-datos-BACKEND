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


def test_tree_api_traversals(client):
    token(client); ids = seed_reports(client,[20,30,40,50,60,70,80])
    for order in ['inorder','descending','preorder','postorder','level']:
        body = client.get(URL+'?order='+order).json()
        assert set(body['binary']['traversal']['reportIds']) == set(ids)
        assert [r['id'] for r in body['reports']] == body['binary']['traversal']['reportIds']
        assert body['binary']['traversal']['order'] == order


def test_tree_api_public_fields_only(client):
    token(client); seed_reports(client,[70])
    body = client.get(URL).json(); text = str(body)
    assert body['reports'][0]['source'] == 'COMMUNITY'
    for field in ['password_hash','session_id','user_id','email_lookup','token_hash','encrypted_details']:
        assert field not in text


def test_tree_api_is_read_only(client):
    token(client); seed_reports(client,[30,60])
    with client.app.state.engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(s.audit_events)).scalar_one()
    client.get(URL); client.get(URL+'?order=level')
    with client.app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.reports)).scalar_one() == 2
        assert conn.execute(select(func.count()).select_from(s.audit_events)).scalar_one() == before


def test_tree_api_two_accounts(client):
    token(client); ids = seed_reports(client,[70,80]); first = client.get(URL).json()
    token(client); second = client.get(URL).json()
    assert {r['id'] for r in second['reports']} == set(ids)
    assert second['binary'] == first['binary'] and second['geography'] == first['geography']


def test_tree_api_excludes_inactive(client):
    token(client); ids = seed_reports(client,[60,70,80])
    with client.app.state.engine.begin() as conn:
        holes = dict(conn.execute(select(s.reports.c.id,s.reports.c.pothole_id)).all())
        conn.execute(update(s.potholes).where(s.potholes.c.id == holes[ids[0]]).values(status='REPAIRED'))
        conn.execute(update(s.potholes).where(s.potholes.c.id == holes[ids[1]]).values(status='REJECTED'))
    body = client.get(URL).json()
    assert [r['id'] for r in body['reports']] == [ids[2]] and body['scope']['totalReports'] == 1


def test_priority_pages_have_consistent_binary_tie_order(client):
    token(client); ids = seed_reports(client,[70]*5)
    with client.app.state.engine.begin() as conn:
        conn.execute(update(s.reports).values(created_at=100))
    first = client.get('/api/reports/priority?limit=2').json()['reports']
    second = client.get('/api/reports/priority?limit=2&offset=2').json()['reports']
    assert [r['id'] for r in first+second] == sorted(ids,reverse=True)[:4]
