-- Server-only volatile transaction evaluator. Durable authority: Supabase PostgreSQL.
CREATE TABLE product_model(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  version INTEGER NOT NULL CHECK(version=2));

CREATE TABLE packages(
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  source_json TEXT NOT NULL CHECK(json_valid(source_json)),
  active_revision_id INTEGER REFERENCES package_revisions(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);

CREATE TABLE package_revisions(
  id INTEGER PRIMARY KEY,
  package_id INTEGER NOT NULL REFERENCES packages(id),
  version INTEGER NOT NULL CHECK(version>0),
  digest TEXT NOT NULL,
  manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)
    AND (json_extract(manifest_json,'$.schema') IS 'runteams.skill-revision/v2' OR json_extract(manifest_json,'$.schema') IS 'runteams.skill-revision/v3')),
  blob_ref TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(package_id,version), UNIQUE(package_id,digest));

CREATE TABLE employees(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  avatar TEXT NOT NULL,
  draft_json TEXT NOT NULL CHECK(json_valid(draft_json)
    AND json_extract(draft_json,'$.schema') IS 'runteams.employee-draft/v2'),
  draft_revision INTEGER NOT NULL DEFAULT 0 CHECK(draft_revision>=0),
  source_json TEXT NOT NULL CHECK(json_valid(source_json)
    AND json_extract(source_json,'$.kind') IN ('authored','marketplace')
    AND json_type(source_json,'$.author_id') IS 'text'),
  active_release_id INTEGER REFERENCES employee_releases(id) ON DELETE SET NULL,
  restored_from_release_id INTEGER REFERENCES employee_releases(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  trashed_at TEXT);

CREATE TABLE employee_releases(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  version INTEGER NOT NULL CHECK(version>0),
  digest TEXT NOT NULL,
  snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)
    AND (json_extract(snapshot_json,'$.schema') IS 'runteams.employee-release/v3' OR json_extract(snapshot_json,'$.schema') IS 'runteams.employee-release/v4')),
  restored_from_release_id INTEGER REFERENCES employee_releases(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  UNIQUE(employee_id,version));

CREATE TABLE employee_module_provisions(
  employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  module_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(employee_id,module_id));

CREATE TRIGGER frozen_skill_revision BEFORE UPDATE ON package_revisions BEGIN
  SELECT RAISE(ABORT, 'Skill revisions are immutable');
END;

CREATE TRIGGER frozen_employee_release BEFORE UPDATE ON employee_releases BEGIN
  SELECT RAISE(ABORT, 'Employee releases are immutable');
END;

CREATE TABLE marketplace_publications(
  actor_id TEXT NOT NULL,
  listing_id TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK(source_type IN ('employee','pipeline')),
  source_id INTEGER NOT NULL,
  PRIMARY KEY(actor_id,listing_id),
  UNIQUE(actor_id,source_type,source_id));

CREATE TABLE pipeline_marketplace_employee_refs(
  pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  portable_ref TEXT NOT NULL UNIQUE,
  PRIMARY KEY(pipeline_id,employee_id));

CREATE TABLE pipelines(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, definition_json TEXT NOT NULL, source_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, trashed_at TEXT,
  paused_at TEXT, active_release_id INTEGER REFERENCES pipeline_releases(id) ON DELETE SET NULL, restored_from_release_id INTEGER REFERENCES pipeline_releases(id) ON DELETE SET NULL);

CREATE TABLE pipeline_releases(
  id INTEGER PRIMARY KEY, pipeline_id INTEGER NOT NULL REFERENCES pipelines(id),
  version INTEGER NOT NULL, digest TEXT NOT NULL, snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(pipeline_id,version), UNIQUE(pipeline_id,digest));

CREATE TRIGGER pipeline_releases_immutable
BEFORE UPDATE ON pipeline_releases BEGIN SELECT RAISE(ABORT, 'pipeline release is immutable'); END;

CREATE TABLE marketplace_installs(
  actor_id TEXT NOT NULL, publisher_id TEXT NOT NULL, listing_id TEXT NOT NULL,
  receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)), updated_at TEXT NOT NULL,
  PRIMARY KEY(actor_id,publisher_id,listing_id));

