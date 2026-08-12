CREATE TABLE ai_suggestion_feedback (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR, 
	doctor_id VARCHAR, 
	suggestion_category VARCHAR(20) NOT NULL, 
	suggestion_id VARCHAR(100), 
	suggestion_text TEXT NOT NULL, 
	verdict VARCHAR(10) NOT NULL, 
	comment TEXT, 
	prompt_version VARCHAR(20), 
	prompt_scene VARCHAR(50), 
	model_name VARCHAR(100), 
	recorded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_ai_feedback_prompt_version ON ai_suggestion_feedback (prompt_version);

CREATE INDEX ix_ai_suggestion_feedback_doctor_id ON ai_suggestion_feedback (doctor_id);

CREATE INDEX ix_ai_suggestion_feedback_encounter_id ON ai_suggestion_feedback (encounter_id);

CREATE INDEX ix_ai_suggestion_feedback_prompt_version ON ai_suggestion_feedback (prompt_version);

CREATE INDEX ix_ai_suggestion_feedback_suggestion_category ON ai_suggestion_feedback (suggestion_category);

CREATE TABLE audit_logs (
	id VARCHAR NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	user_id VARCHAR(36), 
	user_name VARCHAR(50), 
	user_role VARCHAR(30), 
	action VARCHAR(50) NOT NULL, 
	resource_type VARCHAR(50), 
	resource_id VARCHAR(36), 
	detail TEXT, 
	ip_address VARCHAR(50), 
	status VARCHAR(10) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE departments (
	id VARCHAR NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	code VARCHAR(50) NOT NULL, 
	parent_id VARCHAR, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	FOREIGN KEY(parent_id) REFERENCES departments (id)
);

CREATE TABLE model_configs (
	id VARCHAR NOT NULL, 
	scene VARCHAR(50) NOT NULL, 
	model_name VARCHAR(100) NOT NULL, 
	temperature FLOAT NOT NULL, 
	max_tokens INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	description TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (scene)
);

CREATE TABLE problem_list (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR NOT NULL, 
	problem_name VARCHAR(200) NOT NULL, 
	icd_code VARCHAR(20), 
	onset_date VARCHAR(30), 
	status VARCHAR(20) NOT NULL, 
	is_primary BOOLEAN NOT NULL, 
	added_by VARCHAR(50), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_problem_list_encounter_id ON problem_list (encounter_id);

CREATE TABLE progress_notes (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR NOT NULL, 
	note_type VARCHAR(30) NOT NULL, 
	title VARCHAR(200), 
	content TEXT NOT NULL, 
	recorded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	recorded_by VARCHAR(50), 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_progress_notes_encounter_id ON progress_notes (encounter_id);

CREATE TABLE prompt_templates (
	id VARCHAR NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	scene VARCHAR(50), 
	content TEXT NOT NULL, 
	version VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE qc_rules (
	id VARCHAR NOT NULL, 
	rule_code VARCHAR(20) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	rule_type VARCHAR(30), 
	scope VARCHAR(20) NOT NULL, 
	gender_scope VARCHAR(10) NOT NULL, 
	field_name VARCHAR(50), 
	keywords JSON, 
	indication_keywords JSON, 
	risk_level VARCHAR(10), 
	issue_description TEXT, 
	suggestion TEXT, 
	score_impact VARCHAR(20), 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rule_code)
);

CREATE TABLE revoked_tokens (
	jti VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (jti)
);

CREATE TABLE vital_signs (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR NOT NULL, 
	recorded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	temperature FLOAT, 
	pulse INTEGER, 
	respiration INTEGER, 
	bp_systolic INTEGER, 
	bp_diastolic INTEGER, 
	spo2 INTEGER, 
	weight FLOAT, 
	height FLOAT, 
	notes TEXT, 
	recorded_by VARCHAR(50), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_vital_signs_encounter_id ON vital_signs (encounter_id);

CREATE TABLE users (
	id VARCHAR NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	real_name VARCHAR(50) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	department_id VARCHAR, 
	employee_no VARCHAR(50), 
	phone VARCHAR(20), 
	email VARCHAR(100), 
	is_active BOOLEAN NOT NULL, 
	last_login_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	FOREIGN KEY(department_id) REFERENCES departments (id)
);

CREATE TABLE patients (
	id VARCHAR NOT NULL, 
	patient_no VARCHAR(50), 
	name VARCHAR(50) NOT NULL, 
	name_pinyin VARCHAR(512), 
	name_pinyin_initials VARCHAR(128), 
	gender VARCHAR(10), 
	birth_date DATE, 
	id_card VARCHAR(20), 
	phone VARCHAR(20), 
	address VARCHAR, 
	is_from_his BOOLEAN NOT NULL, 
	is_deleted BOOLEAN NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	deleted_by VARCHAR, 
	ethnicity VARCHAR(20), 
	marital_status VARCHAR(10), 
	occupation VARCHAR(100), 
	workplace VARCHAR(200), 
	contact_name VARCHAR(50), 
	contact_phone VARCHAR(20), 
	contact_relation VARCHAR(20), 
	blood_type VARCHAR(10), 
	profile JSONB, 
	profile_past_history TEXT, 
	profile_allergy_history TEXT, 
	profile_family_history TEXT, 
	profile_personal_history TEXT, 
	profile_current_medications TEXT, 
	profile_marital_history TEXT, 
	profile_menstrual_history TEXT, 
	profile_religion_belief TEXT, 
	profile_updated_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (patient_no), 
	FOREIGN KEY(deleted_by) REFERENCES users (id)
);

CREATE UNIQUE INDEX uq_patients_id_card_active ON patients (id_card) WHERE id_card IS NOT NULL AND is_deleted = false;

CREATE TABLE encounters (
	id VARCHAR NOT NULL, 
	patient_id VARCHAR NOT NULL, 
	doctor_id VARCHAR NOT NULL, 
	department_id VARCHAR, 
	visit_type VARCHAR(20) NOT NULL, 
	visit_no VARCHAR(50), 
	is_first_visit BOOLEAN NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	chief_complaint_brief VARCHAR(200), 
	visited_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITHOUT TIME ZONE, 
	bed_no VARCHAR(20), 
	admission_route VARCHAR(20), 
	admission_condition VARCHAR(10), 
	cancel_reason VARCHAR(500), 
	cancelled_at TIMESTAMP WITHOUT TIME ZONE, 
	cancelled_by VARCHAR, 
	his_external_ref JSONB, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(patient_id) REFERENCES patients (id), 
	FOREIGN KEY(doctor_id) REFERENCES users (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id), 
	FOREIGN KEY(cancelled_by) REFERENCES users (id)
);

CREATE INDEX idx_encounters_doctor_visited ON encounters (doctor_id, visited_at);

CREATE INDEX idx_encounters_his_patient_no ON encounters USING gin ((his_external_ref -> 'his_patient_no'));

CREATE TABLE imaging_studies (
	id VARCHAR NOT NULL, 
	patient_id VARCHAR NOT NULL, 
	uploaded_by VARCHAR NOT NULL, 
	study_instance_uid VARCHAR(128), 
	modality VARCHAR(20), 
	body_part VARCHAR(100), 
	series_description VARCHAR(200), 
	study_date TIMESTAMP WITHOUT TIME ZONE, 
	total_frames INTEGER NOT NULL, 
	storage_dir VARCHAR(500), 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT imaging_studies_study_instance_uid_key UNIQUE (study_instance_uid), 
	FOREIGN KEY(patient_id) REFERENCES patients (id), 
	FOREIGN KEY(uploaded_by) REFERENCES users (id)
);

CREATE INDEX idx_imaging_studies_study_instance_uid ON imaging_studies (study_instance_uid);

CREATE TABLE imaging_reports (
	id VARCHAR NOT NULL, 
	study_id VARCHAR NOT NULL, 
	radiologist_id VARCHAR, 
	published_by VARCHAR, 
	selected_frames JSONB, 
	ai_analysis TEXT, 
	final_report TEXT, 
	is_published BOOLEAN NOT NULL, 
	published_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (study_id), 
	FOREIGN KEY(study_id) REFERENCES imaging_studies (id), 
	FOREIGN KEY(radiologist_id) REFERENCES users (id)
);

CREATE TABLE inquiry_inputs (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR NOT NULL, 
	chief_complaint TEXT, 
	history_present_illness TEXT, 
	past_history TEXT, 
	allergy_history TEXT, 
	personal_history TEXT, 
	physical_exam TEXT, 
	initial_impression TEXT, 
	temperature VARCHAR(10), 
	pulse VARCHAR(10), 
	respiration VARCHAR(10), 
	bp_systolic VARCHAR(10), 
	bp_diastolic VARCHAR(10), 
	spo2 VARCHAR(10), 
	height VARCHAR(10), 
	weight VARCHAR(10), 
	marital_history TEXT, 
	menstrual_history TEXT, 
	family_history TEXT, 
	history_informant TEXT, 
	current_medications TEXT, 
	rehabilitation_assessment TEXT, 
	religion_belief TEXT, 
	pain_assessment TEXT, 
	vte_risk TEXT, 
	nutrition_assessment TEXT, 
	psychology_assessment TEXT, 
	auxiliary_exam TEXT, 
	admission_diagnosis TEXT, 
	tcm_inspection TEXT, 
	tcm_auscultation TEXT, 
	tongue_coating TEXT, 
	pulse_condition TEXT, 
	western_diagnosis TEXT, 
	tcm_disease_diagnosis TEXT, 
	tcm_syndrome_diagnosis TEXT, 
	treatment_method TEXT, 
	treatment_plan TEXT, 
	followup_advice TEXT, 
	precautions TEXT, 
	observation_notes TEXT, 
	patient_disposition TEXT, 
	visit_time VARCHAR(30), 
	onset_time VARCHAR(50), 
	version INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(encounter_id) REFERENCES encounters (id)
);

CREATE INDEX idx_inquiry_inputs_enc_ver ON inquiry_inputs (encounter_id, version);

CREATE TABLE lab_reports (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR, 
	doctor_id VARCHAR, 
	original_filename VARCHAR(300), 
	file_path VARCHAR(500), 
	mime_type VARCHAR(100), 
	ocr_text TEXT, 
	status VARCHAR(20) NOT NULL, 
	analyzed_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(encounter_id) REFERENCES encounters (id), 
	FOREIGN KEY(doctor_id) REFERENCES users (id)
);

CREATE TABLE medical_records (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR NOT NULL, 
	record_type VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	current_version INTEGER NOT NULL, 
	submitted_at TIMESTAMP WITHOUT TIME ZONE, 
	patient_snapshot JSONB, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(encounter_id) REFERENCES encounters (id)
);

CREATE INDEX idx_medical_records_enc_type ON medical_records (encounter_id, record_type);

CREATE TABLE voice_records (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR, 
	doctor_id VARCHAR, 
	visit_type VARCHAR(20), 
	status VARCHAR(20) NOT NULL, 
	raw_transcript TEXT, 
	audio_file_path VARCHAR(500), 
	mime_type VARCHAR(100), 
	transcript_summary TEXT, 
	speaker_dialogue TEXT, 
	structured_inquiry TEXT, 
	draft_record TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(encounter_id) REFERENCES encounters (id), 
	FOREIGN KEY(doctor_id) REFERENCES users (id)
);

CREATE TABLE ai_tasks (
	id VARCHAR NOT NULL, 
	encounter_id VARCHAR, 
	medical_record_id VARCHAR, 
	task_type VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	input_snapshot JSONB, 
	output_result JSONB, 
	model_name VARCHAR(50), 
	prompt_version VARCHAR(20), 
	token_input INTEGER, 
	token_output INTEGER, 
	duration_ms INTEGER, 
	error_message TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(encounter_id) REFERENCES encounters (id), 
	FOREIGN KEY(medical_record_id) REFERENCES medical_records (id)
);

CREATE TABLE record_versions (
	id VARCHAR NOT NULL, 
	medical_record_id VARCHAR NOT NULL, 
	version_no INTEGER NOT NULL, 
	content JSONB NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	triggered_by VARCHAR, 
	ai_task_id VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	sign_hash VARCHAR(64), 
	prev_hash VARCHAR(64), 
	ai_similarity FLOAT, 
	ai_base_version_no INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(medical_record_id) REFERENCES medical_records (id), 
	FOREIGN KEY(triggered_by) REFERENCES users (id)
);

CREATE INDEX idx_record_versions_rec_ver ON record_versions (medical_record_id, version_no);

CREATE TABLE qc_issues (
	id VARCHAR NOT NULL, 
	ai_task_id VARCHAR NOT NULL, 
	medical_record_id VARCHAR, 
	record_version_no INTEGER, 
	issue_type VARCHAR(30) NOT NULL, 
	risk_level VARCHAR(10) NOT NULL, 
	field_name VARCHAR(50), 
	issue_description TEXT NOT NULL, 
	suggestion TEXT, 
	status VARCHAR(20) NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	resolved_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ai_task_id) REFERENCES ai_tasks (id), 
	FOREIGN KEY(medical_record_id) REFERENCES medical_records (id)
)