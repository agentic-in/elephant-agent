import React from "react";
import { createPortal } from "react-dom";

import elephantLogo from "../../assets/brand/elephant-logo.png";

import {
  ActionButton,
  EmptyPanel,
  MetricCard,
  Panel,
  StatusBadge,
  ViewButton,
  type DetailListItem,
} from "../../components/primitives/DashboardPrimitives";
import { useDashboardSnapshot } from "../../hooks/useOperatorConsole";
import {
  answerPersonalModelQuestion,
  bumpPersonalModelQuestion,
  createCronJob,
  correctPersonalModelClaim,
  createDashboardEgg,
  deleteCustomMcpServer,
  deleteCronJob,
  deleteDiaryEntry,
  deleteDashboardEgg,
  deleteProviderKey,
  discoverCustomMcpTools,
  dismissPersonalModelQuestion,
  forgetPersonalModelClaim,
  loadProviderSetup,
  loadProviderModels,
  runCronJob,
  runGatewayAction,
  runProviderTest,
  saveOperatorGlobalConfig,
  saveProviderKey,
  setConsoleItemEnabled,
  setCronJobStatus,
  setPersonalModelQuestionIntensity,
  setCustomMcpToolEnabled,
  setDefaultProvider,
  setEmbeddingProvider,
  syncCustomMcpServer,
  triggerDiaryWrite,
  triggerReflectJob,
  updateDashboardEgg,
  type CustomMcpToolPayload,
  type DashboardEggPayload,
  type GatewayServiceConfigPayload,
} from "../../lib/dashboardApi";
import { cx } from "../../lib/classNames";
import { compactText, formatTimestamp } from "../../lib/dashboardFormatting";
import type {
  DashboardJson,
  DashboardMetric,
  DashboardSection,
  DashboardRow,
  HealthTone,
  InternalDashboardSnapshot,
} from "../../types/dashboard";
import { RoutePageHeader } from "../shared/RoutePageHeader";
import styles from "../RouteLayouts.module.css";

type PageControls = {
  refresh: () => Promise<void>;
  loading: boolean;
};

function asRows(value: DashboardJson | undefined): DashboardRow[] {
  return Array.isArray(value)
    ? value.filter((item): item is DashboardRow => item !== null && typeof item === "object" && !Array.isArray(item))
    : [];
}

function asTextList(value: DashboardJson | undefined): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return [];
    }
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item)).filter(Boolean);
      }
    } catch {
      // Fall through to a readable scalar.
    }
    return [trimmed];
  }
  return [];
}

function valueOf(row: DashboardRow | null | undefined, key: string, fallback = "n/a"): string {
  if (!row) {
    return fallback;
  }
  const item = row[key];
  if (item === null || item === undefined || item === "") {
    return fallback;
  }
  if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
    return String(item);
  }
  return JSON.stringify(item);
}

function numberOf(row: DashboardRow, key: string): number {
  const item = row[key];
  return typeof item === "number" ? item : Number(item || 0);
}

function boolOf(row: DashboardRow, key: string): boolean {
  return row[key] === true;
}

