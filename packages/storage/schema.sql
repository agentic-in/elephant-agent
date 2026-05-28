CREATE TABLE storage_metadata (
    metadata_key TEXT PRIMARY KEY,
    metadata_value TEXT NOT NULL
);

CREATE TABLE personal_models (
    personal_model_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE states (
    state_id TEXT PRIMARY KEY,
    personal_model_id TEXT NOT NULL,
    state_anchor TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    elephant_id TEXT NOT NULL DEFAULT '',
    elephant_name TEXT NOT NULL DEFAULT '',
    identity_mode TEXT NOT NULL DEFAULT '',
    posture TEXT NOT NULL DEFAULT '',
    capability_boundaries_json TEXT NOT NULL DEFAULT '[]',
    initiative TEXT NOT NULL DEFAULT '',
    working_style TEXT NOT NULL DEFAULT '',
    surface_bindings_json TEXT NOT NULL DEFAULT '[]',
    safety_boundaries_json TEXT NOT NULL DEFAULT '[]',
    disclosure_boundaries_json TEXT NOT NULL DEFAULT '[]',
    source_manifest TEXT NOT NULL DEFAULT '',
    elephant_identity_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    current_context_note TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_states_elephant_id
    ON states(elephant_id)
    WHERE elephant_id != '';
CREATE INDEX idx_states_personal_model
    ON states(personal_model_id, status);
CREATE INDEX idx_states_anchor_status
    ON states(state_anchor, status);

CREATE TABLE local_agent_runtimes (
    runtime_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    command TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    resolved_path TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'detected',
    auth_status TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL DEFAULT 'path',
    default_model TEXT NOT NULL DEFAULT '',
    can_execute INTEGER NOT NULL DEFAULT 0,
    role_title TEXT NOT NULL DEFAULT '',
    role_prompt TEXT NOT NULL DEFAULT '',
    detected_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_local_agent_runtimes_provider
    ON local_agent_runtimes(provider_id, status);

CREATE TABLE current_state_bindings (
    binding_id TEXT PRIMARY KEY CHECK(binding_id = 'current'),
    state_id TEXT,
    selected_at TEXT NOT NULL,
    FOREIGN KEY(state_id) REFERENCES states(state_id) ON DELETE SET NULL
);

CREATE TABLE episodes (
    episode_id TEXT PRIMARY KEY,
    state_id TEXT NOT NULL,
    personal_model_id TEXT NOT NULL,
    entry_surface TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    updated_at TEXT,
    exit_summary TEXT NOT NULL DEFAULT '',
    elephant_id TEXT NOT NULL DEFAULT '',
    parent_episode_id TEXT,
    interruption_state TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(state_id) REFERENCES states(state_id) ON DELETE CASCADE,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_episodes_state_started
    ON episodes(state_id, started_at);
CREATE INDEX idx_episodes_state_status_started
    ON episodes(state_id, status, started_at);
CREATE INDEX idx_episodes_personal_model_status_started
    ON episodes(personal_model_id, status, started_at);
CREATE INDEX idx_episodes_elephant_started
    ON episodes(elephant_id, started_at);

CREATE TABLE loops (
    loop_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    personal_model_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(episode_id) REFERENCES episodes(episode_id) ON DELETE CASCADE,
    FOREIGN KEY(state_id) REFERENCES states(state_id) ON DELETE CASCADE,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_loops_episode_started
    ON loops(episode_id, started_at);
CREATE INDEX idx_loops_checkpoint_scan
    ON loops(trigger_type, status, state_id, personal_model_id, started_at);

CREATE TABLE steps (
    step_id TEXT PRIMARY KEY,
    loop_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    personal_model_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('observation', 'reasoning', 'acting')),
    action TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('planned', 'completed', 'failed', 'cancelled')),
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    summary TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    payload_refs_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(loop_id) REFERENCES loops(loop_id) ON DELETE CASCADE,
    FOREIGN KEY(episode_id) REFERENCES episodes(episode_id) ON DELETE CASCADE,
    FOREIGN KEY(state_id) REFERENCES states(state_id) ON DELETE CASCADE,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE,
    UNIQUE(loop_id, sequence)
);

CREATE INDEX idx_steps_episode_sequence
    ON steps(episode_id, sequence);
CREATE INDEX idx_steps_state_pm_created
    ON steps(state_id, personal_model_id, created_at);

CREATE TABLE semantic_index_entries (
    semantic_index_entry_id TEXT PRIMARY KEY,
    owner_scope TEXT NOT NULL CHECK(owner_scope IN ('state', 'personal_model')),
    source_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
    content_hash TEXT NOT NULL,
    personal_model_id TEXT,
    state_id TEXT,
    backend TEXT NOT NULL DEFAULT 'sqlite-vec',
    vector_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'indexed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE,
    FOREIGN KEY(state_id) REFERENCES states(state_id) ON DELETE CASCADE,
    CHECK(owner_scope != 'personal_model' OR personal_model_id IS NOT NULL),
    CHECK(owner_scope != 'state' OR state_id IS NOT NULL),
    UNIQUE(source_id, provider_id, model_id, dimensions, content_hash)
);

CREATE TABLE learning_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    personal_model_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    loop_id TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    progress_stage TEXT NOT NULL DEFAULT '',
    progress_detail TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts >= 1),
    available_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    worker_id TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE,
    FOREIGN KEY(state_id) REFERENCES states(state_id)
        ON DELETE CASCADE,
    FOREIGN KEY(episode_id) REFERENCES episodes(episode_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_learning_jobs_status_available
    ON learning_jobs(status, available_at, created_at);
CREATE INDEX idx_learning_jobs_state_status
    ON learning_jobs(state_id, status, created_at);
CREATE INDEX idx_learning_jobs_profile_status
    ON learning_jobs(personal_model_id, status, created_at);
CREATE INDEX idx_learning_jobs_episode_type_created
    ON learning_jobs(job_type, episode_id, created_at DESC);

CREATE TABLE paths (
    path_id TEXT PRIMARY KEY,
    personal_model_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'paused', 'completed', 'dropped')),
    priority TEXT NOT NULL DEFAULT 'normal',
    review_mode TEXT NOT NULL DEFAULT 'trusted'
        CHECK(review_mode IN ('ask_first', 'trusted')),
    owner_elephant_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_paths_pm_status_updated
    ON paths(personal_model_id, status, updated_at DESC);
CREATE INDEX idx_paths_owner_updated
    ON paths(owner_elephant_id, updated_at DESC);

CREATE TABLE path_steps (
    path_step_id TEXT PRIMARY KEY,
    path_id TEXT NOT NULL,
    personal_model_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'next'
        CHECK(status IN ('later', 'next', 'moving', 'checking', 'done', 'stuck', 'dropped')),
    order_index INTEGER NOT NULL DEFAULT 0 CHECK(order_index >= 0),
    assignee_elephant_id TEXT NOT NULL DEFAULT '',
    creator_elephant_id TEXT NOT NULL DEFAULT '',
    due_at TEXT,
    related_episode_id TEXT,
    related_loop_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(path_id) REFERENCES paths(path_id) ON DELETE CASCADE,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE,
    FOREIGN KEY(related_episode_id) REFERENCES episodes(episode_id) ON DELETE SET NULL,
    FOREIGN KEY(related_loop_id) REFERENCES loops(loop_id) ON DELETE SET NULL
);

CREATE INDEX idx_path_steps_path_status_order
    ON path_steps(path_id, status, order_index, updated_at DESC);
CREATE INDEX idx_path_steps_pm_status_updated
    ON path_steps(personal_model_id, status, updated_at DESC);
CREATE INDEX idx_path_steps_assignee_status_updated
    ON path_steps(assignee_elephant_id, status, updated_at DESC);

CREATE TABLE path_step_runs (
    run_id TEXT PRIMARY KEY,
    path_step_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    personal_model_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued', 'dispatched', 'running', 'completed', 'failed', 'cancelled')),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK(attempt >= 1),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts >= 1),
    parent_run_id TEXT NOT NULL DEFAULT '',
    assignee_elephant_id TEXT NOT NULL DEFAULT '',
    runtime_id TEXT NOT NULL DEFAULT '',
    claim_token TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    work_dir TEXT NOT NULL DEFAULT '',
    progress_stage TEXT NOT NULL DEFAULT '',
    progress_detail TEXT NOT NULL DEFAULT '',
    progress_current INTEGER NOT NULL DEFAULT 0 CHECK(progress_current >= 0),
    progress_total INTEGER NOT NULL DEFAULT 0 CHECK(progress_total >= 0),
    failure_reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    started_at TEXT,
    heartbeat_at TEXT,
    lease_expires_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(path_step_id) REFERENCES path_steps(path_step_id) ON DELETE CASCADE,
    FOREIGN KEY(path_id) REFERENCES paths(path_id) ON DELETE CASCADE,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_path_step_runs_step_status_created
    ON path_step_runs(path_step_id, status, created_at DESC);
CREATE INDEX idx_path_step_runs_path_status_created
    ON path_step_runs(path_id, status, created_at DESC);
CREATE INDEX idx_path_step_runs_runtime_status_heartbeat
    ON path_step_runs(runtime_id, status, heartbeat_at DESC);
CREATE INDEX idx_path_step_runs_claim_queue
    ON path_step_runs(status, assignee_elephant_id, created_at);
CREATE INDEX idx_path_step_runs_lease
    ON path_step_runs(status, lease_expires_at);
CREATE INDEX idx_path_step_runs_parent
    ON path_step_runs(parent_run_id);

CREATE TABLE path_step_comments (
    comment_id TEXT PRIMARY KEY,
    path_step_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    personal_model_id TEXT NOT NULL,
    body TEXT NOT NULL,
    author_kind TEXT NOT NULL DEFAULT 'user'
        CHECK(author_kind IN ('user', 'elephant', 'system')),
    author_id TEXT NOT NULL DEFAULT '',
    comment_type TEXT NOT NULL DEFAULT 'comment'
        CHECK(comment_type IN ('comment', 'run_output', 'status', 'system')),
    run_id TEXT NOT NULL DEFAULT '',
    parent_comment_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(path_step_id) REFERENCES path_steps(path_step_id) ON DELETE CASCADE,
    FOREIGN KEY(path_id) REFERENCES paths(path_id) ON DELETE CASCADE,
    FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_path_step_comments_step_created
    ON path_step_comments(path_step_id, created_at ASC, comment_id ASC);
CREATE INDEX idx_path_step_comments_run_created
    ON path_step_comments(run_id, created_at ASC);
CREATE INDEX idx_path_step_comments_parent
    ON path_step_comments(parent_comment_id);

CREATE TABLE learning_summaries (
    summary_id TEXT PRIMARY KEY,
    path_step_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    summary_type TEXT NOT NULL DEFAULT 'task',
    what_done TEXT NOT NULL DEFAULT '',
    why_it_matters TEXT NOT NULL DEFAULT '',
    how_it_was_done TEXT NOT NULL DEFAULT '',
    knowledge TEXT NOT NULL DEFAULT '',
    human_takeaway TEXT NOT NULL DEFAULT '',
    created_by_elephant_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(path_step_id) REFERENCES path_steps(path_step_id) ON DELETE CASCADE,
    FOREIGN KEY(path_id) REFERENCES paths(path_id) ON DELETE CASCADE
);

CREATE INDEX idx_learning_summaries_step_created
    ON learning_summaries(path_step_id, created_at DESC);
CREATE INDEX idx_learning_summaries_path_created
    ON learning_summaries(path_id, created_at DESC);

CREATE TABLE understanding_checks (
    check_id TEXT PRIMARY KEY,
    path_step_id TEXT NOT NULL,
    summary_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'understood', 'needs_clarification', 'skipped')),
    checked_by TEXT NOT NULL DEFAULT 'user',
    checked_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(path_step_id) REFERENCES path_steps(path_step_id) ON DELETE CASCADE,
    FOREIGN KEY(summary_id) REFERENCES learning_summaries(summary_id) ON DELETE CASCADE,
    UNIQUE(summary_id, checked_by)
);

CREATE INDEX idx_understanding_checks_step_updated
    ON understanding_checks(path_step_id, updated_at DESC);

CREATE TABLE personal_model_facts (
    fact_id TEXT PRIMARY KEY,
    personal_model_id TEXT NOT NULL,
    lens TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence REAL NOT NULL,
    committed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_episode_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    supersedes_fact_id TEXT,
    metadata TEXT,
    last_accessed_at TEXT,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX idx_fact_pm_status
    ON personal_model_facts(personal_model_id, status);
CREATE INDEX idx_fact_pm_lens_status
    ON personal_model_facts(personal_model_id, lens, status);

CREATE TABLE personal_model_open_questions (
    question_id TEXT PRIMARY KEY,
    personal_model_id TEXT NOT NULL,
    lens TEXT NOT NULL,
    sub_lens TEXT NOT NULL,
    text TEXT NOT NULL,
    rationale TEXT NOT NULL,
    priority REAL NOT NULL,
    sensitivity TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    asked_count INTEGER NOT NULL DEFAULT 0,
    last_asked_at TEXT,
    last_asked_surface TEXT,
    user_response_episode_ids TEXT NOT NULL DEFAULT '[]',
    dismissed_reason TEXT,
    generated_fact_ids TEXT NOT NULL DEFAULT '[]',
    metadata TEXT
);

CREATE INDEX idx_oq_pm_status_prio
    ON personal_model_open_questions(personal_model_id, status, priority DESC);
CREATE INDEX idx_oq_pm_lens_sub_status
    ON personal_model_open_questions(personal_model_id, lens, sub_lens, status);

CREATE TABLE diary_entries (
    entry_id TEXT PRIMARY KEY,
    personal_model_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    content TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    source_episode_ids TEXT NOT NULL DEFAULT '[]',
    metadata TEXT,
    UNIQUE(personal_model_id, entry_date)
);

CREATE INDEX idx_diary_pm_date
    ON diary_entries(personal_model_id, entry_date);

CREATE TABLE personal_model_growth (
    profile_id TEXT PRIMARY KEY,
    growth_score INTEGER NOT NULL DEFAULT 0,
    total_dialogues INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_experiences INTEGER NOT NULL DEFAULT 0,
    promoted_experiences INTEGER NOT NULL DEFAULT 0,
    active_days INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    first_dialogue_at TEXT,
    last_dialogue_at TEXT,
    last_active_day TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES personal_models(personal_model_id)
        ON DELETE CASCADE
);

CREATE TABLE canonical_elephant_identities (
    profile_id TEXT PRIMARY KEY,
    elephant_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    identity_mode TEXT NOT NULL,
    personality_preset TEXT NOT NULL,
    initiative TEXT NOT NULL,
    relational_stance TEXT NOT NULL,
    working_style_contract TEXT NOT NULL,
    elephant_identity_text TEXT,
    governance_flags_json TEXT NOT NULL DEFAULT '[]',
    source_manifest_path TEXT,
    source_elephant_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES personal_models(personal_model_id) ON DELETE CASCADE
);
