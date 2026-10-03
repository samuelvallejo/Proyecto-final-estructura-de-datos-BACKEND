import hashlib
import math
import secrets
from sqlalchemy import select, func, text, update
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from . import schema as s


def distance(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    delta = math.radians(b['lng'] - a['lng'])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    return 12742000 * math.asin(min(1, math.sqrt(h)))


def upsert(conn, relation, values, keys):
    stmt = insert(relation).values(**values).on_conflict_do_nothing(index_elements=keys).returning(relation.c.id)
    value = conn.execute(stmt).scalar_one_or_none()
    return value or conn.execute(select(relation.c.id).where(*(relation.c[key] == values[key] for key in keys))).scalar_one()


class Repository:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as conn:
            device = conn.execute(s.devices.insert().values(platform='mobile-pwa').returning(s.devices.c.id)).scalar_one()
            session = conn.execute(s.sessions.insert().values(device_id=device,
                token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=s.now() + self.settings.session_hours * 3600_000)
                .returning(s.sessions.c.id)).scalar_one()
        return {'token': token, 'sessionId': session, 'expiresAt': s.now() + self.settings.session_hours * 3600_000}

    def session(self, token):
        if not token:
            raise HTTPException(401, 'Inicia una sesión de escaneo.')
        with self.engine.connect() as conn:
            row = conn.execute(select(s.sessions).where(
                s.sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                s.sessions.c.expires_at > s.now())).mappings().first()
        if not row:
            raise HTTPException(401, 'La sesión ha expirado. Inicia el escaneo de nuevo.')
        return row['id']

    def reserve_usage(self, session_id):
        with self.engine.begin() as conn:
            # Global, persistente y válido incluso con múltiples procesos.
            conn.execute(text('SELECT pg_advisory_xact_lock(771011)'))
            since = s.now() - 3600_000
            total = conn.execute(select(func.count()).select_from(s.api_usage).where(s.api_usage.c.created_at > since)).scalar_one()
            count, last = conn.execute(select(func.count(), func.max(s.api_usage.c.created_at)).where(
                s.api_usage.c.created_at > since, s.api_usage.c.session_id == session_id)).one()
            local = self.settings.ai_provider == 'local' or not self.settings.gemini_api_key
            maximum_global = self.settings.local_max_global_scans_per_hour if local else self.settings.max_global_scans_per_hour
            maximum_session = self.settings.local_max_scans_per_hour if local else self.settings.max_scans_per_hour
            interval = self.settings.local_scan_interval_seconds if local else self.settings.scan_interval_seconds
            if total >= maximum_global or count >= maximum_session:
                raise HTTPException(429, 'Se alcanzó el límite de escaneos por hora.', headers={'Retry-After': '60'})
            if last and s.now() - last < interval * 1000:
                raise HTTPException(429, 'Espera unos segundos antes del próximo análisis.', headers={'Retry-After': '5'})
            return conn.execute(s.api_usage.insert().values(session_id=session_id, status='pending', provider='pending')
                                .returning(s.api_usage.c.id)).scalar_one()

    def finish_usage(self, usage_id, provider, failed=False):
        with self.engine.begin() as conn:
            conn.execute(update(s.api_usage).where(s.api_usage.c.id == usage_id).values(
                status='failed' if failed else 'done', provider=provider, error_code='scan_failed' if failed else None))

    def zone(self, conn, zone):
        city_id = neighborhood_id = road_id = None
        if zone.get('countryCode') and zone.get('city'):
            country_id = upsert(conn, s.countries, {'code': zone['countryCode'].upper()[:3], 'name': zone.get('country') or zone['countryCode']}, ['code'])
            region_id = upsert(conn, s.regions, {'country_id': country_id, 'name': zone.get('region') or 'Sin región identificada'}, ['country_id', 'name'])
            city_id = upsert(conn, s.cities, {'region_id': region_id, 'name': zone['city']}, ['region_id', 'name'])
            if zone.get('neighborhood'):
                neighborhood_id = upsert(conn, s.neighborhoods, {'city_id': city_id, 'name': zone['neighborhood']}, ['city_id', 'name'])
            if zone.get('street'):
                road_id = upsert(conn, s.roads, {'city_id': city_id, 'name': zone['street']}, ['city_id', 'name'])
        values = {'city_id': city_id, 'neighborhood_id': neighborhood_id, 'road_id': road_id,
                  'cache_key': zone['cacheKey'], 'address': zone.get('fullAddress') or '',
                  'source': zone['source'], 'resolved_at': s.now()}
        stmt = insert(s.zones).values(**values).on_conflict_do_update(index_elements=['cache_key'], set_={k: v for k, v in values.items() if k != 'cache_key'})
        return conn.execute(stmt.returning(s.zones.c.id)).scalar_one()

    def save_scan(self, session_id, data, image, analysis, provider, model, fallback, duration, position, zone):
        result = analysis.result()
        with self.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(771012)'))
            scan_session = conn.execute(select(s.scan_sessions.c.id).where(s.scan_sessions.c.session_id == session_id).limit(1)).scalar_one_or_none()
            if not scan_session:
                scan_session = conn.execute(s.scan_sessions.insert().values(session_id=session_id).returning(s.scan_sessions.c.id)).scalar_one()
            frame_id = conn.execute(s.frames.insert().values(scan_session_id=scan_session,
                sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data), width=image.width, height=image.height)
                .returning(s.frames.c.id)).scalar_one()
            if position:
                conn.execute(s.gps_samples.insert().values(frame_id=frame_id, **position.model_dump()))
            model_id = upsert(conn, s.ai_models, {'provider': provider, 'name': model}, ['provider', 'name'])
            analysis_id = conn.execute(s.analyses.insert().values(frame_id=frame_id, model_id=model_id,
                result=result, duration_ms=duration, fallback=fallback).returning(s.analyses.c.id)).scalar_one()
            report_id = None
            existing = False
            if analysis.isPothole:
                detection_id = conn.execute(s.detections.insert().values(analysis_id=analysis_id, kind=analysis.potholeType,
                    bounding_box=analysis.boundingBox.model_dump() if analysis.boundingBox else None,
                    confidence=analysis.confidence).returning(s.detections.c.id)).scalar_one()
                if position:
                    radius = max(15, min(position.accuracy, 35))
                    # Búsqueda indexada por latitud + Haversine, válida en polos y antimeridiano.
                    candidates = conn.execute(select(s.potholes).where(
                        s.potholes.c.created_at > s.now() - 30 * 60_000,
                        s.potholes.c.kind == analysis.potholeType,
                        s.potholes.c.lat.between(position.lat - radius / 110000, position.lat + radius / 110000),
                        s.potholes.c.status != 'REPAIRED')).mappings().all()
                    match = next((row for row in candidates if distance(row, position.model_dump()) <= radius), None)
                    if match:
                        report_id = conn.execute(select(s.reports.c.id).where(s.reports.c.pothole_id == match['id'])
                                                 .order_by(s.reports.c.created_at.desc()).limit(1)).scalar_one()
                        existing = True
                    else:
                        zone_id = self.zone(conn, zone)
                        pothole_id = conn.execute(s.potholes.insert().values(zone_id=zone_id, lat=position.lat,
                            lng=position.lng, kind=analysis.potholeType, status='UNVERIFIED').returning(s.potholes.c.id)).scalar_one()
                        report_id = conn.execute(s.reports.insert().values(pothole_id=pothole_id, detection_id=detection_id,
                            session_id=session_id, accuracy=position.accuracy, description=analysis.aiDescription)
                            .returning(s.reports.c.id)).scalar_one()
                        assessment = conn.execute(s.risk_assessments.insert().values(report_id=report_id, pothole_id=pothole_id,
                            score=analysis.hazardScore, level=result['hazardLevel'], method='visual-' + provider)
                            .returning(s.risk_assessments.c.id)).scalar_one()
                        for factor in analysis.riskFactors:
                            factor_id = upsert(conn, s.risk_factors, {'label': factor}, ['label'])
                            conn.execute(s.assessment_factors.insert().values(assessment_id=assessment, factor_id=factor_id))
                        conn.execute(s.status_events.insert().values(pothole_id=pothole_id, old_status='NEW',
                            new_status='UNVERIFIED', reason='Detección automática pendiente de inspección'))
                        conn.execute(s.audit_events.insert().values(session_id=session_id, action='report.created',
                            entity_id=report_id, details={'provider': provider, 'locationSource': 'phone-gps'}))
        return self.get_report(report_id) if report_id else None, existing, analysis_id

    def query(self):
        return select(s.reports.c.id, s.reports.c.created_at, s.reports.c.accuracy,
                      s.potholes.c.lat, s.potholes.c.lng, s.potholes.c.status,
                      s.analyses.c.result, s.zones.c.address, s.zones.c.source,
                      s.roads.c.name.label('street'), s.neighborhoods.c.name.label('neighborhood'), s.cities.c.name.label('city'))\
            .select_from(s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id)
                         .outerjoin(s.detections, s.reports.c.detection_id == s.detections.c.id)
                         .outerjoin(s.analyses, s.detections.c.analysis_id == s.analyses.c.id)
                         .outerjoin(s.zones, s.potholes.c.zone_id == s.zones.c.id)
                         .outerjoin(s.roads, s.zones.c.road_id == s.roads.c.id)
                         .outerjoin(s.neighborhoods, s.zones.c.neighborhood_id == s.neighborhoods.c.id)
                         .outerjoin(s.cities, s.zones.c.city_id == s.cities.c.id))

    def serialize(self, row):
        original = row['result'].get('legacyZone', {})
        return {**row['result'], 'id': row['id'], 'timestamp': row['created_at'], 'status': row['status'],
                'location': {'lat': row['lat'], 'lng': row['lng'], 'accuracy': row['accuracy']},
                'zone': {'street': row['street'] or original.get('street'), 'neighborhood': row['neighborhood'] or original.get('neighborhood'), 'city': row['city'] or original.get('city'),
                         'fullAddress': row['address'] or None, 'source': row['source']}}

    def get_report(self, report_id):
        with self.engine.connect() as conn:
            row = conn.execute(self.query().where(s.reports.c.id == report_id)).mappings().first()
        return self.serialize(row) if row else None

    def list_reports(self, limit=100, offset=0, priority=False, position=None, radius=5000):
        query = self.query()
        if position:
            query = query.where(s.potholes.c.lat.between(position['lat'] - radius / 110000, position['lat'] + radius / 110000))
        if priority:
            query = query.join(s.risk_assessments, s.risk_assessments.c.report_id == s.reports.c.id)
            query = query.order_by(s.risk_assessments.c.score.desc(), s.reports.c.created_at.desc(), s.reports.c.id)
        else:
            query = query.order_by(s.reports.c.created_at.desc(), s.reports.c.id)
        with self.engine.connect() as conn:
            if position:
                rows = conn.execute(query).mappings()
                results = [self.serialize(row) for row in rows if distance(row, position) <= radius]
                return results[offset:offset + limit], len(results)
            total = conn.execute(select(func.count()).select_from(s.reports)).scalar_one()
            rows = conn.execute(query.limit(limit).offset(offset)).mappings().all()
        return [self.serialize(row) for row in rows], total
