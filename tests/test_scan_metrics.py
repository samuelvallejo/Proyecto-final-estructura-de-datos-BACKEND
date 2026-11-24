"""Persisted scan metrics: percentiles and folding of detections into scans (real PostgreSQL)."""
from app import schema as s
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