CREATE TABLE tasks(
  id INTEGER PRIMARY KEY, pipeline_id INTEGER REFERENCES pipelines(id),
  employee_id INTEGER REFERENCES employees(id),
  start_column_key TEXT,
  opportunity_key TEXT,
  title TEXT NOT NULL, payload_json TEXT NOT NULL, state TEXT NOT NULL,
  pipeline_snapshot_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, trashed_at TEXT,
  CHECK ((pipeline_id IS NOT NULL) != (employee_id IS NOT NULL)));

CREATE UNIQUE INDEX idx_tasks_employee_opportunity
ON tasks(employee_id,opportunity_key)
WHERE employee_id IS NOT NULL AND opportunity_key IS NOT NULL;

CREATE UNIQUE INDEX idx_tasks_pipeline_opportunity
ON tasks(pipeline_id,opportunity_key)
WHERE pipeline_id IS NOT NULL AND opportunity_key IS NOT NULL;

CREATE TABLE workflow_runs(
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),
  state TEXT NOT NULL, available_at TEXT, manual_column_key TEXT,
  cursor_key TEXT,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE employee_runs(
  id INTEGER PRIMARY KEY, workflow_run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
  position_key TEXT NOT NULL, employee_release_id INTEGER REFERENCES employee_releases(id),
  attempt INTEGER NOT NULL, state TEXT NOT NULL, input_json TEXT NOT NULL,
  output_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workflow_run_id,position_key,attempt));

CREATE TABLE artifacts(
  id INTEGER PRIMARY KEY, employee_run_id INTEGER REFERENCES employee_runs(id),
  name TEXT NOT NULL, ref TEXT NOT NULL, meta_json TEXT NOT NULL, created_at TEXT NOT NULL, trashed_at TEXT);

CREATE TABLE events(
  id INTEGER PRIMARY KEY, stream TEXT NOT NULL, type TEXT NOT NULL,
  data_json TEXT NOT NULL, created_at TEXT NOT NULL,
  actor_id TEXT, correlation_id TEXT, source TEXT NOT NULL DEFAULT 'system',
  schema_version INTEGER NOT NULL DEFAULT 1,
  prev_hash TEXT, event_hash TEXT);

CREATE INDEX idx_events_correlation ON events(correlation_id,id);

CREATE INDEX idx_events_stream ON events(stream,id);

CREATE INDEX idx_events_type_stream ON events(type,stream,id);

CREATE INDEX idx_employee_runs_workflow ON employee_runs(workflow_run_id,id);

CREATE INDEX idx_workflow_source_chat ON workflow_runs(
  CAST(json_extract(snapshot_json,'$.source.chat_id') AS INTEGER),id);

CREATE TABLE business_connections(
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  external_account_id TEXT NOT NULL,
  credential_ref TEXT NOT NULL,
  granted_operations_json TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active',
  cursor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(provider, external_account_id));

CREATE TABLE business_events(
  id INTEGER PRIMARY KEY,
  connection_id INTEGER NOT NULL REFERENCES business_connections(id),
  provider_event_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  workflow_run_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(connection_id,provider_event_id));

CREATE INDEX idx_business_events_pending
  ON business_events(state,id);

CREATE TABLE business_connection_grants(
  id INTEGER PRIMARY KEY,
  connection_id INTEGER NOT NULL REFERENCES business_connections(id),
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  operations_json TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(connection_id,employee_id));

CREATE TABLE employee_module_bindings(
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  module_id TEXT NOT NULL,
  primary_connection_id INTEGER NOT NULL REFERENCES business_connections(id),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(employee_id,module_id));

CREATE TABLE business_actions(
  id INTEGER PRIMARY KEY,
  connection_id INTEGER NOT NULL REFERENCES business_connections(id),
  operation_key TEXT NOT NULL,
  operation TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  request_json TEXT NOT NULL,
  state TEXT NOT NULL,
  receipt_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(connection_id,operation_key));

