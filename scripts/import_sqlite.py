"""Idempotent import that keeps IDs/dates and opens SQLite read-only."""
import argparse
import hashlib
import json
import secrets
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine, select, text
from app.config import Settings
from app.contracts import Analysis, Position
from app.repository import Repository
from app.structures import SinglyLinkedList
from app import schema as s


class SQLiteImporter:
    """Copies reports from the legacy SQLite file into PostgreSQL without duplicating existing ids."""

    def __init__(self, engine):
        self.engine = engine
        self.settings = Settings(_env_file=None)
        self.repo = Repository(engine, self.settings)

    def legacy_session(self) -> str:
        """Creates the device session that owns the imported records (it expires immediately)."""
        with self.engine.begin() as conn:
            device = conn.execute(s.devices.insert().values(platform='sqlite-import').returning(s.devices.c.id)).scalar_one()
            return conn.execute(s.sessions.insert().values(device_id=device,
                token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(), expires_at=s.Clock.now())
                .returning(s.sessions.c.id)).scalar_one()

    def run(self, source: Path) -> int:
        if not source.is_file():
            raise FileNotFoundError(source)
        connection = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            raw = SinglyLinkedList[dict](json.loads(row[0]) for row in connection.execute('SELECT data FROM reports ORDER BY created_at ASC'))
        finally:
            connection.close()
        engine, repo = self.engine, self.repo
        missing = SinglyLinkedList[dict]()
        with engine.connect() as conn:
            for record in raw:
                if conn.execute(select(s.reports.c.id).where(s.reports.c.id == record['id'])).scalar_one_or_none() is None:
                    missing.append(record)
        if not missing:
            return 0
        session = self.legacy_session()
        with engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(771012)'))
            scan_session = conn.execute(s.scan_sessions.insert().values(session_id=session).returning(s.scan_sessions.c.id)).scalar_one()
            model = Repository._upsert(conn, s.ai_models, {'provider': 'legacy', 'name': 'sqlite-import'}, ['provider', 'name'])
            count = 0
            for record in missing:
                if conn.execute(select(s.reports.c.id).where(s.reports.c.id == record['id'])).scalar_one_or_none():
                    continue
                position = Position(**record['location'])
                analysis = Analysis.model_validate(record)
                created = int(record['timestamp'])
                original_zone = record.get('zone', {})
                # Only addresses present in the source; a city is never guessed from a photo.
                zone = {**original_zone, 'cacheKey': f'{position.lat:.4f},{position.lng:.4f}', 'source': 'legacy',
                        'countryCode': original_zone.get('countryCode'), 'country': original_zone.get('country'),
                        'region': original_zone.get('region')}
                zone_id = repo.zone(conn, zone)
                payload = json.dumps(record, ensure_ascii=False).encode()
                # Historical frame without a file: zero dimensions/size, fingerprint of the imported JSON.
                frame = conn.execute(s.frames.insert().values(scan_session_id=scan_session, sha256=hashlib.sha256(payload).hexdigest(),
                    byte_size=0, width=0, height=0, created_at=created).returning(s.frames.c.id)).scalar_one()
                conn.execute(s.gps_samples.insert().values(frame_id=frame, created_at=created, **position.model_dump()))
                imported_result = {**analysis.result(), 'legacyZone': original_zone}
                analysis_id = conn.execute(s.analyses.insert().values(frame_id=frame, model_id=model, result=imported_result,
                    duration_ms=0, fallback=False, created_at=created).returning(s.analyses.c.id)).scalar_one()
                detection = conn.execute(s.detections.insert().values(analysis_id=analysis_id, kind=analysis.potholeType,
                    bounding_box=analysis.boundingBox.model_dump() if analysis.boundingBox else None,
                    confidence=analysis.confidence, created_at=created).returning(s.detections.c.id)).scalar_one()
                pothole = conn.execute(s.potholes.insert().values(zone_id=zone_id, lat=position.lat, lng=position.lng,
                    kind=analysis.potholeType, status='UNVERIFIED', created_at=created).returning(s.potholes.c.id)).scalar_one()
                conn.execute(s.reports.insert().values(id=record['id'], pothole_id=pothole, detection_id=detection,
                    session_id=session, accuracy=position.accuracy, description=analysis.aiDescription, created_at=created))
                assessment = conn.execute(s.risk_assessments.insert().values(report_id=record['id'], pothole_id=pothole,
                    score=analysis.hazardScore, level=analysis.result()['hazardLevel'], method='legacy-visual', created_at=created)
                    .returning(s.risk_assessments.c.id)).scalar_one()
                for label in analysis.riskFactors:
                    factor = Repository._upsert(conn, s.risk_factors, {'label': label}, ['label'])
                    conn.execute(s.assessment_factors.insert().values(assessment_id=assessment, factor_id=factor))
                conn.execute(s.audit_events.insert().values(session_id=session, action='sqlite.import', entity_id=record['id'],
                    details={'source': source.name, 'preservedTimestamp': created, 'originalZone': original_zone}))
                conn.execute(s.status_events.insert().values(pothole_id=pothole, old_status='IMPORTED', new_status='UNVERIFIED',
                    reason='Importación de registro histórico SQLite; mantiene verificación pendiente'))
                count += 1
        return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('../backend/data/bachescan.sqlite'))
    args = parser.parse_args()
    engine = create_engine(Settings().sqlalchemy_url())
    try:
        print(f'Reportes importados: {SQLiteImporter(engine).run(args.source)}')
    finally:
        engine.dispose()
