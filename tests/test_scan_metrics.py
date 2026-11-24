"""Scan history and latency are the same for every replica (real PostgreSQL)."""
from app import schema as s
from app.pipeline import ScanPipeline
from app.repository import Repository
from app.scan_metrics import ScanMetrics, percentile
from test_postgres_api import client  # noqa: F401  (PostgreSQL fixture)
from test_admin_profile import demo, login
from test_operator_api import custom_detector  # noqa: F401  (light detector fixture)


def store_scan(client, session_id, duration, detections=1, created=None, frame='a' * 64):
    """Persist a scan the way save_scan does: one frame and analysis per detection."""
    with client.app.state.engine.begin() as conn:
        scan_session = conn.execute(s.scan_sessions.insert().values(session_id=session_id).returning(s.scan_sessions.c.id)).scalar_one()
        model = Repository._upsert(conn, s.ai_models, {'provider': 'local-yolo', 'name': 'best.pt'}, ['provider', 'name'])
        for index in range(max(1, detections)):
            frame_id = conn.execute(s.frames.insert().values(scan_session_id=scan_session, sha256=frame, byte_size=10,
                                    width=640, height=480).returning(s.frames.c.id)).scalar_one()
            conn.execute(s.analyses.insert().values(frame_id=frame_id, model_id=model, duration_ms=duration,
                         result={'isPothole': detections > 0}, created_at=(created or s.Clock.now()) + index))


def test_percentile_matches_pipeline_rule():
    assert percentile([], 50) is None
    assert percentile([300, 100, 200], 50) == 200 and percentile(list(range(1, 101)), 95) == 95


def test_history_and_latency_do_not_depend_on_the_replica(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    session_id = client.get('/api/me').json()['sessionId']
    now = s.Clock.now()
    store_scan(client, session_id, 120, detections=3, created=now - 3000, frame='b' * 64)  # One scan, three detections.
    store_scan(client, session_id, 80, detections=0, created=now - 2000, frame='c' * 64)
    store_scan(client, session_id, 400, detections=1, created=now - 1000, frame='d' * 64)

    first = client.get('/api/scans/history').json()
    assert [event['durationMs'] for event in first['events']] == [400, 80, 120]
    assert [event['isPothole'] for event in first['events']] == [True, False, True]
    assert [event['durationMs'] for event in client.get('/api/scans/history?reverse=false').json()['events']] == [120, 80, 400]

    # A fresh pipeline stands for the other replica: its memory is empty, the answer is not.
    original, client.app.state.pipeline = client.app.state.pipeline, ScanPipeline()
    try:
        assert client.get('/api/scans/history').json()['events'] == first['events']
        stats = client.get('/api/data-structures/stats').json()
    finally:
        client.app.state.pipeline = original  # Let the app stop the running workers on shutdown.
    assert stats['totalLatencyMs'] == {'samples': 3, 'p50': 120, 'p95': 400, 'scope': 'all-replicas'}
    assert stats['doublyLinkedList']['size'] == 0 and stats['instance']['id']
    pipeline = client.get('/api/dashboard?section=pipeline').json()['data']
    assert pipeline['latency']['samples'] == 3 and pipeline['modelLatency']['scope'] == 'this-replica' and pipeline['instance']

    # Another account never sees these scans.
    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    assert client.get('/api/scans/history').json()['events'] == []


def test_scans_fold_detections_of_one_frame(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    session_id = client.get('/api/me').json()['sessionId']
    store_scan(client, session_id, 90, detections=5)
    scans = ScanMetrics(client.app.state.engine).scans(10)
    assert len(scans) == 1 and scans[0]['isPothole'] and scans[0]['durationMs'] == 90
    # The same frame analysed again later with the same duration is a separate scan.
    store_scan(client, session_id, 90, detections=1, created=s.Clock.now() + 500)
    assert len(ScanMetrics(client.app.state.engine).scans(10)) == 2