CREATE TABLE catalog_terms(
 id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('profession','industry','capability')),
 name TEXT NOT NULL, definition TEXT NOT NULL DEFAULT '',
 aliases_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(aliases_json) AND json_type(aliases_json)='array'),
 details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json) AND json_type(details_json)='object'),
 maintainer TEXT NOT NULL DEFAULT '', review_due_at TEXT, retired_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE catalog_term_relations(
 id INTEGER PRIMARY KEY,
 source_term_id INTEGER NOT NULL REFERENCES catalog_terms(id),
 target_term_id INTEGER NOT NULL REFERENCES catalog_terms(id),
 relation TEXT NOT NULL CHECK(relation IN ('requires','applies_to')),
 rationale TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(source_term_id != target_term_id),
 UNIQUE(source_term_id,target_term_id,relation));

CREATE TABLE catalog_asset_terms(
 id INTEGER PRIMARY KEY,
 asset_kind TEXT NOT NULL CHECK(asset_kind IN ('employee','employee_skill','package','native_extension','pipeline')),
 asset_ref TEXT NOT NULL, term_id INTEGER NOT NULL REFERENCES catalog_terms(id),
 rationale TEXT NOT NULL DEFAULT '', applicability TEXT NOT NULL DEFAULT '',
 maintainer TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(asset_kind,asset_ref,term_id));

CREATE TABLE catalog_references(
 id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE,
 term_id INTEGER REFERENCES catalog_terms(id),
 asset_kind TEXT CHECK(asset_kind IN ('employee','employee_skill','package','native_extension','pipeline')),
 asset_ref TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('standard','case','rule','review','counterexample')),
 title TEXT NOT NULL, source_url TEXT,
 artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
 source_locator TEXT NOT NULL DEFAULT '', source_version TEXT NOT NULL DEFAULT '',
 source_digest TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 evidence_status TEXT NOT NULL DEFAULT 'proposed' CHECK(evidence_status IN ('proposed','source_backed')),
 content_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(content_json) AND json_type(content_json)='object'),
 maintainer TEXT NOT NULL DEFAULT '', checked_at TEXT, review_due_at TEXT, retired_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK((term_id IS NOT NULL) != (asset_ref IS NOT NULL)),
 CHECK((asset_ref IS NULL AND asset_kind IS NULL) OR (asset_ref IS NOT NULL AND asset_kind IS NOT NULL)),
 CHECK(source_url IS NOT NULL OR artifact_id IS NOT NULL));

CREATE INDEX idx_catalog_relations_target ON catalog_term_relations(target_term_id);

CREATE INDEX idx_catalog_asset_terms_term ON catalog_asset_terms(term_id,asset_kind);

CREATE INDEX idx_catalog_references_term ON catalog_references(term_id);

CREATE INDEX idx_catalog_references_asset ON catalog_references(asset_kind,asset_ref);

CREATE INDEX idx_catalog_references_review ON catalog_references(review_due_at) WHERE retired_at IS NULL;

CREATE TRIGGER catalog_employee_deleted AFTER DELETE ON employees BEGIN
 DELETE FROM catalog_asset_terms WHERE
  (asset_kind='employee' AND asset_ref='employee:'||OLD.id) OR
  (asset_kind='employee_skill' AND substr(asset_ref,1,length('employee-skill:'||OLD.id||'/'))='employee-skill:'||OLD.id||'/');
 DELETE FROM catalog_references WHERE
  (asset_kind='employee' AND asset_ref='employee:'||OLD.id) OR
  (asset_kind='employee_skill' AND substr(asset_ref,1,length('employee-skill:'||OLD.id||'/'))='employee-skill:'||OLD.id||'/');
END;

CREATE TRIGGER catalog_pipeline_deleted AFTER DELETE ON pipelines BEGIN
 DELETE FROM catalog_asset_terms WHERE asset_kind='pipeline' AND asset_ref='pipeline:'||OLD.id;
 DELETE FROM catalog_references WHERE asset_kind='pipeline' AND asset_ref='pipeline:'||OLD.id;
END;

