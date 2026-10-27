import os
import uuid
import pytest
from sqlalchemy import select, func, update
from app import schema as s
from test_postgres_api import client, token
from tree_helpers import seed_reports

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='PostgreSQL temporal requerido')
URL = '/api/data-structures/graphs/reports'


def test_graph_requires_authentication_and_empty_snapshot(client):
    assert client.get(URL).status_code == 401
    token(client)
    body = client.get(URL).json()
    assert body['scope']['loaded'] == 0 and body['graph']['metrics']['vertices'] == 0
    assert body['graph']['path'] is None and body['graph']['traversal']['startId'] is None


def test_graph_validates_all_queries_without_exposing_values(client):
    token(client)
    for query in ['radius=49', 'radius=2001', 'limit=81', 'limit=0', 'start=private-sentinel', 'order=private-sentinel']:
        response = client.get(URL + '?' + query)
        assert response.status_code == 422 and 'private-sentinel' not in response.text
    assert client.get(URL + '?start=' + str(uuid.uuid4())).status_code == 404


def test_graph_chain_traversal_path_and_components(client):
    token(client); ids = seed_reports(client, [70, 80, 90, 60])
    for order in ('bfs', 'dfs'):
        body = client.get(URL, params={'radius': 150, 'start': ids[0], 'end': ids[-1], 'order': order}).json()
        graph = body['graph']
        assert graph['metrics']['edges'] == 3 and graph['metrics']['components'] == 1
        assert graph['path']['reportIds'] == ids
        assert 330 < graph['path']['distanceMeters'] < 340
        assert graph['traversal']['reportIds'] == ids
    body = client.get(URL, params={'radius': 50, 'start': ids[0], 'end': ids[-1]}).json()
    assert not body['graph']['path']['reachable'] and body['graph']['metrics']['components'] == 4


def test_graph_bounded_active_sample_public_fields_and_no_writes(client):
    token(client); ids = seed_reports(client, [i % 101 for i in range(85)])
    with client.app.state.engine.begin() as conn:
        hole = conn.execute(select(s.reports.c.pothole_id).where(s.reports.c.id == ids[-1])).scalar_one()
        conn.execute(update(s.potholes).where(s.potholes.c.id == hole).values(status='REPAIRED'))
        before = conn.execute(select(func.count()).select_from(s.reports)).scalar_one()
    response = client.get(URL); body = response.json()
    assert response.status_code == 200 and body['scope']['loaded'] == 80
    assert body['scope']['totalReports'] == 84 and body['scope']['hasMore']
    assert ids[-1] not in [r['id'] for r in body['reports']]
    assert min(r['hazardScore'] for r in body['reports']) >= 4
    assert all(e['distanceMeters'] <= 250 for e in body['graph']['edges'])
    for name in ['email', 'password_hash', 'encrypted_details', 'session_id', 'user_id', 'token_hash']:
        assert name not in response.text
    with client.app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.reports)).scalar_one() == before
    stats = client.get('/api/data-structures/stats').json()
    assert 'Dijkstra' in stats['graph']['use']
