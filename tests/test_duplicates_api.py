"""Duplicate review and merge on real PostgreSQL."""
from sqlalchemy import func, select
from app import schema as s
from test_postgres_api import client  # noqa: F401  (PostgreSQL fixture)
from test_admin_profile import demo, login
from test_operator_api import custom_detector, publish  # noqa: F401  (light detector fixture)


def clone(client, report_id, lat_offset, lng_offset=0.0):
    """Insert another pothole and report next to an existing one, like a second detection."""
    with client.app.state.engine.begin() as conn:
        original = conn.execute(select(s.reports, s.potholes.c.lat, s.potholes.c.lng, s.potholes.c.zone_id)
                                .select_from(s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id))
                                .where(s.reports.c.id == report_id)).mappings().one()
        pothole = conn.execute(s.potholes.insert().values(zone_id=original['zone_id'], lat=original['lat'] + lat_offset,
                               lng=original['lng'] + lng_offset, kind='BACHE', status='UNVERIFIED').returning(s.potholes.c.id)).scalar_one()
        report = conn.execute(s.reports.insert().values(pothole_id=pothole, session_id=original['session_id'], accuracy=6,
                              description='Detección repetida').returning(s.reports.c.id)).scalar_one()
        conn.execute(s.risk_assessments.insert().values(report_id=report, pothole_id=pothole, score=70, level='HIGH', method='community'))
        user = conn.execute(select(s.devices.c.user_id).select_from(s.sessions.join(s.devices))
                            .where(s.sessions.c.id == original['session_id'])).scalar_one()
        conn.execute(s.pothole_passes.insert().values(pothole_id=pothole, user_id=user, session_id=original['session_id'],
                                                      source='gps', distance_m=3))
    return report


def test_review_and_merge_duplicates(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    first = publish(client, 1.2114826, -77.2914189)
    twin_a = clone(client, first['id'], 0.0)
    twin_b = clone(client, first['id'], 0.00003)  # ~3 m
    far = publish(client, 1.2400, -77.2600)
    assert client.get('/api/operator/duplicates').status_code == 403

    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    review = client.get('/api/operator/duplicates?radius=10').json()
    [cluster] = review['clusters']
    assert cluster['canonical']['id'] == first['id'] and cluster['size'] == 3
    assert {item['id'] for item in cluster['duplicates']} == {twin_a, twin_b}
    assert review['stats']['estimatedPhysicalPotholes'] == 2 and review['stats']['duplicates'] == 2
    assert client.get('/api/operator/duplicates?radius=0').status_code == 422
    brute = client.get('/api/operator/duplicates?radius=10&method=brute-force').json()
    assert brute['stats']['method'] == 'brute-force' and len(brute['clusters']) == 1
    assert brute['stats']['candidateChecks'] == brute['stats']['bruteForceChecks']

    merge = '/api/operator/duplicates/merge'
    assert client.post(merge, json={'canonicalReportId': first['id'], 'duplicateReportIds': [far['id']]}).status_code == 409
    assert client.post(merge, json={'canonicalReportId': first['id'], 'duplicateReportIds': [first['id']]}).status_code == 422
    assert client.post(merge, json={'canonicalReportId': first['id'], 'duplicateReportIds': [twin_a, twin_a]}).status_code == 422
    response = client.post(merge, json={'canonicalReportId': first['id'], 'duplicateReportIds': [twin_a, twin_b]})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['merged'] == 2 and data['passesMoved'] == 2 and data['report']['passCount'] == 2

    assert client.get('/api/operator/duplicates?radius=10').json()['clusters'] == []
    with client.app.state.engine.connect() as conn:
        rows = dict(conn.execute(select(s.reports.c.id, s.potholes.c.status)
                                 .select_from(s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id))
                                 .where(s.reports.c.id.in_([twin_a, twin_b, first['id']]))).all())
        reasons = conn.execute(select(s.status_events.c.reason).where(s.status_events.c.new_status == 'REJECTED')).scalars().all()
        audits = conn.execute(select(func.count()).select_from(s.audit_events)
                              .where(s.audit_events.c.action == 'operator.duplicates.merged')).scalar_one()
    assert rows == {first['id']: 'UNVERIFIED', twin_a: 'REJECTED', twin_b: 'REJECTED'}
    assert reasons == [f"Duplicado del reporte {first['id']}"] * 2 and audits == 1
    # A merged report is no longer open, so merging it again is refused.
    assert client.post(merge, json={'canonicalReportId': first['id'], 'duplicateReportIds': [twin_a]}).status_code == 409
    missing = '00000000-0000-4000-8000-000000000000'
    assert client.post(merge, json={'canonicalReportId': first['id'], 'duplicateReportIds': [missing]}).status_code == 404