function jsonObject(value: DashboardJson | undefined): DashboardRow {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function embeddingSaveStatusMessage(result: unknown): string {
  const payload = jsonObject(result as DashboardJson | undefined);
  const embedding = jsonObject(payload.embedding_provider);
  const source = valueOf(embedding, "source", "");
  const bootstrapStatus = valueOf(embedding, "embedding_bootstrap_status", "unknown");
  if (source !== "local-default") {
    return "Embedding provider saved.";
  }
  if (bootstrapStatus === "ready") {
    return "Local semantic recall is ready. You can confirm this anytime with `elephant status`.";
  }
  if (bootstrapStatus === "pending" || bootstrapStatus === "downloading") {
    return "Local semantic recall is still preparing in the background. Use `elephant status` to watch when it's ready.";
  }
  if (bootstrapStatus === "failed") {
    return "Local semantic recall was selected, but the local setup needs attention. Use `elephant status` to see what happened.";
  }
  return "Embedding provider saved.";
}

function readString(row: DashboardRow | undefined, keys: readonly string[], fallback = ""): string {
  for (const key of keys) {
    const item = row?.[key];
    if (typeof item === "string" && item.trim()) {
      return item;
    }
    if (typeof item === "number" || typeof item === "boolean") {
      return String(item);
    }
  }
  return fallback;
}

function readBoolean(row: DashboardRow | undefined, keys: readonly string[], fallback = false): boolean {
  for (const key of keys) {
    const item = row?.[key];
    if (typeof item === "boolean") {
      return item;
    }
    if (typeof item === "string") {
      const normalized = item.trim().toLowerCase();
      if (normalized === "true") return true;
      if (normalized === "false") return false;
    }
  }
  return fallback;
}

function personalPreferredName(row: DashboardRow | undefined): string {
  return readString(row, ["user_preferred_name", "preferred_name"], "").trim();
}

function personalModelHeading(row: DashboardRow | undefined, fallback: string): string {
  return personalPreferredName(row) || fallback;
}

// What Elephant Agent has learned about the person, in a shape the You page
// can render as human facts instead of dumping raw memory blobs.
type YouProfileFact = { label: string; value: string; full?: boolean };
type YouProfileList = { label: string; items: readonly string[] };

type YouFactRow = { left: YouProfileFact; right?: YouProfileFact; full?: boolean };

function _sanitizeFactValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function _sanitizeFactList(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map((item) => _sanitizeFactValue(item)).filter(Boolean);
  }
  if (typeof value === "string") {
    return value.split(/\n|;|,/).map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function _humanFactLabel(raw: string): string {
  const normalized = raw.trim().replace(/_/g, " ").replace(/\s+/g, " ");
  const lower = normalized.toLowerCase();
  const known: Record<string, string> = {
    boundaries: "Boundaries",
    current_work: "Working on",
    current_city: "City",
    birth_date: "Birth date",
    gender: "Gender",
    hobbies: "Hobbies",
    mbti: "MBTI",
    relationship_mode: "Relationship mode",
    safety_boundaries: "Care context",
    medication_allergies: "Medication allergies",
    "medication allergies": "Medication allergies",
    food_allergies: "Food allergies",
    "food allergies": "Food allergies",
    chronic_conditions: "Health notes",
    "chronic conditions": "Health notes",
    "药物过敏": "Medication allergies",
    "慢性疾病等": "Health notes",
    "不愿给别人说、藏在心里的秘密": "Secrets you keep inside",
    "藏在心里的秘密": "Secrets you keep inside",
  };
  if (known[raw.trim()] || known[lower]) {
    return known[raw.trim()] ?? known[lower];
  }
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function _factWantsFullRow(label: string, value = ""): boolean {
  const normalized = `${label} ${value}`.toLowerCase();
  return (
    normalized.includes("hobbies")
    || normalized.includes("relationship mode")
    || normalized.includes("medication allergies")
    || normalized.includes("health notes")
    || normalized.includes("secrets you keep inside")
    || normalized.includes("不愿给别人说、藏在心里的秘密")
    || normalized.includes("mbti")
    || normalized.includes("药物过敏")
  );
}

const BASIC_FACT_LABELS = new Set([
  "Name",
  "Working on",
  "City",
  "Life stage",
  "Self-description",
  "Gender",
  "Birth date",
  "Speaks",
  "Timezone",
  "School",
  "Dream",
  "Creative hobby",
  "Media hobby",
  "Symbol",
  "Communication",
]);

const AFTER_BASIC_FACT_ORDER = [
  "Medication allergies",
  "Health notes",
  "Secrets you keep inside",
  "MBTI",
  "Hobbies",
  "Relationship mode",
];

function sortYouProfileFacts(facts: readonly YouProfileFact[]): YouProfileFact[] {
  const order = new Map<string, number>();
  AFTER_BASIC_FACT_ORDER.forEach((label, index) => order.set(label, index));
  return [...facts].sort((left, right) => {
    const leftBasic = BASIC_FACT_LABELS.has(left.label);
    const rightBasic = BASIC_FACT_LABELS.has(right.label);
    if (leftBasic !== rightBasic) return leftBasic ? -1 : 1;
    if (!leftBasic && !rightBasic) {
      return (order.get(left.label) ?? 99) - (order.get(right.label) ?? 99);
    }
    return 0;
  });
}

function _profileListFact(sectionLabel: string, item: string): YouProfileFact | null {
  const cleaned = item.trim();
  if (!cleaned) return null;
  const splitAt = cleaned.search(/[:：]/);
  if (splitAt > 0) {
    const rawLabel = cleaned.slice(0, splitAt).trim();
    const value = cleaned.slice(splitAt + 1).trim();
    const label = _humanFactLabel(rawLabel);
    return { label, value, full: _factWantsFullRow(label, value) };
  }
  for (const rawLabel of ["不愿给别人说、藏在心里的秘密", "藏在心里的秘密", "慢性疾病等", "药物过敏"]) {
    if (!cleaned.startsWith(rawLabel)) continue;
    const value = cleaned.slice(rawLabel.length).replace(/^\s+/, "").trim();
    if (!value) break;
    const label = _humanFactLabel(rawLabel);
    return { label, value, full: _factWantsFullRow(label, value) };
  }
  const label = sectionLabel;
  return { label, value: cleaned, full: _factWantsFullRow(label, cleaned) };
}

function youFactRows(facts: readonly YouProfileFact[]): YouFactRow[] {
  const rows: YouFactRow[] = [];
  const used = new Set<number>();
  const byLabel = (label: string): [number, YouProfileFact] | undefined => {
    const index = facts.findIndex((fact, candidate) => !used.has(candidate) && fact.label.toLowerCase() === label.toLowerCase());
    return index >= 0 ? [index, facts[index]] : undefined;
  };
  const pushPair = (leftLabel: string, rightLabel: string) => {
    const left = byLabel(leftLabel);
    const right = byLabel(rightLabel);
    if (!left && !right) return;
    if (left) used.add(left[0]);
    if (right) used.add(right[0]);
    rows.push({ left: left?.[1] ?? right![1], right: left ? right?.[1] : undefined });
  };
  pushPair("Name", "Gender");
  pushPair("City", "Birth date");
  facts.forEach((fact, index) => {
    if (used.has(index)) return;
    rows.push({ left: fact, full: true });
  });
  return rows;
}

// Ordered labels we want to show prominently. Any extra keys on the
// user_profile still render underneath, but these come first and with
// steady human phrasing rather than raw field names.
const YOU_FACT_ORDER: readonly { key: string; label: string }[] = [
  { key: "preferred_name", label: "Name" },
  { key: "current_work", label: "Working on" },
  { key: "current_city", label: "City" },
  { key: "birth_date", label: "Birth date" },
  { key: "age", label: "Life stage" },
  { key: "gender", label: "Gender" },
  { key: "mbti", label: "MBTI" },
  { key: "hobbies", label: "Hobbies" },
  { key: "symbolic_shorthand", label: "Symbol" },
  { key: "relationship_mode", label: "Relationship mode" },
  { key: "communication_preference", label: "Communication" },
  { key: "locale", label: "Speaks" },
  { key: "timezone", label: "Timezone" },
  { key: "school", label: "School" },
  { key: "dream", label: "Dream" },
  { key: "creative_hobby", label: "Creative hobby" },
  { key: "media_hobby", label: "Media hobby" },
];

function youProfileFacts(row: DashboardRow | undefined): {
  facts: YouProfileFact[];
  lists: YouProfileList[];
} {
  const card = row && typeof row.user_profile === "object" && row.user_profile !== null
    ? row.user_profile as Record<string, unknown>
    : {};
  const facts: YouProfileFact[] = [];
  const seen = new Set<string>();
  for (const { key, label } of YOU_FACT_ORDER) {
    const value = _sanitizeFactValue(card[key]);
    if (value) {
      facts.push({ label, value, full: _factWantsFullRow(label, value) });
      seen.add(key);
    }
  }
  // Fall back to top-level preferred_name from the model row when user_profile
  // is missing (e.g. historic profiles written before user_profile was split
  // into its own record).
  if (!seen.has("preferred_name")) {
    const fallback = personalPreferredName(row);
    if (fallback) {
      facts.unshift({ label: "Name", value: fallback });
    }
  }
  const lists: YouProfileList[] = [];
  const addListFacts = (label: string, items: readonly string[]) => {
    items.forEach((item) => {
      const fact = _profileListFact(label, item);
      if (!fact) return;
      const key = `${fact.label}:${fact.value}`.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      facts.push(fact);
    });
  };
  addListFacts("How they like to be spoken to", _sanitizeFactList(card.communication_preferences));
  addListFacts("Boundaries", _sanitizeFactList(card.boundaries));
  addListFacts("Worth remembering", _sanitizeFactList(card.biography_fragments));
  addListFacts("Pinned notes", _sanitizeFactList(card.durable_notes));
  addListFacts("What they share with you", _sanitizeFactList(card.shared_preferences));
  return { facts, lists };
}

function youFirstPersonName(row: DashboardRow | undefined): string {
  const name = personalPreferredName(row);
  return name || "you";
}

function userCard(row: DashboardRow | undefined): Record<string, unknown> {
  return row && typeof row.user_profile === "object" && row.user_profile !== null
    ? row.user_profile as Record<string, unknown>
    : {};
}

function userCardValue(row: DashboardRow | undefined, key: string, fallback = "Not set yet"): string {
  const value = _sanitizeFactValue(userCard(row)[key]);
  return value || fallback;
}

function relationshipModeFromRow(row: DashboardRow | undefined, fallback = "Learning the right distance"): string {
  const direct = userCardValue(row, "relationship_mode", "");
  if (direct) return direct;
  const shared = _sanitizeFactList(userCard(row).shared_preferences);
  const found = shared.find((item) => item.startsWith("relationship_mode="));
  return found ? found.split("=", 2)[1]?.trim() || fallback : fallback;
}

function formatCompactNumber(item: unknown): string {
  const number = typeof item === "number" ? item : Number(item || 0);
  if (!Number.isFinite(number)) {
    return "0";
  }
  return Intl.NumberFormat("en", {
    maximumFractionDigits: number >= 1_000_000 ? 1 : 0,
    notation: number >= 10_000 ? "compact" : "standard",
  }).format(number);
}

function capabilityStateLabel(item: DashboardRow): string {
  if (item.enabled) {
    return "Enabled";
  }
  if (valueOf(item, "activationMode") === "on-demand" || item.defaultEnabled === false) {
    return "On demand";
  }
  return "Disabled";
}

function skillStateLabel(item: DashboardRow): string {
  if (item.toggleable === false) {
    return "Discover only";
  }
  return capabilityStateLabel(item);
}

type RowIconKind = "models" | "skills" | "skillsDiscoverOnly" | "tools";

function RowIcon({ kind }: { kind: RowIconKind }): React.JSX.Element {
  if (kind === "models") {
    return (
      <svg className={styles.rowGlyph} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path d="M7 10.5 16 5.5l9 5-9 5-9-5Z" />
        <path d="M7 16 16 21l9-5" />
        <path d="M7 21.5 16 26.5l9-5" />
        <path d="M16 15.5v5.5M16 21v5.5" />
      </svg>
    );
  }
  if (kind === "skills" || kind === "skillsDiscoverOnly") {
    return (
      <svg className={styles.rowGlyph} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path d="M16 4 19.2 11.2 27 12 21.1 17.1 22.8 25 16 21 9.2 25 10.9 17.1 5 12 12.8 11.2 16 4Z" />
        <path d="M16 11.5v5.2l3.5 2" />
      </svg>
    );
  }
  return (
    <svg className={styles.rowGlyph} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path d="M11.5 6.5 15 10l-4.8 4.8-3.5-3.5A6.5 6.5 0 0 0 15 19.5l6.5 6.5a3.2 3.2 0 0 0 4.5-4.5L19.5 15a6.5 6.5 0 0 0-8-8.5Z" />
      <path d="M20.5 21.5 22.8 19.2M8 24l6.5-6.5" />
    </svg>
  );
}

function PaginationBar({
  totalItems,
  currentPage,
  totalPages,
  pageSize,
  label,
  onPrevious,
  onNext,
}: {
  totalItems: number;
  currentPage: number;
  totalPages: number;
  pageSize: number;
  label: string;
  onPrevious: () => void;
  onNext: () => void;
}): React.JSX.Element | null {
  if (totalItems <= pageSize) {
    return null;
  }
  return (
    <div className={styles.paginationBar}>
      <ActionButton variant="ghost" disabled={currentPage <= 0} onClick={onPrevious}>
        Previous
      </ActionButton>
      <span>{totalItems} {label} · page {currentPage + 1}/{totalPages} · {pageSize} per page</span>
      <ActionButton variant="ghost" disabled={currentPage >= totalPages - 1} onClick={onNext}>
        Next
      </ActionButton>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }): React.JSX.Element {
  return <pre className={styles.resultBlock}>{JSON.stringify(value, null, 2)}</pre>;
}

function SearchBox({
  query,
  setQuery,
  placeholder,
  actions,
  hint,
}: {
  query: string;
  setQuery: (value: string) => void;
  placeholder: string;
  actions?: React.ReactNode;
  hint?: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className={styles.filterToolbarShell}>
      <div className={styles.filterToolbar}>
        <label>
          <span>Search</span>
          <input type="search" value={query} placeholder={placeholder} onChange={(event) => setQuery(event.target.value)} />
        </label>
        {actions ? <div className={styles.filterToolbarActions}>{actions}</div> : null}
      </div>
      {hint ? <div className={styles.filterToolbarHint}>{hint}</div> : null}
    </div>
  );
}

function FloatingFormModal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  subtitle: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}): React.JSX.Element | null {
  React.useEffect(() => {
    if (!open) {
      return undefined;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div className={styles.consoleModalBackdrop} role="presentation" onMouseDown={onClose}>
      <section
        aria-label={title}
        aria-modal="true"
        className={styles.consoleModalPanel}
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className={styles.consoleModalHeader}>
          <div className={styles.consoleModalHeaderCopy}>
            <span>{subtitle}</span>
            <strong>{title}</strong>
          </div>
          <button className={styles.consoleModalClose} type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <div className={styles.consoleModalBody}>{children}</div>
        {footer ? <footer className={styles.consoleModalFooter}>{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}

function useAsyncAction(
  refresh: () => Promise<void>,
): {
  busy: string | null;
  message: string;
  run: (label: string, action: () => Promise<unknown>) => Promise<void>;
} {
  const [busy, setBusy] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState("");

  async function run(label: string, action: () => Promise<unknown>): Promise<void> {
    setBusy(label);
    setMessage("");
    try {
      await action();
      await refresh();
      setMessage(`${label} completed.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${label} failed.`);
    } finally {
      setBusy(null);
    }
  }

  return { busy, message, run };
}

function componentSteadyth(component: DashboardRow): string {
  const key = valueOf(component, "component_key", "").toLowerCase();
  if (key.includes("core")) {
    return "What seems stable about this person, kept carefully and revised only with stronger evidence.";
  }
  if (key.includes("knowledge")) {
    return "What Elephant Agent can rely on when helping this person think, decide, and remember.";
  }
  if (key.includes("episodic")) {
    return "The lived trail of recent moments that keeps understanding from becoming abstract.";
  }
  if (key.includes("procedural")) {
    return "The ways of working that should make the next interaction feel easier and more personal.";
  }
  if (key.includes("style") || key.includes("preference")) {
    return "The tone, pace, and care signals Elephant Agent should honor while responding.";
  }
  return "A grounded slice of the person model, visible here before it is trusted by future Loops.";
}

function toneForStatus(statusLike: unknown): HealthTone {
  const normalized = String(statusLike ?? "").toLowerCase();
  if (["ready", "active", "indexed", "healthy", "ok", "completed"].some((item) => normalized.includes(item))) {
    return "healthy";
  }
  if (["error", "failed", "missing", "critical"].some((item) => normalized.includes(item))) {
    return "critical";
  }
  if (["pending", "empty", "paused", "attention", "degraded", "cancelled"].some((item) => normalized.includes(item))) {
    return "attention";
  }
  return "neutral";
}

function renderDetailValue(item: DashboardJson): React.ReactNode {
  if (item === null || item === undefined) {
    return "n/a";
  }
  if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
    return String(item);
  }
  if (Array.isArray(item)) {
    const items = item.map((entry) => String(entry)).filter(Boolean);
    return items.length ? (
      <ul>
        {items.map((entry) => (
          <li key={entry}>{entry}</li>
        ))}
      </ul>
    ) : "[]";
  }
  return <code>{JSON.stringify(item, null, 2)}</code>;
}

function detailItems(row: DashboardRow): DetailListItem[] {
  return Object.entries(row).map(([key, item]) => ({
    label: key,
    value: renderDetailValue(item),
  }));
}

function learningJobDetailItems(row: DashboardRow): DetailListItem[] {
  const progressDetail = valueOf(row, "progress_detail", "");
  const items = detailItems(row).filter((item) => item.label !== "progress_detail");
  if (!progressDetail) {
    return items;
  }
  return [
    {
      label: "progress_detail",
      value: <MarkdownText text={progressDetail} />,
    },
    ...items,
  ];
}

function eggDetailItems(row: DashboardRow): DetailListItem[] {
  const eggIdentityFile = jsonObject(row.elephant_identity_file);
  const eggIdentityText = publicElephantIdentityText(valueOf(eggIdentityFile, "text", ""));
  const eggIdentityPath = valueOf(eggIdentityFile, "path", "n/a");
  return [
    ...detailItems(row).filter((item) => item.label !== "elephant_identity_file"),
    { label: "elephant_identity_path", value: eggIdentityPath },
    {
      label: "Character",
      value: <MarkdownText text={eggIdentityText || "No character written for this elephant yet."} />,
    },
  ];
}

const PERSONAL_DETAIL_LABELS: Record<string, string> = {
  approval_state: "Approval state",
  backend: "Backend",
  behavioral_state: "Behavior state",
  behavior_projections: "Behavior projections",
  candidate_count: "Candidate count",
  candidate_signals: "Candidate signals",
  candidate_updates: "Candidate updates",
  committed_source_ids: "Committed support IDs",
  communication_preferences: "Communication preferences",
  confidence: "Confidence",
  content: "Content",
  created_at: "Created",
  description: "Description",
  episode_id: "Conversation ID",
  kind: "Kind",
  label: "Label",
  layer_type: "Layer type",
  lens: "Lens",
  metadata: "Metadata",
  maturity_state: "Maturity state",
  observer: "Observer",
  observer_mode: "Observer mode",
  observer_status: "Observer status",
  owner_scope: "Owner scope",
  payload: "Payload",
  personal_model_id: "Your-Elephant Agent ID",
  proposal_status: "Proposal status",
  proposal_type: "Proposal type",
  promoter_decisions: "Promoter decisions",
  reflection_trigger: "Insight trigger",
  reflection_window_source_id: "Insight window source ID",
  reinforced_source_ids: "Reinforced support IDs",
  schema_version: "Schema version",
  semantic_index_entry_id: "Recall index ID",
  sensitivity: "Sensitivity",
  skill_id: "Skill",
  signal_type: "Signal type",
  source_id: "Source ID",
  source_ids: "Source IDs",
  stability: "Stability",
  state_id: "Elephant row ID",
  status: "Status",
  summary: "Summary",
  summary_source_id: "Summary support ID",
  support_count: "Support count",
  target_key: "Target key",
  title: "Title",
  trigger: "Trigger",
  updated_at: "Updated",
};

const PERSONAL_VALUE_LABELS: Record<string, string> = {
  active: "Active",
  approved: "Approved",
  archived: "Archived",
  committed: "Committed",
  completed: "Completed",
  core: "Core understanding",
  deferred: "Deferred",
  deleted: "Deleted",
  derived: "Derived",
  episodic_index: "From your conversations",
  false: "No",
  high: "High",
  inactive: "Inactive",
  knowledge: "Personal knowledge",
  low: "Low",
  medium: "Medium",
  no_op: "No-op",
  not_configured: "Not configured",
  pending: "Pending",
  personal_model: "Your Elephant Agent",
  procedural: "Workflow pattern",
  promoted: "Promoted",
  proposal: "Proposal",
  proposal_or_merge: "Proposal or merge",
  rejected: "Rejected",
  relationship: "Relationship understanding",
  retired: "Retired",
  state: "State",
  style: "Working style",
  disputed: "Disputed",
  true: "Yes",
  unavailable: "Unavailable",
};

type PersonalSupportKind = "fact" | "summary" | "trace" | "semantic" | "support";

function normalizedDisplayText(value: string): string {
  return value
    .replace(/\s+/g, " ")
    .replace(/[。.!！?？,，;；:：]+$/g, "")
    .trim()
    .toLowerCase();
}

function uniqueText(items: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    const trimmed = item.trim();
    const key = normalizedDisplayText(trimmed);
    if (!trimmed || !key || seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed);
  }
  return out;
}

function prettifyIdentifier(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function humanizeSupportValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "n/a";
  }
  const normalized = trimmed.toLowerCase();
  return PERSONAL_VALUE_LABELS[trimmed] ?? PERSONAL_VALUE_LABELS[normalized] ?? trimmed;
}

function labelForPersonalDetail(key: string): string {
  return PERSONAL_DETAIL_LABELS[key] ?? prettifyIdentifier(key);
}

function renderPersonalDetailValue(key: string, item: DashboardJson | undefined): React.ReactNode {
  if (item === null || item === undefined || item === "") {
    return "n/a";
  }
  if (typeof item === "string") {
    return key.endsWith("_at") ? formatWhen(item) : humanizeSupportValue(item);
  }
  if (typeof item === "number" || typeof item === "boolean") {
    return humanizeSupportValue(String(item));
  }
  if (Array.isArray(item) && item.every((entry) => entry === null || ["string", "number", "boolean"].includes(typeof entry))) {
    const values = item.map((entry) => humanizeSupportValue(String(entry))).filter(Boolean);
    return values.length ? (
      <ul>
        {values.map((entry) => (
          <li key={entry}>{entry}</li>
        ))}
      </ul>
    ) : "[]";
  }
  return <JsonBlock value={item} />;
}

function prioritizedPersonalKeys(row: DashboardRow): string[] {
  const preferred = [
    "title",
    "label",
    "summary",
    "content",
    "description",
    "kind",
    "layer_type",
    "status",
    "approval_state",
    "behavioral_state",
    "maturity_state",
    "confidence",
    "support_count",
    "proposal_type",
    "skill_id",
    "backend",
    "trigger",
    "episode_id",
    "target_key",
    "owner_scope",
    "source_id",
    "source_ids",
    "personal_model_id",
    "state_id",
    "semantic_index_entry_id",
    "created_at",
    "updated_at",
    "payload",
    "metadata",
  ];
  const keys = Object.keys(row).filter((key) => row[key] !== undefined && row[key] !== null && row[key] !== "");
  return [...preferred.filter((key) => keys.includes(key)), ...keys.filter((key) => !preferred.includes(key))];
}

function payloadRows(row: DashboardRow, key: string): DashboardRow[] {
  return asRows(jsonObject(row.payload)[key]);
}

function payloadText(row: DashboardRow, keys: readonly string[], fallback = ""): string {
  return readString(jsonObject(row.payload), keys, fallback);
}

function metadataText(row: DashboardRow, keys: readonly string[], fallback = ""): string {
  return readString(jsonObject(row.metadata), keys, fallback);
}

function normalizeSupportFamily(rawValue: string): string {
  const normalized = rawValue.toLowerCase().replace(/[-./]/g, "_");
  if (normalized.includes("relationship")) {
    return "relationship";
  }
  if (normalized.includes("procedure") || normalized.includes("skill")) {
    return "procedural_pattern";
  }
  if (normalized.includes("episode")) {
    return "episodic_index";
  }
  if (normalized.includes("personality") || normalized.includes("style")) {
    return "personality_style";
  }
  if (normalized.includes("knowledge") || normalized.includes("user_profile")) {
    return "personal_knowledge";
  }
  if (normalized.includes("core") || normalized.includes("identity") || normalized.includes("boundary")) {
    return "core_claim";
  }
  return normalized;
}

function supportFamily(row: DashboardRow): string {
  return normalizeSupportFamily(
    metadataText(row, ["component_family", "component"], "")
      || valueOf(row, "component_key", "")
      || valueOf(row, "kind", "")
      || valueOf(row, "layer_type", "")
      || valueOf(row, "schema_version", ""),
  );
}

function matchesSupportFamily(row: DashboardRow, families: readonly string[]): boolean {
  return families.includes(supportFamily(row));
}

function isCoreClaimEntry(row: DashboardRow, kind: PersonalSupportKind): boolean {
  return kind === "fact" && supportFamily(row) === "core_claim";
}

function personalSupportKind(row: DashboardRow): PersonalSupportKind {
  if (valueOf(row, "fact_id", "")) {
    return "fact";
  }
  const layerType = valueOf(row, "layer_type", "").toLowerCase();
  if (layerType === "personal_model_learning_summary") {
    return "summary";
  }
  if (layerType === "personal_model_learning_trace") {
    return "trace";
  }
  if (layerType === "personal_model_learning_source_packet") {
    return "support";
  }
  if (valueOf(row, "semantic_index_entry_id", "")) {
    return "semantic";
  }
  return "support";
}

function personalSupportTypeLabel(kind: PersonalSupportKind): string {
  switch (kind) {
    case "fact":
      return "Personal Model fact";
    case "summary":
      return "Learning summary";
    case "trace":
      return "Learning trace";
    case "semantic":
      return "Semantic recall";
    default:
      return "Supporting provenance";
  }
}

function personalSupportKey(row: DashboardRow, index: number): string {
  return (
    valueOf(row, "fact_id", "")
    || valueOf(row, "semantic_index_entry_id", "")
    || valueOf(row, "source_id", "")
    || `support-${index}`
  );
}

function summarySupportHighlights(row: DashboardRow): string[] {
  return uniqueText(
    [
      payloadText(row, ["continuation_note"], ""),
      ...payloadRows(row, "candidate_signals").flatMap((signal) => [valueOf(signal, "behavioral_effect", ""), valueOf(signal, "claim", "")]),
    ].filter((item) => item && !textLooksInternal(item)),
  ).slice(0, 3);
}

function traceSupportHighlights(row: DashboardRow): string[] {
  return uniqueText(
    [
      ...payloadRows(row, "behavior_projections").map((projection) => valueOf(projection, "effect", "")),
      ...payloadRows(row, "promoter_decisions").flatMap((decision) => [valueOf(decision, "behavioral_effect", ""), valueOf(decision, "reason", "")]),
      payloadText(row, ["reason"], ""),
    ].filter((item) => item && !textLooksInternal(item)),
  ).slice(0, 3);
}

function personalSupportHighlights(row: DashboardRow, kind: PersonalSupportKind): string[] {
  switch (kind) {
    case "fact":
      return uniqueText([valueOf(row, "text", "")].filter((item) => item && !textLooksInternal(item))).slice(0, 2);
    case "summary":
      return summarySupportHighlights(row);
    case "trace":
      return traceSupportHighlights(row);
    default:
      return [];
  }
}

function personalSupportTitle(row: DashboardRow, kind: PersonalSupportKind): string {
  const payload = jsonObject(row.payload);
  const layerType = valueOf(row, "layer_type", "");
  const preferred = humanText(
    readString(row, ["title", "label", "summary"], readString(payload, ["title", "target_key"], "")),
    "",
  );
  if (kind === "fact") {
    return preferred || prettifyIdentifier(valueOf(row, "lens", "Fact"));
  }
  if (kind === "summary") {
    return preferred || "Episode-close learning summary";
  }
  if (kind === "trace") {
    return preferred || "Learning promotion trace";
  }
  if (kind === "semantic") {
    return preferred || valueOf(row, "source_id", "Semantic recall anchor");
  }
  return preferred || (layerType ? prettifyIdentifier(layerType) : "Personal Model provenance");
}

function personalSupportSummary(row: DashboardRow, kind: PersonalSupportKind): string {
  const highlights = personalSupportHighlights(row, kind);
  if (kind === "fact") {
    return humanText(valueOf(row, "text", ""), "Committed Personal Model fact.");
  }
  if (kind === "summary") {
    return humanText(
      payloadText(row, ["continuation_note", "summary"], highlights[0] || ""),
      highlights[0] || "Observer summary available.",
    );
  }
  if (kind === "trace") {
    return humanText(payloadText(row, ["reason", "decision"], highlights[0] || ""), highlights[0] || "Promotion trace recorded.");
  }
  if (kind === "semantic") {
    return humanText(readString(row, ["summary", "content", "source_id"], ""), "Semantic recall anchor for future retrieval.");
  }
  return humanText(
    payloadText(row, ["summary", "content", "learning_text_excerpt"], rowContent(row)),
    highlights[0] || "Personal Model provenance available for inspection.",
  );
}

function personalSupportChips(row: DashboardRow, kind: PersonalSupportKind): string[] {
  const observer = jsonObject(jsonObject(row.payload).observer);
  const committedIds = jsonObject(row.payload).committed_source_ids;
  const chips = [
    kind === "fact" ? `Lens ${humanizeSupportValue(valueOf(row, "lens", ""))}` : "",
    kind === "fact" ? `Source ${humanizeSupportValue(valueOf(row, "source", ""))}` : "",
    kind === "fact" ? `Confidence ${valueOf(row, "confidence", "0")}` : "",
    kind === "summary" ? `Observer ${humanizeSupportValue(valueOf(observer, "status", ""))}` : "",
    kind === "summary" ? `Candidates ${valueOf(observer, "signal_count", "0")}` : "",
    kind === "trace" ? `Decision ${humanizeSupportValue(payloadText(row, ["decision"], ""))}` : "",
    kind === "trace" && Array.isArray(committedIds) ? `Committed ${committedIds.length}` : "",
    kind === "semantic" ? `Backend ${humanizeSupportValue(valueOf(row, "backend", ""))}` : "",
    formatWhen(row.updated_at ?? row.created_at) !== "n/a" ? `Updated ${formatWhen(row.updated_at ?? row.created_at)}` : "",
  ];
  return uniqueText(chips.filter(Boolean)).slice(0, 4);
}

function personalSupportDetailItems(row: DashboardRow): DetailListItem[] {
  const kind = personalSupportKind(row);
  const title = personalSupportTitle(row, kind);
  const summary = personalSupportSummary(row, kind);
  const highlights = personalSupportHighlights(row, kind);
  return [
    { label: "Claim type", value: personalSupportTypeLabel(kind) },
    { label: "Title", value: title },
    { label: "Current summary", value: summary },
    ...(highlights.length
      ? [
          {
            label: "Key signals",
            value: (
              <ul>
                {highlights.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ),
          } satisfies DetailListItem,
        ]
      : []),
    ...prioritizedPersonalKeys(row).map((key) => ({
      label: labelForPersonalDetail(key),
      value: renderPersonalDetailValue(key, row[key]),
    })),
  ];
}

function PersonalSupportRowCard({ row, index }: { row: DashboardRow; index: number }): React.JSX.Element {
  const kind = personalSupportKind(row);
  const title = personalSupportTitle(row, kind);
  const summary = personalSupportSummary(row, kind);
  const chips = personalSupportChips(row, kind);
  const highlights = personalSupportHighlights(row, kind).filter((item) => compactText(item, 220) !== compactText(summary, 220));
  const toneClass = {
    fact: styles.personalSupportCardFact,
    summary: styles.personalSupportCardSummary,
    trace: styles.personalSupportCardTrace,
    semantic: styles.personalSupportCardSemantic,
    support: styles.personalSupportCardSupport,
  }[kind];
  const coreClaimClass = isCoreClaimEntry(row, kind) ? styles.personalSupportCardCoreClaim : undefined;

  return (
    <article className={cx(styles.personalSupportCard, toneClass, coreClaimClass)}>
      <div className={styles.personalSupportMain}>
        <div className={styles.personalSupportHeader}>
          <div className={styles.personalSupportTitleGroup}>
            <span className={styles.personalSupportKind}>{personalSupportTypeLabel(kind)}</span>
            <strong>{title}</strong>
          </div>
          {chips.length ? (
            <div className={styles.personalSupportMeta}>
              {chips.map((chip) => (
                <span key={chip}>{chip}</span>
              ))}
            </div>
          ) : null}
        </div>
        <p className={styles.personalSupportSummary}>{compactText(summary, 260)}</p>
        {highlights.length ? (
          <ul className={styles.personalSupportHighlights}>
            {highlights.slice(0, 3).map((item) => (
              <li key={item}>{compactText(item, 220)}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className={styles.personalSupportAside}>
        <ViewButton
          className={styles.personalSupportButton}
          title={`${personalSupportTypeLabel(kind)} · ${title}`}
          items={personalSupportDetailItems(row)}
          variant="ghost"
        />
      </div>
    </article>
  );
}

function formatWhen(value: DashboardJson | undefined): string {
  if (typeof value !== "string" || !value.trim()) {
    return "n/a";
  }
  return Number.isNaN(new Date(value).getTime()) ? value : formatTimestamp(value);
}

function daysSince(value: DashboardJson | undefined): string {
  if (typeof value !== "string" || !value.trim()) return "New";
  const started = new Date(value).getTime();
  if (Number.isNaN(started)) return "New";
  const days = Math.max(1, Math.ceil((Date.now() - started) / 86_400_000));
  return `${days} day${days === 1 ? "" : "s"}`;
}

function DashboardPage({
  section,
  children,
}: {
  section: DashboardSection;
  children: (dashboard: InternalDashboardSnapshot, controls: PageControls) => React.ReactNode;
}): React.JSX.Element {
  const { dashboard, loading, error, refresh } = useDashboardSnapshot(section);

  return (
    <div className={styles.pageStack}>
      <RoutePageHeader />
      {error ? (
        <Panel
          eyebrow="API"
          title="Internal dashboard unavailable"
          detail="The dashboard could not read the internal inspection route."
        >
          <EmptyPanel title="Read failed" detail={error} />
        </Panel>
      ) : null}
      {!dashboard && !error ? (
        <Panel
          eyebrow="API"
          title="Loading dashboard data"
          detail={`Waiting for the local API to return the ${section} dashboard section.`}
        >
          <EmptyPanel title="Loading" detail="Fetching only the data this page needs." />
        </Panel>
      ) : null}
      {dashboard ? children(dashboard, { refresh, loading }) : null}
    </div>
  );
}

export function SystemPage(): React.JSX.Element {
  return (
    <DashboardPage section="overview">
      {(dashboard) => {
        const currentModel =
          dashboard.personal_models.find(
            (row) => valueOf(row, "personal_model_id", "") === (dashboard.overview.current_personal_model_id ?? ""),
          ) ?? dashboard.personal_models[0];
        const components = asRows(currentModel?.understanding_components);
        const learningSummaries = asRows(currentModel?.learning_summaries);
        const behaviorEffects = components.flatMap((component) => asTextList(component.behavioral_effects)).filter(Boolean);
        const recentEpisode = dashboard.runtime.episode_traces[0];
        const currentEgg =
          dashboard.herd.find((row) => row.current === true) ?? dashboard.herd[0];
        const learningSummary = (dashboard.learning?.summary ?? {}) as DashboardRow;
        const learningCount = dashboard.overview.counts.learning_jobs ?? learningSummaries.length;
        const activeLearningJobs = numberOf(learningSummary, "running") + numberOf(learningSummary, "queued");
        const pmFactCount = numberOf(currentModel ?? {}, "personal_model_fact_count");
        const overviewProfileFacts = youProfileFacts(currentModel).facts;
        const overviewFactRows = asRows(currentModel?.personal_model_facts);
        const waitingQuestions = dashboard.questions.waiting_questions ?? [];
        const askedQuestions = dashboard.questions.asked_questions ?? [];
        const nextQuestion = waitingQuestions[0] ?? askedQuestions[0];
        const currentFocusFact = overviewFactRows.find((row) => valueOf(jsonObject(row.metadata), "field", "") === "occupation");
        const rapportFact = overviewFactRows.find((row) => valueOf(row, "lens", "") === "identity" && valueOf(jsonObject(row.metadata), "topic", "").includes("style.companion"));
        const chapterFact = overviewFactRows.find((row) => valueOf(row, "lens", "") === "pulse" || valueOf(jsonObject(row.metadata), "topic", "").startsWith("pulse."));
        const traitFact = overviewFactRows.find((row) => valueOf(row, "lens", "") === "identity" && valueOf(jsonObject(row.metadata), "topic", "").includes("character"));
        const overviewHeading = currentModel
          ? `${personalModelHeading(currentModel, "Your Elephant Agent")} is taking shape`
          : "Your Elephant Agent begins with the next honest thread";
        const overviewRole = userCardValue(currentModel, "current_work", "");
        const overviewCity = userCardValue(currentModel, "current_city", "");
        const overviewMbti = userCardValue(currentModel, "mbti", "");
        const overviewMode = relationshipModeFromRow(currentModel, "");
        const overviewBoundary = _sanitizeFactList(userCard(currentModel).boundaries)[0] || "No care boundary written yet";
        const overviewFocus = humanText(valueOf(currentFocusFact, "text", ""), overviewRole || humanText(valueOf(chapterFact, "text", ""), "A first real conversation"));
        const overviewPlace = [overviewCity, overviewMbti].filter(Boolean).join(" · ") || humanText(valueOf(traitFact, "text", ""), "Still learning your world");
        const overviewPosture = overviewMode || humanText(valueOf(rapportFact, "text", ""), "Steady, careful, and corrigible");
        const overviewMemoryLabel = pmFactCount
          ? `${pmFactCount} things Elephant Agent can use`
          : `${overviewProfileFacts.length} profile anchor${overviewProfileFacts.length === 1 ? "" : "s"}`;
        const overviewLead = currentModel
          ? "A home view for the person Elephant Agent is learning: what matters now, how to approach you, and what Elephant Agent may ask next."
          : "No generic assistant profile here — the first chat is where Elephant Agent starts learning what should be carried forward.";
        const companionDays = daysSince(currentModel?.created_at ?? recentEpisode?.started_at);
        const conversationCount = String(dashboard.overview.counts.episodes ?? 0);
        const questionCount = waitingQuestions.length + askedQuestions.length;
        const nextQuestionText = humanText(valueOf(nextQuestion, "text", ""), "No open question right now — conversation can lead naturally.");
        return (
          <>
            <section className={styles.companionHero} aria-label="Elephant Agent overview">
              <div className={styles.companionAvatarWrap}>
                <div className={styles.companionAura} />
                <div className={styles.companionAvatar}>
                  <img src={elephantLogo} alt="" />
                </div>
              </div>
              <div className={styles.companionCopy}>
                <span>Home</span>
                <h2>{overviewHeading}</h2>
                <p>{behaviorEffects[0] || overviewLead}</p>
              </div>
              <div className={styles.companionStats}>
                <div>
                  <span>Together</span>
                  <strong>{companionDays}</strong>
                </div>
                <div>
                  <span>Threads</span>
                  <strong>{conversationCount}</strong>
                </div>
                <div>
                  <span>Questions</span>
                  <strong>{questionCount ? `${questionCount} open` : "clear"}</strong>
                </div>
              </div>
            </section>

            <div className={styles.contentGridDouble}>
              <Panel
                eyebrow="Personal Model"
                title="What Elephant Agent can carry into the next reply"
                detail="A home snapshot of the person, not an audit table. Deeper evidence stays on You and Evidence."
              >
                <div className={styles.statusDetailGrid}>
                  <article className={styles.statusDetailCard}>
                    <span>What is alive now</span>
                    <strong>{overviewFocus}</strong>
                    <p className={styles.statusDetailSummary}>{overviewPlace}</p>
                  </article>
                  <article className={styles.statusDetailCard}>
                    <span>How to be with you</span>
                    <strong>{overviewPosture}</strong>
                    <p className={styles.statusDetailSummary}>
                      {behaviorEffects[1] || "Start gentle and specific; revise the read whenever new evidence arrives."}
                    </p>
                  </article>
                  <article className={styles.statusDetailCard}>
                    <span>Care to remember</span>
                    <strong>{overviewBoundary}</strong>
                    <p className={styles.statusDetailSummary}>
                      {pmFactCount ? overviewMemoryLabel : "Nothing to overstate yet — let the next thread teach Elephant Agent."}
                    </p>
                  </article>
                </div>
              </Panel>

              <Panel
                eyebrow="Questions"
                title={nextQuestion ? "What Elephant Agent may ask next" : "No question queued"}
                detail="Pulled from the same Questions surface, so the home page matches what Elephant Agent is actually trying to learn."
              >
                {nextQuestion ? (
                  <article className={styles.feedRow}>
                    <span className={styles.feedRowMeta}>{valueOf(nextQuestion, "lens", "question")} · {valueOf(nextQuestion, "sub_lens", valueOf(nextQuestion, "topic", ""))}</span>
                    <strong>{nextQuestionText}</strong>
                    <p>{valueOf(nextQuestion, "rationale", "Only worth asking when the answer would make future help better.")}</p>
                  </article>
                ) : recentEpisode ? (
                  <article className={styles.feedRow}>
                    <span className={styles.feedRowMeta}>{formatWhen(recentEpisode.started_at)}</span>
                    <strong>{valueOf(recentEpisode, "exit_summary", "Conversation closed")}</strong>
                    <p>A soft landing point for returning to the conversation.</p>
                  </article>
                ) : (
                  <EmptyPanel title="Nothing to ask yet" detail="Wake Elephant Agent and speak normally — the first useful overview will grow from that thread." />
                )}
              </Panel>
            </div>

            <section className={styles.metricGrid}>
              {[
                {
                  label: "Known anchors",
                  value: String(Math.max(overviewProfileFacts.length, pmFactCount)),
                  note: "Names, context, care notes, and patterns Elephant Agent can actually use.",
                  tone: overviewProfileFacts.length || pmFactCount ? "healthy" : "attention",
                },
                {
                  label: "Herd to return to",
                  value: String(dashboard.overview.counts.states ?? 0),
                  note: "Named continuity threads that can reopen with their own context.",
                  tone: dashboard.overview.counts.states ? "healthy" : "attention",
                },
                {
                  label: "Conversation threads",
                  value: String(dashboard.overview.counts.episodes ?? 0),
                  note: "Places where the relationship has already started to leave a trace.",
                  tone: dashboard.overview.counts.episodes ? "healthy" : "neutral",
                },
                {
                  label: "Reflections carried",
                  value: activeLearningJobs ? `${activeLearningJobs} settling` : `${valueOf(learningSummary, "completed", "0")} settled`,
                  note: learningCount ? `${learningCount} reflection job${learningCount === 1 ? "" : "s"} total.` : "No background reflection yet — conversation comes first.",
                  tone: numberOf(learningSummary, "failed")
                    ? "critical"
                    : activeLearningJobs
                      ? "attention"
                      : numberOf(learningSummary, "completed")
                        ? "healthy"
                        : "neutral",
                },
                {
                  label: "Questions waiting",
                  value: questionCount ? String(questionCount) : "0",
                  note: questionCount ? "Open prompts that may deepen future help." : "Nothing queued; conversation can lead naturally.",
                  tone: questionCount ? "attention" : "healthy",
                },
              ].map((metric) => (
                <MetricCard key={metric.label} metric={metric as DashboardMetric} />
              ))}
            </section>
          </>
        );
      }}
    </DashboardPage>
  );
}

function rowContent(row: DashboardRow): string {
  return humanText(
    readString(row, ["content", "summary", "description", "skill_id", "source_id"], ""),
    "",
  );
}

function supportDisplayText(row: DashboardRow): string {
  const kind = personalSupportKind(row);
  const summary = personalSupportSummary(row, kind);
  return summary || rowContent(row);
}

function supportTextKey(row: DashboardRow): string {
  return normalizedDisplayText(supportDisplayText(row));
}

function uniqueSupportRows(rows: readonly DashboardRow[], seenText?: Set<string>): DashboardRow[] {
  const seen = seenText ?? new Set<string>();
  const out: DashboardRow[] = [];
  const seenIds = new Set<string>();
  rows.forEach((row, index) => {
    const id = personalSupportKey(row, index);
    const textKey = supportTextKey(row);
    if (seenIds.has(id)) return;
    if (textKey && seen.has(textKey)) return;
    seenIds.add(id);
    if (textKey) seen.add(textKey);
    out.push(row);
  });
  return out;
}

function latestMeaningfulText(rows: readonly DashboardRow[], fallback: string, seenText?: Set<string>): string {
  for (const row of rows) {
    const text = supportDisplayText(row) || rowContent(row);
    const key = normalizedDisplayText(text);
    if (!text || (seenText && key && seenText.has(key))) continue;
    if (seenText && key) seenText.add(key);
    return compactText(text, 260);
  }
  return fallback;
}

function findComponent(components: readonly DashboardRow[], needles: readonly string[]): DashboardRow | undefined {
  return components.find((component) => {
    const haystack = `${valueOf(component, "component_key", "")} ${valueOf(component, "label", "")}`.toLowerCase();
    return needles.some((needle) => haystack.includes(needle));
  });
}

function componentEffects(component: DashboardRow | undefined): string[] {
  return component ? asTextList(component.behavioral_effects).filter((item) => !textLooksInternal(item)).slice(0, 3) : [];
}

function learningSignalRows(summary: DashboardRow): DashboardRow[] {
  const payload = jsonObject(summary.payload);
  return asRows(payload.candidate_signals);
}

function learningBehaviorLines(learningSummaries: readonly DashboardRow[], learningTraces: readonly DashboardRow[]): string[] {
  const fromSummaries = learningSummaries.flatMap((summary) =>
    learningSignalRows(summary).map((signal) => valueOf(signal, "behavioral_effect", "")).filter(Boolean),
  );
  const fromTraces = learningTraces.flatMap((trace) =>
    asRows(jsonObject(trace.payload).behavior_projections).map((projection) => valueOf(projection, "effect", "")).filter(Boolean),
  );
  return uniqueText([...fromSummaries, ...fromTraces].filter((item) => item && !textLooksInternal(item))).slice(0, 8);
}

const FACT_IDENTITY_FIELDS = new Set(["preferred_name", "occupation", "age", "gender", "mbti", "city"]);
const FACT_RELATIONSHIP_FIELDS = new Set(["inferred_companion_posture", "safety_boundaries", "communication_preference", "relationship_mode"]);

function factField(row: DashboardRow): string {
  return valueOf(jsonObject(row.metadata), "field", "");
}

function factsForLayer(facts: readonly DashboardRow[], lens: string, fields?: ReadonlySet<string>): DashboardRow[] {
  return facts.filter((row) => {
    if (valueOf(row, "lens", "") !== lens) return false;
    return !fields || fields.has(factField(row));
  });
}

type PersonalLayer = {
  key: string;
  eyebrow: string;
  title: string;
  body: string;
  details: string[];
  claims: DashboardRow[];
  evidence: DashboardRow[];
  defaultOpen?: boolean;
};

function personalLayers({
  facts,
}: {
  displayName: string;
  components: DashboardRow[];
  facts: DashboardRow[];
  reflections: DashboardRow[];
  learningSummaries: DashboardRow[];
  learningTraces: DashboardRow[];
}): PersonalLayer[] {
  const identityFacts = facts.filter((row) => valueOf(row, "lens", "") === "identity");
  const worldFacts = facts.filter((row) => valueOf(row, "lens", "") === "world");
  const pulseFacts = facts.filter((row) => valueOf(row, "lens", "") === "pulse");
  const journeyFacts = facts.filter((row) => valueOf(row, "lens", "") === "journey");

  const layerBody = (rows: DashboardRow[], fallback: string): string => {
    const first = rows.find((r) => valueOf(r, "text", "").trim());
    return first ? valueOf(first, "text", fallback) : fallback;
  };

  return [
    {
      key: "identity",
      eyebrow: "Identity",
      title: "Who you are",
      body: layerBody(identityFacts, "No durable Identity claim has settled yet."),
      details: [],
      claims: identityFacts,
      evidence: [],
      defaultOpen: true,
    },
    {
      key: "world",
      eyebrow: "World",
      title: "Your world",
      body: layerBody(worldFacts, "No World claim has settled yet."),
      details: [],
      claims: worldFacts,
      evidence: [],
      defaultOpen: true,
    },
    {
      key: "pulse",
      eyebrow: "Pulse",
      title: "Where you are now",
      body: layerBody(pulseFacts, "No current Pulse claim has settled yet."),
      details: [],
      claims: pulseFacts,
      evidence: [],
      defaultOpen: true,
    },
    {
      key: "journey",
      eyebrow: "Journey",
      title: "Your journey",
      body: layerBody(journeyFacts, "No Journey claim has settled yet."),
      details: [],
      claims: journeyFacts,
      evidence: [],
      defaultOpen: false,
    },
  ];
}

function claimRef(row: DashboardRow): string {
  return valueOf(row, "ref", valueOf(row, "fact_id", ""));
}

function claimTopic(row: DashboardRow): string {
  return valueOf(jsonObject(row.metadata), "topic", valueOf(row, "topic", "claim"));
}

const LAYER_PAGE_SIZE = 6;

function LayerClaimList({ claims, layerKey, refresh }: { claims: DashboardRow[]; layerKey: string; refresh: () => Promise<void> }): React.JSX.Element {
  const [page, setPage] = React.useState(0);
  const totalPages = Math.max(1, Math.ceil(claims.length / LAYER_PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const visible = claims.slice(currentPage * LAYER_PAGE_SIZE, currentPage * LAYER_PAGE_SIZE + LAYER_PAGE_SIZE);

  return (
    <div className={styles.feedList}>
      {visible.map((claim, claimIndex) => {
        const ref = claimRef(claim) || `${layerKey}-${currentPage}-${claimIndex}`;
        return (
          <article key={ref} className={cx(styles.feedRow, styles.personalClaimRow)}>
            <div className={styles.personalClaimCopy}>
              <span className={styles.feedRowMeta}>{valueOf(claim, "source", valueOf(jsonObject(claim.metadata), "source_kind", "claim"))} · {valueOf(claim, "confidence", "")}</span>
              <strong>{valueOf(claim, "text", "")}</strong>
            </div>
            <div className={styles.personalClaimActions}>
              <ActionButton className={styles.personalClaimActionButton} variant="ghost" onClick={() => void correctClaimFromDashboard(claim, refresh)}>Correct</ActionButton>
              <ActionButton className={styles.personalClaimActionButton} variant="ghost" onClick={() => void forgetClaimFromDashboard(claim, refresh)}>Forget</ActionButton>
            </div>
          </article>
        );
      })}
      {totalPages > 1 && (
        <div className={styles.personalClaimPager}>
          <ActionButton variant="ghost" disabled={currentPage <= 0} onClick={() => setPage((p) => p - 1)}>←</ActionButton>
          <span>{currentPage + 1} / {totalPages}</span>
          <ActionButton variant="ghost" disabled={currentPage >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>→</ActionButton>
        </div>
      )}
    </div>
  );
}

async function correctClaimFromDashboard(row: DashboardRow, refresh: () => Promise<void>): Promise<void> {
  const ref = claimRef(row);
  if (!ref) return;
  const current = valueOf(row, "text", "");
  const next = window.prompt("Correct this Personal Model claim", current);
  const trimmed = (next ?? "").trim();
  if (!trimmed || trimmed === current.trim()) return;
  await correctPersonalModelClaim(ref, {
    text: trimmed,
    lens: valueOf(row, "lens", "identity"),
    topic: claimTopic(row),
    reason: "dashboard correction",
  });
  await refresh();
}

async function forgetClaimFromDashboard(row: DashboardRow, refresh: () => Promise<void>): Promise<void> {
  const ref = claimRef(row);
  if (!ref) return;
  const ok = window.confirm("Forget this Personal Model claim?");
  if (!ok) return;
  await forgetPersonalModelClaim(ref, {
    lens: valueOf(row, "lens", "identity"),
    topic: claimTopic(row),
    reason: "dashboard forget",
  });
  await refresh();
}

function DiarySection(): React.JSX.Element {
  const { dashboard: diaryDashboard, refresh: refreshDiary } = useDashboardSnapshot("diary");
  const [writingDate, setWritingDate] = React.useState("");
  const [isWriting, setIsWriting] = React.useState(false);
  const [deletingDate, setDeletingDate] = React.useState<string | null>(null);
  const [writeStatus, setWriteStatus] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(0);
  const pageSize = 2;

  const entries = (diaryDashboard as any)?.diary?.entries ?? [];
  const latestEntry = entries.length > 0 ? entries[0] : null;
  const olderEntries = entries.slice(1);
  const totalPages = Math.max(1, Math.ceil(olderEntries.length / pageSize));
  const currentPage = Math.min(page, totalPages - 1);
  const visibleOlder = olderEntries.slice(currentPage * pageSize, (currentPage + 1) * pageSize);

  async function handleWriteDiary() {
    const date = writingDate || new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    setIsWriting(true);
    setWriteStatus(null);
    try {
      await triggerDiaryWrite(date);
      setWriteStatus(`Writing diary for ${date}…`);
      setTimeout(() => { refreshDiary(); setWriteStatus(null); }, 10000);
    } catch (err: any) {
      setWriteStatus(`Failed: ${err?.message || "unknown error"}`);
    } finally {
      setIsWriting(false);
    }
  }

  async function handleDeleteDiary(entry: any) {
    const entryDate = String(entry.entry_date || "").trim();
    if (!entryDate || deletingDate) return;
    if (!window.confirm(`Delete diary entry for ${entryDate}?`)) return;
    setDeletingDate(entryDate);
    setWriteStatus(null);
    try {
      await deleteDiaryEntry(entryDate);
      setWriteStatus(`Deleted diary for ${entryDate}.`);
      await refreshDiary();
      setTimeout(() => setWriteStatus(null), 3000);
    } catch (err: any) {
      setWriteStatus(`Failed: ${err?.message || "unknown error"}`);
    } finally {
      setDeletingDate(null);
    }
  }

  function diaryTitle(entry: any): string {
    const content = String(entry.content || "");
    const firstLine = content.split("\n").find((l: string) => l.trim()) || "";
    const headingMatch = firstLine.match(/^#+\s*(.+)/);
    if (headingMatch) return headingMatch[1].trim();
    const sentence = content.slice(0, 80).split(/[。.!！？?]/)[0];
    return sentence.trim() || "Untitled entry";
  }

  function diaryBody(entry: any): string {
    const content = String(entry.content || "");
    const lines = content.split("\n");
    const firstNonEmpty = lines.findIndex((l: string) => l.trim());
    if (firstNonEmpty >= 0 && /^#+\s/.test(lines[firstNonEmpty])) {
      return lines.slice(firstNonEmpty + 1).join("\n").trim();
    }
    return content.trim();
  }

  function renderDiaryCard(entry: any, className = ""): React.JSX.Element {
    const entryDate = String(entry.entry_date || "");
    const isDeleting = deletingDate === entryDate;
    return (
      <article key={entry.entry_id || entryDate} className={`${styles.diaryCard} ${className}`.trim()}>
        <button
          type="button"
          className={styles.diaryDeleteButton}
          onClick={() => handleDeleteDiary(entry)}
          disabled={isDeleting}
          aria-label={`Delete diary entry for ${entryDate}`}
          title={`Delete ${entryDate}`}
        >
          ×
        </button>
        <header className={styles.diaryCardHeader}>
          <time className={styles.diaryCardDate}>{entry.entry_date}</time>
          <h4 className={styles.diaryCardTitle}>{diaryTitle(entry)}</h4>
        </header>
        <div className={styles.diaryCardBody}>{diaryBody(entry)}</div>
      </article>
    );
  }

  return (
    <div className={styles.diarySection}>
      <div className={styles.diaryToolbar}>
        <div className={styles.diaryToolbarLeft}>
          <h3 className={styles.diarySectionTitle}>Your Own Diary</h3>
          {writeStatus && <span className={styles.diaryStatus}>{writeStatus}</span>}
        </div>
        <div className={styles.diaryActions}>
          <input
            type="date"
            value={writingDate}
            onChange={(e) => setWritingDate(e.target.value)}
            className={styles.diaryDateInput}
          />
          <ActionButton onClick={handleWriteDiary} disabled={isWriting}>
            {isWriting ? "Writing…" : "Write diary"}
          </ActionButton>
        </div>
      </div>

      {entries.length === 0 && (
        <div className={styles.diaryEmpty}>
          <p>No diary entries yet.</p>
          <p>Pick a date and write your first one, or let the daily cron handle it.</p>
        </div>
      )}

      {latestEntry && (
        renderDiaryCard(latestEntry, styles.diaryCardLatest)
      )}

      {olderEntries.length > 0 && (
        <>
          <h4 className={styles.diaryPreviousHeading}>Previous diaries</h4>
          <div className={styles.diaryEntryList}>
            {visibleOlder.map((entry: any) => (
              renderDiaryCard(entry)
            ))}
          </div>
          {totalPages > 1 && (
            <div className={styles.diaryPagination}>
              <button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>← Newer</button>
              <span>{currentPage + 1} / {totalPages}</span>
              <button disabled={currentPage >= totalPages - 1} onClick={() => setPage(currentPage + 1)}>Older →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function PersonalModelsPage(): React.JSX.Element {
  const { dashboard, loading, error, refresh } = useDashboardSnapshot("personal-models");

  return (
    <div className={styles.pageStack}>
      {error && (
        <Panel eyebrow="API" title="Unavailable" detail="Could not load Personal Model data.">
          <EmptyPanel title="Load failed" detail={error} />
        </Panel>
      )}
      {!dashboard && !error && (
        <Panel eyebrow="API" title="Loading" detail="Fetching Personal Model data.">
          <EmptyPanel title="Loading" detail="Preparing your view." />
        </Panel>
      )}
      {dashboard && (
        <>
          {dashboard.personal_models.length ? (
            dashboard.personal_models.map((row) => {
              const modelId = valueOf(row, "personal_model_id");

              return (
                <section key={modelId} className={styles.pageStack} aria-label={`Diary ${modelId}`}>
                  <DiarySection />
                </section>
              );
            })
          ) : (
            <Panel
              eyebrow="Your Elephant Agent"
              title="We haven't met properly yet"
              detail="Run `elephant init` or open your first chat, and I'll start knowing you from that moment."
            >
              <EmptyPanel title="Still an elephant" detail="Open a chat for the first time and I'll start picking up who you are." />
            </Panel>
          )}
        </>
      )}
      {loading && <p className={styles.routeHint}>Refreshing…</p>}
    </div>
  );
}

function textLooksInternal(value: string): boolean {
  const normalized = value.toLowerCase();
  return [
    "elephant_smoke_ok",
    "assistant_display_name",
    "user_preferred_name",
    "do not mention internal",
    "internal identifiers",
    "opening_profile_gap",
    "reengagement_style",
    "source item",
    "system identity",
    "preserve-relationship-timeline",
    "preserve-preferences",
    "preserve-corrections",
    "preserve-emotional-context",
  ].some((needle) => normalized.includes(needle));
}

function humanText(value: string, fallback: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "n/a" || textLooksInternal(trimmed)) {
    return fallback;
  }
  return trimmed;
}

function humanEggSummary(row: DashboardRow): string {
  const eggName = valueOf(row, "elephant_name", "This elephant");
  return humanText(
    valueOf(row, "summary", ""),
    `${eggName} is ready. Write its character, then open Chat when it should continue.`,
  );
}

type EggDraft = {
  eggId: string;
  displayName: string;
  mode: string;
  personalityPreset: string;
  initiative: string;
  eggIdentityText: string;
};

const EMPTY_ELEPHANT_DRAFT: EggDraft = {
  eggId: "",
  displayName: "",
  mode: "companion",
  personalityPreset: "",
  initiative: "gentle",
  eggIdentityText: "",
};

function eggDisplayName(row: DashboardRow): string {
  return valueOf(row, "elephant_name", valueOf(row, "elephant_id", valueOf(row, "state_id", "Unnamed elephant")));
}

function eggIdentityText(row: DashboardRow): string {
  const eggIdentityFile = jsonObject(row.elephant_identity_file);
  return valueOf(eggIdentityFile, "text", valueOf(row, "elephant_identity_text", ""));
}

function publicElephantIdentityText(text: string): string {
  return text
    .replace(/<!--[\s\S]*?-->/g, "")
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .join("\n")
    .replace(/^\s+|\s+$/g, "");
}

function eggLevelLabel(row: DashboardRow): string {
  const checkpointLabel = valueOf(row, "checkpoint_label", "");
  return checkpointLabel && checkpointLabel !== "n/a" ? checkpointLabel : `checkpoint ${valueOf(row, "level", "0")}`;
}

function eggVibePreview(row: DashboardRow): string {
  const text = publicElephantIdentityText(eggIdentityText(row));
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.replace(/^#+\s*/, "").replace(/^[-*]\s+/, "").trim())
    .filter(Boolean)
    .filter((line) => !/^elephant id:|^display name:|^mode:/i.test(line));
  return compactText(lines[0] || humanEggSummary(row), 150);
}

function defaultElephantIdentityText(draft: EggDraft): string {
  const eggId = draft.eggId.trim() || "new-elephant";
  const displayName = draft.displayName.trim() || eggId.replace(/[-_]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const mode = draft.mode.trim() || "companion";
  return [
    `<!-- Internal metadata (not shown to the model). id: ${eggId}. mode: ${mode}. Edit the paragraphs below to reshape how ${displayName} introduces themselves. -->`,
    "",
    `You are ${displayName}, this person's companion.`,
    "How you show up: steady, curious, lightly playful, and present without making a performance of it.",
    "How you sound: clear and warm, with the occasional dry little wink when the moment can carry it.",
    "How you take initiative: notice loose threads, nudge gently, and make it easy for them to correct your read.",
    "Stay continuous without faking closeness or certainty.",
  ].join("\n");
}

function eggDraftFromRow(row: DashboardRow): EggDraft {
  const eggId = valueOf(row, "elephant_id", "");
  const displayName = eggDisplayName(row);
  return {
    eggId,
    displayName,
    mode: valueOf(row, "identity_mode", "companion"),
    personalityPreset: valueOf(row, "working_style", ""),
    initiative: valueOf(row, "initiative", ""),
    eggIdentityText: eggIdentityText(row) || defaultElephantIdentityText({
      ...EMPTY_ELEPHANT_DRAFT,
      eggId,
      displayName,
    }),
  };
}

function eggPayloadFromDraft(draft: EggDraft, options: { includeEggId: boolean }): DashboardEggPayload {
  return {
    ...(options.includeEggId ? { elephant_id: draft.eggId.trim() } : {}),
    display_name: draft.displayName.trim() || draft.eggId.trim(),
    mode: draft.mode.trim() || "companion",
    personality_preset: draft.personalityPreset.trim() || undefined,
    initiative: draft.initiative.trim() || undefined,
    elephant_identity_text: draft.eggIdentityText.trim() || defaultElephantIdentityText(draft),
  };
}

function EggDraftFields({
  draft,
  onChange,
  lockEggId = false,
  showEggId = true,
  showDefaults = true,
  showElephantIdentity = true,
}: {
  draft: EggDraft;
  onChange: (draft: EggDraft) => void;
  lockEggId?: boolean;
  showEggId?: boolean;
  showDefaults?: boolean;
  showElephantIdentity?: boolean;
}): React.JSX.Element {
  return (
    <div className={styles.eggManageForm}>
      {showEggId ? (
        <label className={styles.fieldStack}>
          <span>Elephant ID</span>
          <input
            disabled={lockEggId}
            placeholder="Auto-generated from name"
            value={draft.eggId}
            onChange={(event) => onChange({ ...draft, eggId: event.target.value })}
          />
        </label>
      ) : null}
      <label className={styles.fieldStack}>
        <span>Name</span>
        <input
          autoFocus={!showEggId}
          placeholder="Atlas"
          required
          value={draft.displayName}
          onChange={(event) => onChange({ ...draft, displayName: event.target.value })}
        />
      </label>
      {showDefaults ? (
        <>
          <label className={styles.fieldStack}>
            <span>Mode</span>
            <input
              placeholder="companion"
              value={draft.mode}
              onChange={(event) => onChange({ ...draft, mode: event.target.value })}
            />
          </label>
          <label className={styles.fieldStack}>
            <span>Personality / style</span>
            <input
              placeholder="companion, operator, direct..."
              value={draft.personalityPreset}
              onChange={(event) => onChange({ ...draft, personalityPreset: event.target.value })}
            />
          </label>
          <label className={styles.fieldStack}>
            <span>Initiative</span>
            <input
              placeholder="gentle, proactive..."
              value={draft.initiative}
              onChange={(event) => onChange({ ...draft, initiative: event.target.value })}
            />
          </label>
        </>
      ) : null}
      {showElephantIdentity ? (
        <label className={cx(styles.fieldStack, styles.eggVibeField)}>
          <span>Character</span>
          <textarea
            value={draft.eggIdentityText}
            onChange={(event) => onChange({ ...draft, eggIdentityText: event.target.value })}
            onFocus={() => {
              if (!draft.eggIdentityText.trim()) {
                onChange({ ...draft, eggIdentityText: defaultElephantIdentityText(draft) });
              }
            }}
          />
        </label>
      ) : null}
    </div>
  );
}

function EggCreateModal({
  open,
  draft,
  busy,
  onChange,
  onClose,
  onCreate,
}: {
  open: boolean;
  draft: EggDraft;
  busy: boolean;
  onChange: (draft: EggDraft) => void;
  onClose: () => void;
  onCreate: (event: React.FormEvent<HTMLFormElement>) => void;
}): React.JSX.Element | null {
  if (!open) {
    return null;
  }
  return (
    <FloatingFormModal
      open={open}
      title="Add elephant"
      subtitle="Elephant management"
      onClose={onClose}
      footer={(
        <>
          <ActionButton variant="ghost" onClick={onClose}>Cancel</ActionButton>
          <ActionButton disabled={busy || !draft.displayName.trim()} form="elephant-create-form" type="submit">
            {busy ? "Creating" : "Create elephant"}
          </ActionButton>
        </>
      )}
    >
      <form id="elephant-create-form" className={styles.eggCreatePanel} onSubmit={onCreate}>
        <EggDraftFields
          draft={draft}
          showEggId={false}
          showDefaults={false}
          showElephantIdentity={false}
          onChange={onChange}
        />
        <p className={styles.eggManageMessage}>Elephant ID, mode, initiative, and character are generated from defaults.</p>
      </form>
    </FloatingFormModal>
  );
}

function EggEditorModal({
  row,
  draft,
  busy,
  onChange,
  onClose,
  onSave,
}: {
  row: DashboardRow | null;
  draft: EggDraft;
  busy: boolean;
  onChange: (draft: EggDraft) => void;
  onClose: () => void;
  onSave: () => void;
}): React.JSX.Element | null {
  if (!row) {
    return null;
  }
  return (
    <FloatingFormModal
      open={Boolean(row)}
      title={`Edit ${eggDisplayName(row)}`}
      subtitle="Elephant vibe"
      onClose={onClose}
      footer={(
        <>
          <ActionButton variant="ghost" onClick={onClose}>Cancel</ActionButton>
          <ActionButton disabled={busy} onClick={onSave}>{busy ? "Saving" : "Save elephant"}</ActionButton>
        </>
      )}
    >
      <EggDraftFields draft={draft} lockEggId onChange={onChange} />
    </FloatingFormModal>
  );
}

function EggManagementContent({ dashboard, controls }: { dashboard: InternalDashboardSnapshot; controls: PageControls }): React.JSX.Element {
  const [createDraft, setCreateDraft] = React.useState<EggDraft>(EMPTY_ELEPHANT_DRAFT);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editRow, setEditRow] = React.useState<DashboardRow | null>(null);
  const [editDraft, setEditDraft] = React.useState<EggDraft>(EMPTY_ELEPHANT_DRAFT);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState("");
  const herd = dashboard.herd;
  const currentEgg = herd.find((row) => row.current === true) ?? herd[0];

  async function run(label: string, action: () => Promise<unknown>): Promise<void> {
    setBusy(label);
    setMessage("");
    try {
      await action();
      await controls.refresh();
      setMessage(`${label} completed.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${label} failed.`);
    } finally {
      setBusy(null);
    }
  }

  function openEdit(row: DashboardRow): void {
    setEditRow(row);
    setEditDraft(eggDraftFromRow(row));
  }

  const createEgg = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const displayName = createDraft.displayName.trim();
    if (!displayName) {
      setMessage("Elephant name is required.");
      return;
    }
    void run("Create elephant", async () => {
      await createDashboardEgg({ display_name: displayName });
      setCreateDraft(EMPTY_ELEPHANT_DRAFT);
      setCreateOpen(false);
    });
  };

  const saveEgg = () => {
    if (!editRow) {
      return;
    }
    const eggId = valueOf(editRow, "elephant_id", editDraft.eggId);
    void run("Save elephant", async () => {
      await updateDashboardEgg(eggId, eggPayloadFromDraft(editDraft, { includeEggId: false }));
      setEditRow(null);
    });
  };

  const deleteEgg = (row: DashboardRow) => {
    const eggId = valueOf(row, "elephant_id", "");
    if (!eggId || !window.confirm(`Delete elephant ${eggId}? Everything it remembers about you is preserved.`)) {
      return;
    }
    void run("Delete elephant", () => deleteDashboardEgg(eggId));
  };

  return (
    <>
      <Panel eyebrow="Overview" title="Elephant basics" detail="At a glance: how many herd you have, which is open, its level, and whether it has a written character.">
        <div className={styles.eggBasicsGrid}>
          <article className={styles.statusDetailCard}>
            <span>Total</span>
            <strong>{String(herd.length)}</strong>
            <p className={styles.statusDetailSummary}>Named herd you can return to.</p>
          </article>
          <article className={styles.statusDetailCard}>
            <span>Open</span>
            <strong>{currentEgg ? eggDisplayName(currentEgg) : "None"}</strong>
            <p className={styles.statusDetailSummary}>{currentEgg ? valueOf(currentEgg, "elephant_id", "") : "Create an elephant first."}</p>
          </article>
          <article className={styles.statusDetailCard}>
            <span>Memory</span>
            <strong>{currentEgg ? `${eggLevelLabel(currentEgg)} · ${valueOf(currentEgg, "stage", "learning the path")}` : "checkpoint 0"}</strong>
            <p className={styles.statusDetailSummary}>{currentEgg ? `${valueOf(currentEgg, "progress_percent", "0")}% to next memory checkpoint` : "No elephant open right now."}</p>
          </article>
          <article className={styles.statusDetailCard}>
            <span>Character</span>
            <strong>{currentEgg && eggIdentityText(currentEgg) ? "Ready" : "Empty"}</strong>
            <p className={styles.statusDetailSummary}>{currentEgg ? compactText(eggVibePreview(currentEgg), 90) : "Add an elephant to seed its starting character."}</p>
          </article>
        </div>
        {message ? <p className={styles.eggManageMessage}>{message}</p> : null}
      </Panel>

      <Panel eyebrow="Your herd" title="Open, edit, or let one go" detail="Each elephant is its own thread you can return to. Give it a character, write its opening vibe, or remove one you're done with.">
        <div className={styles.eggManageToolbar}>
          <span>{herd.length ? `${herd.length} herd` : "No herd yet"}</span>
          <ActionButton disabled={busy === "Create elephant" || controls.loading} onClick={() => setCreateOpen(true)}>
            Add
          </ActionButton>
        </div>
        {herd.length ? (
          <div className={styles.eggManageGrid}>
            {herd.map((row) => {
              const eggId = valueOf(row, "elephant_id", valueOf(row, "state_id"));
              const eggName = eggDisplayName(row);
              const identityPath = valueOf(jsonObject(row.elephant_identity_file), "path", "n/a");
              return (
                <article key={valueOf(row, "state_id", eggId)} className={styles.eggJournalCard}>
                  <header className={styles.eggJournalHeader}>
                    <div>
                      <span>{row.current ? "Current elephant" : "Elephant"}</span>
                      <strong>{eggName}</strong>
                    </div>
                    <div className={styles.eggBadgeRow}>
                      <StatusBadge tone={toneForStatus(row.status)}>{row.current ? "current" : valueOf(row, "status", "active")}</StatusBadge>
                      <StatusBadge tone="neutral">{eggLevelLabel(row)}</StatusBadge>
                    </div>
                  </header>
                  <p>{eggVibePreview(row)}</p>
                  <div className={styles.eggJournalMeta}>
                    <div>
                      <span>ID</span>
                      <strong>{eggId}</strong>
                    </div>
                    <div>
                      <span>Style</span>
                      <strong>{valueOf(row, "working_style", "Unset")}</strong>
                    </div>
                    <div>
                      <span>Initiative</span>
                      <strong>{valueOf(row, "initiative", "Unset")}</strong>
                    </div>
                    <div>
                      <span>Stage</span>
                      <strong>{valueOf(row, "stage", "Seed")}</strong>
                    </div>
                    <div>
                      <span>Character</span>
                      <strong>{identityPath === "n/a" ? "Not written" : "Written"}</strong>
                    </div>
                    <div>
                      <span>Updated</span>
                      <strong>{formatTimestamp(valueOf(row, "updated_at", ""))}</strong>
                    </div>
                  </div>
                  <div className={styles.eggVibePreview}>
                    <MarkdownText text={publicElephantIdentityText(eggIdentityText(row)) || "No character written yet."} />
                  </div>
                  <div className={styles.eggActionRow}>
                    <ActionButton variant="ghost" onClick={() => openEdit(row)}>Edit character</ActionButton>
                    <ViewButton title={`${eggName} details`} items={eggDetailItems(row)} variant="ghost" />
                    <ActionButton variant="ghost" disabled={busy === "Delete elephant"} onClick={() => deleteEgg(row)}>
                      {busy === "Delete elephant" ? "Deleting" : "Delete"}
                    </ActionButton>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyPanel title="No herd yet" detail="Use Add to create a named elephant line." />
        )}
      </Panel>

      <EggCreateModal
        open={createOpen}
        draft={createDraft}
        busy={busy === "Create elephant"}
        onChange={setCreateDraft}
        onClose={() => setCreateOpen(false)}
        onCreate={createEgg}
      />

      <EggEditorModal
        row={editRow}
        draft={editDraft}
        busy={busy === "Save elephant"}
        onChange={setEditDraft}
        onClose={() => setEditRow(null)}
        onSave={saveEgg}
      />
    </>
  );
}

export function StatesPage(): React.JSX.Element {
  return (
    <DashboardPage section="herd">
      {(dashboard, controls) => <EggManagementContent dashboard={dashboard} controls={controls} />}
    </DashboardPage>
  );
}

function conversationSpeaker(eventType: string): string {
  if (eventType === "user_query") {
    return "You";
  }
  if (["llm_answer", "final_response"].includes(eventType)) {
    return "Elephant Agent";
  }
  if (["tool_call", "tool_execute"].includes(eventType)) {
    return "Tool";
  }
  if (eventType === "personal_model_update") {
    return "Learning";
  }
  if (eventType === "state_write") {
    return "State";
  }
  return "Runtime";
}

function conversationBubbleTone(eventType: string): string {
  if (["user_query", "llm_answer", "final_response", "tool_call", "tool_execute"].includes(eventType)) {
    return "primary";
  }
  if (["system_prompt", "context_bundle", "context_compaction", "checkpoint"].includes(eventType)) {
    return "system";
  }
  return "secondary";
}

function conversationContent(row: DashboardRow): string {
  return valueOf(row, "content", valueOf(row, "summary", ""));
}

function normalizedConversationContent(row: DashboardRow): string {
  return conversationContent(row).replace(/\s+/g, " ").trim();
}

function runtimeEventLabel(eventType: string): string {
  if (eventType === "system_prompt") {
    return "System prompt";
  }
  if (eventType === "tool_call") {
    return "Tool call";
  }
  if (eventType === "tool_execute") {
    return "Tool result";
  }
  if (eventType === "context_bundle") {
    return "Context bundle";
  }
  if (eventType === "context_compaction") {
    return "Context compaction";
  }
  if (eventType === "checkpoint") {
    return "Checkpoint";
  }
  return "Runtime event";
}

function runtimeEventPreview(text: string, fallback: string, limit = 220): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return fallback;
  }
  return compactText(normalized, limit);
}

function shouldCollapseRuntimeEvent(eventType: string): boolean {
  return ["system_prompt", "tool_call", "tool_execute", "context_bundle", "context_compaction", "checkpoint"].includes(eventType);
}

function RuntimeDisclosure({
  label,
  text,
  fallback,
  hint,
  previewLimit = 220,
}: {
  label: string;
  text: string;
  fallback: string;
  hint: string;
  previewLimit?: number;
}): React.JSX.Element {
  return (
    <details className={styles.runtimePromptDisclosure}>
      <summary className={styles.runtimePromptDisclosureSummary}>
        <span>{label}</span>
        <strong>{runtimeEventPreview(text, fallback, previewLimit)}</strong>
        <small>{hint}</small>
      </summary>
      <div className={styles.runtimePromptDisclosureBody}>
        <MarkdownText text={text || fallback} />
      </div>
    </details>
  );
}

function RuntimeEventDisclosure({ eventType, text }: { eventType: string; text: string }): React.JSX.Element {
  const label = runtimeEventLabel(eventType);
  const lowerLabel = label.toLowerCase();
  const fallback = `No ${lowerLabel} persisted.`;
  return (
    <RuntimeDisclosure
      label={label}
      text={text}
      fallback={fallback}
      hint={`Click to expand the full ${lowerLabel}`}
    />
  );
}

function RuntimeReasoningDisclosure({ text }: { text: string }): React.JSX.Element {
  return (
    <RuntimeDisclosure
      label="Reasoning"
      text={text}
      fallback="No reasoning persisted."
      hint="Click to expand the full reasoning trace"
      previewLimit={180}
    />
  );
}

function conversationRows(episode: DashboardRow): DashboardRow[] {
  const rows = asRows(episode.timeline).filter((step) =>
    [
      "user_query",
      "system_prompt",
      "context_bundle",
      "context_compaction",
      "llm_answer",
      "final_response",
      "tool_call",
      "tool_execute",
      "checkpoint",
    ].includes(valueOf(step, "event_type", "")),
  );
  let latestAnswer = "";
  return rows.filter((step) => {
    const eventType = valueOf(step, "event_type", "");
    if (eventType === "llm_answer") {
      latestAnswer = normalizedConversationContent(step);
      return true;
    }
    if (eventType === "final_response" && latestAnswer && normalizedConversationContent(step) === latestAnswer) {
      return false;
    }
    return true;
  });
}

function runtimeStepReasoning(step: DashboardRow): string {
  return readString(jsonObject(step.detail), ["assistant_reasoning", "reasoning_trace"], "");
}

function eggNameForEpisode(episode: DashboardRow, dashboard: InternalDashboardSnapshot): string {
  const stateId = valueOf(episode, "state_id", "");
  const state = dashboard.herd.find((elephant) => valueOf(elephant, "state_id", "") === stateId)
    ?? dashboard.states.find((candidate) => valueOf(candidate, "state_id", "") === stateId);
  return valueOf(state ?? {}, "elephant_name", valueOf(episode, "elephant_id", "Elephant Agent"));
}

function renderInlineMarkdown(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={`${token}-${match.index}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`${token}-${match.index}`}>{token.slice(2, -2)}</strong>);
    } else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (link) {
        nodes.push(
          <a key={`${token}-${match.index}`} href={link[2]} rel="noreferrer" target="_blank">
            {link[1]}
          </a>,
        );
      }
    }
    cursor = pattern.lastIndex;
  }
  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes.length ? nodes : [text];
}

function renderListItemMarkdown(text: string): React.ReactNode {
  const heading = /^(#{1,6})\s+(.+)$/.exec(text.trim());
  if (heading) {
    return <strong>{renderInlineMarkdown(heading[2])}</strong>;
  }
  return renderInlineMarkdown(text);
}

function MarkdownText({ text }: { text: string }): React.JSX.Element {
  const lines = text.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let listItems: string[] = [];
  let codeLines: string[] = [];
  let inCode = false;

  const flushList = () => {
    if (!listItems.length) {
      return;
    }
    const items = listItems;
    listItems = [];
    blocks.push(
      <ul key={`list-${blocks.length}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{renderListItemMarkdown(item)}</li>
        ))}
      </ul>,
    );
  };
  const flushCode = () => {
    if (!codeLines.length) {
      return;
    }
    const code = codeLines.join("\n");
    codeLines = [];
    blocks.push(<pre key={`code-${blocks.length}`}>{code}</pre>);
  };

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        inCode = false;
        flushCode();
      } else {
        flushList();
        inCode = true;
      }
      return;
    }
    if (inCode) {
      codeLines.push(line);
      return;
    }
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    if (bullet) {
      listItems.push(bullet[1]);
      return;
    }
    flushList();
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push(<strong key={`heading-${blocks.length}`}>{renderInlineMarkdown(heading[2])}</strong>);
      return;
    }
    if (line.trim()) {
      blocks.push(<p key={`p-${blocks.length}`}>{renderInlineMarkdown(line)}</p>);
    }
  });
  flushList();
  flushCode();

  return <div className={styles.markdownText}>{blocks.length ? blocks : <p>No content persisted.</p>}</div>;
}

function RuntimeTraceStepCard({ step }: { step: DashboardRow }): React.JSX.Element {
  const eventType = valueOf(step, "event_type", valueOf(step, "action", "step"));
  const usage = jsonObject(step.usage);
  const hasUsage = numberOf(usage, "total_tokens") > 0;
  const content = valueOf(step, "content", valueOf(step, "summary", "No content persisted."));
  const reasoning = runtimeStepReasoning(step);

  return (
    <article className={styles.runtimeTraceStep}>
      <header className={styles.runtimeTraceStepHeader}>
        <div className={styles.runtimeTraceStepHeading}>
          <div className={styles.runtimeTraceTagRow}>
            <StatusBadge tone="neutral">{eventType}</StatusBadge>
            <StatusBadge tone={toneForStatus(step.status)}>{valueOf(step, "status")}</StatusBadge>
            <StatusBadge tone="neutral">step {valueOf(step, "sequence", "0")}</StatusBadge>
            {hasUsage ? (
              <StatusBadge tone="neutral">
                {valueOf(usage, "prompt_tokens", "0")} in / {valueOf(usage, "completion_tokens", "0")} out
              </StatusBadge>
            ) : null}
          </div>
          <strong>{valueOf(step, "action", "step")}</strong>
        </div>
        <ViewButton
          className={styles.runtimeTraceViewButton}
          title={valueOf(step, "step_id")}
          items={detailItems(step)}
          variant="ghost"
        />
      </header>
      <div className={styles.runtimeTraceContent}>
        {shouldCollapseRuntimeEvent(eventType) ? (
          <RuntimeEventDisclosure eventType={eventType} text={content} />
        ) : (
          <MarkdownText text={content} />
        )}
        {eventType === "llm_answer" && reasoning ? <RuntimeReasoningDisclosure text={reasoning} /> : null}
      </div>
    </article>
  );
}

function RuntimeTraceLoopCard({ loop }: { loop: DashboardRow }): React.JSX.Element {
  const steps = asRows(loop.steps);

  return (
    <section className={styles.runtimeTraceLoop}>
      <header className={styles.runtimeTraceHeader}>
        <div className={styles.runtimeTraceHeading}>
          <div className={styles.runtimeTraceTagRow}>
            <StatusBadge tone="neutral">{valueOf(loop, "trigger_type", "loop")}</StatusBadge>
            <StatusBadge tone={toneForStatus(loop.status)}>{valueOf(loop, "status")}</StatusBadge>
            <StatusBadge tone="neutral">{steps.length} step(s)</StatusBadge>
          </div>
          <strong>{valueOf(loop, "loop_id")}</strong>
        </div>
        <ViewButton
          className={styles.runtimeTraceViewButton}
          title={valueOf(loop, "loop_id")}
          items={detailItems(loop)}
          variant="ghost"
        />
      </header>
      {steps.length ? (
        <details className={styles.runtimeTraceDisclosure}>
          <summary className={styles.runtimeTraceDisclosureSummary}>View step chain</summary>
          <div className={styles.runtimeTraceSteps}>
            {steps.map((step) => (
              <RuntimeTraceStepCard key={valueOf(step, "step_id")} step={step} />
            ))}
          </div>
        </details>
      ) : (
        <div className={styles.runtimeTraceEmpty}>
          <EmptyPanel title="No Step rows" detail="This Loop does not yet have persisted Step facts." />
        </div>
      )}
    </section>
  );
}

function RuntimeTraceEpisodeCard({ episode }: { episode: DashboardRow }): React.JSX.Element {
  const loops = asRows(episode.loops);
  const loopCount = valueOf(episode, "loop_count", String(loops.length));
  const stepCount = valueOf(episode, "step_count", "0");

  return (
    <article className={styles.runtimeTraceEpisode}>
      <header className={styles.runtimeTraceHeader}>
        <div className={styles.runtimeTraceHeading}>
          <div className={styles.runtimeTraceTagRow}>
            <StatusBadge tone="neutral">{valueOf(episode, "entry_surface", "episode")}</StatusBadge>
            <StatusBadge tone={toneForStatus(episode.status)}>{valueOf(episode, "status")}</StatusBadge>
            <StatusBadge tone="neutral">{loopCount} loop(s)</StatusBadge>
            <StatusBadge tone="neutral">{stepCount} step(s)</StatusBadge>
          </div>
          <strong>{valueOf(episode, "episode_id")}</strong>
          <p className={styles.runtimeTraceLead}>{valueOf(episode, "exit_summary", "No exit summary persisted.")}</p>
        </div>
        <div className={styles.runtimeTraceHeaderActions}>
          <span>{formatWhen(episode.started_at)}</span>
          <ViewButton
            className={styles.runtimeTraceViewButton}
            title={valueOf(episode, "episode_id")}
            items={detailItems(episode)}
            variant="ghost"
          />
        </div>
      </header>
      {loops.length ? (
        <details className={styles.runtimeTraceDisclosure} open>
          <summary className={styles.runtimeTraceDisclosureSummary}>View loop chain</summary>
          <div className={styles.runtimeTraceLoops}>
            {loops.map((loop) => (
              <RuntimeTraceLoopCard key={valueOf(loop, "loop_id")} loop={loop} />
            ))}
          </div>
        </details>
      ) : (
        <div className={styles.runtimeTraceEmpty}>
          <EmptyPanel title="No turns yet" detail="This conversation hasn't produced any turns to trace." />
        </div>
      )}
    </article>
  );
}

function learningResultRows(job: DashboardRow): DashboardRow[] {
  const result = jsonObject(job.learning_result) || jsonObject(job.result_json);
  if (Object.keys(result).length > 0) return [result];
  return asRows(job.result_facts);
}

function learningModeName(job: DashboardRow): string {
  const trigger = valueOf(job, "trigger", "").toLowerCase();
  const jobType = valueOf(job, "job_type", "").toLowerCase();
  if (trigger === "init_profile") return "Bootstrap";
  if (trigger.includes("idle")) return "IM Idle";
  if (trigger === "context_compaction" || jobType.includes("compaction")) return "Compression";
  if (trigger === "manual") return "Manual";
  return "Episode Close";
}

function learningDuration(job: DashboardRow): string {
  const created = valueOf(job, "created_at", "");
  const finished = valueOf(job, "finished_at", "");
  if (!created || !finished) return "";
  try {
    const ms = new Date(finished).getTime() - new Date(created).getTime();
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${Math.round(ms / 1000)}s`;
    return `${Math.round(ms / 60000)}m`;
  } catch {
    return "";
  }
}

function learningResultSummary(job: DashboardRow): { created: string[]; updated: string[]; retired: string[]; questions: string[] } {
  const results = learningResultRows(job);
  const created: string[] = [];
  const updated: string[] = [];
  const retired: string[] = [];
  const questions: string[] = [];
  for (const row of results) {
    const payload = Object.keys(jsonObject(row.payload)).length > 0 ? jsonObject(row.payload) : row;
    const pmFacts = jsonObject(payload.pm_facts);
    for (const ref of asRows(pmFacts.created_refs) as unknown as string[] || []) if (ref) created.push(String(ref));
    for (const ref of asRows(pmFacts.updated_refs) as unknown as string[] || []) if (ref) updated.push(String(ref));
    for (const ref of asRows(pmFacts.retired_refs) as unknown as string[] || []) if (ref) retired.push(String(ref));
    const q = jsonObject(payload.questions);
    for (const id of asRows(q.created_ids) as unknown as string[] || []) if (id) questions.push(String(id));
  }
  return { created, updated, retired, questions };
}

function LearningJobTraceCard({ job }: { job: DashboardRow }): React.JSX.Element {
  const duration = learningDuration(job);
  const status = valueOf(job, "status", "queued");
  const progressDetail = valueOf(job, "progress_detail", "");
  const summary = valueOf(job, "summary", "");
  const lastError = valueOf(job, "last_error", "");
  const results = learningResultRows(job);
  const trigger = valueOf(job, "trigger", "");
  const isDiary = trigger === "diary";
  const metadata = jsonObject(job.metadata);
  const jobFeatures = String(metadata.features || "").trim();
  const featureBadges = jobFeatures ? jobFeatures.split(",").map((f) => f.trim()).filter(Boolean) : [];

  return (
    <article className={`${styles.runtimeTraceEpisode}${isDiary ? ` ${styles.learningJobDiary}` : ""}`}>
      <header className={styles.runtimeTraceHeader}>
        <div className={styles.runtimeTraceHeading}>
          <div className={styles.runtimeTraceTagRow}>
            <StatusBadge tone={toneForStatus(status)}>{status}</StatusBadge>
            {trigger && <StatusBadge tone={isDiary ? "healthy" : "attention"}>{trigger}</StatusBadge>}
            {duration && <StatusBadge tone="neutral">{duration}</StatusBadge>}
            {results.length > 0 && <StatusBadge tone="healthy">{results.length} result(s)</StatusBadge>}
          </div>
          {featureBadges.length > 0 && (
            <div className={styles.runtimeTraceTagRow} style={{ marginTop: "0.25rem" }}>
              {featureBadges.map((f) => <StatusBadge key={f} tone="neutral">{f}</StatusBadge>)}
            </div>
          )}
          {progressDetail ? (
            <div className={styles.learningJobProgressDetail}>
              <MarkdownText text={progressDetail} />
            </div>
          ) : summary ? (
            <p className={styles.runtimeTraceLead}>{compactText(summary, 300)}</p>
          ) : null}
        </div>
        <div className={styles.runtimeTraceHeaderActions}>
          <span>{formatWhen(job.created_at)}</span>
          <ViewButton
            className={styles.runtimeTraceViewButton}
            title={`${trigger || "reflect"} job`}
            items={learningJobDetailItems(job)}
            variant="ghost"
          />
        </div>
      </header>
      {lastError && lastError !== "n/a" && (
        <p className={styles.runtimeTraceLead} style={{ color: "var(--color-critical, #d32f2f)" }}>
          Error: {compactText(lastError, 200)}
        </p>
      )}
      {results.length > 0 && (
        <details className={styles.runtimeTraceDisclosure}>
          <summary className={styles.runtimeTraceDisclosureSummary}>Learning results</summary>
          <div className={styles.runtimeTraceSteps}>
            {results.map((result, index) => (
              <article key={index} className={styles.runtimeTraceStep}>
                <p className={styles.runtimeTraceLead}>
                  {compactText(valueOf(result, "summary", valueOf(result, "content", valueOf(result, "layer_type", "result"))), 300)}
                </p>
              </article>
            ))}
          </div>
        </details>
      )}
    </article>
  );
}

export function ReflectPage(): React.JSX.Element {
  const action = useAsyncAction(async () => undefined);
  const [jobPage, setJobPage] = React.useState(0);
  const [showCreate, setShowCreate] = React.useState(false);
  const [selectedFeatures, setSelectedFeatures] = React.useState<Record<string, boolean>>({
    pm: true, questions: true, recall: true, dream: false, diary: false, skills: false, compress: false,
  });
  const jobPageSize = 8;

  const featureList = [
    { id: "pm", label: "PM Learning", desc: "Search and write personal model facts" },
    { id: "questions", label: "Questions", desc: "Create, settle, dismiss proactive questions" },
    { id: "recall", label: "Recall", desc: "Search conversation history for evidence" },
    { id: "dream", label: "Dream", desc: "Consolidate and clean Personal Model facts" },
    { id: "diary", label: "Diary", desc: "Write a reflective daily entry" },
    { id: "skills", label: "Skills", desc: "Audit skill affinities against catalog" },
    { id: "compress", label: "Compress", desc: "Check if compressed content loses facts" },
  ];

  const toggleFeature = (id: string) => setSelectedFeatures((prev) => ({ ...prev, [id]: !prev[id] }));
  const activeFeatures = Object.entries(selectedFeatures).filter(([, v]) => v).map(([k]) => k).join(",");

  return (
    <DashboardPage section="reflect">
      {(dashboard, { refresh }) => {
        const learning = jsonObject(dashboard.learning);
        const learningSummary = jsonObject(learning.summary);
        const learningJobs = asRows(learning.jobs);
        const totalPages = Math.max(1, Math.ceil(learningJobs.length / jobPageSize));
        const currentPage = Math.min(jobPage, totalPages - 1);
        const visibleJobs = learningJobs.slice(currentPage * jobPageSize, currentPage * jobPageSize + jobPageSize);
        const running = numberOf(learningSummary, "running");
        const queued = numberOf(learningSummary, "queued");
        const completed = numberOf(learningSummary, "completed");
        const failed = numberOf(learningSummary, "failed");

        return (
          <>
            <section className={cx(styles.metricGrid, styles.metricGridCompact)} style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem" }}>
              <MetricCard compact metric={{ label: "Running", value: `${running}`, note: "Active reflect agents.", tone: running ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Queued", value: `${queued}`, note: "Waiting for worker.", tone: queued ? "attention" : "neutral" }} />
              <MetricCard compact metric={{ label: "Completed", value: `${completed}`, note: "Successfully finished.", tone: completed ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Failed", value: `${failed}`, note: "Errors encountered.", tone: failed ? "critical" : "neutral" }} />
            </section>
            <Panel
              eyebrow="History"
              title="Reflect jobs"
              detail={`${learningJobs.length} total jobs across all triggers.`}
            >
              <div className={styles.settingsActionBar} style={{ justifyContent: "flex-end" }}>
                <ActionButton onClick={() => setShowCreate(true)}>New reflect job</ActionButton>
              </div>
              {visibleJobs.length > 0 ? (
                <div className={styles.runtimeTraceList}>
                  {visibleJobs.map((job, index) => (
                    <LearningJobTraceCard key={valueOf(job, "job_id", `job-${index}`)} job={job} />
                  ))}
                </div>
              ) : (
                <EmptyPanel title="No reflect jobs yet" detail="Run a reflect job or wait for automatic triggers (episode close or dream cron)." />
              )}
              <PaginationBar
                totalItems={learningJobs.length}
                currentPage={currentPage}
                totalPages={totalPages}
                pageSize={jobPageSize}
                label="reflect jobs"
                onPrevious={() => setJobPage((p) => Math.max(0, p - 1))}
                onNext={() => setJobPage((p) => Math.min(totalPages - 1, p + 1))}
              />
            </Panel>
            {showCreate && (
              <div className={styles.modalOverlay} onClick={() => setShowCreate(false)}>
                <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
                  <header className={styles.modalHeader}>
                    <strong>New reflect job</strong>
                    <ActionButton variant="ghost" onClick={() => setShowCreate(false)}>✕</ActionButton>
                  </header>
                  <p className={styles.modalDetail}>Select which features the reflect agent should exercise.</p>
                  <div className={styles.reflectFeatureGrid}>
                    {featureList.map((f) => (
                      <label key={f.id} className={styles.reflectFeatureItem}>
                        <input
                          type="checkbox"
                          checked={Boolean(selectedFeatures[f.id])}
                          onChange={() => toggleFeature(f.id)}
                        />
                        <div>
                          <strong>{f.label}</strong>
                          <small>{f.desc}</small>
                        </div>
                      </label>
                    ))}
                  </div>
                  <div className={styles.modalActions}>
                    <ActionButton variant="ghost" onClick={() => setShowCreate(false)}>Cancel</ActionButton>
                    <ActionButton
                      disabled={!activeFeatures || Boolean(action.busy)}
                      onClick={() => {
                        void action.run("Trigger reflect", async () => {
                          await triggerReflectJob({ trigger: "manual", features: activeFeatures });
                          setShowCreate(false);
                          await new Promise((r) => setTimeout(r, 500));
                          await refresh();
                        });
                      }}
                    >
                      {action.busy ? "Running…" : "Run reflect"}
                    </ActionButton>
                  </div>
                </div>
              </div>
            )}
          </>
        );
      }}
    </DashboardPage>
  );
}

export function RuntimePage(): React.JSX.Element {
  const [episodePage, setEpisodePage] = React.useState(0);
  const pageSize = 1;

  return (
    <DashboardPage section="runtime">
      {(dashboard) => {
        const episodeTraces = dashboard.runtime.episode_traces;
        const totalPages = Math.max(1, Math.ceil(episodeTraces.length / pageSize));
        const currentPage = Math.min(episodePage, totalPages - 1);
        const visibleEpisodes = episodeTraces.slice(currentPage * pageSize, currentPage * pageSize + pageSize);

        return (
          <>
            <Panel
              eyebrow="Your history"
              title="Conversation history"
              detail="Each thread you've held with Elephant Agent, in the order it happened — your words, Elephant Agent's replies, any tools it reached for, and what it learned. Open the technical trace below only if you want the raw facts."
            >
              {episodeTraces.length ? (
                <>
                  <PaginationBar
                    totalItems={episodeTraces.length}
                    currentPage={currentPage}
                    totalPages={totalPages}
                    pageSize={pageSize}
                    label="conversations"
                    onPrevious={() => setEpisodePage((page) => Math.max(0, page - 1))}
                    onNext={() => setEpisodePage((page) => Math.min(totalPages - 1, page + 1))}
                  />
                  <div className={styles.conversationList}>
                    {visibleEpisodes.map((episode) => {
                      const rows = conversationRows(episode);
                      const eggName = eggNameForEpisode(episode, dashboard);
                      return (
                        <article key={valueOf(episode, "episode_id")} className={styles.conversationEpisode}>
                          <header className={styles.timelineCardHeader}>
                            <div>
                              <span>{formatWhen(episode.started_at)}</span>
                              <strong>{valueOf(episode, "entry_surface", "episode")}</strong>
                            </div>
                            <div className={styles.conversationEpisodeAside}>
                              <strong>{eggName}</strong>
                              <StatusBadge tone={toneForStatus(episode.status)}>{valueOf(episode, "status")}</StatusBadge>
                            </div>
                          </header>
                          <div className={styles.conversationThread}>
                            {rows.length ? (
                              rows.map((step, stepIndex) => {
                                const eventType = valueOf(step, "event_type", valueOf(step, "action", "step"));
                                const content = conversationContent(step) || "No content persisted.";
                                const reasoning = runtimeStepReasoning(step);
                                return (
                                  <article
                                    key={`${valueOf(step, "step_id")}-${eventType}-${stepIndex}`}
                                    className={cx(
                                      styles.conversationBubble,
                                      conversationSpeaker(eventType) === "You" && styles.conversationBubbleUser,
                                      conversationBubbleTone(eventType) === "primary" && styles.conversationBubblePrimary,
                                      conversationBubbleTone(eventType) === "system" && styles.conversationBubbleSystem,
                                      shouldCollapseRuntimeEvent(eventType) && styles.conversationBubbleDisclosure,
                                    )}
                                  >
                                    <span>{conversationSpeaker(eventType)} · {eventType}</span>
                                    {shouldCollapseRuntimeEvent(eventType) ? (
                                      <RuntimeEventDisclosure eventType={eventType} text={content} />
                                    ) : (
                                      <MarkdownText text={content} />
                                    )}
                                    {eventType === "llm_answer" && reasoning ? <RuntimeReasoningDisclosure text={reasoning} /> : null}
                                  </article>
                                );
                              })
                            ) : (
                              <EmptyPanel title="Nothing to show yet" detail="This conversation has raw internals but no user, Elephant Agent, tool, or learning content to render." />
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </>
              ) : (
                <EmptyPanel title="No conversations yet" detail="Open a chat and the first thread begins here." />
              )}
            </Panel>
          </>
        );
      }}
    </DashboardPage>
  );
}

export function ProvidersPage(): React.JSX.Element {
  return (
    <DashboardPage section="providers">
      {(dashboard, { refresh }) => (
        <>
          <ProviderModelControls dashboard={dashboard} refresh={refresh} />
          <EmbeddingProviderControls dashboard={dashboard} refresh={refresh} />
        </>
      )}
    </DashboardPage>
  );
}

type ProviderDraft = {
  modelId?: string;
  baseUrl?: string;
  apiKey?: string;
  testPrompt?: string;
};

type EmbeddingDraft = {
  mode: "local" | "openai-compatible";
  baseUrl: string;
  modelId: string;
  dimensions: string;
  apiKey: string;
};

type ProviderSection = {
  id: string;
  title: string;
  detail: string;
  providers: DashboardRow[];
};

const OAUTH_PROVIDER_IDS = new Set(["openai-codex", "qwen-oauth", "claude-code", "anthropic", "copilot"]);

function providerId(provider: DashboardRow): string {
  return readString(provider, ["provider_id", "providerId", "id", "source"], "provider");
}

function providerDisplayName(provider: DashboardRow): string {
  return readString(provider, ["display_name", "displayName", "name", "provider_id"], providerId(provider));
}

function providerSecretRefs(provider: DashboardRow): DashboardRow[] {
  const id = providerId(provider);
  const normalizedId = id.replace(/[^a-zA-Z0-9_-]/g, "-");
  const envVars = asTextList(provider.env_var_names ?? provider.envVarNames);
  if (!asTextList(provider.required_secret_keys ?? provider.requiredSecretKeys).includes("api_key")) {
    return [];
  }
  return [
    {
      reference_id: `secret-provider-${normalizedId}-api-key`,
      provider_id: id,
      secret_name: "api_token",
      secret_key: "api_key",
      source: "workspace",
      metadata: {
        storage: "local-vault",
        ...(envVars[0] ? { env_var: envVars[0] } : {}),
      },
    },
  ];
}

function providerKeyRows(provider: DashboardRow, keys: DashboardRow[]): DashboardRow[] {
  const id = providerId(provider);
  return keys.filter((key) => valueOf(key, "providerId", valueOf(key, "provider_id", "")) === id);
}

function providerHasRuntimeAuth(provider: DashboardRow): boolean {
  const status = valueOf(provider, "status", "").toLowerCase();
  return ["authenticated", "configured", "available"].some((item) => status.includes(item));
}

function providerSectionId(provider: DashboardRow): "oauth" | "api-key" {
  const id = providerId(provider);
  const authMethod = valueOf(provider, "auth_method", valueOf(provider, "auth_type", "")).toLowerCase();
  if (OAUTH_PROVIDER_IDS.has(id) || authMethod.includes("oauth")) {
    return "oauth";
  }
  return "api-key";
}

function providerSections(providers: DashboardRow[]): ProviderSection[] {
  const oauthProviders = providers.filter((provider) => providerSectionId(provider) === "oauth");
  const apiKeyProviders = providers.filter((provider) => providerSectionId(provider) === "api-key");
  return [
    {
      id: "oauth",
      title: "OAuth providers",
      detail: "Local CLI-token and OAuth-backed providers such as Codex, Copilot, Qwen, Claude Code, and Anthropic.",
      providers: oauthProviders,
    },
    {
      id: "api-key",
      title: "API key providers",
      detail: "Direct API keys, OpenAI-compatible endpoints, and local or self-hosted model providers.",
      providers: apiKeyProviders,
    },
  ].filter((section) => section.providers.length);
}

function providerModelOptions(provider: DashboardRow, discovered: DashboardRow[] | undefined): DashboardRow[] {
  const seen = new Set<string>();
  const rows: DashboardRow[] = [];
  const push = (modelId: string, source: string, label?: string) => {
    const normalized = modelId.trim();
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    rows.push({
      model_id: normalized,
      label: label || normalized,
      source,
    });
  };
  discovered?.forEach((model) => {
    push(valueOf(model, "model_id", valueOf(model, "id", "")), valueOf(model, "source", "endpoint"), valueOf(model, "label", ""));
  });
  asTextList(provider.model_hints ?? provider.modelHints).forEach((modelId) => push(modelId, "catalog-hint"));
  push(valueOf(provider, "default_model_id", valueOf(provider, "defaultModelId", "")), "default");
  return rows;
}

function providerDraft(provider: DashboardRow, activeProvider: DashboardRow, drafts: Record<string, ProviderDraft>): ProviderDraft {
  const id = providerId(provider);
  const isActive = valueOf(activeProvider, "provider_id") === id;
  const current = drafts[id] ?? {};
  const discovered = jsonObject(provider.discovered_state as DashboardJson | undefined);
  const defaultModel = valueOf(discovered, "default_model", "") || valueOf(provider, "default_model_id", valueOf(activeProvider, "model_id", ""));
  const defaultBaseUrl = valueOf(discovered, "base_url", "") || valueOf(provider, "default_base_url", valueOf(activeProvider, "base_url", ""));
  return {
    modelId: current.modelId ?? (isActive ? valueOf(activeProvider, "model_id", defaultModel) : defaultModel),
    baseUrl: current.baseUrl ?? (isActive ? valueOf(activeProvider, "base_url", defaultBaseUrl) : defaultBaseUrl),
    apiKey: current.apiKey ?? "",
    testPrompt: current.testPrompt ?? "Confirm the active provider path in one short sentence.",
  };
}

function providerProfilePayload(provider: DashboardRow, draft: ProviderDraft): Record<string, unknown> {
  const id = providerId(provider);
  const discovered = jsonObject(provider.discovered_state as DashboardJson | undefined);
  const modelId = draft.modelId || valueOf(provider, "default_model_id", "") || valueOf(discovered, "default_model", "");
  const payload: Record<string, unknown> = {
    profile_id: `provider-${id}`,
    provider_id: id,
    default_model: modelId,
    secret_references: providerSecretRefs(provider),
    metadata: { configured_from: "dashboard" },
  };
  const transportId = valueOf(provider, "transport_id", "");
  const authMethod = valueOf(provider, "auth_method", "");
  const baseUrl = draft.baseUrl || valueOf(provider, "default_base_url", "") || valueOf(discovered, "base_url", "");
  if (transportId) {
    payload.transport_id = transportId;
  }
  if (authMethod) {
    payload.auth_method = authMethod;
  }
  if (baseUrl) {
    payload.base_url = baseUrl;
  }
  return payload;
}

function EmbeddingProviderControls({
  dashboard,
  refresh,
}: {
  dashboard: InternalDashboardSnapshot;
  refresh: () => Promise<void>;
}): React.JSX.Element {
  const models = jsonObject(dashboard.operations.models);
  const activeEmbedding = {
    ...jsonObject(models.embeddingProvider),
    ...dashboard.providers.embedding_provider,
  };
  const [draft, setDraft] = React.useState<EmbeddingDraft>({
    mode: valueOf(activeEmbedding, "source", "local-default") === "configured" ? "openai-compatible" : "local",
    baseUrl: valueOf(activeEmbedding, "base_url", ""),
    modelId: valueOf(activeEmbedding, "model_id", ""),
    dimensions: valueOf(activeEmbedding, "dimensions", "1536"),
    apiKey: "",
  });
  const [status, setStatus] = React.useState("");

  React.useEffect(() => {
    setDraft((current) => ({
      ...current,
      mode: valueOf(activeEmbedding, "source", "local-default") === "configured" ? "openai-compatible" : "local",
      baseUrl: valueOf(activeEmbedding, "base_url", ""),
      modelId: valueOf(activeEmbedding, "model_id", current.modelId || ""),
      dimensions: valueOf(activeEmbedding, "dimensions", current.dimensions || "1536"),
      apiKey: "",
    }));
  }, [
    activeEmbedding.config_id,
    activeEmbedding.source,
    activeEmbedding.base_url,
    activeEmbedding.model_id,
    activeEmbedding.dimensions,
  ]);

  const saveEmbedding = async () => {
    setStatus("Saving embedding provider...");
    try {
      let result: unknown;
      if (draft.mode === "local") {
        result = await setEmbeddingProvider({ source: "local" });
      } else {
        const dimensions = Number(draft.dimensions.replaceAll(",", ""));
        if (!Number.isFinite(dimensions) || dimensions <= 0) {
          throw new Error("Embedding dimensions must be a positive number.");
        }
        result = await setEmbeddingProvider({
          source: "openai-compatible",
          baseUrl: draft.baseUrl,
          modelId: draft.modelId,
          dimensions,
          apiKey: draft.apiKey,
        });
      }
      await refresh();
      setStatus(embeddingSaveStatusMessage(result));
      setDraft((current) => ({ ...current, apiKey: "" }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Embedding provider save failed.");
    }
  };

  const activeEmbeddingSource = valueOf(activeEmbedding, "source", "local-default");
  const activeEmbeddingSecretReady = valueOf(activeEmbedding, "secret_status", "not-required") === "stored";
  const embeddingRows = [
    {
      id: "embedding-local-default",
      eyebrow: "local-elephant",
      title: "elephant-embed",
      summary: `Bundled local path · ${activeEmbeddingSource === "local-default" ? valueOf(activeEmbedding, "dimensions", "256") : "256"} dims · no external key required`,
      statusLabel: activeEmbeddingSource === "local-default" ? "In use" : "Built in",
      statusValue: activeEmbeddingSource === "local-default" ? "Local semantic recall" : "Ready when selected",
      statusMeta: activeEmbeddingSource === "local-default"
        ? valueOf(activeEmbedding, "embedding_bootstrap_status", valueOf(activeEmbedding, "status", "active"))
        : "Bundled path available",
      cardClass: activeEmbeddingSource === "local-default" ? styles.providerCardActive : undefined,
    },
    ...(activeEmbeddingSource === "configured"
      ? [
          {
            id: valueOf(activeEmbedding, "profile_id", "provider-embedding-openai-compatible"),
            eyebrow: valueOf(activeEmbedding, "provider_kind", "embedding"),
            title: valueOf(activeEmbedding, "provider_id", "openai-compatible-embed"),
            summary: `${valueOf(activeEmbedding, "model_id", "model")} · ${valueOf(activeEmbedding, "dimensions", "0")} dims · ${valueOf(activeEmbedding, "base_url", "endpoint saved")}`,
            statusLabel: activeEmbeddingSecretReady ? "Connected" : "Needs setup",
            statusValue: activeEmbeddingSecretReady ? "Stored local key" : "Missing stored key",
            statusMeta: valueOf(activeEmbedding, "base_url", valueOf(activeEmbedding, "status", "saved")),
            cardClass: activeEmbeddingSecretReady ? styles.providerCardActive : styles.providerCardConfigured,
          },
        ]
      : []),
  ];
  return (
    <Panel
      eyebrow="Embeddings"
      title="Embedding provider"
      detail="Choose how Elephant Agent indexes memory for recall. Local inference runs on-device; external uses an OpenAI-compatible embedding endpoint."
    >
      <div className={styles.segmentedControl} aria-label="Embedding provider mode">
        <button
          className={cx(draft.mode === "local" && styles.segmentedControlActive)}
          type="button"
          onClick={() => setDraft((current) => ({ ...current, mode: "local" }))}
        >
          Local inference
        </button>
        <button
          className={cx(draft.mode === "openai-compatible" && styles.segmentedControlActive)}
          type="button"
          onClick={() => setDraft((current) => ({ ...current, mode: "openai-compatible" }))}
        >
          External provider
        </button>
      </div>

      {draft.mode === "openai-compatible" ? (
        <section className={styles.providerConfigGrid}>
          <label className={styles.fieldStack}>
            <span>Base URL</span>
            <input value={draft.baseUrl} onChange={(event) => setDraft((current) => ({ ...current, baseUrl: event.target.value }))} />
          </label>
          <label className={styles.fieldStack}>
            <span>Model</span>
            <input value={draft.modelId} onChange={(event) => setDraft((current) => ({ ...current, modelId: event.target.value }))} />
          </label>
          <label className={styles.fieldStack}>
            <span>Dimensions</span>
            <input value={draft.dimensions} onChange={(event) => setDraft((current) => ({ ...current, dimensions: event.target.value }))} />
          </label>
          <label className={styles.fieldStack}>
            <span>API key</span>
            <input
              type="password"
              placeholder={valueOf(activeEmbedding, "secret_status", "") === "stored" ? "stored locally" : "paste once to store"}
              value={draft.apiKey}
              onChange={(event) => setDraft((current) => ({ ...current, apiKey: event.target.value }))}
            />
          </label>
        </section>
      ) : (
        <article className={styles.statusDetailCard}>
          <span>On-device embedding</span>
          <strong>elephant-embed · {valueOf(activeEmbedding, "dimensions", "256")} dims</strong>
          <p className={styles.statusDetailSummary}>
            Runs locally with no external API key. Model: {valueOf(activeEmbedding, "model_id", "elephant-embed")}.
          </p>
        </article>
      )}

      <div className={styles.controlToolbar}>
        <ActionButton onClick={() => void saveEmbedding()}>
          {draft.mode === "local" ? "Use local inference" : "Save external provider"}
        </ActionButton>
        {status ? <span>{status}</span> : null}
      </div>
    </Panel>
  );
}

function ProviderModelControls({
  dashboard,
  refresh,
}: {
  dashboard: InternalDashboardSnapshot;
  refresh: () => Promise<void>;
}): React.JSX.Element {
  const models = jsonObject(dashboard.operations.models);
  const activeProvider = jsonObject(models.activeProvider);
  const providers = asRows(models.providers);
  const keys = asRows(models.keys);
  const [expandedProvider, setExpandedProvider] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<string | null>(null);
  const [setupGuides, setSetupGuides] = React.useState<Record<string, unknown>>({});
  const [testResults, setTestResults] = React.useState<Record<string, unknown>>({});
  const [modelOptions, setModelOptions] = React.useState<Record<string, DashboardRow[]>>({});
  const [keyDrafts, setKeyDrafts] = React.useState<Record<string, string>>({});
  const [drafts, setDrafts] = React.useState<Record<string, ProviderDraft>>({});

  const updateDraft = (id: string, patch: Partial<ProviderDraft>) => {
    setDrafts((current) => ({ ...current, [id]: { ...(current[id] ?? {}), ...patch } }));
  };

  const loadSetup = async (provider: DashboardRow) => {
    const id = providerId(provider);
    try {
      setStatus(`Loading ${providerDisplayName(provider)} setup...`);
      const result = await loadProviderSetup(id);
      setSetupGuides((current) => ({ ...current, [id]: result.guide ?? result }));
      setStatus(`${providerDisplayName(provider)} setup loaded.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Provider setup load failed.");
    }
  };

  const loadModels = async (provider: DashboardRow, draft: ProviderDraft) => {
    const id = providerId(provider);
    try {
      setStatus(`Loading ${providerDisplayName(provider)} models...`);
      const result = await loadProviderModels({
        providerId: id,
        baseUrl: draft.baseUrl,
        apiKey: draft.apiKey,
      });
      const rows = asRows((result.models ?? []) as DashboardJson);
      setModelOptions((current) => ({ ...current, [id]: rows }));
      setStatus(`${providerDisplayName(provider)} models loaded: ${rows.length || "catalog hints only"}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Model discovery failed.");
    }
  };

  const toggleProvider = (provider: DashboardRow, draft: ProviderDraft, shouldAutoLoadModels: boolean) => {
    const id = providerId(provider);
    const shouldExpand = expandedProvider !== id;
    setExpandedProvider(shouldExpand ? id : null);
    if (shouldExpand && shouldAutoLoadModels && modelOptions[id] === undefined) {
      void loadModels(provider, draft);
    }
  };

  const runTest = async (provider: DashboardRow, draft: ProviderDraft) => {
    const id = providerId(provider);
    try {
      setStatus("Running active provider test...");
      const result = await runProviderTest(draft.testPrompt ?? "Confirm the active provider path.");
      setTestResults((current) => ({ ...current, [id]: result }));
      setStatus(`Test: ${readString(result as DashboardRow, ["status"], "completed")}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Provider test failed.");
    }
  };

  const saveProvider = async (provider: DashboardRow, draft: ProviderDraft) => {
    const id = providerId(provider);
    try {
      setStatus(`Saving ${providerDisplayName(provider)} as default...`);
      const payload = providerProfilePayload(provider, draft);
      await setDefaultProvider(payload);
      const secretRefs = providerSecretRefs(provider).map((ref) => ({ referenceId: valueOf(ref, "reference_id"), value: draft.apiKey }));
      for (const ref of secretRefs) {
        if (ref.value?.trim()) {
          await saveProviderKey(ref.referenceId, ref.value);
        }
      }
      await refresh();
      setStatus(`${providerDisplayName(provider)} saved as the default provider.`);
      setDrafts((current) => ({
        ...current,
        [id]: {
          ...(current[id] ?? {}),
          apiKey: "",
        },
      }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Provider save failed.");
    }
  };

  const saveExistingKey = async (referenceId: string, valueText: string) => {
    try {
      await saveProviderKey(referenceId, valueText);
      await refresh();
      setStatus(`${referenceId} saved to the local secret store.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Key save failed.");
    }
  };

  const clearKey = async (referenceId: string) => {
    try {
      await deleteProviderKey(referenceId);
      await refresh();
      setStatus(`${referenceId} removed from the local secret store.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Key delete failed.");
    }
  };

  const activeProviderId = valueOf(activeProvider, "provider_id");
  const configuredCount = providers.filter((provider) =>
    providerId(provider) === activeProviderId
    || providerHasRuntimeAuth(provider)
    || providerKeyRows(provider, keys).some((key) => key.hasValue === true),
  ).length;
  const sections = providerSections(providers);

  return (
    <>
      <section className={cx(styles.metricGrid, styles.metricGridCompact)}>
        <MetricCard compact metric={{ label: "Active provider", value: valueOf(activeProvider, "display_name", activeProviderId), note: `${valueOf(activeProvider, "source")} · ${valueOf(activeProvider, "model_id", valueOf(activeProvider, "default_model"))}`, tone: toneForStatus(valueOf(activeProvider, "source")) }} />
        <MetricCard compact metric={{ label: "Configured", value: `${configuredCount}/${providers.length}`, note: "Providers with active selection, stored keys, or local OAuth/runtime auth.", tone: configuredCount ? "healthy" : "attention" }} />
        <MetricCard compact metric={{ label: "Keys", value: `${keys.filter((key) => key.hasValue === true).length}/${keys.length}`, note: "Encrypted local key references with stored values.", tone: keys.some((key) => key.hasValue === true) ? "healthy" : "attention" }} />
      </section>

      <Panel eyebrow="Models" title="How Elephant Agent thinks" detail="Pick the model Elephant Agent reaches for, sign in with OAuth or an API key, and test the path — all from one place.">
        {status ? (
          <div className={styles.controlToolbar}>
            <span>{status}</span>
          </div>
        ) : null}
        {sections.length ? (
          <div className={styles.providerSections}>
            {sections.map((section) => (
              <section key={section.id} className={styles.providerSection}>
                <header className={styles.providerSectionHeader}>
                  <div>
                    <strong>{section.title}</strong>
                    <span>{section.detail}</span>
                  </div>
                  <small>{section.providers.length} provider{section.providers.length === 1 ? "" : "s"}</small>
                </header>
                <div className={styles.providerList}>
                  {section.providers.map((provider) => {
                    const id = providerId(provider);
                    const draft = providerDraft(provider, activeProvider, drafts);
                    const isExpanded = expandedProvider === id;
                    const isActive = id === activeProviderId;
                    const providerKeys = providerKeyRows(provider, keys);
                    const storedKeyCount = providerKeys.filter((key) => key.hasValue === true).length;
                    const hasRuntimeAuth = providerHasRuntimeAuth(provider);
                    const providerStatus = valueOf(provider, "status", "");
                    const providerSource = valueOf(provider, "source", "");
                    const providerConnectionLabel = isActive
                      ? "In use"
                      : hasRuntimeAuth
                        ? "Connected"
                        : storedKeyCount
                          ? "Configured"
                          : "Needs setup";
                    const providerCardStatusClass = isActive
                      ? styles.providerCardActive
                      : hasRuntimeAuth
                        ? styles.providerCardConnected
                        : undefined;
                    const secretRefs = providerSecretRefs(provider);
                    const modelRows = providerModelOptions(provider, modelOptions[id]);
                    const canAutoLoadModels = isActive || hasRuntimeAuth || storedKeyCount > 0 || Boolean(draft.apiKey?.trim());
                    return (
                      <article key={id} className={cx(styles.providerCard, providerCardStatusClass, isExpanded && styles.providerCardOpen)}>
                        <button className={styles.providerCardHeader} type="button" onClick={() => toggleProvider(provider, draft, canAutoLoadModels)}>
                          <RowIcon kind="models" />
                          <div className={styles.providerCardTitle}>
                            <span>{id}</span>
                            <strong>{providerDisplayName(provider)}</strong>
                            <p>{valueOf(provider, "catalog_summary", "Provider from the runtime catalog.")}</p>
                          </div>
                          <div className={styles.providerCardState}>
                            <span>{providerConnectionLabel}</span>
                            <strong>{storedKeyCount ? `${storedKeyCount} stored key${storedKeyCount === 1 ? "" : "s"}` : providerSource || "No key stored"}</strong>
                            {providerStatus ? <small>{providerStatus}</small> : <small>{valueOf(provider, "auth_method", "auth n/a")}</small>}
                          </div>
                        </button>
                        {isExpanded ? (
                          <div className={styles.providerExpanded}>
                            <div className={styles.compactInfoGrid}>
                              <div><span>Transport</span><strong>{valueOf(provider, "transport_id")}</strong></div>
                              <div><span>Default model</span><strong>{valueOf(provider, "default_model_id")}</strong></div>
                              <div><span>Base URL</span><strong>{valueOf(provider, "default_base_url", valueOf(activeProvider, "base_url"))}</strong></div>
                              <div><span>Env aliases</span><strong>{asTextList(provider.env_var_names ?? provider.envVarNames).join(", ") || "n/a"}</strong></div>
                            </div>
                            <section className={styles.providerConfigGrid}>
                              <label className={styles.fieldStack}>
                                <span>Model</span>
                                <select value={draft.modelId ?? ""} onChange={(event) => updateDraft(id, { modelId: event.target.value })}>
                                  {modelRows.map((model) => (
                                    <option key={valueOf(model, "model_id")} value={valueOf(model, "model_id")}>
                                      {valueOf(model, "label", valueOf(model, "model_id"))}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <label className={styles.fieldStack}>
                                <span>Base URL</span>
                                <input value={draft.baseUrl ?? ""} onChange={(event) => updateDraft(id, { baseUrl: event.target.value })} />
                              </label>
                            </section>
                            {secretRefs.length ? (
                              <section className={styles.providerSecretPanel}>
                                <label className={styles.fieldStack}>
                                  <span>API key</span>
                                  <input
                                    type="password"
                                    value={draft.apiKey ?? ""}
                                    placeholder={storedKeyCount ? "stored locally" : "paste once to store locally"}
                                    onChange={(event) => updateDraft(id, { apiKey: event.target.value })}
                                  />
                                </label>
                                <p>The API key is stored locally and reused by this provider profile. OAuth providers skip this secret field.</p>
                              </section>
                            ) : (
                              <EmptyPanel title="OAuth or local auth provider" detail="No API key field is required for this provider. Use setup to confirm the local auth path." />
                            )}
                            {providerKeys.length ? (
                              <details className={styles.inlineDetails}>
                                <summary>Stored key records</summary>
                                <div className={styles.providerInlineSection}>
                                  {providerKeys.map((key) => {
                                    const referenceId = valueOf(key, "referenceId", valueOf(key, "reference_id"));
                                    const draftKey = keyDrafts[referenceId] ?? "";
                                    return (
                                      <article key={referenceId} className={styles.providerKeyRow}>
                                        <div>
                                          <span>{valueOf(key, "profileId", valueOf(key, "profile_id"))}</span>
                                          <strong>{valueOf(key, "secretKey", valueOf(key, "secret_key", "api_key"))}</strong>
                                        </div>
                                        <StatusBadge tone={key.hasValue ? "healthy" : "attention"}>{key.hasValue ? "stored" : "missing"}</StatusBadge>
                                        <input
                                          type="password"
                                          placeholder="replace stored value"
                                          value={draftKey}
                                          onChange={(event) => setKeyDrafts((current) => ({ ...current, [referenceId]: event.target.value }))}
                                        />
                                        <ActionButton variant="ghost" onClick={() => void saveExistingKey(referenceId, draftKey)}>Save</ActionButton>
                                        <ActionButton variant="ghost" onClick={() => void clearKey(referenceId)}>Remove</ActionButton>
                                      </article>
                                    );
                                  })}
                                </div>
                              </details>
                            ) : null}
                            <label className={styles.fieldStack}>
                              <span>Runtime test prompt</span>
                              <textarea rows={3} value={draft.testPrompt ?? ""} onChange={(event) => updateDraft(id, { testPrompt: event.target.value })} />
                            </label>
                            <div className={styles.controlToolbar}>
                              <ActionButton onClick={() => void saveProvider(provider, draft)}>Save as default</ActionButton>
                              <ActionButton variant="ghost" onClick={() => void loadModels(provider, draft)}>Load models</ActionButton>
                              <ActionButton variant="ghost" onClick={() => void loadSetup(provider)}>Load setup</ActionButton>
                              <ActionButton variant="ghost" onClick={() => void runTest(provider, draft)}>Run active test</ActionButton>
                              <ViewButton title={`${providerDisplayName(provider)} payload`} items={[{ label: "provider_profile", value: <JsonBlock value={providerProfilePayload(provider, draft)} /> }]} />
                            </div>
                            {setupGuides[id] ? (
                              <details className={styles.inlineDetails} open>
                                <summary>Setup guide</summary>
                                <JsonBlock value={setupGuides[id]} />
                              </details>
                            ) : null}
                            {testResults[id] ? (
                              <details className={styles.inlineDetails} open>
                                <summary>Runtime test result</summary>
                                <JsonBlock value={testResults[id]} />
                              </details>
                            ) : null}
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <EmptyPanel title="No providers yet" detail="Providers will appear here once Elephant Agent has any set up." />
        )}
      </Panel>

    </>
  );
}

export function ModelsPage(): React.JSX.Element {
  return <ProvidersPage />;
}

function skillExternalDirs(settings: DashboardRow): string[] {
  const globalConfig = jsonObject(settings.globalConfig);
  const skillsConfig = jsonObject(globalConfig.skills);
  return asTextList(skillsConfig.external_dirs);
}

export function SkillsPage(): React.JSX.Element {
  const [query, setQuery] = React.useState("");
  const [page, setPage] = React.useState(0);
  const [message, setMessage] = React.useState<string | null>(null);
  const [pendingId, setPendingId] = React.useState<string | null>(null);
  const pageSize = 24;
  React.useEffect(() => {
    setPage(0);
  }, [query]);
  return (
    <DashboardPage section="skills">
      {(dashboard, { refresh }) => {
        const normalized = query.trim().toLowerCase();
        const skills = dashboard.operations.skills.filter((skill) =>
          !normalized || JSON.stringify(skill).toLowerCase().includes(normalized),
        );
        const totalPages = Math.max(1, Math.ceil(skills.length / pageSize));
        const currentPage = Math.min(page, totalPages - 1);
        const visibleSkills = skills.slice(currentPage * pageSize, currentPage * pageSize + pageSize);
        const toggle = async (skill: DashboardRow) => {
          const skillId = valueOf(skill, "skillId");
          const enabled = !Boolean(skill.enabled);
          try {
            setPendingId(skillId);
            const result = await setConsoleItemEnabled("skills", skillId, enabled) as DashboardRow;
            await refresh();
            setMessage(`${skillId} ${enabled ? "enabled" : "disabled"}; ${valueOf(result, "runtimeStatus", "profile override written")}.`);
          } catch (error) {
            setMessage(error instanceof Error ? error.message : "Skill override failed.");
          } finally {
            setPendingId(null);
          }
        };
        const operatorSkills = dashboard.operations.skills.filter((skill) => skill.toggleable !== false);
        const enabledCount = operatorSkills.filter((skill) => skill.enabled === true).length;
        const discoverOnlyCount = dashboard.operations.skills.length - operatorSkills.length;
        const skillAffinities = asRows(dashboard.operations.skill_affinities);
        const activeAffinityClaims = skillAffinities.reduce((sum, row) => sum + numberOf(row, "activeCount"), 0);
        return (
          <>
            <section className={cx(styles.metricGrid, styles.metricGridCompact, styles.skillsMetricGrid)}>
              <MetricCard compact metric={{ label: "Skills", value: `${dashboard.operations.skills.length}`, note: "Installed, authored, built-in, and external entries.", tone: "neutral" }} />
              <MetricCard compact metric={{ label: "Ready to use", value: `${enabledCount}`, note: "Skills active and available to Elephant Agent's next reply.", tone: enabledCount ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Affinities", value: `${skillAffinities.length}`, note: `${activeAffinityClaims} active PM skill affinity claim(s).`, tone: skillAffinities.length ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Discover only", value: `${discoverOnlyCount}`, note: "External shelves available for list/view without toggles.", tone: discoverOnlyCount ? "attention" : "neutral" }} />
            </section>
            <Panel eyebrow="Skills" title="What Elephant Agent knows how to do" detail="Search, inspect, and toggle skill packages. What Elephant Agent has learned to use naturally stays on the You page.">
              <SearchBox
                query={query}
                setQuery={setQuery}
                placeholder="Skill name, id, source..."
                hint={(
                  <>
                    <span>{skills.length} matching skill(s).</span>
                    <span>Config.yaml shelves: {skillExternalDirs(dashboard.operations.settings).join(", ") || "none"}</span>
                  </>
                )}
              />
              {message ? <EmptyPanel title="Override written" detail={message} /> : null}
              {skills.length ? (
                <>
                  <div className={styles.capabilityList}>
                    {visibleSkills.map((skill) => {
                      const skillId = valueOf(skill, "skillId");
                      const enabled = skill.enabled === true;
                      const toggleable = skill.toggleable !== false;
                      return (
                        <article
                          key={valueOf(skill, "reference", skillId)}
                          className={cx(styles.capabilityRow, !toggleable && styles.capabilityRowDiscoverOnly)}
                        >
                          <RowIcon kind={toggleable ? "skills" : "skillsDiscoverOnly"} />
                          <div className={styles.capabilityMain}>
                            <span>
                              {toggleable
                                ? `${valueOf(skill, "source")} · default ${skill.defaultEnabled ? "enabled" : "disabled"}`
                                : `${valueOf(skill, "source")} · external discover-only shelf`}
                            </span>
                            <strong>{valueOf(skill, "displayName", skillId)}</strong>
                            <p>{compactText(valueOf(skill, "summary", "No summary persisted."), 210)}</p>
                          </div>
                          <div className={styles.capabilityState}>
                            <span>{skillStateLabel(skill)}</span>
                            {toggleable ? <small>{skill.override == null ? `default ${skill.defaultEnabled ? "on" : "off"}` : "profile override"}</small> : null}
                          </div>
                          {toggleable ? (
                            <button
                              aria-pressed={enabled}
                              className={cx(styles.toggleSwitch, enabled && styles.toggleSwitchOn)}
                              disabled={pendingId === skillId || !boolOf(skill, "toggleable")}
                              type="button"
                              onClick={() => void toggle(skill)}
                            >
                              <span />
                              <strong>{pendingId === skillId ? "Saving" : enabled ? "On" : "Off"}</strong>
                            </button>
                          ) : null}
                          <ViewButton title={skillId} items={detailItems(skill)} />
                        </article>
                      );
                    })}
                  </div>
                  <PaginationBar
                    totalItems={skills.length}
                    currentPage={currentPage}
                    totalPages={totalPages}
                    pageSize={pageSize}
                    label="skills"
                    onPrevious={() => setPage((current) => Math.max(0, current - 1))}
                    onNext={() => setPage((current) => Math.min(totalPages - 1, current + 1))}
                  />
                </>
              ) : (
                <EmptyPanel
                  title={dashboard.operations.skills.length ? "No skills match" : "No skills exposed"}
                  detail="Adjust the search text or inspect the active skill registry if expected skills are missing."
                />
              )}
            </Panel>
          </>
        );
      }}
    </DashboardPage>
  );
}

type McpDraftHeader = {
  key: string;
  value: string;
};

type McpToolDraft = {
  serverId: string;
  toolName: string;
  serverLabel: string;
  transport: string;
  command: string;
  argsText: string;
  url: string;
  envText: string;
  headers: McpDraftHeader[];
};

const DEFAULT_CUSTOM_MCP_TOOL_NAME = "server";
const EMPTY_MCP_HEADER: McpDraftHeader = { key: "", value: "" };

const EMPTY_MCP_TOOL_DRAFT: McpToolDraft = {
  serverId: "",
  toolName: DEFAULT_CUSTOM_MCP_TOOL_NAME,
  serverLabel: "",
  transport: "stdio",
  command: "",
  argsText: "[]",
  url: "",
  envText: "{}",
  headers: [{ ...EMPTY_MCP_HEADER }],
};

function asStringRecord(valueLike: DashboardJson | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(jsonObject(valueLike)).map(([key, value]) => [key, String(value)]),
  );
}

function parseObjectText(text: string, label: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) {
    return {};
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function parseStringArrayText(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return [];
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.map((item) => String(item).trim()).filter(Boolean);
    }
  } catch {
    // Fall back to comma-separated input.
  }
  return trimmed.split(",").map((item) => item.trim()).filter(Boolean);
}

function parseStringRecordText(text: string, label: string): Record<string, string> {
  return Object.fromEntries(
    Object.entries(parseObjectText(text, label)).map(([key, value]) => [key, String(value)]),
  );
}

function stringRecordToDraftHeaders(valueLike: DashboardJson | undefined): McpDraftHeader[] {
  const rows = Object.entries(asStringRecord(valueLike)).map(([key, value]) => ({ key, value }));
  return rows.length ? rows : [{ ...EMPTY_MCP_HEADER }];
}

function draftHeadersToRecord(entries: readonly McpDraftHeader[], label: string): Record<string, string> {
  const next: Record<string, string> = {};
  entries.forEach((entry) => {
    const key = entry.key.trim();
    const valueText = entry.value;
    if (!key && !valueText.trim()) {
      return;
    }
    if (!key) {
      throw new Error(`${label} key is required when a value is provided.`);
    }
    if (Object.hasOwn(next, key)) {
      throw new Error(`${label} contains a duplicate key: ${key}`);
    }
    next[key] = valueText;
  });
  return next;
}

function isStdioMcpTransport(transport: string): boolean {
  return !transport.trim() || transport === "stdio";
}

function mcpRuntimeTarget(row: DashboardRow | undefined, fallback = "No command or URL configured yet"): string {
  return readString(row, ["command", "url"], fallback);
}

function mcpDraftFromRows(server: DashboardRow, tool?: DashboardRow): McpToolDraft {
  return {
    serverId: valueOf(server, "serverId", valueOf(tool ?? {}, "serverId", "")),
    toolName: valueOf(tool ?? {}, "toolName", DEFAULT_CUSTOM_MCP_TOOL_NAME),
    serverLabel: valueOf(server, "label", valueOf(tool ?? {}, "serverLabel", "")),
    transport: valueOf(server, "transport", valueOf(tool ?? {}, "transport", "stdio")),
    command: valueOf(server, "command", valueOf(tool ?? {}, "command", "")),
    argsText: JSON.stringify(asTextList((server.args ?? tool?.args) as DashboardJson | undefined), null, 2),
    url: valueOf(server, "url", valueOf(tool ?? {}, "url", "")),
    envText: JSON.stringify(asStringRecord((server.env ?? tool?.env) as DashboardJson | undefined), null, 2),
    headers: stringRecordToDraftHeaders((server.headers ?? tool?.headers) as DashboardJson | undefined),
  };
}

function customMcpPayloadFromDraft(draft: McpToolDraft): CustomMcpToolPayload {
  return {
    serverId: draft.serverId.trim(),
    toolName: draft.toolName.trim() || DEFAULT_CUSTOM_MCP_TOOL_NAME,
    serverLabel: draft.serverLabel.trim() || undefined,
    transport: draft.transport.trim() || undefined,
    command: draft.command.trim() || undefined,
    args: parseStringArrayText(draft.argsText),
    url: draft.url.trim() || undefined,
    env: parseStringRecordText(draft.envText, "Environment"),
    headers: draftHeadersToRecord(draft.headers, "Headers"),
  };
}

function McpToolEditorDialog({
  open,
  editingToolKey,
  draft,
  setDraft,
  pending,
  discoveryPending,
  discovery,
  configPath,
  onClose,
  onSave,
  onDiscover,
}: {
  open: boolean;
  editingToolKey: string | null;
  draft: McpToolDraft;
  setDraft: React.Dispatch<React.SetStateAction<McpToolDraft>>;
  pending: boolean;
  discoveryPending: boolean;
  discovery: DashboardRow | null;
  configPath: string;
  onClose: () => void;
  onSave: () => Promise<unknown>;
  onDiscover: () => Promise<unknown>;
}): React.JSX.Element {
  const editMode = Boolean(editingToolKey);
  const stdioTransport = isStdioMcpTransport(draft.transport);
  const runtimeTarget = stdioTransport
    ? (draft.command.trim() || "No command configured yet")
    : (draft.url.trim() || "No URL configured yet");
  const discoveredTools = asRows(discovery?.tools as DashboardJson | undefined);
  const discoveryStatus = discovery ? valueOf(discovery, "status", "unknown") : "Not run";

  const updateHeader = (index: number, patch: Partial<McpDraftHeader>) => {
    setDraft((current) => ({
      ...current,
      headers: current.headers.map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patch } : entry),
    }));
  };

  const removeHeader = (index: number) => {
    setDraft((current) => {
      const nextHeaders = current.headers.filter((_, entryIndex) => entryIndex !== index);
      return {
        ...current,
        headers: nextHeaders.length ? nextHeaders : [{ ...EMPTY_MCP_HEADER }],
      };
    });
  };

  const addHeader = () => {
    setDraft((current) => ({
      ...current,
      headers: [...current.headers, { ...EMPTY_MCP_HEADER }],
    }));
  };

  return (
    <FloatingFormModal
      open={open}
      title={editMode ? `Edit MCP server · ${draft.serverId || "custom"}` : "Add custom MCP server"}
      subtitle={stdioTransport ? "Save the stdio server and sync its live tool list into config." : "Save the remote MCP server and sync its live tool list into config."}
      onClose={onClose}
      footer={(
        <>
          <span>{configPath}</span>
          <div className={styles.controlToolbar}>
            <ActionButton disabled={pending || discoveryPending} variant="ghost" onClick={onClose}>
              Cancel
            </ActionButton>
            <ActionButton disabled={pending || discoveryPending} variant="ghost" onClick={() => void onDiscover()}>
              {discoveryPending ? "Verifying" : "Verify connection"}
            </ActionButton>
            <ActionButton disabled={pending || discoveryPending} onClick={() => void onSave()}>
              {pending ? "Saving" : editMode ? "Save & sync tools" : "Add & sync tools"}
            </ActionButton>
          </div>
        </>
      )}
    >
      <section className={styles.mcpSummaryStrip}>
        <div className={styles.mcpSummaryItem}>
          <span>Server</span>
          <strong>{draft.serverId || "new server"}</strong>
        </div>
        <div className={styles.mcpSummaryItem}>
          <span>Transport</span>
          <strong>{draft.transport || "stdio"}</strong>
        </div>
        <div className={styles.mcpSummaryItem}>
          <span>Target</span>
          <strong>{runtimeTarget}</strong>
        </div>
      </section>

      <article className={cx(styles.settingsSectionCard, styles.mcpFormMainCard)}>
        <header>
          <div className={styles.settingsSectionHeaderCopy}>
            <span>Core MCP config</span>
            <strong>Save server config together with the current live MCP tool list</strong>
          </div>
        </header>
        <div className={styles.formGrid}>
          <label className={styles.fieldStack}>
            <span>Server ID</span>
            <input
              disabled={editMode}
              placeholder="filesystem"
              value={draft.serverId}
              onChange={(event) => setDraft((current) => ({ ...current, serverId: event.target.value }))}
            />
          </label>
          <label className={styles.fieldStack}>
            <span>Server label</span>
            <input
              placeholder="Filesystem"
              value={draft.serverLabel}
              onChange={(event) => setDraft((current) => ({ ...current, serverLabel: event.target.value }))}
            />
          </label>
          <label className={styles.fieldStack}>
            <span>Transport</span>
            <select
              value={draft.transport}
              onChange={(event) => setDraft((current) => ({ ...current, transport: event.target.value }))}
            >
              <option value="stdio">stdio</option>
              <option value="http">http</option>
              <option value="streamable-http">streamable-http</option>
            </select>
          </label>
          {stdioTransport ? (
            <>
              <label className={styles.fieldStack}>
                <span>Command</span>
                <input
                  placeholder="npx"
                  value={draft.command}
                  onChange={(event) => setDraft((current) => ({ ...current, command: event.target.value }))}
                />
              </label>
              <label className={styles.fieldStack}>
                <span>Args JSON or CSV</span>
                <textarea
                  placeholder='["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]'
                  value={draft.argsText}
                  onChange={(event) => setDraft((current) => ({ ...current, argsText: event.target.value }))}
                />
              </label>
              <label className={styles.fieldStack}>
                <span>Environment JSON</span>
                <textarea
                  placeholder='{"HTTP_PROXY": "http://127.0.0.1:7890"}'
                  value={draft.envText}
                  onChange={(event) => setDraft((current) => ({ ...current, envText: event.target.value }))}
                />
              </label>
            </>
          ) : (
            <>
              <label className={styles.fieldStack}>
                <span>URL</span>
                <input
                  placeholder="https://example.com/mcp"
                  value={draft.url}
                  onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))}
                />
              </label>
              <div className={cx(styles.fieldStack, styles.mcpKeyValueField)}>
                <span>Headers</span>
                <div className={styles.mcpKeyValueList}>
                  {draft.headers.map((entry, index) => (
                    <div key={`${entry.key}-${index}`} className={styles.mcpKeyValueRow}>
                      <input
                        placeholder="Authorization"
                        value={entry.key}
                        onChange={(event) => updateHeader(index, { key: event.target.value })}
                      />
                      <input
                        placeholder="Bearer <token>"
                        value={entry.value}
                        onChange={(event) => updateHeader(index, { value: event.target.value })}
                      />
                      <ActionButton
                        variant="ghost"
                        disabled={draft.headers.length === 1 && !entry.key.trim() && !entry.value.trim()}
                        onClick={() => removeHeader(index)}
                      >
                        Remove
                      </ActionButton>
                    </div>
                  ))}
                </div>
                <ActionButton variant="ghost" onClick={addHeader}>Add header</ActionButton>
              </div>
            </>
          )}
        </div>
      </article>

      <article className={cx(styles.settingsSectionCard, styles.mcpDiscoveryCard)}>
        <header>
          <div className={styles.settingsSectionHeaderCopy}>
            <span>Live discovery</span>
            <strong>Preview the live MCP tools that will be synced when you save this server</strong>
          </div>
          <StatusBadge tone={toneForStatus(discoveryStatus)}>{discoveryStatus}</StatusBadge>
        </header>
        {discovery ? (
          <>
            <div className={styles.compactInfoGrid}>
              <div><span>Tools</span><strong>{valueOf(discovery, "toolCount", `${discoveredTools.length}`)}</strong></div>
              <div><span>Duration</span><strong>{valueOf(discovery, "durationMs", "n/a")}ms</strong></div>
              <div><span>Transport</span><strong>{valueOf(discovery, "transport", draft.transport || "stdio")}</strong></div>
            </div>
            {valueOf(discovery, "error", "") ? (
              <EmptyPanel title="Discovery failed" detail={valueOf(discovery, "error")} />
            ) : discoveredTools.length ? (
              <div className={styles.mcpDiscoveredToolList}>
                {discoveredTools.map((tool) => {
                  const requiredFields = asTextList(tool.requiredFields).join(", ");
                  return (
                    <article key={valueOf(tool, "name")} className={styles.mcpDiscoveredToolRow}>
                      <div>
                        <span>{requiredFields ? `Required · ${requiredFields}` : "No required params"}</span>
                        <strong>{valueOf(tool, "name")}</strong>
                        <p>{compactText(valueOf(tool, "description", "No description provided."), 220)}</p>
                      </div>
                      <ViewButton title={valueOf(tool, "name")} items={detailItems(tool)} variant="ghost" />
                    </article>
                  );
                })}
              </div>
            ) : (
              <EmptyPanel title="No tools discovered" detail="The server responded, but no MCP tool contracts were returned." />
            )}
            <details className={styles.inlineDetails}>
              <summary>Raw discovery response</summary>
              <JsonBlock value={discovery} />
            </details>
          </>
        ) : (
          <p className={styles.mcpFormHint}>Use Verify connection to preview the live MCP tool list. Saving the server will sync those tools into config.</p>
        )}
      </article>
    </FloatingFormModal>
  );
}

export function ToolsPage(): React.JSX.Element {
  const [query, setQuery] = React.useState("");
  const [toolPage, setToolPage] = React.useState(0);
  const [mcpPage, setMcpPage] = React.useState(0);
  const [message, setMessage] = React.useState<string | null>(null);
  const [pendingId, setPendingId] = React.useState<string | null>(null);
  const [editingToolKey, setEditingToolKey] = React.useState<string | null>(null);
  const [mcpDraft, setMcpDraft] = React.useState<McpToolDraft>(EMPTY_MCP_TOOL_DRAFT);
  const [mcpModalOpen, setMcpModalOpen] = React.useState(false);
  const [mcpDiscovery, setMcpDiscovery] = React.useState<DashboardRow | null>(null);
  const [serverDiscoveryResults, setServerDiscoveryResults] = React.useState<Record<string, DashboardRow>>({});
  const toolPageSize = 18;
  const mcpPageSize = 8;

  React.useEffect(() => {
    setToolPage(0);
    setMcpPage(0);
  }, [query]);

  const resetMcpDraft = React.useCallback(() => {
    setEditingToolKey(null);
    setMcpDraft(EMPTY_MCP_TOOL_DRAFT);
    setMcpDiscovery(null);
  }, []);

  const closeMcpModal = React.useCallback(() => {
    setMcpModalOpen(false);
    setMcpDiscovery(null);
  }, []);

  const openCreateMcpModal = React.useCallback(() => {
    setMessage(null);
    resetMcpDraft();
    setMcpModalOpen(true);
  }, [resetMcpDraft]);

  return (
    <DashboardPage section="tools">
      {(dashboard, { refresh }) => {
        const mcp = jsonObject(dashboard.operations.mcp);
        const settings = dashboard.operations.settings;
        const configPath = valueOf(mcp, "configPath", valueOf(settings, "globalConfigPath"));
        const normalized = query.trim().toLowerCase();
        const builtinTools = dashboard.operations.tools.filter((tool) =>
          !normalized || JSON.stringify(tool).toLowerCase().includes(normalized),
        );
        const toolTotalPages = Math.max(1, Math.ceil(builtinTools.length / toolPageSize));
        const currentToolPage = Math.min(toolPage, toolTotalPages - 1);
        const visibleBuiltinTools = builtinTools.slice(currentToolPage * toolPageSize, currentToolPage * toolPageSize + toolPageSize);
        const mcpToolsAll = asRows(mcp.tools);
        const storedToolsByServerId = new Map<string, DashboardRow[]>();
        mcpToolsAll.forEach((tool) => {
          const serverId = valueOf(tool, "serverId", "");
          if (!serverId) {
            return;
          }
          const existing = storedToolsByServerId.get(serverId) ?? [];
          existing.push(tool);
          storedToolsByServerId.set(serverId, existing);
        });
        const customMcpServersAll: DashboardRow[] = asRows(mcp.servers).map((server) => ({
          ...server,
          storedTools: storedToolsByServerId.get(valueOf(server, "serverId", "")) ?? [],
        }));
        const customMcpServers = customMcpServersAll.filter((server) =>
          !normalized || JSON.stringify({ ...server, storedTools: server.storedTools ?? [] }).toLowerCase().includes(normalized),
        );
        const mcpTotalPages = Math.max(1, Math.ceil(customMcpServers.length / mcpPageSize));
        const currentMcpPage = Math.min(mcpPage, mcpTotalPages - 1);
        const visibleCustomMcpServers = customMcpServers.slice(currentMcpPage * mcpPageSize, currentMcpPage * mcpPageSize + mcpPageSize);
        const verifiedServerCount = customMcpServersAll.filter((server) => {
          const result = serverDiscoveryResults[valueOf(server, "serverId", "")];
          return result && valueOf(result, "status", "").toLowerCase() === "ok";
        }).length;
        const syncedToolCount = mcpToolsAll.length;
        const enabledCustomMcpToolCount = mcpToolsAll.filter((tool) => tool.enabled === true).length;

        const openEditMcpModal = (server: DashboardRow) => {
          const serverId = valueOf(server, "serverId", "");
          setEditingToolKey(serverId || null);
          setMcpDraft(mcpDraftFromRows(server));
          setMcpDiscovery(serverDiscoveryResults[serverId] ?? null);
          setMessage(null);
          setMcpModalOpen(true);
        };

        const toggleBuiltin = async (tool: DashboardRow) => {
          const toolId = valueOf(tool, "toolId");
          const enabled = !Boolean(tool.enabled);
          try {
            setPendingId(`builtin:${toolId}`);
            const result = await setConsoleItemEnabled("tools", toolId, enabled) as DashboardRow;
            await refresh();
            setMessage(`${toolId} ${enabled ? "enabled" : "disabled"}; ${valueOf(result, "runtimeStatus", "profile override written")}.`);
          } catch (error) {
            setMessage(error instanceof Error ? error.message : "Built-in tool update failed.");
          } finally {
            setPendingId(null);
          }
        };

        const discoverServer = async (payload: CustomMcpToolPayload, pendingKey: string) => {
          try {
            setPendingId(pendingKey);
            const result = await discoverCustomMcpTools(payload) as DashboardRow;
            const serverId = payload.serverId;
            setServerDiscoveryResults((current) => ({ ...current, [serverId]: result }));
            setMcpDiscovery(result);
            const toolCount = asRows(result.tools as DashboardJson | undefined).length || numberOf(result, "toolCount");
            setMessage(
              valueOf(result, "status", "unknown") === "ok"
                ? `${serverId} verified; discovered ${toolCount} tool${toolCount === 1 ? "" : "s"}.`
                : `${serverId} verification failed: ${valueOf(result, "error", "unknown error")}`,
            );
            return result;
          } catch (error) {
            const failure: DashboardRow = { status: "failed", error: error instanceof Error ? error.message : "MCP discovery failed." };
            setMcpDiscovery(failure);
            setMessage(valueOf(failure, "error"));
            return null;
          } finally {
            setPendingId(null);
          }
        };

        const saveMcpServer = async () => {
          const payload = customMcpPayloadFromDraft(mcpDraft);
          try {
            setPendingId("mcp-form");
            const discovery = await discoverCustomMcpTools(payload) as DashboardRow;
            const discoveredTools = asRows(discovery.tools as DashboardJson | undefined);
            setMcpDiscovery(discovery);
            setServerDiscoveryResults((current) => ({ ...current, [payload.serverId]: discovery }));
            if (valueOf(discovery, "status", "unknown") !== "ok") {
              setMessage(`${payload.serverId} verification failed: ${valueOf(discovery, "error", "unknown error")}`);
              return null;
            }
            if (!discoveredTools.length) {
              setMessage(`${payload.serverId} verified, but no MCP tools were returned; nothing was saved.`);
              return null;
            }
            const result = await syncCustomMcpServer({
              ...payload,
              tools: discoveredTools,
            });
            await refresh();
            setMessage(
              `${payload.serverId} ${editingToolKey ? "updated" : "added"} and synced ${discoveredTools.length} tool${discoveredTools.length === 1 ? "" : "s"}.`,
            );
            setMcpModalOpen(false);
            resetMcpDraft();
            return result;
          } catch (error) {
            setMessage(error instanceof Error ? error.message : "Custom MCP server save failed.");
            return null;
          } finally {
            setPendingId(null);
          }
        };

        const discoverMcpDraft = async () => {
          const payload = customMcpPayloadFromDraft(mcpDraft);
          return discoverServer(payload, "mcp-discover-modal");
        };

        const removeMcpServer = async (server: DashboardRow) => {
          const serverId = valueOf(server, "serverId", "");
          try {
            setPendingId(`mcp-delete:${serverId}`);
            await deleteCustomMcpServer({ serverId });
            await refresh();
            if (editingToolKey === serverId) {
              setMcpModalOpen(false);
              resetMcpDraft();
            }
            setServerDiscoveryResults((current) => {
              const next = { ...current };
              delete next[serverId];
              return next;
            });
            setMessage(`${serverId} removed from config.yaml.`);
          } catch (error) {
            setMessage(error instanceof Error ? error.message : "Custom MCP server delete failed.");
          } finally {
            setPendingId(null);
          }
        };

        const verifyAndSyncMcpServer = async (server: DashboardRow) => {
          const serverId = valueOf(server, "serverId", "");
          const payload = customMcpPayloadFromDraft(mcpDraftFromRows(server));
          const pendingKey = `mcp-discover:${serverId}`;
          try {
            setPendingId(pendingKey);
            const discovery = await discoverCustomMcpTools(payload) as DashboardRow;
            const discoveredTools = asRows(discovery.tools as DashboardJson | undefined);
            setServerDiscoveryResults((current) => ({ ...current, [serverId]: discovery }));
            if (valueOf(discovery, "status", "unknown") !== "ok") {
              setMessage(`${serverId} verification failed: ${valueOf(discovery, "error", "unknown error")}`);
              return null;
            }
            if (!discoveredTools.length) {
              setMessage(`${serverId} verified, but returned no MCP tools; nothing changed.`);
              return discovery;
            }
            const result = await syncCustomMcpServer({
              ...payload,
              tools: discoveredTools,
            }) as DashboardRow;
            await refresh();
            setMessage(`${serverId} verified and synced ${discoveredTools.length} tool${discoveredTools.length === 1 ? "" : "s"}; ${valueOf(result, "runtimeStatus", "runtime reloaded")}.`);
            return result;
          } catch (error) {
            setMessage(error instanceof Error ? error.message : "Custom MCP server verification failed.");
            return null;
          } finally {
            setPendingId(null);
          }
        };

        const toggleCustomMcpTool = async (tool: DashboardRow) => {
          const serverId = valueOf(tool, "serverId", "");
          const toolName = valueOf(tool, "toolName", DEFAULT_CUSTOM_MCP_TOOL_NAME);
          const enabled = !Boolean(tool.enabled);
          const pendingKey = `mcp-toggle:${serverId}:${toolName}`;
          try {
            setPendingId(pendingKey);
            const result = await setCustomMcpToolEnabled({
              serverId,
              toolName,
              enabled,
            }) as DashboardRow;
            await refresh();
            setMessage(`${serverId}:${toolName} ${enabled ? "enabled" : "disabled"}; ${valueOf(result, "runtimeStatus", "runtime reloaded")}.`);
          } catch (error) {
            setMessage(error instanceof Error ? error.message : "Custom MCP tool enable update failed.");
          } finally {
            setPendingId(null);
          }
        };

        return (
          <>
            <section className={cx(styles.metricGrid, styles.metricGridCompact)}>
              <MetricCard compact metric={{ label: "Built-in tools", value: `${dashboard.operations.tools.length}`, note: "Runtime-loaded operator tools.", tone: dashboard.operations.tools.length ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Built-in enabled", value: `${dashboard.operations.tools.filter((tool) => tool.enabled === true).length}`, note: "Built-in tool overrides only.", tone: dashboard.operations.tools.some((tool) => tool.enabled === true) ? "healthy" : "attention" }} />
              <MetricCard compact metric={{ label: "Custom MCP servers", value: `${customMcpServersAll.length}`, note: `${verifiedServerCount} verified in this session.`, tone: customMcpServersAll.length ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Synced MCP tools", value: `${syncedToolCount}`, note: `${enabledCustomMcpToolCount} enabled across custom servers.`, tone: syncedToolCount ? "healthy" : "neutral" }} />
            </section>
            <Panel eyebrow="Toolbox" title="Search and compose" detail="Search across built-in tools and custom MCP servers, then open the focused server editor to save config or run live discovery.">
              <SearchBox
                query={query}
                setQuery={setQuery}
                placeholder="Tool, server, transport, command, url..."
                actions={(
                  <ActionButton disabled={pendingId === "mcp-form" || pendingId === "mcp-discover-modal"} onClick={openCreateMcpModal}>
                    Add server
                  </ActionButton>
                )}
                hint={(
                  <>
                    <span>Filtering {builtinTools.length} built-in tool row(s) and {customMcpServers.length} custom MCP server(s).</span>
                    <span>{configPath}</span>
                  </>
                )}
              />
              {message ? <EmptyPanel title="Latest console action" detail={message} /> : null}
            </Panel>
            <Panel eyebrow="Tools" title="Built-in tools" detail="What Elephant Agent can reach for, with risk level and an on/off switch for each.">
              {builtinTools.length ? (
                <>
                  <div className={styles.capabilityList}>
                    {visibleBuiltinTools.map((tool) => {
                      const toolId = valueOf(tool, "toolId");
                      const pendingKey = `builtin:${toolId}`;
                      return (
                        <article key={toolId} className={styles.capabilityRow}>
                          <RowIcon kind="tools" />
                          <div className={styles.capabilityMain}>
                            <span>{valueOf(tool, "family")} · {valueOf(tool, "riskClass")}</span>
                            <strong>{valueOf(tool, "displayName", toolId)}</strong>
                            <p>{compactText(valueOf(tool, "description", "No description persisted."), 210)}</p>
                          </div>
                          <div className={styles.capabilityState}>
                            <span>{tool.enabled ? "Enabled" : "Disabled"}</span>
                            <small>{tool.available ? "available" : valueOf(tool, "availabilityReason", "unavailable")}</small>
                          </div>
                          <button
                            aria-pressed={Boolean(tool.enabled)}
                            className={cx(styles.toggleSwitch, Boolean(tool.enabled) && styles.toggleSwitchOn)}
                            disabled={pendingId === pendingKey}
                            type="button"
                            onClick={() => void toggleBuiltin(tool)}
                          >
                            <span />
                            <strong>{pendingId === pendingKey ? "Saving" : tool.enabled ? "On" : "Off"}</strong>
                          </button>
                          <ViewButton title={toolId} items={detailItems(tool)} />
                        </article>
                      );
                    })}
                  </div>
                  <PaginationBar
                    totalItems={builtinTools.length}
                    currentPage={currentToolPage}
                    totalPages={toolTotalPages}
                    pageSize={toolPageSize}
                    label="tools"
                    onPrevious={() => setToolPage((current) => Math.max(0, current - 1))}
                    onNext={() => setToolPage((current) => Math.min(toolTotalPages - 1, current + 1))}
                  />
                </>
              ) : (
                <EmptyPanel
                  title={dashboard.operations.tools.length ? "No built-in tools match" : "No built-in tools exposed"}
                  detail="Try different search text. If a tool you expect is missing, check the setup in Settings."
                />
              )}
            </Panel>
            <Panel eyebrow="Custom MCP" title="Custom MCP server management" detail="Save a server to sync its live MCP tools, then expand the stored list below to disable or inspect individual tools.">
              <section className={styles.mcpSummaryStrip}>
                <div className={styles.mcpSummaryItem}>
                  <span>Configured servers</span>
                  <strong>{customMcpServersAll.length}</strong>
                </div>
                <div className={styles.mcpSummaryItem}>
                  <span>Verified this session</span>
                  <strong>{verifiedServerCount}</strong>
                </div>
                <div className={styles.mcpSummaryItem}>
                  <span>Stored in</span>
                  <strong>{configPath}</strong>
                </div>
              </section>
              {customMcpServers.length ? (
                <>
                  <div className={styles.mcpToolGrid}>
                    {visibleCustomMcpServers.map((server) => {
                    const serverId = valueOf(server, "serverId", "");
                    const storedTools = asRows(server.storedTools as DashboardJson | undefined);
                    const deleteKey = `mcp-delete:${serverId}`;
                    const verifyKey = `mcp-discover:${serverId}`;
                    const argsCount = asTextList(server.args).length;
                    const envCount = asTextList(server.envKeys).length;
                    const headerCount = asTextList(server.headerKeys).length;
                    const runtimeTarget = mcpRuntimeTarget(server, "No command or URL configured.");
                    const discovery = serverDiscoveryResults[serverId];
                    const discoveredTools = asRows(discovery?.tools as DashboardJson | undefined);
                    const discoveryStatus = discovery ? valueOf(discovery, "status", "unknown") : "not verified";
                    const enabledCount = storedTools.filter((tool) => tool.enabled === true).length;
                    const discoverySummary = valueOf(discovery, "error", "")
                      || (discoveredTools.length
                        ? `Live verify found ${discoveredTools.length} tool${discoveredTools.length === 1 ? "" : "s"}: ${discoveredTools.map((row) => valueOf(row, "name")).join(", ")}`
                        : storedTools.length
                          ? `${storedTools.length} tool${storedTools.length === 1 ? "" : "s"} currently synced. Run Verify & sync tools to refresh from the live server.`
                          : "Save this server to sync its live MCP tools, or verify it now to preview the list.");
                    return (
                      <article key={serverId} className={cx(styles.settingsSectionCard, styles.mcpToolCard)}>
                        <header className={styles.mcpToolCardHeader}>
                          <div className={styles.mcpToolCardCopy}>
                            <span>{valueOf(server, "transport", "stdio")}</span>
                            <strong>{valueOf(server, "label", serverId)}</strong>
                          </div>
                          <div className={styles.mcpBadgeRow}>
                            <StatusBadge tone={mcpRuntimeTarget(server, "") ? "healthy" : "attention"}>{mcpRuntimeTarget(server, "") ? "configured" : "incomplete"}</StatusBadge>
                            <StatusBadge tone={toneForStatus(discoveryStatus)}>{discoveryStatus}</StatusBadge>
                          </div>
                        </header>
                        <p className={styles.mcpToolTarget}>{runtimeTarget}</p>
                        <div className={styles.mcpMetaRow}>
                          <span>{serverId}</span>
                          <span>{argsCount} arg{argsCount === 1 ? "" : "s"}</span>
                          <span>{envCount} env</span>
                          <span>{headerCount} header{headerCount === 1 ? "" : "s"}</span>
                          <span>{storedTools.length} synced tool{storedTools.length === 1 ? "" : "s"}</span>
                          <span>{enabledCount} enabled</span>
                        </div>
                        <p>{compactText(discoverySummary, 220)}</p>
                        <footer className={styles.mcpToolFooter}>
                          <div className={styles.mcpActionCluster}>
                            <ActionButton variant="ghost" disabled={Boolean(pendingId)} onClick={() => openEditMcpModal(server)}>
                              Edit
                            </ActionButton>
                            <ActionButton
                              variant="ghost"
                              disabled={Boolean(pendingId)}
                              onClick={() => void verifyAndSyncMcpServer(server)}
                            >
                              {pendingId === verifyKey ? "Syncing" : "Verify & sync tools"}
                            </ActionButton>
                            <ActionButton variant="ghost" disabled={pendingId === deleteKey} onClick={() => void removeMcpServer(server)}>
                              {pendingId === deleteKey ? "Deleting" : "Delete"}
                            </ActionButton>
                            <ViewButton title={serverId} items={detailItems(server)} variant="ghost" />
                          </div>
                        </footer>
                        {storedTools.length ? (
                          <details className={styles.recordDetails} open={storedTools.length <= 4}>
                            <summary>Stored tools · {storedTools.length} ({enabledCount} enabled)</summary>
                            <div className={styles.capabilityList}>
                              {storedTools.map((tool) => {
                                const toolName = valueOf(tool, "toolName", DEFAULT_CUSTOM_MCP_TOOL_NAME);
                                const toolKey = valueOf(tool, "toolKey", `${serverId}:${toolName}`);
                                const toggleKey = `mcp-toggle:${serverId}:${toolName}`;
                                const requiredFields = asTextList(tool.requiredFields).join(", ");
                                const meta = [
                                  "custom mcp",
                                  serverId,
                                  requiredFields ? `required ${requiredFields}` : "",
                                ].filter(Boolean).join(" · ");
                                const availability = tool.available === true
                                  ? (requiredFields ? `available · required ${requiredFields}` : "available")
                                  : valueOf(tool, "availabilityReason", "unavailable");
                                return (
                                  <article key={toolKey} className={styles.capabilityRow}>
                                    <RowIcon kind="tools" />
                                    <div className={styles.capabilityMain}>
                                      <span>{meta}</span>
                                      <strong>{valueOf(tool, "displayName", toolName)}</strong>
                                      <p>{compactText(valueOf(tool, "description", "No description provided."), 210)}</p>
                                    </div>
                                    <div className={styles.capabilityState}>
                                      <span>{tool.enabled ? "Enabled" : "Disabled"}</span>
                                      <small>{availability}</small>
                                    </div>
                                    <button
                                      aria-pressed={Boolean(tool.enabled)}
                                      className={cx(styles.toggleSwitch, Boolean(tool.enabled) && styles.toggleSwitchOn)}
                                      disabled={pendingId === toggleKey}
                                      type="button"
                                      onClick={() => void toggleCustomMcpTool(tool)}
                                    >
                                      <span />
                                      <strong>{pendingId === toggleKey ? "Saving" : tool.enabled ? "On" : "Off"}</strong>
                                    </button>
                                    <ViewButton title={toolKey} items={detailItems(tool)} />
                                  </article>
                                );
                              })}
                            </div>
                          </details>
                        ) : (
                          <EmptyPanel title="No synced tools yet" detail="Save this server or run Verify & sync tools to pull the live MCP tool list into config." />
                        )}
                      </article>
                    );
                    })}
                  </div>
                  <PaginationBar
                    totalItems={customMcpServers.length}
                    currentPage={currentMcpPage}
                    totalPages={mcpTotalPages}
                    pageSize={mcpPageSize}
                    label="MCP servers"
                    onPrevious={() => setMcpPage((current) => Math.max(0, current - 1))}
                    onNext={() => setMcpPage((current) => Math.min(mcpTotalPages - 1, current + 1))}
                  />
                </>
              ) : (
                <EmptyPanel
                  title={customMcpServersAll.length ? "No custom MCP servers match" : "No custom MCP servers yet"}
                  detail={customMcpServersAll.length
                    ? "Try a broader search, or clear the filter to edit the full list again."
                    : "Use Add server to open the focused MCP editor and create the first custom entry."}
                />
              )}
            </Panel>
            <McpToolEditorDialog
              open={mcpModalOpen}
              editingToolKey={editingToolKey}
              draft={mcpDraft}
              setDraft={setMcpDraft}
              pending={pendingId === "mcp-form"}
              discoveryPending={pendingId === "mcp-discover-modal"}
              discovery={mcpDiscovery}
              configPath={configPath}
              onClose={closeMcpModal}
              onSave={saveMcpServer}
              onDiscover={discoverMcpDraft}
            />
          </>
        );
      }}
    </DashboardPage>
  );
}

type GatewayDraft = GatewayServiceConfigPayload & {
  secrets: Record<string, string>;
};

type GatewayQrState = {
  sessionId?: string;
  status?: string;
  message?: string;
  qrcodeUrl?: string;
  qrScanData?: string;
  qrMatrix?: number[][];
  credentials?: Record<string, unknown>;
};

function gatewayServiceId(service: DashboardRow): string {
  return readString(service, ["service", "id", "key"], "gateway");
}

function gatewaySecretFields(service: DashboardRow): DashboardRow[] {
  return asRows(service.secretFields);
}

function gatewayAccounts(service: DashboardRow): DashboardRow[] {
  return asRows(service.accounts);
}

function gatewayPrimaryAccount(service: DashboardRow): DashboardRow {
  return gatewayAccounts(service)[0] ?? {};
}

function gatewayDraft(service: DashboardRow, drafts: Record<string, Partial<GatewayDraft>>): GatewayDraft {
  const serviceId = gatewayServiceId(service);
  const current = drafts[serviceId] ?? {};
  const primaryAccount = gatewayPrimaryAccount(service);
  return {
    accountId: current.accountId ?? valueOf(service, "primaryAccountId", valueOf(primaryAccount, "account_id", "default")),
    transport: current.transport ?? valueOf(service, "configuredTransport", valueOf(service, "defaultTransport", "configured")),
    eventPath: current.eventPath ?? valueOf(service, "eventPath", ""),
    enabled: current.enabled ?? (service.enabled !== false),
    accountEnabled: current.accountEnabled ?? (primaryAccount.enabled !== false),
    allowGroupChats: current.allowGroupChats ?? service.allowGroupChats === true,
    allowGuildIds: current.allowGuildIds ?? asTextList(primaryAccount.allow_guild_ids ?? primaryAccount.allowGuildIds),
    allowChannelIds: current.allowChannelIds ?? asTextList(primaryAccount.allow_channel_ids ?? primaryAccount.allowChannelIds),
    secrets: current.secrets ?? {},
  };
}

function gatewayConfigPayload(draft: GatewayDraft): GatewayServiceConfigPayload {
  return {
    accountId: draft.accountId,
    transport: draft.transport,
    eventPath: draft.eventPath,
    enabled: draft.enabled,
    accountEnabled: draft.accountEnabled,
    allowGroupChats: draft.allowGroupChats,
    allowGuildIds: draft.allowGuildIds,
    allowChannelIds: draft.allowChannelIds,
    secrets: draft.secrets,
  };
}

function GatewayQrMatrix({ matrix }: { matrix: number[][] }): React.JSX.Element {
  const width = matrix[0]?.length ?? 0;
  return (
    <div
      className={styles.gatewayQrMatrix}
      style={{ gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))` }}
      aria-label="WeChat QR code"
    >
      {matrix.flatMap((row, rowIndex) =>
        row.map((cell, columnIndex) => (
          <i key={`${rowIndex}-${columnIndex}`} className={cell ? styles.gatewayQrCellDark : styles.gatewayQrCellLight} />
        )),
      )}
    </div>
  );
}

type GatewayBusyState = "starting" | "stopping" | null;

function gatewayBusyState(busy: string | null, service: DashboardRow, serviceId: string): GatewayBusyState {
  if (!busy) {
    return null;
  }
  const serviceLabel = valueOf(service, "label", serviceId).toLowerCase();
  const normalizedBusy = busy.toLowerCase();
  const matchesService = normalizedBusy.includes(serviceId.toLowerCase()) || normalizedBusy.includes(serviceLabel);
  if (!matchesService && !(serviceId === "weixin" && normalizedBusy.includes("wechat qr"))) {
    return null;
  }
  if (normalizedBusy.includes("stop")) {
    return "stopping";
  }
  if (normalizedBusy.includes("start") || normalizedBusy.includes("restart") || normalizedBusy.includes("qr")) {
    return "starting";
  }
  return null;
}

function gatewayRuntimeLabel(isRunning: boolean, isConfigured: boolean, busyState: GatewayBusyState, isStarting: boolean = false): string {
  if (busyState === "starting") {
    return isRunning ? "Restarting" : "Starting";
  }
  if (busyState === "stopping") {
    return "Stopping";
  }
  if (isRunning) {
    return "Started";
  }
  if (isStarting) {
    return "Starting";
  }
  return isConfigured ? "Stopped" : "Needs setup";
}

function gatewayRuntimeDetail(isRunning: boolean, isConfigured: boolean, busyState: GatewayBusyState, isStarting: boolean = false, lastError: string = ""): string {
  if (busyState === "starting") {
    return "Start request is running; the card will refresh when the bridge reports back.";
  }
  if (busyState === "stopping") {
    return "Stop request is running; the card will refresh when the bridge shuts down.";
  }
  if (isRunning) {
    return "The IM bridge is running from this dashboard profile.";
  }
  if (isStarting) {
    return "The bridge process is coming up; dashboard will refresh as status stabilizes.";
  }
  if (isConfigured) {
    return lastError
      ? `Configured but not running. Last error: ${lastError}`
      : "Configured but not running. Press Start to bring it online.";
  }
  return "Configure the account before this bridge can be started.";
}

export function GatewayPage(): React.JSX.Element {
  const action = useAsyncAction(async () => undefined);
  const [expandedService, setExpandedService] = React.useState<string | null>("weixin");
  const [drafts, setDrafts] = React.useState<Record<string, Partial<GatewayDraft>>>({});
  const [qrStates, setQrStates] = React.useState<Record<string, GatewayQrState>>({});
  const refreshGatewayRef = React.useRef<(() => Promise<void>) | null>(null);
  const qrPollingRef = React.useRef(false);
  const activeWeixinQr = qrStates.weixin;

  React.useEffect(() => {
    const sessionId = activeWeixinQr?.sessionId;
    const status = activeWeixinQr?.status;
    if (!sessionId || status === "confirmed" || status === "expired" || status === "failed") {
      return undefined;
    }
    let cancelled = false;
    const poll = async () => {
      if (qrPollingRef.current) {
        return;
      }
      qrPollingRef.current = true;
      try {
        const result = await runGatewayAction({ service: "weixin", action: "qr-poll", sessionId }) as GatewayQrState;
        if (cancelled) {
          return;
        }
        if (result.status === "confirmed") {
          // Run start BEFORE updating qrState to "confirmed" — updating state would
          // trigger effect cleanup (cancelled = true) and discard the start result.
          const accountId = String(result.credentials?.["account_id"] ?? result.credentials?.["accountId"] ?? "").trim();
          let startMessage: string;
          try {
            const startResult = await runGatewayAction({ service: "weixin", action: "start", accountId, transport: "ilink" }) as { status?: unknown; stderr?: unknown };
            startMessage = startResult.status === "ok"
              ? "WeChat connected and started."
              : `WeChat connected, but start failed: ${String(startResult.stderr ?? "check details")}`;
          } catch (startError) {
            startMessage = `WeChat connected, but start failed: ${startError instanceof Error ? startError.message : String(startError)}`;
          }
          if (!cancelled) {
            setQrStates((current) => ({
              ...current,
              weixin: { ...result, message: startMessage },
            }));
            await refreshGatewayRef.current?.();
          }
        } else {
          setQrStates((current) => ({ ...current, weixin: result }));
        }
      } catch (error) {
        if (!cancelled) {
          setQrStates((current) => ({
            ...current,
            weixin: { ...(current.weixin ?? {}), status: "failed", message: error instanceof Error ? error.message : String(error) },
          }));
        }
      } finally {
        qrPollingRef.current = false;
      }
    };
    void poll();
    const intervalId = window.setInterval(() => void poll(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeWeixinQr?.sessionId, activeWeixinQr?.status]);

  const updateGatewaySecret = (serviceId: string, secretKey: string, value: string) => {
    setDrafts((current) => {
      const draft = current[serviceId] ?? {};
      return {
        ...current,
        [serviceId]: {
          ...draft,
          secrets: { ...(draft.secrets ?? {}), [secretKey]: value },
        },
      };
    });
  };

  return (
    <DashboardPage section="gateway">
      {(dashboard, { refresh }) => {
        refreshGatewayRef.current = refresh;
        const gateway = dashboard.operations.gateway;
        const services = asRows(gateway.services).sort((left, right) => {
          const order = ["weixin", "feishu", "discord", "dingding", "wecom"];
          return order.indexOf(gatewayServiceId(left)) - order.indexOf(gatewayServiceId(right));
        });
        const configuredCount = Number(gateway.configuredServiceCount ?? services.filter((service) => service.configured === true).length);
        const runningCount = Number(gateway.runningServiceCount ?? services.filter((service) => service.running === true).length);

        const startWeixinQr = async (draft: GatewayDraft) => {
          await action.run("WeChat QR setup", async () => {
            const result = await runGatewayAction({
              service: "weixin",
              action: "qr-start",
              config: gatewayConfigPayload(draft),
            }) as GatewayQrState;
            setQrStates((current) => ({ ...current, weixin: result }));
          });
        };

        const resolveAccountId = (service: DashboardRow, draft: GatewayDraft): string => {
          const fromDraft = typeof draft.accountId === "string" ? draft.accountId.trim() : "";
          if (fromDraft) {
            return fromDraft;
          }
          const primary = String((service as Record<string, unknown>).primaryAccountId ?? "").trim();
          if (primary) {
            return primary;
          }
          const accounts = Array.isArray((service as Record<string, unknown>).accounts)
            ? ((service as Record<string, unknown>).accounts as Array<Record<string, unknown>>)
            : [];
          const first = accounts[0];
          if (first && typeof first === "object") {
            const id = String(first["account_id"] ?? first["accountId"] ?? "").trim();
            if (id) {
              return id;
            }
          }
          return "";
        };

        const startServiceFromDashboard = async (service: DashboardRow, draft: GatewayDraft) => {
          const serviceId = gatewayServiceId(service);
          if (serviceId === "weixin" && service.configured !== true) {
            await startWeixinQr(draft);
            return;
          }
          const startAction = service.running === true ? "restart" : "start";
          await action.run(`${valueOf(service, "label", serviceId)} ${startAction}`, async () => {
            if (serviceId !== "weixin") {
              await runGatewayAction({ service: serviceId, action: "configure", config: gatewayConfigPayload(draft) });
              setDrafts((current) => ({ ...current, [serviceId]: { ...(current[serviceId] ?? {}), secrets: {} } }));
            }
            await runGatewayAction({ service: serviceId, action: startAction, accountId: draft.accountId, transport: draft.transport });
            await refresh();
            // The detached runtime writes `starting` → `running` over a few
            // hundred ms; poll briefly so the card reflects the true state
            // without the user needing to refresh manually.
            for (let attempt = 0; attempt < 8; attempt += 1) {
              await new Promise((resolve) => window.setTimeout(resolve, 800));
              await refresh();
            }
          });
        };

        const stopService = async (service: DashboardRow, draft: GatewayDraft) => {
          const serviceId = gatewayServiceId(service);
          await action.run(`${valueOf(service, "label", serviceId)} stop`, async () => {
            await runGatewayAction({ service: serviceId, action: "stop", accountId: draft.accountId, transport: draft.transport, force: true });
            if (serviceId === "weixin") {
              setQrStates((current) => { const next = { ...current }; delete next.weixin; return next; });
            }
            await refresh();
          });
        };

        const removeServiceAccount = async (service: DashboardRow, draft: GatewayDraft) => {
          const serviceId = gatewayServiceId(service);
          const isServiceRunning = service.running === true;
          const resolvedAccountId = resolveAccountId(service, draft);
          await action.run(`Remove ${valueOf(service, "label", serviceId)} account`, async () => {
            if (isServiceRunning) {
              await runGatewayAction({ service: serviceId, action: "stop", accountId: resolvedAccountId, force: true });
            }
            await runGatewayAction({ service: serviceId, action: "remove", accountId: resolvedAccountId });
            setQrStates((current) => { const next = { ...current }; delete next[serviceId]; return next; });
            await refresh();
          });
        };

        return (
          <>
            <section className={cx(styles.metricGrid, styles.metricGridCompact)}>
              <MetricCard compact metric={{ label: "Supported IMs", value: `${services.length}`, note: "WeChat, Feishu, Discord, DingDing, and WeCom bridge cards.", tone: services.length ? "healthy" : "attention" }} />
              <MetricCard compact metric={{ label: "Configured", value: `${configuredCount}/${services.length}`, note: "IM cards with at least one persisted account.", tone: configuredCount ? "healthy" : "attention" }} />
              <MetricCard compact metric={{ label: "Running", value: `${runningCount}`, note: valueOf(gateway, "gatewayDir", "Gateway directory not created yet."), tone: runningCount ? "healthy" : "neutral" }} />
            </section>

            <Panel
              eyebrow="Gateway"
              title="IM bridge cards"
              detail="Connect the messaging apps where Elephant Agent should meet you — all from one place. Starting a bridge saves the local settings and brings it online."
            >
              {action.message ? (
                <div className={styles.controlToolbar}>
                  <span>{action.message}</span>
                </div>
              ) : null}
              {services.length ? (
                <div className={styles.providerList}>
                  {services.map((service) => {
                    const serviceId = gatewayServiceId(service);
                    const serviceLabel = valueOf(service, "label", serviceId);
                    const draft = gatewayDraft(service, drafts);
                    const isExpanded = expandedService === serviceId;
                    const isConfigured = service.configured === true;
                    const isRunning = service.running === true;
                    const isStarting = (service as Record<string, unknown>).starting === true;
                    const lastError = String((service as Record<string, unknown>).lastError ?? "");
                    const busyState = gatewayBusyState(action.busy, service, serviceId);
                    const runtimeLabel = gatewayRuntimeLabel(isRunning, isConfigured, busyState, isStarting);
                    const runtimeDetail = gatewayRuntimeDetail(isRunning, isConfigured, busyState, isStarting, lastError);
                    const runtimeClass = busyState
                      ? styles.gatewayRuntimeBusy
                      : isRunning
                        ? styles.gatewayRuntimeStarted
                        : isStarting
                          ? styles.gatewayRuntimeBusy
                          : isConfigured
                            ? styles.gatewayRuntimeStopped
                            : styles.gatewayRuntimeSetup;
                    const cardClass = isRunning ? styles.providerCardActive : isConfigured ? styles.providerCardConfigured : undefined;
                    const secretFields = gatewaySecretFields(service);
                    const storedSecrets = secretFields.filter((field) => field.hasValue === true).length;
                    const qrState = qrStates[serviceId];
                    const qrWaiting = Boolean(qrState?.sessionId && !["confirmed", "expired", "failed"].includes(qrState.status ?? ""));
                    const setupNote = readString(service, ["setupNote"], "");
                    const secretSummary = secretFields.length ? `${storedSecrets}/${secretFields.length} secret(s)` : "QR setup";
                    return (
                      <article key={serviceId} className={cx(styles.providerCard, cardClass, isExpanded && styles.providerCardOpen)}>
                        <button className={styles.providerCardHeader} type="button" onClick={() => setExpandedService(isExpanded ? null : serviceId)}>
                          <RowIcon kind="tools" />
                          <div className={styles.providerCardTitle}>
                            <span>{serviceId}</span>
                            <strong>{serviceLabel}</strong>
                            <p>{valueOf(service, "summary", "Configure and operate this IM bridge.")}</p>
                          </div>
                          <div className={styles.providerCardState}>
                            <span>{runtimeLabel}</span>
                            <strong>{valueOf(service, "accountCount", "0")} account(s)</strong>
                            <small>{secretSummary} · {isRunning ? "online" : isConfigured ? "offline" : "not ready"}</small>
                          </div>
                        </button>
                        {isExpanded ? (
                          <div className={styles.providerExpanded}>
                            <div className={cx(styles.gatewayRuntimeBanner, runtimeClass)} role="status" aria-live="polite">
                              <i className={styles.gatewayRuntimeDot} aria-hidden="true" />
                              <div>
                                <strong>{runtimeLabel}</strong>
                                <p>{runtimeDetail}</p>
                              </div>
                            </div>
                            {setupNote ? (
                              <EmptyPanel title="Setup note" detail={setupNote} />
                            ) : null}
                            {serviceId === "weixin" ? (
                              <section className={styles.providerSecretPanel}>
                                <div className={styles.controlToolbar}>
                                  <ActionButton
                                    aria-pressed={isRunning}
                                    className={styles.gatewayStartButton}
                                    disabled={Boolean(action.busy) || qrWaiting}
                                    onClick={() => void startServiceFromDashboard(service, draft)}
                                  >
                                    {qrWaiting
                                      ? "Waiting for scan"
                                      : busyState === "starting"
                                        ? isRunning ? "Restarting" : "Starting"
                                        : isRunning
                                          ? "Restart"
                                          : isConfigured ? "Start" : "Connect & start WeChat"}
                                  </ActionButton>
                                  {isRunning ? (
                                    <ActionButton
                                      className={styles.gatewayStopButton}
                                      disabled={Boolean(action.busy)}
                                      variant="ghost"
                                      onClick={() => void stopService(service, draft)}
                                    >
                                      {busyState === "stopping" ? "Stopping" : "Stop"}
                                    </ActionButton>
                                  ) : null}
                                  {isConfigured ? (
                                    <ActionButton
                                      variant="ghost"
                                      disabled={Boolean(action.busy)}
                                      onClick={() => void removeServiceAccount(service, draft)}
                                    >
                                      Remove
                                    </ActionButton>
                                  ) : null}
                                  {isConfigured ? (
                                    <span>Account: {valueOf(gatewayPrimaryAccount(service), "account_id", "default")}</span>
                                  ) : null}
                                  {qrState?.status === "confirmed" ? (
                                    <span>Connected</span>
                                  ) : qrState?.status ? (
                                    <span>{qrState.message || `QR status: ${qrState.status}`}</span>
                                  ) : null}
                                </div>
                                {qrState?.qrMatrix?.length && qrState.status !== "confirmed" ? (
                                  <div className={styles.gatewayQrPanel}>
                                    <GatewayQrMatrix matrix={qrState.qrMatrix} />
                                    <div>
                                      <strong>Scan with WeChat</strong>
                                      <p>Scan and confirm on your phone. Dashboard will detect confirmation and start the bridge automatically.</p>
                                      {qrState.qrcodeUrl ? <a href={qrState.qrcodeUrl} target="_blank" rel="noreferrer">Open QR link</a> : null}
                                    </div>
                                  </div>
                                ) : null}
                              </section>
                            ) : null}
                            {secretFields.length ? (
                              <section className={styles.providerSecretPanel}>
                                {secretFields.map((field) => {
                                  const secretKey = valueOf(field, "key");
                                  return (
                                    <label key={secretKey} className={styles.fieldStack}>
                                      <span>{valueOf(field, "label", secretKey)}</span>
                                      <input
                                        type="password"
                                        value={draft.secrets[secretKey] ?? ""}
                                        placeholder={field.hasValue ? "stored locally" : "paste once to store locally"}
                                        onChange={(event) => updateGatewaySecret(serviceId, secretKey, event.target.value)}
                                      />
                                    </label>
                                  );
                                })}
                              </section>
                            ) : null}
                            {serviceId !== "weixin" ? (
                              <div className={styles.controlToolbar}>
                                <ActionButton
                                  aria-pressed={isRunning}
                                  className={styles.gatewayStartButton}
                                  disabled={Boolean(action.busy)}
                                  onClick={() => void startServiceFromDashboard(service, draft)}
                                >
                                  {busyState === "starting" ? (isRunning ? "Restarting" : "Starting") : isRunning ? "Restart" : "Start"}
                                </ActionButton>
                                {isRunning ? (
                                  <ActionButton
                                    className={styles.gatewayStopButton}
                                    disabled={Boolean(action.busy)}
                                    variant="ghost"
                                    onClick={() => void stopService(service, draft)}
                                  >
                                    {busyState === "stopping" ? "Stopping" : "Stop"}
                                  </ActionButton>
                                ) : null}
                                {isConfigured ? (
                                  <ActionButton
                                    variant="ghost"
                                    disabled={Boolean(action.busy)}
                                    onClick={() => void removeServiceAccount(service, draft)}
                                  >
                                    Remove
                                  </ActionButton>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <EmptyPanel title="No messaging apps available" detail="Once Elephant Agent knows about a messaging app, its card will appear here." />
              )}
            </Panel>
          </>
        );
      }}
    </DashboardPage>
  );
}

type CronEggOption = {
  key: string;
  label: string;
  eggId: string;
  profileId: string;
};

const CRON_SCHEDULE_PRESETS: readonly { label: string; value: string }[] = [
  { label: "Every morning", value: "every morning" },
  { label: "Daily 09:00", value: "daily at 09:00" },
  { label: "Weekdays 09:00", value: "0 9 * * 1-5" },
  { label: "Every 2h", value: "every 2h" },
] as const;

function cronEggOptions(dashboard: InternalDashboardSnapshot): CronEggOption[] {
  const seen = new Set<string>();
  const rows = [...dashboard.herd, ...dashboard.states];
  return rows.flatMap((row) => {
    const eggId = readString(row, ["elephant_id", "eggId"]);
    const profileId = readString(row, ["profile_id", "profileId"]);
    const stateId = readString(row, ["state_id", "stateId"]);
    const key = eggId || profileId || stateId;
    if (!key || seen.has(key)) {
      return [];
    }
    seen.add(key);
    const name = readString(row, ["elephant_name", "display_name", "displayName"], eggId || profileId || stateId);
    return [{
      key,
      label: `${name}${eggId ? ` · ${eggId}` : ""}`,
      eggId,
      profileId,
    }];
  });
}

function cronPromptSummary(job: DashboardRow): string {
  const payload = jsonObject(job.payload);
  const jobKind = valueOf(job, "jobKind", valueOf(job, "action_kind", "prompt"));
  if (jobKind === "learning") {
    const trigger = readString(payload, ["trigger"], "");
    const summary = readString(payload, ["summary"], "");
    return trigger ? `${trigger} agent${summary ? ` · ${summary}` : ""}` : summary || "Learning job";
  }
  return compactText(readString(payload, ["prompt", "message", "query"], valueOf(job, "lastSummary", "No prompt persisted.")), 180);
}

function cronSystemKind(job: DashboardRow): "proactive-ask" | "dream" | null {
  const explicit = readString(job, ["systemKind"], "").trim().toLowerCase();
  if (explicit === "proactive-ask" || explicit === "dream") {
    return explicit;
  }
  const payload = jsonObject(job.payload);
  const jobKind = valueOf(job, "jobKind", valueOf(job, "action_kind", "prompt")).toLowerCase();
  if (jobKind === "system" || readBoolean(job, ["isSystem"])) {
    return "proactive-ask";
  }
  const trigger = readString(payload, ["trigger"], "").trim().toLowerCase();
  if (jobKind === "learning" && trigger === "dream") {
    return "dream";
  }
  return null;
}

function cronIsSystemJob(job: DashboardRow): boolean {
  return cronSystemKind(job) !== null || readBoolean(job, ["isSystem"]);
}

function cronCanRunNow(job: DashboardRow): boolean {
  return readBoolean(job, ["canRunNow"], true);
}

function cronCanPause(job: DashboardRow): boolean {
  return readBoolean(job, ["canPause"], true);
}

function cronCanDelete(job: DashboardRow): boolean {
  return readBoolean(job, ["canDelete"], !cronIsSystemJob(job));
}

function cronSystemDescription(job: DashboardRow): string {
  switch (cronSystemKind(job)) {
    case "proactive-ask":
      return "Built-in proactive question scheduler.";
    case "dream":
      return "Built-in nightly learning consolidation, including diary writing.";
    default:
      return cronPromptSummary(job);
  }
}

function cronDetailTitle(job: DashboardRow, jobId: string): string {
  return `${valueOf(job, "name", jobId)} details`;
}

function cronTimingDetails(job: DashboardRow): string[] {
  if (cronSystemKind(job) === "proactive-ask") {
    const summary = valueOf(job, "lastSummary", "");
    return summary && summary !== "n/a" ? [summary] : [];
  }
  return [
    `Next ${cronTimestamp(job.nextRunAt ?? job.next_run_at, "Not scheduled")}`,
    `Last ${cronTimestamp(job.lastRunAt ?? job.last_run_at, "Not yet")}`,
    `${valueOf(job, "runCount", valueOf(job, "run_count", "0"))} run(s)`,
  ];
}

function cronScopeSummary(job: DashboardRow): string {
  const systemKind = cronSystemKind(job);
  if (systemKind === "proactive-ask") {
    return "All IM adapters";
  }
  if (systemKind === "dream") {
    return "Background agent";
  }
  const jobKind = valueOf(job, "jobKind", valueOf(job, "action_kind", "prompt"));
  if (jobKind === "learning") {
    return "Background agent";
  }
  const eggId = readString(job, ["eggId", "elephant_id"], "");
  if (eggId) {
    return eggId;
  }
  const profileId = readString(job, ["profileId", "profile_id"], "");
  return profileId || "No elephant selected";
}

function cronScheduleLabel(job: DashboardRow): string {
  const schedule = valueOf(job, "schedule", valueOf(job, "scheduleText", valueOf(job, "schedule_text", "")));
  if (!schedule || schedule === "n/a") {
    return "n/a";
  }
  // If it looks like an ISO timestamp (one-shot delay), format it as local time.
  const parsed = new Date(schedule);
  if (!Number.isNaN(parsed.getTime()) && /^\d{4}-\d{2}-\d{2}T/.test(schedule)) {
    return formatTimestamp(schedule);
  }
  return schedule;
}

function cronTimestamp(item: DashboardJson | undefined, fallback: string): string {
  const timestamp = String(item ?? "").trim();
  if (!timestamp || timestamp === "n/a" || timestamp === "null" || timestamp === "undefined") {
    return fallback;
  }
  return Number.isNaN(new Date(timestamp).getTime()) ? timestamp : formatTimestamp(timestamp);
}

function cronStatusCount(cronJobs: readonly DashboardRow[], status: string): number {
  return cronJobs.filter((job) => valueOf(job, "status", "").toLowerCase() === status).length;
}

export function CronPage(): React.JSX.Element {
  const action = useAsyncAction(async () => undefined);
  const [name, setName] = React.useState("Daily Elephant Agent job");
  const [schedule, setSchedule] = React.useState("daily at 09:00");
  const [prompt, setPrompt] = React.useState("Review current priorities and suggest the next grounded step.");
  const [eggId, setEggId] = React.useState("");
  return (
    <DashboardPage section="cron">
      {(dashboard, { refresh }) => {
        const cron = jsonObject(dashboard.operations.cron);
        const jobs = asRows(cron.jobs);
        const herd = cronEggOptions(dashboard);
        const selectedEgg = herd.find((elephant) => elephant.key === eggId) ?? null;
        const scheduledJobs = cronStatusCount(jobs, "scheduled") + cronStatusCount(jobs, "active");
        const pausedJobs = cronStatusCount(jobs, "paused");
        const completedJobs = cronStatusCount(jobs, "completed");
        const createDisabled = Boolean(action.busy) || selectedEgg == null || !schedule.trim() || !prompt.trim();

        return (
          <>
            <section className={cx(styles.metricGrid, styles.metricGridCompact, styles.cronMetricGrid)}>
              <MetricCard compact metric={{ label: "Scheduled jobs", value: `${jobs.length}`, note: "Local prompts that can wake Elephant Agent later.", tone: jobs.length ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Active", value: `${scheduledJobs}`, note: "Jobs still allowed to run.", tone: scheduledJobs ? "healthy" : "neutral" }} />
              <MetricCard compact metric={{ label: "Paused", value: `${pausedJobs}`, note: `${completedJobs} completed`, tone: pausedJobs ? "attention" : "neutral" }} />
            </section>
            <Panel
              eyebrow="Cron"
              title="Scheduled elephant work"
              detail="Create and manage durable prompt jobs for a selected elephant."
            >
              <section className={cx(styles.settingsSectionGrid, styles.cronWorkspaceGrid)}>
                <article className={cx(styles.settingsSectionCard, styles.cronCreateCard)}>
                  <header>
                    <div>
                      <span>Create</span>
                      <strong>New scheduled prompt</strong>
                    </div>
                    <StatusBadge tone={selectedEgg ? "healthy" : "attention"}>{selectedEgg ? "elephant selected" : "choose elephant"}</StatusBadge>
                  </header>
                  <label className={cx(styles.fieldStack, styles.cronScheduleField)}>
                    <span>Schedule</span>
                    <input value={schedule} placeholder="daily at 09:00 or 0 9 * * 1-5" onChange={(event) => setSchedule(event.target.value)} />
                  </label>
                  <div className={styles.controlToolbar}>
                    {CRON_SCHEDULE_PRESETS.map((preset) => (
                      <ActionButton
                        key={preset.value}
                        className={styles.cronPresetButton}
                        variant={schedule.trim() === preset.value ? "default" : "ghost"}
                        onClick={() => setSchedule(preset.value)}
                      >
                        {preset.label}
                      </ActionButton>
                    ))}
                  </div>
                  <label className={styles.fieldStack}>
                    <span>Name</span>
                    <input value={name} placeholder="Daily summary" onChange={(event) => setName(event.target.value)} />
                  </label>
                  <label className={styles.fieldStack}>
                    <span>Prompt</span>
                    <textarea
                      rows={8}
                      placeholder="What should this elephant do each time the schedule fires?"
                      value={prompt}
                      onChange={(event) => setPrompt(event.target.value)}
                    />
                  </label>
                  <div className={styles.cronComposerGrid}>
                    <label className={styles.fieldStack}>
                      <span>Elephant</span>
                      <select value={eggId} onChange={(event) => setEggId(event.target.value)}>
                        <option value="">Select elephant...</option>
                        {herd.map((elephant) => (
                          <option key={elephant.key} value={elephant.key}>{elephant.label}</option>
                        ))}
                      </select>
                    </label>
                    <div className={styles.cronComposerAction}>
                      <ActionButton
                        className={styles.cronComposerButton}
                        disabled={createDisabled}
                        onClick={() =>
                          void action.run("Create cron job", async () => {
                            await createCronJob({
                              name: name.trim(),
                              schedule: schedule.trim(),
                              job_kind: "prompt",
                              prompt: prompt.trim(),
                              elephant_id: selectedEgg?.eggId || undefined,
                              profile_id: selectedEgg?.profileId || undefined,
                            });
                            await refresh();
                          })
                        }
                      >
                        {action.busy === "Create cron job" ? "Creating" : "Create job"}
                      </ActionButton>
                    </div>
                  </div>
                </article>
                <article className={cx(styles.settingsSectionCard, styles.cronManageCard)}>
                  <header>
                    <div>
                      <span>Manage</span>
                      <strong>{jobs.length} scheduled job(s)</strong>
                    </div>
                    <StatusBadge tone={scheduledJobs ? "healthy" : "neutral"}>{scheduledJobs ? `${scheduledJobs} active` : "idle"}</StatusBadge>
                  </header>
                  {jobs.length ? (
                    <div className={styles.cronJobList}>
                      {jobs.map((job) => {
                        const jobId = valueOf(job, "jobId", valueOf(job, "job_id"));
                        const status = valueOf(job, "status", "unknown");
                        const statusAction = status.toLowerCase() === "paused" ? "resume" : "pause";
                        const isSystem = cronIsSystemJob(job);
                        const canRunNow = cronCanRunNow(job) && Boolean(jobId);
                        const canPause = cronCanPause(job) && Boolean(jobId);
                        const canDelete = cronCanDelete(job) && Boolean(jobId);
                        const timingDetails = cronTimingDetails(job);
                        return (
                          <article key={jobId} className={cx(styles.cronJobRow, isSystem && styles.cronJobRowSystem)}>
                            <div className={styles.cronJobMain}>
                              <div className={styles.cronJobTitle}>
                                <strong>{valueOf(job, "name", jobId)}</strong>
                                {isSystem ? <StatusBadge tone="healthy">System job</StatusBadge> : null}
                                <StatusBadge tone={toneForStatus(status)}>{status}</StatusBadge>
                              </div>
                              <span className={styles.cronJobMeta}>{cronScheduleLabel(job)} · {cronScopeSummary(job)}</span>
                              <p className={styles.cronJobMeta}>{isSystem ? cronSystemDescription(job) : valueOf(job, "lastSummary", cronPromptSummary(job))}</p>
                              {isSystem ? <p className={cx(styles.cronJobMeta, styles.cronJobCapabilityMeta)}>Run now and pause supported · Delete disabled</p> : null}
                              {timingDetails.length ? (
                                <div className={styles.cronJobTimestamps}>
                                  {timingDetails.map((item) => (
                                    <small key={item}>{item}</small>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                            <div className={styles.cronJobActions}>
                              {canRunNow ? (
                                <ActionButton
                                  disabled={Boolean(action.busy) || !jobId}
                                  variant="ghost"
                                  onClick={() =>
                                    void action.run("Run cron job", async () => {
                                      await runCronJob(jobId);
                                      await refresh();
                                    })
                                  }
                                >
                                  Run now
                                </ActionButton>
                              ) : null}
                              {canPause ? (
                                <ActionButton
                                  disabled={Boolean(action.busy) || !jobId}
                                  variant="ghost"
                                  onClick={() =>
                                    void action.run(`${statusAction === "pause" ? "Pause" : "Resume"} cron job`, async () => {
                                      await setCronJobStatus(jobId, statusAction);
                                      await refresh();
                                    })
                                  }
                                >
                                  {statusAction === "pause" ? "Pause" : "Resume"}
                                </ActionButton>
                              ) : null}
                              {canDelete ? (
                                <ActionButton
                                  disabled={Boolean(action.busy) || !jobId}
                                  variant="ghost"
                                  onClick={() =>
                                    void action.run("Remove cron job", async () => {
                                      await deleteCronJob(jobId);
                                      await refresh();
                                    })
                                  }
                                >
                                  Delete
                                </ActionButton>
                              ) : null}
                              <ViewButton title={cronDetailTitle(job, jobId)} items={detailItems(job)} variant="ghost" />
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  ) : (
                    <EmptyPanel title="No jobs scheduled" detail="Create a scheduled job when Elephant Agent should quietly revisit something without you starting a new chat." />
                  )}
                </article>
              </section>
              {action.message ? <p className={styles.statusDetailSummary}>{action.message}</p> : null}
            </Panel>
          </>
        );
      }}
    </DashboardPage>
  );
}

function settingsDetailItems(settings: DashboardRow): DetailListItem[] {
  const globalConfig = jsonObject(settings.globalConfig);
  const runtimeConfig = jsonObject(globalConfig.runtime);
  const modelsConfig = jsonObject(globalConfig.models);
  const providerConfig = jsonObject(modelsConfig.provider);
  const sessionsConfig = jsonObject(globalConfig.sessions);
  const skillsConfig = jsonObject(globalConfig.skills);
  const toolsConfig = jsonObject(globalConfig.tools);
  const gatewayConfig = jsonObject(globalConfig.gateway);
  const dashboardConfig = jsonObject(globalConfig.dashboard);
  const personalModelConfig = jsonObject(globalConfig.personal_model);
  const questionConfig = jsonObject(globalConfig.personal_model_questions);
  const proactiveAsk = jsonObject(questionConfig.proactive_ask);
  const idleThreshold = valueOf(proactiveAsk, "idle_threshold_minutes", "180");
  const dailyMax = valueOf(proactiveAsk, "daily_max", "8");
  const externalSkillDirs = asTextList(skillsConfig.external_dirs);
  const providerId = valueOf(providerConfig, "provider_id", valueOf(providerConfig, "profile_id", "not configured"));
  const providerModel = valueOf(providerConfig, "default_model", valueOf(providerConfig, "default_model_id", "n/a"));

  return [
    { label: "Global config file", value: valueOf(settings, "globalConfigPath", "n/a") },
    { label: "Config file exists", value: settings.globalConfigExists === true ? "yes" : "no" },
    { label: "Runtime state directory", value: valueOf(runtimeConfig, "state_dir", valueOf(settings, "eggDir", "n/a")) },
    { label: "Default profile", value: valueOf(runtimeConfig, "default_profile_id", "default") },
    { label: "First language", value: valueOf(personalModelConfig, "first_language", "en") },
    { label: "Dashboard bind", value: `${valueOf(dashboardConfig, "host", "127.0.0.1")}:${valueOf(dashboardConfig, "port", "4174")}` },
    { label: "Provider", value: providerId === "not configured" ? providerId : `${providerId} · ${providerModel}` },
    { label: "Gateway", value: `${valueOf(gatewayConfig, "enabled", "false")} · state ${valueOf(gatewayConfig, "state_dir", valueOf(settings, "eggDir", "n/a"))}` },
    { label: "Questions", value: `proactive ${valueOf(proactiveAsk, "enabled", "true")} · idle ${idleThreshold}min · ${dailyMax}/day` },
    {
      label: "External skill dirs",
      value: externalSkillDirs.length ? (
        <ul>
          {externalSkillDirs.map((entry) => <li key={entry}>{entry}</li>)}
        </ul>
      ) : "none",
    },
    {
      label: "Session retention",
      value: `${valueOf(sessionsConfig, "max_history_rows", "200")} rows · prompts ${valueOf(sessionsConfig, "persist_system_prompts", "true")} · replies ${valueOf(sessionsConfig, "persist_assistant_responses", "true")}`,
    },
    { label: "Risky tool approval", value: valueOf(toolsConfig, "require_approval_for_risky", "true") },
  ];
}

function SettingsEditor({
  settings,
  refresh,
}: {
  settings: DashboardRow;
  refresh: () => Promise<void>;
}): React.JSX.Element {
  const action = useAsyncAction(refresh);
  const incomingYaml = valueOf(settings, "globalConfigYaml", "");
  const [yamlText, setYamlText] = React.useState(incomingYaml);

  React.useEffect(() => {
    setYamlText(incomingYaml);
  }, [incomingYaml]);

  return (
    <Panel
      eyebrow="Settings"
      title="Global runtime config"
      detail="Edit the single global config file. runtime.state_dir and gateway.state_dir are state/database directories, not separate config files."
    >
      <textarea
        className={styles.settingsTextArea}
        value={yamlText}
        onChange={(event) => setYamlText(event.target.value)}
        spellCheck={false}
      />
      <div className={styles.settingsActionBar}>
        <div className={styles.settingsActionCopy}>
          <span>Config actions</span>
          <strong>{valueOf(settings, "globalConfigPath", "Local config")}</strong>
          <p>Save writes the YAML above. Summary opens only the useful runtime fields.</p>
        </div>
        <div className={styles.settingsActionButtons}>
          <ActionButton
            disabled={Boolean(action.busy)}
            onClick={() => void action.run("Save config", () => saveOperatorGlobalConfig({ yamlText }))}
          >
            {action.busy ? "Saving config" : "Save config"}
          </ActionButton>
          <ViewButton title="Settings detail" items={settingsDetailItems(settings)} variant="ghost">
            Summary
          </ViewButton>
        </div>
      </div>
      {action.message ? <p className={styles.statusDetailSummary}>{action.message}</p> : null}
    </Panel>
  );
}

export function SettingsPage(): React.JSX.Element {
  return (
    <DashboardPage section="settings">
      {(dashboard, { refresh }) => {
        const settings = dashboard.operations.settings;
        const globalConfig = jsonObject(settings.globalConfig);
        const runtimeConfig = jsonObject(globalConfig.runtime);
        const dashboardConfig = jsonObject(globalConfig.dashboard);
        const configPath = valueOf(settings, "globalConfigPath", "n/a");
        const stateDir = valueOf(runtimeConfig, "state_dir", valueOf(settings, "eggDir", "n/a"));
        const dashboardBind = `${valueOf(dashboardConfig, "host", "127.0.0.1")}:${valueOf(dashboardConfig, "port", "4174")}`;
        return (
          <>
            <Panel
              eyebrow="Settings"
              title="Local runtime files"
              detail="There is one global config file; the state directory stores the SQLite DB and runtime files used by that config."
            >
              <div className={styles.compactInfoGrid}>
                <div><span>Global config file</span><strong>{configPath}</strong></div>
                <div><span>Runtime state dir</span><strong>{stateDir}</strong></div>
                <div><span>Config exists</span><strong>{settings.globalConfigExists === true ? "yes" : "no"}</strong></div>
                <div><span>Dashboard bind</span><strong>{dashboardBind}</strong></div>
              </div>
            </Panel>
            <SettingsEditor settings={settings} refresh={refresh} />
          </>
        );
      }}
    </DashboardPage>
  );
}

function usageAnalyticsRows(usage: DashboardRow, source: "trend" | "elephant", days: number): DashboardRow[] {
  if (source === "trend") {
    return asRows(usage.tokenTrend).slice(0, days).map((row) => ({
      label: valueOf(row, "day"),
      tokens: Number(row.totalTokens ?? row.total_tokens ?? row.tokens ?? 0),
      input: Number(row.promptTokens ?? row.prompt_tokens ?? row.input_tokens ?? 0),
      output: Number(row.completionTokens ?? row.completion_tokens ?? row.output_tokens ?? 0),
      turns: Number(row.turns ?? row.sessions ?? 0),
    }));
  }
  return asRows(usage.eggUsage).map((row) => ({
    label: valueOf(row, "eggName", valueOf(row, "eggId", valueOf(row, "profile_id", "elephant"))),
    tokens: Number(row.totalTokens ?? row.total_tokens ?? row.tokens ?? 0),
    input: Number(row.promptTokens ?? row.prompt_tokens ?? row.input_tokens ?? 0),
    output: Number(row.completionTokens ?? row.completion_tokens ?? row.output_tokens ?? 0),
    turns: Number(row.turns ?? row.sessions ?? 0),
  }));
}

function logLineClass(line: string): string | undefined {
  const normalized = line.toLowerCase();
  if (normalized.includes("error") || normalized.includes("traceback") || normalized.includes("exception")) {
    return styles.logLineError;
  }
  if (normalized.includes("warn")) {
    return styles.logLineWarn;
  }
  if (normalized.includes("info") || normalized.includes("ready") || normalized.includes("serving")) {
    return styles.logLineInfo;
  }
  return undefined;
}

function LogBrowser({
  logs,
  selectedLogId,
  setSelectedLogId,
}: {
  logs: DashboardRow[];
  selectedLogId: string;
  setSelectedLogId: (id: string) => void;
}): React.JSX.Element {
  const selected = logs.find((row) => logId(row) === selectedLogId) ?? logs[0] ?? {};
  const tail = asTextList(selected.tail);
  return (
    <div className={styles.logBrowser}>
      <nav className={styles.logPicker} aria-label="Log files">
        {logs.map((row) => {
          const id = logId(row);
          return (
            <button
              key={id}
              className={cx(styles.logPickerButton, id === logId(selected) && styles.logPickerButtonActive)}
              type="button"
              onClick={() => setSelectedLogId(id)}
            >
              <span>{valueOf(row, "name", "log")}</span>
              <strong>{valueOf(row, "path", "log file")}</strong>
              <small>{valueOf(row, "size", "0")} bytes · {formatWhen(row.updatedAt ?? row.updated_at)}</small>
            </button>
          );
        })}
      </nav>
      <article className={styles.logViewer}>
        <header>
          <div>
            <span>{valueOf(selected, "name", "log")}</span>
            <strong>{valueOf(selected, "path", "log file")}</strong>
          </div>
          <ViewButton title={valueOf(selected, "name", "log")} items={detailItems(selected)} variant="ghost" />
        </header>
        <p>{valueOf(selected, "size", "0")} bytes · updated {formatWhen(selected.updatedAt ?? selected.updated_at)}</p>
        {tail.length ? (
          <pre className={styles.logLineList}>
            {tail.map((line, index) => (
              <code key={`${index}-${line.slice(0, 20)}`} className={cx(styles.logLine, logLineClass(line))}>
                {line}
              </code>
            ))}
          </pre>
        ) : (
          <EmptyPanel title="No tail" detail="This log file is empty or could not be read." />
        )}
      </article>
    </div>
  );
}

function logId(row: DashboardRow | undefined): string {
  return valueOf(row ?? {}, "path", valueOf(row ?? {}, "name", "log"));
}

function LogFileCard({ row }: { row: DashboardRow }): React.JSX.Element {
  const tail = asTextList(row.tail);
  return (
    <article className={styles.logFileCard}>
      <header>
        <div>
          <span>{valueOf(row, "name", "log")}</span>
          <strong>{valueOf(row, "path", "log file")}</strong>
        </div>
        <StatusBadge tone="neutral">{valueOf(row, "size", "0")} bytes</StatusBadge>
      </header>
      <p>Updated {formatWhen(row.updatedAt)}</p>
      {tail.length ? (
        <pre className={styles.logTail}>{tail.join("\n")}</pre>
      ) : (
        <EmptyPanel title="No tail" detail="This log file is empty or could not be read." />
      )}
      <ViewButton title={valueOf(row, "name", "log")} items={detailItems(row)} variant="ghost" />
    </article>
  );
}

function UsageChart({ rows }: { rows: DashboardRow[] }): React.JSX.Element {
  const maxTokens = Math.max(1, ...rows.map((row) => Number(row.tokens ?? 0)));
  return (
    <div className={styles.usageChart}>
      {rows.map((row) => {
        const tokens = Number(row.tokens ?? 0);
        const width = `${Math.max(2, Math.round((tokens / maxTokens) * 100))}%`;
        return (
          <article key={valueOf(row, "label")} className={styles.usageBarRow}>
            <span>{valueOf(row, "label")}</span>
            <div className={styles.usageBarTrack}>
              <div className={styles.usageBarFill} style={{ width }} />
            </div>
            <strong>{formatCompactNumber(tokens)}</strong>
          </article>
        );
      })}
    </div>
  );
}

function UsageTable({ rows, compact = false }: { rows: DashboardRow[]; compact?: boolean }): React.JSX.Element {
  return (
    <div className={cx(styles.analyticsTable, compact && styles.analyticsTableCompact)}>
      <div className={styles.analyticsTableHeader}>
        <span>Name</span>
        <span>Tokens</span>
        <span>Input</span>
        <span>Output</span>
        {!compact ? <span>Turns</span> : null}
      </div>
      {rows.map((row) => (
        <div key={valueOf(row, "label")} className={styles.analyticsTableRow}>
          <strong>{valueOf(row, "label")}</strong>
          <span>{formatCompactNumber(row.tokens)}</span>
          <span>{formatCompactNumber(row.input)}</span>
          <span>{formatCompactNumber(row.output)}</span>
          {!compact ? <span>{formatCompactNumber(row.turns)}</span> : null}
        </div>
      ))}
    </div>
  );
}

function UsageEventsList({
  tokenEvents,
  page,
  setPage,
}: {
  tokenEvents: DashboardRow[];
  page: number;
  setPage: React.Dispatch<React.SetStateAction<number>>;
}): React.JSX.Element {
  const pageSize = 12;
  const totalPages = Math.max(1, Math.ceil(tokenEvents.length / pageSize));
  const currentPage = Math.min(page, totalPages - 1);
  const visibleEvents = tokenEvents.slice(currentPage * pageSize, currentPage * pageSize + pageSize);

  return (
    <Panel
      eyebrow="Events"
      title="Usage events"
      detail="Every token Elephant Agent used — input, output, cached recall, and which elephant asked for it."
    >
      {tokenEvents.length ? (
        <>
          <div className={styles.usageEventList}>
            {visibleEvents.map((row, index) => {
              const usageId = valueOf(row, "usage_id", `${valueOf(row, "model_id", "usage")}-${index}`);
              const promptTokens = numberOf(row, "prompt_tokens");
              const completionTokens = numberOf(row, "completion_tokens");
              const totalTokens = numberOf(row, "total_tokens") || promptTokens + completionTokens;
              const source = valueOf(row, "sourceLabel", valueOf(row, "provider_id", "provider"));
              const elephant = valueOf(row, "eggName", valueOf(row, "eggId", "No elephant"));
              const createdAt = formatWhen(row.created_at);
              return (
                <article key={usageId} className={styles.usageEventRow}>
                  <div className={styles.usageEventMain}>
                    <span>{createdAt} · {source}</span>
                    <strong>{valueOf(row, "model_id", usageId)}</strong>
                    <p>{elephant} · {valueOf(row, "cache_summary", "cache not reported")}</p>
                  </div>
                  <div className={styles.usageEventStats}>
                    <div>
                      <span>Total</span>
                      <strong>{formatCompactNumber(totalTokens)}</strong>
                    </div>
                    <div>
                      <span>Input</span>
                      <strong>{formatCompactNumber(promptTokens)}</strong>
                    </div>
                    <div>
                      <span>Output</span>
                      <strong>{formatCompactNumber(completionTokens)}</strong>
                    </div>
                  </div>
                  <ViewButton className={styles.usageEventViewButton} title={usageId} items={detailItems(row)} variant="ghost" />
                </article>
              );
            })}
          </div>
          <PaginationBar
            totalItems={tokenEvents.length}
            currentPage={currentPage}
            totalPages={totalPages}
            pageSize={pageSize}
            label="events"
            onPrevious={() => setPage((current) => Math.max(0, current - 1))}
            onNext={() => setPage((current) => Math.min(totalPages - 1, current + 1))}
          />
        </>
      ) : (
        <EmptyPanel title="No token events yet" detail="Once Elephant Agent starts chatting, the tokens it uses will show up here." />
      )}
    </Panel>
  );
}

function usageLogsSection(focus: "all" | "usage" | "logs"): DashboardSection {
  if (focus === "usage") {
    return "usage";
  }
  if (focus === "logs") {
    return "logs";
  }
  return "usage-logs";
}

function UsageLogsSurface({ focus = "all" }: { focus?: "all" | "usage" | "logs" }): React.JSX.Element {
  const [rangeDays, setRangeDays] = React.useState(30);
  const [usageEventsPage, setUsageEventsPage] = React.useState(0);
  const [selectedLogId, setSelectedLogId] = React.useState("");
  return (
    <DashboardPage section={usageLogsSection(focus)}>
      {(dashboard) => {
        const usage = dashboard.operations.usage;
        const summary = jsonObject(usage.summary);
        const tokenEvents = asRows(usage.tokenEvents);
        const trendRows = usageAnalyticsRows(usage, "trend", rangeDays);
        const eggRows = usageAnalyticsRows(usage, "elephant", rangeDays);
        return (
          <>
            {focus !== "logs" ? (
              <section className={cx(styles.metricGrid, styles.metricGridCompact)}>
              {[
                {
                  label: "Total tokens",
                  value: formatCompactNumber(summary.totalTokens),
                  note: valueOf(summary, "recordingLevel", "Token ledger status unknown."),
                  tone: numberOf(summary, "totalTokens") ? "healthy" : "neutral",
                },
                {
                  label: "Prompt / completion",
                  value: `${formatCompactNumber(summary.promptTokens)} / ${formatCompactNumber(summary.completionTokens)}`,
                  note: "Input and output token totals from provider-reported events.",
                  tone: numberOf(summary, "promptTokens") ? "healthy" : "neutral",
                },
                {
                  label: "Recorded events",
                  value: formatCompactNumber(summary.usageEvents ?? summary.runtimeStepUsageEvents),
                  note: "Token ledger rows, filled in from conversation usage when ledger rows are missing.",
                  tone: numberOf(summary, "usageEvents") || numberOf(summary, "runtimeStepUsageEvents") ? "healthy" : "attention",
                },
                {
                  label: "Herd",
                  value: formatCompactNumber(eggRows.length),
                  note: "Elephant-level token totals from the same usage ledger.",
                  tone: eggRows.length ? "healthy" : "neutral",
                },
                ...(focus === "all"
                  ? [
                      {
                        label: "Log files",
                        value: String(dashboard.operations.logs.length),
                        note: "Local API, dashboard, and gateway log files with tails available.",
                        tone: dashboard.operations.logs.length ? "healthy" : "neutral",
                      },
                    ]
                  : []),
              ].map((metric) => (
                <MetricCard key={metric.label} metric={metric as DashboardMetric} />
              ))}
              </section>
            ) : null}

            {focus !== "logs" ? (
              <>
                <div className={styles.segmentedControl} aria-label="Usage time range">
                  {[7, 30, 90].map((days) => (
                    <button key={days} className={cx(rangeDays === days && styles.segmentedControlActive)} type="button" onClick={() => setRangeDays(days)}>
                      {days}D
                    </button>
                  ))}
                </div>

                <Panel
                  eyebrow="Usage"
                  title="Daily token usage"
                  detail="Input and output tokens, grouped by day from the token ledger and conversation usage."
                >
                  {trendRows.length ? (
                    <UsageChart rows={trendRows} />
                  ) : (
                    <EmptyPanel title="No daily trend rows" detail="Daily rows appear once provider-backed turns report token events." />
                  )}
                </Panel>

                <Panel
                  eyebrow="Usage detail"
                  title="Daily detail"
                  detail="Readable daily totals with input/output split from recorded usage events."
                >
                  {trendRows.length ? (
                    <UsageTable rows={trendRows} />
                  ) : (
                    <EmptyPanel title="No daily detail" detail="Daily detail appears after token events are recorded." />
                  )}
                </Panel>

                <Panel
                  eyebrow="Elephant usage"
                  title="Token usage by elephant"
                  detail="Elephant-level totals stay visible alongside daily trends."
                >
                  {eggRows.length ? (
                    <>
                      <UsageChart rows={eggRows} />
                      <UsageTable rows={eggRows} compact />
                    </>
                  ) : (
                    <EmptyPanel title="No elephant totals yet" detail="Totals per elephant appear once Elephant Agent has spent any tokens on their behalf." />
                  )}
                </Panel>

                <UsageEventsList tokenEvents={tokenEvents} page={usageEventsPage} setPage={setUsageEventsPage} />
              </>
            ) : null}

            {focus !== "usage" ? (
              <Panel
                eyebrow="Logs"
                title="Runtime logs"
                detail="Recent local API, dashboard, and gateway log tails. Open this only when debugging concrete system failures."
              >
                {dashboard.operations.logs.length ? (
                  <LogBrowser
                    logs={dashboard.operations.logs}
                    selectedLogId={selectedLogId || logId(dashboard.operations.logs[0])}
                    setSelectedLogId={setSelectedLogId}
                  />
                ) : (
                  <EmptyPanel title="No logs yet" detail="Local logs appear once Elephant Agent has written something to them." />
                )}
              </Panel>
            ) : null}
          </>
        );
      }}
    </DashboardPage>
  );
}

export function UsagePage(): React.JSX.Element {
  return <UsageLogsSurface focus="usage" />;
}

export function LogsPage(): React.JSX.Element {
  return <UsageLogsSurface focus="logs" />;
}

export function UsageLogsPage(): React.JSX.Element {
  return <UsageLogsSurface focus="all" />;
}

/**
 * Personal Model Questions route — open-question ledger and proactive question cadence. Reads from the `/questions` dashboard section surfaced by `apps/api/api_runtime_internal_sections.py`.
 */
export function QuestionsPage(): React.JSX.Element {
  return (
    <DashboardPage section="questions">
      {(dashboard, { refresh }) => {
        const questions = (dashboard as unknown as { questions?: QuestionsSnapshot }).questions;
        const facts = questions?.facts ?? [];
        const waitingQuestions = questions?.waiting_questions ?? [];
        const askedQuestions = questions?.asked_questions ?? [];
        const answeredQuestions = questions?.answered_questions ?? [];
        const dismissedQuestions = questions?.dismissed_questions ?? [];
        const intensity = (questions?.learning_intensity ?? "medium") as "low" | "medium" | "high";
        const effectivePolicy = jsonObject(questions?.effective_policy);
        const totalOpen = waitingQuestions.length + askedQuestions.length;
        return (
          <>
            <QuestionCadenceControl current={intensity} refresh={refresh} />

            <div className={styles.metricGridCompact} style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem" }}>
              <MetricCard metric={{ label: "Facts", value: String(facts.length), note: "Durable, prompt-visible", tone: "healthy" }} compact />
              <MetricCard metric={{ label: "Facets", value: String(new Set(facts.map((row) => valueOf(row, "facet", ""))).size), note: "Topic-keyed claims", tone: "neutral" }} compact />
              <MetricCard metric={{ label: "Open questions", value: String(totalOpen), note: `${waitingQuestions.length} waiting · ${askedQuestions.length} asked`, tone: "neutral" }} compact />
              <MetricCard metric={{ label: "Answered", value: String(answeredQuestions.length), note: "Learned through asking", tone: answeredQuestions.length > 0 ? "healthy" : "neutral" }} compact />
            </div>


            <Panel
              eyebrow="Question ledger"
              title="Questions, answers, and learned conclusions"
              detail="A single evidence-style ledger: each row shows why Elephant Agent wants to ask, where it sits now, and what claim it produced if answered."
            >
              <PersonalModelQuestionLedger
                waitingQuestions={waitingQuestions}
                askedQuestions={askedQuestions}
                answeredQuestions={answeredQuestions}
                dismissedQuestions={dismissedQuestions}
                refresh={refresh}
              />
            </Panel>
          </>
        );
      }}
    </DashboardPage>
  );
}

function QuestionsPersonalField({
  waitingQuestions,
  askedQuestions,
  answeredQuestions,
  dismissedQuestions,
}: {
  waitingQuestions: readonly DashboardRow[];
  askedQuestions: readonly DashboardRow[];
  answeredQuestions: readonly DashboardRow[];
  dismissedQuestions: readonly DashboardRow[];
}): React.JSX.Element {
  const nextQuestions = waitingQuestions.slice(0, 3);
  const pendingAnswers = askedQuestions.slice(0, 3);
  const guideCards = [
    { label: "Ready", value: String(waitingQuestions.length), detail: "Waiting for a natural moment" },
    { label: "Asked", value: String(askedQuestions.length), detail: "Already surfaced, not answered yet" },
    { label: "Answered", value: String(answeredQuestions.length), detail: "Turned into learning" },
    { label: "Dismissed", value: String(dismissedQuestions.length), detail: "Held back or retired" },
  ];

  return (
    <section className={styles.questionField}>
      <div className={styles.questionFieldHero}>
        <span>Question field</span>
        <h2>What Elephant Agent may ask next</h2>
        <p>
          This page only tracks open learning loops: what Elephant Agent may ask, what is waiting for an answer, and what already turned into Personal Model signal. Stable facts stay on You.
        </p>
        <div className={styles.questionGuideGrid}>
          {guideCards.map((card) => (
            <div key={card.label}>
              <strong>{card.value}</strong>
              <span>{card.label}</span>
              <p>{card.detail}</p>
            </div>
          ))}
        </div>
      </div>

      <div className={styles.questionFieldModules}>
        <div className={styles.questionFieldModule}>
          <span>Questions not asked yet</span>
          {nextQuestions.length ? (
            <ul>
              {nextQuestions.map((row, index) => (
                <li key={`${personalModelQuestionId(row, String(index))}`}>{compactText(valueOf(row, "text", ""), 132)}</li>
              ))}
            </ul>
          ) : (
            <p>No open question needs attention right now.</p>
          )}
        </div>

        <div className={styles.questionFieldModule}>
          <span>Waiting for answer</span>
          {pendingAnswers.length ? (
            <ul>
              {pendingAnswers.map((row, index) => (
                <li key={`${personalModelQuestionId(row, String(index))}`}>{compactText(valueOf(row, "text", ""), 132)}</li>
              ))}
            </ul>
          ) : (
            <p>No asked question is waiting on the user.</p>
          )}
        </div>
      </div>
    </section>
  );
}

function QuestionCadenceControl({
  current,
  refresh,
}: {
  current: "low" | "medium" | "high";
  refresh: () => Promise<void>;
}): React.JSX.Element {
  const action = useAsyncAction(refresh);

  // Derive initial numeric values from the effective policy (via dashboard questions section).
  // The dashboard snapshot exposes effective_policy with the new flat fields.
  const [idleThreshold, setIdleThreshold] = React.useState(
    current === "low" ? 720 : current === "high" ? 60 : 180,
  );
  const [dailyMax, setDailyMax] = React.useState(
    current === "low" ? 2 : current === "high" ? 24 : 8,
  );
  const [quietStart, setQuietStart] = React.useState(current === "high" ? 1 : 23);
  const [quietEnd, setQuietEnd] = React.useState(7);

  const formatHour = (h: number) => `${h.toString().padStart(2, "0")}:00`;
  const quietFillStyle = (): React.CSSProperties => {
    const startPct = (quietStart / 24) * 100;
    const endPct = (quietEnd / 24) * 100;
    if (quietStart <= quietEnd) {
      return { left: `${startPct}%`, width: `${endPct - startPct}%` };
    }
    // Wrapping case: use a gradient to show two segments
    return { left: "0%", width: "100%", background: `linear-gradient(to right, var(--dashboard-accent) 0%, var(--dashboard-accent) ${endPct}%, transparent ${endPct}%, transparent ${startPct}%, var(--dashboard-accent) ${startPct}%, var(--dashboard-accent) 100%)` };
  };

  return (
    <Panel
      eyebrow="Cadence"
      title="How often should Elephant Agent ask?"
      detail="Controls when proactive questions may be delivered through running IM routes."
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <span>Idle threshold (minutes)</span>
          <input
            type="number"
            min={1}
            value={idleThreshold}
            onChange={(e) => setIdleThreshold(Math.max(1, Number(e.target.value) || 180))}
            style={{ padding: "0.5rem 0.58rem", borderRadius: "0.52rem", border: "1px solid var(--dashboard-border-strong)", background: "rgba(255, 255, 255, 0.76)", color: "var(--dashboard-text)" }}
          />
          <small style={{ opacity: 0.7 }}>Ask only after user has been idle this long</small>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <span>Daily max</span>
          <input
            type="number"
            min={1}
            value={dailyMax}
            onChange={(e) => setDailyMax(Math.max(1, Number(e.target.value) || 8))}
            style={{ padding: "0.5rem 0.58rem", borderRadius: "0.52rem", border: "1px solid var(--dashboard-border-strong)", background: "rgba(255, 255, 255, 0.76)", color: "var(--dashboard-text)" }}
          />
          <small style={{ opacity: 0.7 }}>Maximum questions per day</small>
        </label>
      </div>
      <div className={styles.quietHoursSlider}>
        <span className={styles.quietHoursLabel}>Quiet hours</span>
        <div className={styles.quietHoursTrack}>
          <div className={styles.quietHoursFill} style={quietFillStyle()} />
          <input
            type="range"
            min={0}
            max={23}
            value={quietStart}
            onChange={(e) => setQuietStart(Number(e.target.value))}
            className={styles.quietHoursThumb}
          />
          <input
            type="range"
            min={0}
            max={23}
            value={quietEnd}
            onChange={(e) => setQuietEnd(Number(e.target.value))}
            className={styles.quietHoursThumb}
          />
        </div>
        <div className={styles.quietHoursMarkers}>
          <span>0</span><span>6</span><span>12</span><span>18</span><span>24</span>
        </div>
        <small className={styles.quietHoursCaption}>{formatHour(quietStart)} – {formatHour(quietEnd)} (no questions delivered)</small>
      </div>
      <div className={styles.settingsActionBar} style={{ marginTop: "1rem" }}>
        <ActionButton
          disabled={Boolean(action.busy)}
          onClick={() => {
            void action.run("Save cadence", () =>
              setPersonalModelQuestionIntensity({
                idle_threshold_minutes: idleThreshold,
                daily_max: dailyMax,
                quiet_hours: [quietStart, quietEnd],
              }),
            );
          }}
        >
          {action.busy ? "Saving…" : "Save cadence"}
        </ActionButton>
      </div>
      {action.message ? <p className={styles.statusDetailSummary}>{action.message}</p> : null}
    </Panel>
  );
}

type PersonalModelQuestionStatus = "ready" | "asked" | "answered" | "dismissed";

type PersonalModelQuestionFilter = PersonalModelQuestionStatus | "all";

type PersonalModelQuestionItem = {
  row: DashboardRow;
  status: PersonalModelQuestionStatus;
};

function personalModelQuestionId(row: DashboardRow, fallback: string): string {
  return String(valueOf(row, "question_id", fallback));
}

function questionStatusLabel(status: PersonalModelQuestionStatus): string {
  switch (status) {
    case "ready":
      return "Ready to ask";
    case "asked":
      return "Asked";
    case "answered":
      return "Learned";
    case "dismissed":
      return "Dismissed";
  }
}

function questionStatusTone(status: PersonalModelQuestionStatus): HealthTone {
  if (status === "answered") return "healthy";
  if (status === "asked") return "attention";
  return "neutral";
}

function PersonalModelQuestionLedger({
  waitingQuestions,
  askedQuestions,
  answeredQuestions,
  dismissedQuestions,
  refresh,
}: {
  waitingQuestions: readonly DashboardRow[];
  askedQuestions: readonly DashboardRow[];
  answeredQuestions: readonly DashboardRow[];
  dismissedQuestions: readonly DashboardRow[];
  refresh: () => Promise<void>;
}): React.JSX.Element {
  const action = useAsyncAction(refresh);
  const [answerDrafts, setAnswerDrafts] = React.useState<Record<string, string>>({});
  const [filter, setFilter] = React.useState<PersonalModelQuestionFilter>("all");
  const [page, setPage] = React.useState(0);
  const pageSize = 8;
  const rows: PersonalModelQuestionItem[] = [
    ...waitingQuestions.map((row) => ({ row, status: "ready" as const })),
    ...askedQuestions.map((row) => ({ row, status: "asked" as const })),
    ...answeredQuestions.map((row) => ({ row, status: "answered" as const })),
    ...dismissedQuestions.map((row) => ({ row, status: "dismissed" as const })),
  ];
  const visibleRows = filter === "all" ? rows : rows.filter((item) => item.status === filter);
  const totalPages = Math.max(1, Math.ceil(visibleRows.length / pageSize));
  const currentPage = Math.min(page, totalPages - 1);
  const pagedRows = visibleRows.slice(currentPage * pageSize, currentPage * pageSize + pageSize);
  const filters: ReadonlyArray<{ id: PersonalModelQuestionFilter; label: string; count: number }> = [
    { id: "all", label: "All", count: rows.length },
    { id: "ready", label: "Ready", count: waitingQuestions.length },
    { id: "asked", label: "Asked", count: askedQuestions.length },
    { id: "answered", label: "Learned", count: answeredQuestions.length },
    { id: "dismissed", label: "Dismissed", count: dismissedQuestions.length },
  ];

  React.useEffect(() => {
    setPage(0);
  }, [filter]);

  React.useEffect(() => {
    if (page > totalPages - 1) {
      setPage(totalPages - 1);
    }
  }, [page, totalPages]);

  if (!rows.length) {
    return <EmptyPanel title="No questions yet" detail="Coverage gaps, ambiguity, and contextual hooks will appear here as a traceable question ledger." />;
  }

  return (
    <section className={styles.questionLedger}>
      <div className={styles.questionLedgerToolbar}>
        <div className={styles.questionLedgerTabs}>
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cx(styles.questionLedgerTab, filter === item.id ? styles.questionLedgerTabActive : "")}
              onClick={() => setFilter(item.id)}
            >
              <span>{item.label}</span>
              <strong>{item.count}</strong>
            </button>
          ))}
        </div>
        <PaginationBar
          totalItems={visibleRows.length}
          currentPage={currentPage}
          totalPages={totalPages}
          pageSize={pageSize}
          label="questions"
          onPrevious={() => setPage((value) => Math.max(0, value - 1))}
          onNext={() => setPage((value) => Math.min(totalPages - 1, value + 1))}
        />
      </div>
      {visibleRows.length ? (
        <div className={styles.runtimeTraceSteps}>
          {pagedRows.map((item, index) => (
            <PersonalModelQuestionRow
              key={`${item.status}-${personalModelQuestionId(item.row, String(index))}`}
              item={item}
              index={currentPage * pageSize + index}
              action={action}
              answerDrafts={answerDrafts}
              setAnswerDrafts={setAnswerDrafts}
            />
          ))}
        </div>
      ) : (
        <EmptyPanel title="Nothing in this state" detail="Switch to All to see the full question ledger." />
      )}
      {action.message ? <p className={styles.statusDetailSummary}>{action.message}</p> : null}
    </section>
  );
}

function PersonalModelQuestionRow({
  item,
  index,
  action,
  answerDrafts,
  setAnswerDrafts,
}: {
  item: PersonalModelQuestionItem;
  index: number;
  action: ReturnType<typeof useAsyncAction>;
  answerDrafts: Record<string, string>;
  setAnswerDrafts: React.Dispatch<React.SetStateAction<Record<string, string>>>;
}): React.JSX.Element {
  const question = item.row;
  const questionId = personalModelQuestionId(question, String(index));
  const text = valueOf(question, "text", "");
  const source = valueOf(question, "source", "");
  const sensitivity = valueOf(question, "sensitivity", "low");
  const lens = valueOf(question, "lens", "");
  const subLens = valueOf(question, "sub_lens", "");
  const askedCount = valueOf(question, "asked_count", "0");
  const lastAskedSurface = valueOf(question, "last_asked_surface", "");
  const lastAskedAt = valueOf(question, "last_asked_at", "");
  const priorityRaw = valueOf(question, "priority", "0");
  const resultingFacts = asRows(question.resulting_facts);
  const canAnswer = item.status === "ready" || item.status === "asked";
  const canDismiss = item.status === "ready" || item.status === "asked";

  return (
    <article className={styles.runtimeTraceStep}>
      <header className={styles.runtimeTraceStepHeader}>
        <div className={styles.runtimeTraceStepHeading}>
          <div className={styles.runtimeTraceTagRow}>
            <StatusBadge tone={questionStatusTone(item.status)}>{questionStatusLabel(item.status)}</StatusBadge>
            <StatusBadge tone="neutral">{lens}{subLens ? ` · ${subLens}` : ""}</StatusBadge>
            <StatusBadge tone="neutral">{source || "coverage"}</StatusBadge>
            <StatusBadge tone="neutral">{sensitivity}</StatusBadge>
          </div>
          <strong>{text}</strong>
        </div>
        <div className={styles.runtimeTraceHeaderActions}>
          <span>
            {item.status === "ready" ? `priority ${priorityRaw}` : item.status === "asked" ? `asked ${askedCount}${lastAskedAt ? ` · ${formatWhen(lastAskedAt)}` : ""}` : formatWhen(valueOf(question, "created_at", ""))}
          </span>
          <ViewButton className={styles.runtimeTraceViewButton} title={questionId} items={detailItems(question)} variant="ghost" />
        </div>
      </header>
      {lastAskedSurface ? <p className={styles.runtimeTraceLead}>Last surfaced through {lastAskedSurface}.</p> : null}
      {resultingFacts.length ? (
        <ul className={styles.questionResultList}>
          {resultingFacts.map((fact, factIndex) => {
            const factId = String(valueOf(fact, "fact_id", `${questionId}-fact-${factIndex}`));
            const factText = valueOf(fact, "text", "");
            const factLens = valueOf(fact, "lens", "");
            return (
              <li key={factId} className={styles.questionResultRow}>
                <span className={styles.questionResultMarker}>Learned</span>
                <span className={styles.questionResultText}>{factText}</span>
                {factLens ? <span className={styles.questionResultLens}>{factLens}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : item.status === "answered" ? (
        <p className={styles.runtimeTraceLead}>Answer recorded; no promoted Fact is linked yet.</p>
      ) : null}
      {canAnswer || canDismiss ? (
        <div className={styles.questionQuestionActions}>
          {item.status === "ready" ? (
            <ActionButton variant="ghost" disabled={Boolean(action.busy)} onClick={() => void action.run("Bump priority", () => bumpPersonalModelQuestion(questionId))}>
              Surface sooner
            </ActionButton>
          ) : null}
          {canDismiss ? (
            <ActionButton variant="ghost" disabled={Boolean(action.busy)} onClick={() => void action.run("Dismiss question", () => dismissPersonalModelQuestion(questionId))}>
              Dismiss
            </ActionButton>
          ) : null}
          {canAnswer ? (
            <AnswerInPlace
              questionId={questionId}
              draft={answerDrafts[questionId] ?? ""}
              onDraft={(next) => setAnswerDrafts((previous) => ({ ...previous, [questionId]: next }))}
              busy={Boolean(action.busy)}
              onSubmit={(content) =>
                action.run("Answer question", async () => {
                  await answerPersonalModelQuestion(questionId, content);
                  setAnswerDrafts((previous) => {
                    const next = { ...previous };
                    delete next[questionId];
                    return next;
                  });
                })
              }
            />
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function AnswerInPlace({
  questionId,
  draft,
  onDraft,
  busy,
  onSubmit,
}: {
  questionId: string;
  draft: string;
  onDraft: (next: string) => void;
  busy: boolean;
  onSubmit: (content: string) => void;
}): React.JSX.Element {
  const trimmed = draft.trim();
  return (
    <form
      className={styles.questionAnswerForm}
      onSubmit={(event) => {
        event.preventDefault();
        if (!trimmed) {
          return;
        }
        onSubmit(trimmed);
      }}
    >
      <input
        aria-label={`Answer question ${questionId}`}
        placeholder="Answer in your own words…"
        value={draft}
        onChange={(event) => onDraft(event.target.value)}
        disabled={busy}
      />
      <ActionButton type="submit" disabled={busy || !trimmed}>
        Answer
      </ActionButton>
    </form>
  );
}

type QuestionsSnapshot = {
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
