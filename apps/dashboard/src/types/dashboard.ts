export type HealthTone = "healthy" | "attention" | "critical" | "neutral";

export type DashboardSection =
  | "overview"
  | "personal-models"
  | "herd"
  | "runtime"
  | "chat"
  | "questions"
  | "providers"
  | "skills"
  | "tools"
  | "gateway"
  | "cron"
  | "reflect"
  | "settings"
  | "usage"
  | "logs"
  | "usage-logs"
  | "diary";

export interface DashboardMetric {
  label: string;
  value: string;
  note: string;
  tone: HealthTone;
}

export type DashboardJson =
  | null
  | boolean
  | number
  | string
  | DashboardJson[]
  | { [key: string]: DashboardJson };

export type DashboardRow = Record<string, DashboardJson>;

export interface InternalDashboardSnapshot {
  meta: {
    generated_at: string;
    database_path: string;
    section: DashboardSection;
    available_sections: DashboardSection[];
    query_contract: string[];
  };
  overview: {
    counts: Record<string, number>;
    current_state_id: string | null;
    current_personal_model_id: string | null;
    provider_status: string;
    semantic_index_status: string;
    note: string;
  };
  herd: DashboardRow[];
  personal_models: DashboardRow[];
  states: DashboardRow[];
  runtime: {
    episodes: DashboardRow[];
    loops: DashboardRow[];
    steps: DashboardRow[];
    episode_traces: DashboardRow[];
    learning_jobs: DashboardRow[];
  };
  learning: {
    worker: DashboardRow;
    summary: DashboardRow;
    jobs: DashboardRow[];
  };
  evidence: {
    semantic_index_entries: DashboardRow[];
  };
  questions: {
    facts: DashboardRow[];
    waiting_questions: DashboardRow[];
    asked_questions: DashboardRow[];
    answered_questions: DashboardRow[];
    dismissed_questions: DashboardRow[];
    lens_coverage: DashboardRow[];
    learning_intensity: string;
    effective_policy?: DashboardRow;
    question_config?: DashboardRow;
  };
  semantic_index_health: DashboardRow;
  providers: {
    active_provider: DashboardRow;
    doctor: DashboardRow;
    embedding_provider: DashboardRow;
    auth_states: DashboardRow[];
  };
  operations: {
    skills: DashboardRow[];
    skill_affinities: DashboardRow[];
    tools: DashboardRow[];
    mcp: DashboardRow;
    cron: DashboardRow;
    gateway: DashboardRow;
    settings: DashboardRow;
    usage: DashboardRow;
    logs: DashboardRow[];
    models: DashboardRow;
  };
}

export interface DesktopCoreStatus {
  apiUrl: string;
  coreStatus: "starting" | "ready" | "stopped" | "error";
  databasePath: string;
  workerStatus: string;
  version: string;
  error?: string | null;
}

export interface SourceImportStatus {
  import_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  scanned_count: number;
  admitted_count: number;
  skipped_count: number;
  skipped_reasons: Record<string, number>;
  episode_id: string | null;
  job_id: string | null;
  error?: string | null;
  paths?: string[];
}
