from app import schema as s
from sqlalchemy import select

def report(identity='a', score=70, timestamp=100, city='Cali', neighborhood='Centro', street='Calle 1'):
    return {'id': identity, 'timestamp': timestamp, 'hazardScore': score,
        'hazardLevel': 'CRITICAL' if score >= 80 else 'HIGH' if score >= 60 else 'MEDIUM' if score >= 35 else 'LOW',
        'isPothole': True, 'potholeType': 'BACHE', 'aiDescription': 'Hueco sintético para pruebas locales.',
        'riskFactors': [], 'location': {'lat': 3.45, 'lng': -76.53, 'accuracy': 8},
        'zone': {'city': city, 'neighborhood': neighborhood, 'street': street, 'fullAddress': None},
        'source': 'COMMUNITY', 'status': 'UNVERIFIED'}

def seed_reports(client, scores):
    identities = []
    with client.app.state.engine.begin() as conn:
        session = conn.execute(select(s.sessions.c.id)).scalar_one()
        holes, reports, assessments = [], [], []
        for i, score in enumerate(scores):
            hole_id, report_id = s.uid(), s.uid(); identities.append(report_id)
            holes.append(dict(id=hole_id, lat=3.45 + i*.001, lng=-76.53, kind='BACHE', status='UNVERIFIED'))
            reports.append(dict(id=report_id, pothole_id=hole_id, session_id=session, accuracy=8, description='Prueba de árboles'))
            assessments.append(dict(pothole_id=hole_id, report_id=report_id, score=score,
                level='CRITICAL' if score >= 80 else 'HIGH' if score >= 60 else 'MEDIUM' if score >= 35 else 'LOW', method='community'))
        if holes:
            conn.execute(s.potholes.insert(), holes); conn.execute(s.reports.insert(), reports)
            conn.execute(s.risk_assessments.insert(), assessments)
    return identities