CREATE TRIGGER catalog_package_deleted AFTER DELETE ON packages BEGIN
 DELETE FROM catalog_asset_terms WHERE asset_kind='package' AND asset_ref='package:'||OLD.key;
 DELETE FROM catalog_references WHERE asset_kind='package' AND asset_ref='package:'||OLD.key;
END;

CREATE TABLE job_sources(
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  connector_kind TEXT NOT NULL CHECK(connector_kind IN(
    'boss_selected_capture','file_import','public_ats','employer_site','authorized_connector')),
  authorization_status TEXT NOT NULL CHECK(authorization_status IN(
    'manual_selection','public_access','written_authorization','disabled')),
  authorization_basis TEXT NOT NULL DEFAULT '',
  policy_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(policy_json) AND json_type(policy_json)='object'),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE jd_research_scopes(
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  scope_kind TEXT NOT NULL CHECK(scope_kind IN('profession_family','profession','specialization')),
  parent_scope_id INTEGER REFERENCES jd_research_scopes(id),
  catalog_profession_term_id INTEGER REFERENCES catalog_terms(id) ON DELETE SET NULL,
  definition_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(definition_json) AND json_type(definition_json)='object'),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN('active','archived')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(id!=parent_scope_id)
);

CREATE TABLE job_postings(
  id INTEGER PRIMARY KEY,
  canonical_key TEXT NOT NULL UNIQUE,
  source_id INTEGER NOT NULL REFERENCES job_sources(id),
  external_job_id TEXT,
  source_url TEXT,
  company_name TEXT NOT NULL DEFAULT '',
  normalized_company_name TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  normalized_title TEXT NOT NULL DEFAULT '',
  location_text TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN('active','closed','unknown','deleted')),
  detail_status TEXT NOT NULL DEFAULT 'pending' CHECK(detail_status IN(
    'pending','fetching','complete','retryable','needs_login','blocked','unavailable')),
  detail_ref_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_ref_json) AND json_type(detail_ref_json)='object'),
  detail_last_error TEXT NOT NULL DEFAULT '',
  detail_updated_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  current_version_id INTEGER,
  created_by_actor_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source_id,external_job_id)
);

CREATE TABLE jd_list_scans(
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES job_sources(id),
  query_json TEXT NOT NULL CHECK(json_valid(query_json) AND json_type(query_json)='object'),
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN(
    'running','completed','partial','needs_login','blocked','failed')),
  discovered_count INTEGER NOT NULL DEFAULT 0 CHECK(discovered_count>=0),
  new_posting_count INTEGER NOT NULL DEFAULT 0 CHECK(new_posting_count>=0),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  created_by_actor_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE job_posting_discoveries(
  scan_id INTEGER NOT NULL REFERENCES jd_list_scans(id) ON DELETE CASCADE,
  posting_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  page_no INTEGER NOT NULL DEFAULT 1 CHECK(page_no>0),
  rank_no INTEGER CHECK(rank_no IS NULL OR rank_no>0),
  is_new INTEGER NOT NULL DEFAULT 0 CHECK(is_new IN(0,1)),
  observed_at TEXT NOT NULL,
  source_ref_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_ref_json) AND json_type(source_ref_json)='object'),
  PRIMARY KEY(scan_id,posting_id)
);

CREATE TABLE jd_detail_jobs(
  posting_id INTEGER PRIMARY KEY REFERENCES job_postings(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN(
    'pending','fetching','completed','retryable','needs_login','blocked','unavailable')),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0),
  available_at TEXT,
  lease_until TEXT,
  last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE job_posting_versions(
  id INTEGER PRIMARY KEY,
  posting_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  version_no INTEGER NOT NULL CHECK(version_no>0),
  content_sha256 TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  description_text TEXT NOT NULL,
  source_facts_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_facts_json) AND json_type(source_facts_json)='object'),
  completeness_json TEXT NOT NULL CHECK(json_valid(completeness_json) AND json_type(completeness_json)='object'),
  normalized_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(normalized_json) AND json_type(normalized_json)='object'),
  parser_status TEXT NOT NULL DEFAULT 'pending' CHECK(parser_status IN('pending','running','parsed','needs_review','failed')),
  parser_version TEXT NOT NULL DEFAULT '',
  captured_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(posting_id,version_no),
  UNIQUE(posting_id,content_sha256)
);

