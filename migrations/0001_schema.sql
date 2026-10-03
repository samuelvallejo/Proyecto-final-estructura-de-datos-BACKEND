CREATE TABLE ai_models (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	provider VARCHAR(180) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_ai_models PRIMARY KEY (id), 
	CONSTRAINT uq_ai_models_provider UNIQUE (provider, name)
);

CREATE TABLE countries (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	code VARCHAR(3) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_countries PRIMARY KEY (id), 
	CONSTRAINT uq_countries_code UNIQUE (code)
);

CREATE TABLE geocode_cache (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	cache_key VARCHAR(64) NOT NULL, 
	payload JSONB NOT NULL, 
	expires_at BIGINT NOT NULL, 
	CONSTRAINT pk_geocode_cache PRIMARY KEY (id), 
	CONSTRAINT uq_geocode_cache_cache_key UNIQUE (cache_key)
);

CREATE TABLE materials (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	unit VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_materials PRIMARY KEY (id), 
	CONSTRAINT uq_materials_name UNIQUE (name)
);

CREATE TABLE permissions (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	code VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_permissions PRIMARY KEY (id), 
	CONSTRAINT uq_permissions_code UNIQUE (code)
);

CREATE TABLE risk_factors (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	label VARCHAR(200) NOT NULL, 
	CONSTRAINT pk_risk_factors PRIMARY KEY (id), 
	CONSTRAINT uq_risk_factors_label UNIQUE (label)
);

CREATE TABLE roles (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_roles PRIMARY KEY (id), 
	CONSTRAINT uq_roles_name UNIQUE (name)
);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	email VARCHAR(180) NOT NULL, 
	display_name VARCHAR(180) NOT NULL, 
	password_hash TEXT NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE TABLE devices (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	user_id VARCHAR(36), 
	platform VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_devices PRIMARY KEY (id), 
	CONSTRAINT fk_devices_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_devices_user_id ON devices (user_id);

CREATE TABLE regions (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	country_id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_regions PRIMARY KEY (id), 
	CONSTRAINT uq_regions_country_id UNIQUE (country_id, name), 
	CONSTRAINT fk_regions_country_id_countries FOREIGN KEY(country_id) REFERENCES countries (id)
);

CREATE INDEX ix_regions_country_id ON regions (country_id);

CREATE TABLE role_permissions (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	role_id VARCHAR(36) NOT NULL, 
	permission_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_role_permissions PRIMARY KEY (id), 
	CONSTRAINT uq_role_permissions_role_id UNIQUE (role_id, permission_id), 
	CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id), 
	CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id)
);

CREATE INDEX ix_role_permissions_permission_id ON role_permissions (permission_id);

CREATE INDEX ix_role_permissions_role_id ON role_permissions (role_id);

CREATE TABLE user_roles (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	role_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_user_roles PRIMARY KEY (id), 
	CONSTRAINT uq_user_roles_user_id UNIQUE (user_id, role_id), 
	CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id)
);

CREATE INDEX ix_user_roles_role_id ON user_roles (role_id);

CREATE INDEX ix_user_roles_user_id ON user_roles (user_id);

CREATE TABLE cities (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	region_id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_cities PRIMARY KEY (id), 
	CONSTRAINT uq_cities_region_id UNIQUE (region_id, name), 
	CONSTRAINT fk_cities_region_id_regions FOREIGN KEY(region_id) REFERENCES regions (id)
);

CREATE INDEX ix_cities_region_id ON cities (region_id);

