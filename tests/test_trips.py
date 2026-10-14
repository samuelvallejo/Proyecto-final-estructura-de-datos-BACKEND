from sqlalchemy import select, update
from app import schema as s
from app.contracts import Analysis, DamageDetection
from test_postgres_api import client, token, scan


def test_trip_encryption_ownership_and_finalization(client):
    token(client)
    payload = {'name': 'Camino privado', 'pointA': 'Salida privada', 'pointB': 'Destino privado', 'position': {'lat': 3.45, 'lng': -76.53, 'accuracy': 10}}
    reply = client.post('/api/trips', json=payload)
    assert reply.status_code == 201, reply.text
    trip = reply.json()
    with client.app.state.engine.connect() as conn:
        assert 'Camino privado' not in conn.execute(select(s.trips.c.encrypted_details)).scalar_one()
        assert '3.45' not in conn.execute(select(s.trip_samples.c.encrypted_position)).scalar_one()
    assert client.post('/api/trips', json=payload).status_code == 409
    with client.app.state.engine.begin() as conn:
        conn.execute(update(s.trip_samples).values(created_at=s.now()-5000))
    assert client.post(f"/api/trips/{trip['id']}/samples", json={'position': {'lat': 3.46, 'lng': -76.54, 'accuracy': 8}}).status_code == 200
    end = client.post(f"/api/trips/{trip['id']}/finish", json={'position': None})
    assert end.status_code == 200 and end.json()['endedAt']
    assert end.json()['end']['lat'] == 3.46
    assert client.post(f"/api/trips/{trip['id']}/samples", json={'position': payload['position']}).status_code == 409
    assert client.get(f"/api/trips/{trip['id']}").json()['pointB'] == 'Destino privado'
    token(client)  # Second user: no access to the first user's route.
    assert client.get('/api/trips').json()['trips'] == []
    assert client.get(f"/api/trips/{trip['id']}").status_code == 404
    assert client.post(f"/api/trips/{trip['id']}/finish", json={'position': None}).status_code == 404


def test_multiple_holes_same_frame_stay_distinct_and_attach_once(client):
    token(client)
    payload = {'name': 'Cali prueba', 'pointA': 'Salida', 'pointB': 'Llegada', 'position': {'lat': 3.45, 'lng': -76.53, 'accuracy': 10}}
    trip = client.post('/api/trips', json=payload).json()
    boxes = [{'xmin': 50, 'ymin': 600, 'xmax': 300, 'ymax': 950}, {'xmin': 650, 'ymin': 600, 'xmax': 900, 'ymax': 950}]
    detections = [DamageDetection(boundingBox=box, confidence=.9, hazardScore=65, aiDescription='Posible bache visible', riskFactors=['Bordes rotos']) for box in boxes]
    async def fake_ai(data, image):
        return Analysis(isPothole=True, potholeType='BACHE', hazardScore=65, aiDescription='Daños visibles', riskFactors=['Bordes rotos'], boundingBox=detections[0].boundingBox, confidence=.9, detections=detections), 'local-yolo', 'test', False
    client.app.state.ai.analyze = fake_ai
    coords = {'lat': '3.45', 'lng': '-76.53', 'accuracy': '10', 'tripId': trip['id']}
    first = scan(client, {}, coords)
    assert first.status_code == 200, first.text
    assert len(first.json()['detections']) == 2
    assert len({report['id'] for report in first.json()['reports']}) == 2
    second = scan(client, {}, coords)
    assert all(item['existing'] for item in second.json()['detections'])
    saved = client.get(f"/api/trips/{trip['id']}").json()
    assert saved['reportCount'] == 2 and len(saved['reports']) == 2
    assert client.get('/api/reports').json()['total'] == 2
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/reports').status_code == 401
    with client.app.state.engine.connect() as conn:
        assert len(conn.execute(select(s.reports.c.id)).all()) == 2


def test_trip_form_bounds_and_cross_account_scan(client):
    token(client)
    payload = {'name': 'Ruta', 'pointA': 'Inicio', 'pointB': 'Destino', 'position': {'lat': 3.4, 'lng': -76.5, 'accuracy': 10}}
    invalid = client.post('/api/trips', json={**payload, 'pointB': 'private-internal-marker' * 30})
    assert invalid.status_code == 422 and 'private-internal-marker' not in invalid.text
    trip = client.post('/api/trips', json=payload).json()
    token(client)
    assert scan(client, {}, {'tripId': trip['id']}).status_code == 404