CREATE TABLE job_posting_scopes(
  posting_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  scope_id INTEGER NOT NULL REFERENCES jd_research_scopes(id) ON DELETE CASCADE,
  assignment_status TEXT NOT NULL DEFAULT 'automatic' CHECK(assignment_status IN('automatic','reviewed')),
  confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),
  is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN(0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(posting_id,scope_id)
);

CREATE TABLE jd_parse_jobs(
  id INTEGER PRIMARY KEY,
  posting_version_id INTEGER NOT NULL UNIQUE REFERENCES job_posting_versions(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN('pending','running','completed','needs_review','failed')),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0),
  available_at TEXT,
  last_error TEXT NOT NULL DEFAULT '',
  runtime_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(runtime_json) AND json_type(runtime_json)='object'),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE job_evidence(
  id INTEGER PRIMARY KEY,
  posting_version_id INTEGER NOT NULL REFERENCES job_posting_versions(id) ON DELETE CASCADE,
  evidence_kind TEXT NOT NULL CHECK(evidence_kind IN(
    'responsibility','deliverable','input','tool','collaboration','qualification',
    'acceptance_signal','business_context')),
  normalized_value TEXT NOT NULL,
  source_quote TEXT NOT NULL,
  source_start INTEGER,
  source_end INTEGER,
  extractor_version TEXT NOT NULL,
  confidence REAL CHECK(confidence IS NULL OR (confidence>=0 AND confidence<=1)),
  review_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK(review_status IN('unreviewed','accepted','rejected')),
  created_at TEXT NOT NULL
);

CREATE TABLE work_concepts(
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK(kind IN(
    'work_activity','deliverable','capability','tool','business_context','qualification','generic_trait')),
  name TEXT NOT NULL,
  definition TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN('candidate','approved','merged','retired')),
  merged_into_concept_id INTEGER REFERENCES work_concepts(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(id!=merged_into_concept_id),
  CHECK(status!='merged' OR merged_into_concept_id IS NOT NULL)
);

CREATE TABLE work_concept_aliases(
  id INTEGER PRIMARY KEY,
  concept_id INTEGER NOT NULL REFERENCES work_concepts(id) ON DELETE CASCADE,
  alias_text TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  locale TEXT NOT NULL DEFAULT 'zh-CN',
  review_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK(review_status IN('unreviewed','accepted','rejected')),
  created_at TEXT NOT NULL,
  UNIQUE(concept_id,normalized_alias)
);

CREATE TABLE job_evidence_concepts(
  evidence_id INTEGER NOT NULL REFERENCES job_evidence(id) ON DELETE CASCADE,
  concept_id INTEGER NOT NULL REFERENCES work_concepts(id),
  mapping_status TEXT NOT NULL DEFAULT 'automatic' CHECK(mapping_status IN('automatic','reviewed','rejected')),
  confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),
  mapper_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(evidence_id,concept_id)
);

CREATE TABLE work_concept_stats(
  concept_id INTEGER NOT NULL REFERENCES work_concepts(id) ON DELETE CASCADE,
  scope_key TEXT NOT NULL,
  unique_posting_count INTEGER NOT NULL CHECK(unique_posting_count>=0),
  unique_employer_count INTEGER NOT NULL CHECK(unique_employer_count>=0),
  total_posting_count INTEGER NOT NULL CHECK(total_posting_count>=unique_posting_count),
  posting_prevalence REAL NOT NULL CHECK(posting_prevalence>=0 AND posting_prevalence<=1),
  employer_prevalence REAL NOT NULL CHECK(employer_prevalence>=0 AND employer_prevalence<=1),
  demand_class TEXT NOT NULL CHECK(demand_class IN('insufficient','core','common','contextual','niche')),
  calculation_version TEXT NOT NULL,
  calculated_at TEXT NOT NULL,
  PRIMARY KEY(concept_id,scope_key)
);