CREATE TABLE sessions (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at BIGINT NOT NULL, 
	CONSTRAINT pk_sessions PRIMARY KEY (id), 
	CONSTRAINT fk_sessions_device_id_devices FOREIGN KEY(device_id) REFERENCES devices (id), 
	CONSTRAINT uq_sessions_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_sessions_device_id ON sessions (device_id);

CREATE TABLE agencies (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	city_id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	contact VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_agencies PRIMARY KEY (id), 
	CONSTRAINT fk_agencies_city_id_cities FOREIGN KEY(city_id) REFERENCES cities (id)
);

CREATE INDEX ix_agencies_city_id ON agencies (city_id);

CREATE TABLE api_usage (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	status VARCHAR(180) NOT NULL, 
	provider VARCHAR(180) NOT NULL, 
	error_code VARCHAR(100), 
	CONSTRAINT pk_api_usage PRIMARY KEY (id), 
	CONSTRAINT fk_api_usage_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_api_usage_recent ON api_usage (created_at);

CREATE INDEX ix_api_usage_session_id ON api_usage (session_id);

CREATE TABLE audit_events (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	session_id VARCHAR(36), 
	action VARCHAR(180) NOT NULL, 
	entity_id VARCHAR(36) NOT NULL, 
	details JSONB NOT NULL, 
	CONSTRAINT pk_audit_events PRIMARY KEY (id), 
	CONSTRAINT fk_audit_events_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_audit_events_session_id ON audit_events (session_id);

CREATE TABLE neighborhoods (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	city_id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_neighborhoods PRIMARY KEY (id), 
	CONSTRAINT uq_neighborhoods_city_id UNIQUE (city_id, name), 
	CONSTRAINT fk_neighborhoods_city_id_cities FOREIGN KEY(city_id) REFERENCES cities (id)
);

CREATE INDEX ix_neighborhoods_city_id ON neighborhoods (city_id);

CREATE TABLE roads (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	city_id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_roads PRIMARY KEY (id), 
	CONSTRAINT uq_roads_city_id UNIQUE (city_id, name), 
	CONSTRAINT fk_roads_city_id_cities FOREIGN KEY(city_id) REFERENCES cities (id)
);

CREATE INDEX ix_roads_city_id ON roads (city_id);

CREATE TABLE scan_sessions (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	ended_at BIGINT, 
	CONSTRAINT pk_scan_sessions PRIMARY KEY (id), 
	CONSTRAINT fk_scan_sessions_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_scan_sessions_session_id ON scan_sessions (session_id);

CREATE TABLE crews (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	agency_id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_crews PRIMARY KEY (id), 
	CONSTRAINT fk_crews_agency_id_agencies FOREIGN KEY(agency_id) REFERENCES agencies (id)
);

CREATE INDEX ix_crews_agency_id ON crews (agency_id);

CREATE TABLE frames (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	scan_session_id VARCHAR(36) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	byte_size INTEGER NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	CONSTRAINT pk_frames PRIMARY KEY (id), 
	CONSTRAINT fk_frames_scan_session_id_scan_sessions FOREIGN KEY(scan_session_id) REFERENCES scan_sessions (id)
);

CREATE INDEX ix_frames_scan_session_id ON frames (scan_session_id);

CREATE TABLE road_segments (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	road_id VARCHAR(36) NOT NULL, 
	start_lat FLOAT NOT NULL, 
	start_lng FLOAT NOT NULL, 
	end_lat FLOAT NOT NULL, 
	end_lng FLOAT NOT NULL, 
	CONSTRAINT pk_road_segments PRIMARY KEY (id), 
	CONSTRAINT fk_road_segments_road_id_roads FOREIGN KEY(road_id) REFERENCES roads (id)
);

CREATE INDEX ix_road_segments_road_id ON road_segments (road_id);

CREATE TABLE zones (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	city_id VARCHAR(36), 
	neighborhood_id VARCHAR(36), 
	road_id VARCHAR(36), 
	cache_key VARCHAR(64) NOT NULL, 
	address TEXT NOT NULL, 
	source VARCHAR(180) NOT NULL, 
	resolved_at BIGINT NOT NULL, 
	CONSTRAINT pk_zones PRIMARY KEY (id), 
	CONSTRAINT fk_zones_city_id_cities FOREIGN KEY(city_id) REFERENCES cities (id), 
	CONSTRAINT fk_zones_neighborhood_id_neighborhoods FOREIGN KEY(neighborhood_id) REFERENCES neighborhoods (id), 
	CONSTRAINT fk_zones_road_id_roads FOREIGN KEY(road_id) REFERENCES roads (id), 
	CONSTRAINT uq_zones_cache_key UNIQUE (cache_key)
);

CREATE INDEX ix_zones_city_id ON zones (city_id);

CREATE INDEX ix_zones_neighborhood_id ON zones (neighborhood_id);

CREATE INDEX ix_zones_road_id ON zones (road_id);

CREATE TABLE analyses (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	frame_id VARCHAR(36) NOT NULL, 
	model_id VARCHAR(36) NOT NULL, 
	result JSONB NOT NULL, 
	duration_ms INTEGER NOT NULL, 
	fallback BOOLEAN NOT NULL, 
	CONSTRAINT pk_analyses PRIMARY KEY (id), 
	CONSTRAINT fk_analyses_frame_id_frames FOREIGN KEY(frame_id) REFERENCES frames (id), 
	CONSTRAINT fk_analyses_model_id_ai_models FOREIGN KEY(model_id) REFERENCES ai_models (id)
);

CREATE INDEX ix_analyses_frame_id ON analyses (frame_id);

CREATE INDEX ix_analyses_model_id ON analyses (model_id);

CREATE TABLE crew_members (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	crew_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_crew_members PRIMARY KEY (id), 
	CONSTRAINT uq_crew_members_crew_id UNIQUE (crew_id, user_id), 
	CONSTRAINT fk_crew_members_crew_id_crews FOREIGN KEY(crew_id) REFERENCES crews (id), 
	CONSTRAINT fk_crew_members_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_crew_members_crew_id ON crew_members (crew_id);

CREATE INDEX ix_crew_members_user_id ON crew_members (user_id);

CREATE TABLE gps_samples (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	frame_id VARCHAR(36) NOT NULL, 
	lat FLOAT NOT NULL, 
	lng FLOAT NOT NULL, 
	accuracy FLOAT NOT NULL, 
	CONSTRAINT pk_gps_samples PRIMARY KEY (id), 
	CONSTRAINT ck_gps_samples_latitude CHECK (lat BETWEEN -90 AND 90), 
	CONSTRAINT ck_gps_samples_longitude CHECK (lng BETWEEN -180 AND 180), 
	CONSTRAINT ck_gps_samples_accuracy CHECK (accuracy BETWEEN 0 AND 100), 
	CONSTRAINT fk_gps_samples_frame_id_frames FOREIGN KEY(frame_id) REFERENCES frames (id)
);

CREATE INDEX ix_gps_samples_frame_id ON gps_samples (frame_id);

CREATE TABLE potholes (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	zone_id VARCHAR(36), 
	lat FLOAT NOT NULL, 
	lng FLOAT NOT NULL, 
	kind VARCHAR(180) NOT NULL, 
	status VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_potholes PRIMARY KEY (id), 
	CONSTRAINT ck_potholes_coordinates CHECK (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180), 
	CONSTRAINT ck_potholes_status CHECK (status IN ('UNVERIFIED','CONFIRMED','IN_PROGRESS','REPAIRED','REJECTED')), 
	CONSTRAINT fk_potholes_zone_id_zones FOREIGN KEY(zone_id) REFERENCES zones (id)
);

CREATE INDEX ix_potholes_location ON potholes (lat, lng);

CREATE INDEX ix_potholes_zone_id ON potholes (zone_id);

CREATE TABLE subscriptions (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	zone_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_subscriptions PRIMARY KEY (id), 
	CONSTRAINT uq_subscriptions_user_id UNIQUE (user_id, zone_id), 
	CONSTRAINT fk_subscriptions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT fk_subscriptions_zone_id_zones FOREIGN KEY(zone_id) REFERENCES zones (id)
);

CREATE INDEX ix_subscriptions_user_id ON subscriptions (user_id);

CREATE INDEX ix_subscriptions_zone_id ON subscriptions (zone_id);

CREATE TABLE zone_road_segments (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	zone_id VARCHAR(36) NOT NULL, 
	segment_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_zone_road_segments PRIMARY KEY (id), 
	CONSTRAINT uq_zone_road_segments_zone_id UNIQUE (zone_id, segment_id), 
	CONSTRAINT fk_zone_road_segments_zone_id_zones FOREIGN KEY(zone_id) REFERENCES zones (id), 
	CONSTRAINT fk_zone_road_segments_segment_id_road_segments FOREIGN KEY(segment_id) REFERENCES road_segments (id)
);

CREATE INDEX ix_zone_road_segments_segment_id ON zone_road_segments (segment_id);

CREATE INDEX ix_zone_road_segments_zone_id ON zone_road_segments (zone_id);

CREATE TABLE detections (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(180) NOT NULL, 
	bounding_box JSONB, 
	confidence FLOAT, 
	CONSTRAINT pk_detections PRIMARY KEY (id), 
	CONSTRAINT fk_detections_analysis_id_analyses FOREIGN KEY(analysis_id) REFERENCES analyses (id)
);

CREATE INDEX ix_detections_analysis_id ON detections (analysis_id);

CREATE TABLE notifications (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	pothole_id VARCHAR(36), 
	body TEXT NOT NULL, 
	read_at BIGINT, 
	CONSTRAINT pk_notifications PRIMARY KEY (id), 
	CONSTRAINT fk_notifications_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT fk_notifications_pothole_id_potholes FOREIGN KEY(pothole_id) REFERENCES potholes (id)
);

CREATE INDEX ix_notifications_pothole_id ON notifications (pothole_id);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE TABLE status_events (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	pothole_id VARCHAR(36) NOT NULL, 
	actor_id VARCHAR(36), 
	old_status VARCHAR(180) NOT NULL, 
	new_status VARCHAR(180) NOT NULL, 
	reason TEXT NOT NULL, 
	CONSTRAINT pk_status_events PRIMARY KEY (id), 
	CONSTRAINT fk_status_events_pothole_id_potholes FOREIGN KEY(pothole_id) REFERENCES potholes (id), 
	CONSTRAINT fk_status_events_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_status_events_actor_id ON status_events (actor_id);

CREATE INDEX ix_status_events_pothole_id ON status_events (pothole_id);

CREATE TABLE work_orders (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	pothole_id VARCHAR(36) NOT NULL, 
	crew_id VARCHAR(36) NOT NULL, 
	status VARCHAR(180) NOT NULL, 
	due_at BIGINT, 
	CONSTRAINT pk_work_orders PRIMARY KEY (id), 
	CONSTRAINT fk_work_orders_pothole_id_potholes FOREIGN KEY(pothole_id) REFERENCES potholes (id), 
	CONSTRAINT fk_work_orders_crew_id_crews FOREIGN KEY(crew_id) REFERENCES crews (id)
);

CREATE INDEX ix_work_orders_crew_id ON work_orders (crew_id);

CREATE INDEX ix_work_orders_pothole_id ON work_orders (pothole_id);

CREATE TABLE repairs (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	order_id VARCHAR(36) NOT NULL, 
	description TEXT NOT NULL, 
	finished_at BIGINT NOT NULL, 
	CONSTRAINT pk_repairs PRIMARY KEY (id), 
	CONSTRAINT fk_repairs_order_id_work_orders FOREIGN KEY(order_id) REFERENCES work_orders (id)
);

CREATE INDEX ix_repairs_order_id ON repairs (order_id);

CREATE TABLE reports (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	pothole_id VARCHAR(36) NOT NULL, 
	detection_id VARCHAR(36), 
	session_id VARCHAR(36) NOT NULL, 
	accuracy FLOAT NOT NULL, 
	description TEXT NOT NULL, 
	CONSTRAINT pk_reports PRIMARY KEY (id), 
	CONSTRAINT ck_reports_accuracy CHECK (accuracy BETWEEN 0 AND 100), 
	CONSTRAINT fk_reports_pothole_id_potholes FOREIGN KEY(pothole_id) REFERENCES potholes (id), 
	CONSTRAINT fk_reports_detection_id_detections FOREIGN KEY(detection_id) REFERENCES detections (id), 
	CONSTRAINT fk_reports_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_reports_detection_id ON reports (detection_id);

CREATE INDEX ix_reports_pothole_id ON reports (pothole_id);

CREATE INDEX ix_reports_recent ON reports (created_at);

CREATE INDEX ix_reports_session_id ON reports (session_id);

CREATE TABLE work_order_events (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	order_id VARCHAR(36) NOT NULL, 
	actor_id VARCHAR(36) NOT NULL, 
	description TEXT NOT NULL, 
	CONSTRAINT pk_work_order_events PRIMARY KEY (id), 
	CONSTRAINT fk_work_order_events_order_id_work_orders FOREIGN KEY(order_id) REFERENCES work_orders (id), 
	CONSTRAINT fk_work_order_events_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_work_order_events_actor_id ON work_order_events (actor_id);

CREATE INDEX ix_work_order_events_order_id ON work_order_events (order_id);

CREATE TABLE comments (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	report_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	body TEXT NOT NULL, 
	CONSTRAINT pk_comments PRIMARY KEY (id), 
	CONSTRAINT fk_comments_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id), 
	CONSTRAINT fk_comments_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_comments_report_id ON comments (report_id);

CREATE INDEX ix_comments_user_id ON comments (user_id);

CREATE TABLE confirmations (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	report_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	confirmed BOOLEAN NOT NULL, 
	CONSTRAINT pk_confirmations PRIMARY KEY (id), 
	CONSTRAINT uq_confirmations_report_id UNIQUE (report_id, user_id), 
	CONSTRAINT fk_confirmations_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id), 
	CONSTRAINT fk_confirmations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_confirmations_report_id ON confirmations (report_id);

CREATE INDEX ix_confirmations_user_id ON confirmations (user_id);

CREATE TABLE repair_materials (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	repair_id VARCHAR(36) NOT NULL, 
	material_id VARCHAR(36) NOT NULL, 
	quantity FLOAT NOT NULL, 
	CONSTRAINT pk_repair_materials PRIMARY KEY (id), 
	CONSTRAINT uq_repair_materials_repair_id UNIQUE (repair_id, material_id), 
	CONSTRAINT ck_repair_materials_quantity CHECK (quantity > 0), 
	CONSTRAINT fk_repair_materials_repair_id_repairs FOREIGN KEY(repair_id) REFERENCES repairs (id), 
	CONSTRAINT fk_repair_materials_material_id_materials FOREIGN KEY(material_id) REFERENCES materials (id)
);

CREATE INDEX ix_repair_materials_material_id ON repair_materials (material_id);

CREATE INDEX ix_repair_materials_repair_id ON repair_materials (repair_id);

CREATE TABLE report_media (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	report_id VARCHAR(36) NOT NULL, 
	storage_url TEXT NOT NULL, 
	mime_type VARCHAR(180) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	CONSTRAINT pk_report_media PRIMARY KEY (id), 
	CONSTRAINT fk_report_media_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id)
);

CREATE INDEX ix_report_media_report_id ON report_media (report_id);

CREATE TABLE risk_assessments (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	report_id VARCHAR(36), 
	pothole_id VARCHAR(36) NOT NULL, 
	score INTEGER NOT NULL, 
	level VARCHAR(180) NOT NULL, 
	method VARCHAR(180) NOT NULL, 
	CONSTRAINT pk_risk_assessments PRIMARY KEY (id), 
	CONSTRAINT ck_risk_assessments_score CHECK (score BETWEEN 0 AND 100), 
	CONSTRAINT ck_risk_assessments_level CHECK (level IN ('LOW','MEDIUM','HIGH','CRITICAL')), 
	CONSTRAINT fk_risk_assessments_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id), 
	CONSTRAINT fk_risk_assessments_pothole_id_potholes FOREIGN KEY(pothole_id) REFERENCES potholes (id)
);

CREATE INDEX ix_risk_assessments_pothole_id ON risk_assessments (pothole_id);

CREATE INDEX ix_risk_assessments_report_id ON risk_assessments (report_id);

CREATE INDEX ix_risk_assessments_score ON risk_assessments (score);

CREATE TABLE assessment_factors (
	id VARCHAR(36) NOT NULL, 
	created_at BIGINT NOT NULL, 
	assessment_id VARCHAR(36) NOT NULL, 
	factor_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_assessment_factors PRIMARY KEY (id), 
	CONSTRAINT uq_assessment_factors_assessment_id UNIQUE (assessment_id, factor_id), 
	CONSTRAINT fk_assessment_factors_assessment_id_risk_assessments FOREIGN KEY(assessment_id) REFERENCES risk_assessments (id), 
	CONSTRAINT fk_assessment_factors_factor_id_risk_factors FOREIGN KEY(factor_id) REFERENCES risk_factors (id)
);

CREATE INDEX ix_assessment_factors_assessment_id ON assessment_factors (assessment_id);

CREATE INDEX ix_assessment_factors_factor_id ON assessment_factors (factor_id);
