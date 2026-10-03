"""Modelo relacional PostgreSQL. Todas las relaciones tienen FK e índices."""
import time
import uuid
from sqlalchemy import (
    MetaData, Table, Column, String, Text, Integer, BigInteger, Float, Boolean,
    JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(naming_convention={
    'ix': 'ix_%(table_name)s_%(column_0_name)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
})
json_type = JSON().with_variant(JSONB(), 'postgresql')


def now():
    return int(time.time() * 1000)


def uid():
    return str(uuid.uuid4())


def col(name, kind=String(180), **kwargs):
    return Column(name, kind, nullable=False, **kwargs)


def ref(name, target, nullable=False):
    return Column(name, String(36), ForeignKey(target + '.id'), nullable=nullable)


def table(name, *fields):
    return Table(name, metadata, col('id', String(36), primary_key=True, default=uid),
                 col('created_at', BigInteger, default=now), *fields)


roles = table('roles', col('name', unique=True))
permissions = table('permissions', col('code', unique=True))
role_permissions = table('role_permissions', ref('role_id', 'roles'), ref('permission_id', 'permissions'), UniqueConstraint('role_id', 'permission_id'))
users = table('users', col('email', unique=True), col('display_name'), col('password_hash', Text))
user_roles = table('user_roles', ref('user_id', 'users'), ref('role_id', 'roles'), UniqueConstraint('user_id', 'role_id'))
devices = table('devices', ref('user_id', 'users', True), col('platform'))
sessions = table('sessions', ref('device_id', 'devices'), col('token_hash', String(64), unique=True), col('expires_at', BigInteger))
countries = table('countries', col('code', String(3), unique=True), col('name'))
regions = table('regions', ref('country_id', 'countries'), col('name'), UniqueConstraint('country_id', 'name'))
cities = table('cities', ref('region_id', 'regions'), col('name'), UniqueConstraint('region_id', 'name'))
neighborhoods = table('neighborhoods', ref('city_id', 'cities'), col('name'), UniqueConstraint('city_id', 'name'))
roads = table('roads', ref('city_id', 'cities'), col('name'), UniqueConstraint('city_id', 'name'))
road_segments = table('road_segments', ref('road_id', 'roads'), col('start_lat', Float), col('start_lng', Float), col('end_lat', Float), col('end_lng', Float))
zones = table('zones', ref('city_id', 'cities', True), ref('neighborhood_id', 'neighborhoods', True), ref('road_id', 'roads', True), col('cache_key', String(64), unique=True), col('address', Text), col('source'), col('resolved_at', BigInteger))
zone_road_segments = table('zone_road_segments', ref('zone_id', 'zones'), ref('segment_id', 'road_segments'), UniqueConstraint('zone_id', 'segment_id'))
scan_sessions = table('scan_sessions', ref('session_id', 'sessions'), Column('ended_at', BigInteger))
frames = table('frames', ref('scan_session_id', 'scan_sessions'), col('sha256', String(64)), col('byte_size', Integer), col('width', Integer), col('height', Integer))
gps_samples = table('gps_samples', ref('frame_id', 'frames'), col('lat', Float), col('lng', Float), col('accuracy', Float), CheckConstraint('lat BETWEEN -90 AND 90', name='latitude'), CheckConstraint('lng BETWEEN -180 AND 180', name='longitude'), CheckConstraint('accuracy BETWEEN 0 AND 100', name='accuracy'))
ai_models = table('ai_models', col('provider'), col('name'), UniqueConstraint('provider', 'name'))
analyses = table('analyses', ref('frame_id', 'frames'), ref('model_id', 'ai_models'), col('result', json_type), col('duration_ms', Integer), col('fallback', Boolean, default=False))
detections = table('detections', ref('analysis_id', 'analyses'), col('kind'), Column('bounding_box', json_type), Column('confidence', Float))
potholes = table('potholes', ref('zone_id', 'zones', True), col('lat', Float), col('lng', Float), col('kind'), col('status', default='UNVERIFIED'), CheckConstraint('lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180', name='coordinates'), CheckConstraint("status IN ('UNVERIFIED','CONFIRMED','IN_PROGRESS','REPAIRED','REJECTED')", name='status'))
reports = table('reports', ref('pothole_id', 'potholes'), ref('detection_id', 'detections', True), ref('session_id', 'sessions'), col('accuracy', Float), col('description', Text), CheckConstraint('accuracy BETWEEN 0 AND 100', name='accuracy'))
report_media = table('report_media', ref('report_id', 'reports'), col('storage_url', Text), col('mime_type'), col('sha256', String(64)))
risk_factors = table('risk_factors', col('label', String(200), unique=True))
risk_assessments = table('risk_assessments', ref('report_id', 'reports', True), ref('pothole_id', 'potholes'), col('score', Integer), col('level'), col('method'), CheckConstraint('score BETWEEN 0 AND 100', name='score'), CheckConstraint("level IN ('LOW','MEDIUM','HIGH','CRITICAL')", name='level'))
assessment_factors = table('assessment_factors', ref('assessment_id', 'risk_assessments'), ref('factor_id', 'risk_factors'), UniqueConstraint('assessment_id', 'factor_id'))
status_events = table('status_events', ref('pothole_id', 'potholes'), ref('actor_id', 'users', True), col('old_status'), col('new_status'), col('reason', Text))
confirmations = table('confirmations', ref('report_id', 'reports'), ref('user_id', 'users'), col('confirmed', Boolean), UniqueConstraint('report_id', 'user_id'))
comments = table('comments', ref('report_id', 'reports'), ref('user_id', 'users'), col('body', Text))
subscriptions = table('subscriptions', ref('user_id', 'users'), ref('zone_id', 'zones'), UniqueConstraint('user_id', 'zone_id'))
notifications = table('notifications', ref('user_id', 'users'), ref('pothole_id', 'potholes', True), col('body', Text), Column('read_at', BigInteger))
agencies = table('agencies', ref('city_id', 'cities'), col('name'), col('contact'))
crews = table('crews', ref('agency_id', 'agencies'), col('name'))
crew_members = table('crew_members', ref('crew_id', 'crews'), ref('user_id', 'users'), UniqueConstraint('crew_id', 'user_id'))
work_orders = table('work_orders', ref('pothole_id', 'potholes'), ref('crew_id', 'crews'), col('status'), Column('due_at', BigInteger))
work_order_events = table('work_order_events', ref('order_id', 'work_orders'), ref('actor_id', 'users'), col('description', Text))
repairs = table('repairs', ref('order_id', 'work_orders'), col('description', Text), col('finished_at', BigInteger))
materials = table('materials', col('name', unique=True), col('unit'))
repair_materials = table('repair_materials', ref('repair_id', 'repairs'), ref('material_id', 'materials'), col('quantity', Float), UniqueConstraint('repair_id', 'material_id'), CheckConstraint('quantity > 0', name='quantity'))
audit_events = table('audit_events', ref('session_id', 'sessions', True), col('action'), col('entity_id', String(36)), col('details', json_type))
geocode_cache = table('geocode_cache', col('cache_key', String(64), unique=True), col('payload', json_type), col('expires_at', BigInteger))
api_usage = table('api_usage', ref('session_id', 'sessions'), col('status'), col('provider'), Column('error_code', String(100)))

for relation in metadata.tables.values():
    for field in relation.c:
        if field.foreign_keys:
            Index('ix_' + relation.name + '_' + field.name, field)
Index('ix_potholes_location', potholes.c.lat, potholes.c.lng)
Index('ix_reports_recent', reports.c.created_at)
Index('ix_api_usage_recent', api_usage.c.created_at)
Index('ix_risk_assessments_score', risk_assessments.c.score)