CREATE TABLE work_concept_catalog_terms(
  concept_id INTEGER NOT NULL REFERENCES work_concepts(id) ON DELETE CASCADE,
  catalog_term_id INTEGER NOT NULL REFERENCES catalog_terms(id) ON DELETE CASCADE,
  relation TEXT NOT NULL DEFAULT 'maps_to' CHECK(relation IN('maps_to','supports','evidences')),
  review_status TEXT NOT NULL DEFAULT 'proposed' CHECK(review_status IN('proposed','approved','rejected')),
  rationale TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(concept_id,catalog_term_id,relation)
);

CREATE TABLE job_role_clusters(
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  scope_id INTEGER REFERENCES jd_research_scopes(id),
  scope_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(scope_json) AND json_type(scope_json)='object'),
  status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN('candidate','reviewing','approved','retired')),
  sample_size INTEGER NOT NULL DEFAULT 0 CHECK(sample_size>=0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE job_role_cluster_concepts(
  cluster_id INTEGER NOT NULL REFERENCES job_role_clusters(id) ON DELETE CASCADE,
  concept_id INTEGER NOT NULL REFERENCES work_concepts(id),
  role TEXT NOT NULL CHECK(role IN('core','supporting','context','excluded')),
  prevalence REAL CHECK(prevalence IS NULL OR (prevalence>=0 AND prevalence<=1)),
  rationale TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY(cluster_id,concept_id)
);

CREATE TABLE job_role_cluster_assets(
  cluster_id INTEGER NOT NULL REFERENCES job_role_clusters(id) ON DELETE CASCADE,
  asset_kind TEXT NOT NULL CHECK(asset_kind IN('employee','pipeline')),
  asset_ref TEXT NOT NULL,
  relation TEXT NOT NULL CHECK(relation IN('candidate_for','implemented_by','validated_by')),
  created_at TEXT NOT NULL,
  PRIMARY KEY(cluster_id,asset_kind,asset_ref,relation)
);

CREATE INDEX idx_job_postings_source ON job_postings(source_id,last_seen_at DESC);

CREATE INDEX idx_jd_list_scans_status ON jd_list_scans(status,id DESC);

CREATE INDEX idx_job_discoveries_posting ON job_posting_discoveries(posting_id,observed_at DESC);

CREATE INDEX idx_jd_detail_jobs_queue ON jd_detail_jobs(status,available_at,posting_id);

CREATE INDEX idx_job_posting_scopes_scope ON job_posting_scopes(scope_id,posting_id);

CREATE INDEX idx_job_versions_status ON job_posting_versions(parser_status,id);

CREATE INDEX idx_job_evidence_version ON job_evidence(posting_version_id,evidence_kind);

CREATE INDEX idx_job_evidence_concepts_concept ON job_evidence_concepts(concept_id,evidence_id);

CREATE INDEX idx_work_concept_stats_scope ON work_concept_stats(scope_key,unique_posting_count DESC);

CREATE TABLE chats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '新对话',
  title_source TEXT NOT NULL DEFAULT 'pending',
  kind TEXT NOT NULL DEFAULT 'general' CHECK(kind IN ('general','employee_design','automation')), context_json TEXT NOT NULL DEFAULT '{}',
  draft_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
  channel_id INTEGER, model TEXT NOT NULL DEFAULT '', reasoning_effort TEXT NOT NULL DEFAULT '',
  scope_pipeline_id INTEGER, extensions_enabled INTEGER NOT NULL DEFAULT 0,
  subject_type TEXT NOT NULL DEFAULT 'workspace', employee_id INTEGER,
  employee_release_id INTEGER, employee_release_digest TEXT NOT NULL DEFAULT '',
  scope_type TEXT NOT NULL DEFAULT 'global', scope_run_id INTEGER,
  runtime_provider TEXT NOT NULL DEFAULT '', runtime_generation INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
  role TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', applied TEXT,
  attachments TEXT NOT NULL DEFAULT '[]', capabilities TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}', ts TEXT NOT NULL);

CREATE TABLE automations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,prompt TEXT NOT NULL DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1,schedule_kind TEXT NOT NULL DEFAULT 'interval',
          interval_sec INTEGER NOT NULL DEFAULT 3600,schedule_config TEXT NOT NULL DEFAULT '{}',
          channel_id INTEGER,model TEXT NOT NULL DEFAULT '',reasoning_effort TEXT NOT NULL DEFAULT '',
          next_run_at TEXT NOT NULL DEFAULT '',last_run_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
          trashed_at TEXT NOT NULL DEFAULT '',trash_meta TEXT NOT NULL DEFAULT '{}');

CREATE TABLE automation_runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,automation_id INTEGER NOT NULL,
          scheduled_for TEXT NOT NULL,trigger_kind TEXT NOT NULL DEFAULT 'scheduled' CHECK(trigger_kind IN ('scheduled','manual')),triggered_at TEXT NOT NULL DEFAULT '',chat_id INTEGER,
          status TEXT NOT NULL DEFAULT 'queued',reason TEXT NOT NULL DEFAULT '',
          snapshot_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT '',
          completed_at TEXT NOT NULL DEFAULT '');

CREATE TABLE automation_run_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,automation_run_id INTEGER NOT NULL,
          ts TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'agent_event',content_json TEXT NOT NULL DEFAULT '{}');

CREATE INDEX idx_automations_due ON automations(enabled,next_run_at);

CREATE INDEX idx_automation_runs_automation ON automation_runs(automation_id,id DESC);

CREATE INDEX idx_automation_runs_status ON automation_runs(status,id);

CREATE INDEX idx_automation_run_events_run ON automation_run_events(automation_run_id,id);

CREATE INDEX idx_automations_trash ON automations(trashed_at,updated_at DESC);

CREATE TRIGGER trg_automation_run_chat_internal
        AFTER UPDATE OF chat_id ON automation_runs
        WHEN NEW.chat_id IS NOT NULL
        BEGIN
          UPDATE chats SET kind='automation' WHERE id=NEW.chat_id;
        END;

CREATE TABLE employee_automations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER, pipeline_id INTEGER REFERENCES pipelines(id),
      name TEXT NOT NULL, work_order_json TEXT NOT NULL DEFAULT '{}',
      enabled INTEGER NOT NULL DEFAULT 1, schedule_kind TEXT NOT NULL DEFAULT 'interval',
      interval_sec INTEGER NOT NULL DEFAULT 3600, schedule_config TEXT NOT NULL DEFAULT '{}',
      next_run_at TEXT NOT NULL DEFAULT '', last_run_at TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      trashed_at TEXT NOT NULL DEFAULT '', trash_meta TEXT NOT NULL DEFAULT '{}',
      CHECK ((employee_id IS NOT NULL) != (pipeline_id IS NOT NULL)));

CREATE TABLE employee_automation_runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, employee_automation_id INTEGER NOT NULL,
      scheduled_for TEXT NOT NULL, trigger_kind TEXT NOT NULL DEFAULT 'scheduled' CHECK(trigger_kind IN ('scheduled','manual')), triggered_at TEXT NOT NULL DEFAULT '',
      task_id INTEGER, workflow_run_id INTEGER, status TEXT NOT NULL DEFAULT 'queued',
      reason TEXT NOT NULL DEFAULT '', snapshot_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT '', completed_at TEXT NOT NULL DEFAULT '');

CREATE TABLE employee_automation_run_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, employee_automation_run_id INTEGER NOT NULL,
      ts TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'system', content_json TEXT NOT NULL DEFAULT '{}');

CREATE INDEX idx_employee_automations_due ON employee_automations(enabled,next_run_at);

CREATE INDEX idx_employee_automation_runs_status ON employee_automation_runs(status,id);

CREATE INDEX idx_employee_automation_runs_automation ON employee_automation_runs(employee_automation_id,id DESC);

CREATE TABLE account_preferences(
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL CHECK(json_valid(value)),
 updated_at TEXT NOT NULL);
