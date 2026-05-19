import { desktopApiBaseUrl } from "./desktopBridge";
import type {
  DashboardRow,
  DashboardSection,
  InternalDashboardSnapshot,
  SourceImportStatus,
} from "../types/dashboard";

const DEFAULT_DASHBOARD_LIVE_TIMEOUT_MS = 30_000;
const DEFAULT_DASHBOARD_TURN_TIMEOUT_MS = 5 * 60_000;
const MIN_DASHBOARD_LIVE_TIMEOUT_MS = 5_000;

function parseDashboardLiveTimeoutMs(rawValue: unknown): number {
  if (typeof rawValue !== "string" || rawValue.trim() === "") {
    return DEFAULT_DASHBOARD_LIVE_TIMEOUT_MS;
  }
  const parsed = Number.parseInt(rawValue, 10);
  if (!Number.isFinite(parsed) || parsed < MIN_DASHBOARD_LIVE_TIMEOUT_MS) {
    return DEFAULT_DASHBOARD_LIVE_TIMEOUT_MS;
  }
  return parsed;
}

export const DASHBOARD_LIVE_TIMEOUT_MS = parseDashboardLiveTimeoutMs(
  import.meta.env.VITE_ELEPHANT_DASHBOARD_LIVE_TIMEOUT_MS,
);

const dashboardApiBase = String(import.meta.env.VITE_ELEPHANT_API_BASE_URL ?? "").trim().replace(/\/$/, "");

type DashboardPayload = {
  dashboard?: InternalDashboardSnapshot;
};

type OperatorApiRequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

type JsonPayload = Record<string, unknown>;

function dashboardEggId(row: DashboardRow): string {
  return String(row.elephant_id ?? row.eggId ?? "").trim();
}

function isHiddenLearningEgg(row: DashboardRow): boolean {
  const eggId = dashboardEggId(row);
  return eggId.startsWith("learn-live");
}

function hideSyntheticLearningHerd(dashboard: InternalDashboardSnapshot): InternalDashboardSnapshot {
  return {
    ...dashboard,
    herd: dashboard.herd.filter((row) => !isHiddenLearningEgg(row)),
    states: dashboard.states.filter((row) => !isHiddenLearningEgg(row)),
  };
}

export type CustomMcpToolPayload = {
  serverId: string;
  toolName?: string;
  serverLabel?: string;
  transport?: string;
  command?: string;
  args?: string[];
  url?: string;
  env?: Record<string, string>;
  headers?: Record<string, string>;
  displayName?: string;
  description?: string;
  family?: string;
  defaultEnabled?: boolean;
  riskClass?: string;
  approvalClass?: string;
  readsState?: boolean;
  writesState?: boolean;
  touchesNetwork?: boolean;
  touchesSecrets?: boolean;
  schema?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

type CustomMcpToolIdentityPayload = {
  serverId: string;
  toolName: string;
};

export type CustomMcpDiscoveryPayload = Pick<
  CustomMcpToolPayload,
  "serverId" | "serverLabel" | "transport" | "command" | "args" | "url" | "env" | "headers"
>;

export type CustomMcpDiscoveryResponse = {
  status?: string;
  serverId?: string;
  serverLabel?: string;
  transport?: string;
  durationMs?: number;
  toolCount?: number;
  tools?: readonly JsonPayload[];
  error?: string;
  stdout?: string;
  stderr?: string;
  returnCode?: number;
};

export type CustomMcpServerSyncPayload = CustomMcpDiscoveryPayload & {
  tools: readonly JsonPayload[];
};

export type CustomMcpServerIdentityPayload = {
  serverId: string;
};

export type ProviderCatalogResponse = {
  active_provider?: JsonPayload;
  providers?: readonly JsonPayload[];
};

export type ProviderDoctorResponse = {
  status?: string;
  active_provider?: JsonPayload;
  checks?: readonly JsonPayload[];
  probe_summary?: string;
  error?: string;
};

export type ProviderSetupResponse = {
  active_provider?: JsonPayload;
  guide?: JsonPayload;
};

export type ProviderTestResponse = {
  active_provider?: JsonPayload;
  status?: string;
  result?: JsonPayload;
  error?: string;
};

export type ProviderModelsResponse = {
  active_provider?: JsonPayload;
  providerId?: string;
  baseUrl?: string | null;
  models?: readonly JsonPayload[];
  error?: string;
};

export type EmbeddingProviderPayload = {
  source: "local" | "openai-compatible";
  baseUrl?: string;
  modelId?: string;
  dimensions?: number;
  apiKey?: string;
  secretEnvVar?: string;
};

class DashboardEndpointError extends Error {
  endpoint: string;
  status?: number;

  constructor(endpoint: string, message: string, status?: number) {
    super(message);
    this.name = "DashboardEndpointError";
    this.endpoint = endpoint;
    this.status = status;
  }
}

// Retry schedule for transient failures on the local Operator API. The dashboard
// is frequently hit immediately after launching the API process, when the
// database schema / provider bootstrap may still be completing. A short
// exponential backoff hides that race from users without masking real outages.
const DASHBOARD_RETRY_DELAYS_MS: readonly number[] = [500, 1000, 2000, 4000];

function isTransientDashboardError(error: unknown): boolean {
  if (error instanceof DashboardLoadAbortedError) {
    return false;
  }
  if (error instanceof DashboardEndpointError) {
    // No status means the request never reached the server (network / DNS /
    // connection refused) — treat as transient during startup.
    if (error.status === undefined) {
      return true;
    }
    // 5xx is transient; 408/425/429 deserve a retry too.
    return error.status >= 500 || error.status === 408 || error.status === 425 || error.status === 429;
  }
  if (error instanceof AggregateError) {
    return error.errors.every((inner) => isTransientDashboardError(inner));
  }
  if (error instanceof Error && error.name === "AggregateError") {
    const aggregate = error as { errors?: unknown[] };
    if (Array.isArray(aggregate.errors)) {
      return aggregate.errors.every((inner) => isTransientDashboardError(inner));
    }
  }
  // Network-level TypeError (fetch failed) also counts as transient.
  return error instanceof TypeError;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DashboardLoadAbortedError());
      return;
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DashboardLoadAbortedError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export class DashboardLoadAbortedError extends Error {
  constructor() {
    super("Dashboard request was cancelled.");
    this.name = "DashboardLoadAbortedError";
  }
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new DashboardLoadAbortedError();
  }
}

async function resolveApiCandidates(route: string): Promise<readonly string[]> {
  const desktopBase = await desktopApiBaseUrl();
  if (typeof window === "undefined") {
    return desktopBase ? [`${desktopBase}${route}`] : dashboardApiBase ? [`${dashboardApiBase}${route}`] : [route];
  }

  const candidates: string[] = [];
  const { hostname, origin, port } = window.location;
  const isLocalHost = hostname === "127.0.0.1" || hostname === "localhost" || hostname === "0.0.0.0";

  if (desktopBase) {
    candidates.push(`${desktopBase}${route}`);
  }
  if (origin.startsWith("http")) {
    candidates.push(`${origin}${route}`);
  }
  if (dashboardApiBase) {
    candidates.push(`${dashboardApiBase}${route}`);
  } else if (isLocalHost && port !== "8000") {
    candidates.push(`http://127.0.0.1:8000${route}`);
  }

  return Array.from(new Set(candidates));
}

function joinEndpointList(endpoints: readonly string[]): string {
  return endpoints.join(" or ");
}

function timeoutMessage(timeoutMs: number, endpoints: readonly string[]): string {
  const seconds = Math.round(timeoutMs / 1000);
  return `Dashboard inspection timed out after ${seconds}s while checking ${joinEndpointList(endpoints)}. Retry after the local API recovers.`;
}

function networkFailureMessage(endpoints: readonly string[], reasons: readonly string[] = []): string {
  const reasonSuffix = reasons.length ? ` Last failure: ${reasons[0]}.` : "";
  return `Dashboard inspection unavailable (${joinEndpointList(endpoints)}). Start the local API and retry.${reasonSuffix}`;
}

async function requestJsonFromEndpoint<T>(
  endpoint: string,
  init: RequestInit,
  signal: AbortSignal,
): Promise<T> {
  try {
    const response = await fetch(endpoint, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
      ...init,
      signal,
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new DashboardEndpointError(
        endpoint,
        detail || `Operator API request failed with status ${response.status}.`,
        response.status,
      );
    }

    return (await response.json()) as T;
  } catch (error) {
    if (signal.aborted) {
      throw new DashboardLoadAbortedError();
    }
    if (error instanceof DashboardEndpointError) {
      throw error;
    }
    if (error instanceof TypeError) {
      throw new DashboardEndpointError(endpoint, `Could not reach ${endpoint}.`);
    }
    throw new DashboardEndpointError(
      endpoint,
      error instanceof Error ? error.message : "Operator API request failed.",
    );
  }
}

async function requestOperatorApiOnce<T>(
  route: string,
  init: RequestInit = {},
  options: OperatorApiRequestOptions = {},
): Promise<T> {
  throwIfAborted(options.signal);

  const endpoints = await resolveApiCandidates(route);
  const requestController = new AbortController();
  let timedOut = false;
  let completed = false;
  const handleAbort = () => {
    requestController.abort();
  };
  const timeoutMs = options.timeoutMs ?? DASHBOARD_LIVE_TIMEOUT_MS;
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    requestController.abort();
  }, timeoutMs);

  options.signal?.addEventListener("abort", handleAbort, { once: true });

  try {
    const payload = await Promise.any(
      endpoints.map((endpoint) => requestJsonFromEndpoint<T>(endpoint, init, requestController.signal)),
    );
    completed = true;
    return payload;
  } catch (error) {
    if (options.signal?.aborted) {
      throw new DashboardLoadAbortedError();
    }
    if (timedOut) {
      throw new Error(timeoutMessage(timeoutMs, endpoints));
    }
    throw error;
  } finally {
    if (completed) {
      requestController.abort();
    }
    window.clearTimeout(timeoutId);
    options.signal?.removeEventListener("abort", handleAbort);
  }
}

async function requestOperatorApi<T>(
  route: string,
  init: RequestInit = {},
  options: OperatorApiRequestOptions = {},
): Promise<T> {
  const endpoints = await resolveApiCandidates(route);
  let lastError: unknown;
  // Initial attempt + configured retry delays. The Operator API typically
  // recovers within a few seconds of launch; retrying transparently keeps the
  // dashboard from flashing a red banner during that steady-up window.
  for (let attempt = 0; attempt <= DASHBOARD_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      return await requestOperatorApiOnce<T>(route, init, options);
    } catch (error) {
      lastError = error;
      if (error instanceof DashboardLoadAbortedError) {
        throw error;
      }
      if (options.signal?.aborted) {
        throw new DashboardLoadAbortedError();
      }
      if (attempt === DASHBOARD_RETRY_DELAYS_MS.length || !isTransientDashboardError(error)) {
        break;
      }
      await sleep(DASHBOARD_RETRY_DELAYS_MS[attempt], options.signal);
    }
  }
  if (lastError instanceof AggregateError) {
    const reasons = lastError.errors.flatMap((item) => {
      if (item instanceof DashboardEndpointError) {
        return [`${item.endpoint}: ${item.message}`];
      }
      if (item instanceof Error) {
        return [item.message];
      }
      return [];
    });
    throw new Error(networkFailureMessage(endpoints, reasons));
  }
  if (lastError instanceof DashboardEndpointError) {
    throw new Error(networkFailureMessage(endpoints, [`${lastError.endpoint}: ${lastError.message}`]));
  }
  throw lastError instanceof Error ? lastError : new Error("Operator API request failed.");
}

export function loadProviderCatalog(
  options: OperatorApiRequestOptions = {},
): Promise<ProviderCatalogResponse> {
  return requestOperatorApi<ProviderCatalogResponse>("/v1/providers", {}, options);
}

export async function loadDashboardSnapshot(
  section: DashboardSection,
  options: OperatorApiRequestOptions = {},
): Promise<InternalDashboardSnapshot> {
  const payload = await requestOperatorApi<DashboardPayload>(
    `/v1/internal/dashboard/${encodeURIComponent(section)}`,
    {},
    options,
  );
  if (!payload.dashboard) {
    throw new Error(`Internal dashboard ${section} response did not include a dashboard payload.`);
  }
  return hideSyntheticLearningHerd(payload.dashboard);
}

export function createDashboardSession(
  payload: {
    profile_id: string;
    display_name: string;
    mode: string;
    elephant_id?: string;
    episode_id?: string;
  },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/episodes",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export type DashboardEggPayload = {
  elephant_id?: string;
  elephant_name?: string;
  display_name?: string;
  personal_model_id?: string;
  profile_id?: string;
  mode?: string;
  personality_preset?: string;
  initiative?: string;
  elephant_identity_text?: string;
};

export function createDashboardEgg(
  payload: DashboardEggPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/herd",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function importSourcePaths(
  payload: { paths: string[]; elephant_id?: string; mode: "profile_builder" | "manual" },
  options: OperatorApiRequestOptions = {},
): Promise<SourceImportStatus> {
  return requestOperatorApi<SourceImportStatus>(
    "/v1/sources/import",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { ...options, timeoutMs: options.timeoutMs ?? DEFAULT_DASHBOARD_TURN_TIMEOUT_MS },
  );
}

export function loadSourceImportStatus(
  importId: string,
  options: OperatorApiRequestOptions = {},
): Promise<SourceImportStatus> {
  return requestOperatorApi<SourceImportStatus>(
    `/v1/sources/imports/${encodeURIComponent(importId)}`,
    {},
    options,
  );
}

export function updateDashboardEgg(
  eggId: string,
  payload: DashboardEggPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/herd/${encodeURIComponent(eggId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function deleteDashboardEgg(
  eggId: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/herd/${encodeURIComponent(eggId)}`,
    { method: "DELETE" },
    options,
  );
}

export function setPersonalModelQuestionIntensity(
  config: { idle_threshold_minutes?: number; daily_max?: number; quiet_hours?: [number, number]; enabled?: boolean },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/personal-model/questions",
    {
      method: "PATCH",
      body: JSON.stringify(config),
    },
    options,
  );
}

export function bumpPersonalModelQuestion(
  questionId: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/questions/${encodeURIComponent(questionId)}/bump`,
    { method: "POST", body: "{}" },
    options,
  );
}

export function dismissPersonalModelQuestion(
  questionId: string,
  reason?: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/questions/${encodeURIComponent(questionId)}/dismiss`,
    { method: "POST", body: JSON.stringify({ reason: reason || "user_opted_out" }) },
    options,
  );
}

export function answerPersonalModelQuestion(
  questionId: string,
  content: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/questions/${encodeURIComponent(questionId)}/answer`,
    { method: "POST", body: JSON.stringify({ content }) },
    options,
  );
}

export function correctPersonalModelClaim(
  claimRef: string,
  payload: { text: string; lens?: string; topic?: string; reason?: string; personal_model_id?: string },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/correct`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function forgetPersonalModelClaim(
  claimRef: string,
  payload: { lens?: string; topic?: string; reason?: string; personal_model_id?: string } = {},
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/forget`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function disputePersonalModelClaim(
  claimRef: string,
  payload: { lens?: string; topic?: string; reason?: string; personal_model_id?: string } = {},
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/dispute`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function restorePersonalModelClaim(
  claimRef: string,
  payload: { lens?: string; topic?: string; reason?: string; personal_model_id?: string } = {},
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/restore`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function deletePersonalModelClaim(
  claimRef: string,
  payload: { lens?: string; topic?: string; reason?: string; personal_model_id?: string } = {},
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/delete`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function protectPersonalModelClaim(
  claimRef: string,
  payload: { reason?: string; personal_model_id?: string } = {},
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/protect`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function unprotectPersonalModelClaim(
  claimRef: string,
  payload: { reason?: string; personal_model_id?: string } = {},
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/personal-model/claims/${encodeURIComponent(claimRef)}/unprotect`,
    { method: "POST", body: JSON.stringify(payload) },
    options,
  );
}

export function sendDashboardTurn(
  episodeId: string,
  payload: {
    prompt: string;
    tool_name?: string;
    tool_arguments?: Record<string, unknown>;
  },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/episodes/${encodeURIComponent(episodeId)}/loops`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { ...options, timeoutMs: options.timeoutMs ?? DEFAULT_DASHBOARD_TURN_TIMEOUT_MS },
  );
}

export function saveOperatorSettings(
  profileManifest: Record<string, unknown>,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/settings",
    {
      method: "PATCH",
      body: JSON.stringify({ profileManifest }),
    },
    options,
  );
}

export function saveOperatorGlobalConfig(
  payload: { config?: Record<string, unknown>; yamlText?: string },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/config",
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function setConsoleItemEnabled(
  kind: "skills" | "tools",
  itemId: string,
  enabled: boolean,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/${kind}/${encodeURIComponent(itemId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    },
    options,
  );
}

export function syncCustomMcpServer(
  payload: CustomMcpServerSyncPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/mcp/servers",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function deleteCustomMcpServer(
  payload: CustomMcpServerIdentityPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/mcp/servers",
    {
      method: "DELETE",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function createCustomMcpTool(
  payload: CustomMcpToolPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/mcp/tools",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function updateCustomMcpTool(
  payload: CustomMcpToolPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/mcp/tools",
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function deleteCustomMcpTool(
  payload: Pick<CustomMcpToolPayload, "serverId" | "toolName">,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/mcp/tools",
    {
      method: "DELETE",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function setCustomMcpToolEnabled(
  payload: CustomMcpToolIdentityPayload & { enabled: boolean },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/mcp/tools/enabled",
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function discoverCustomMcpTools(
  payload: CustomMcpDiscoveryPayload,
  options: OperatorApiRequestOptions = {},
): Promise<CustomMcpDiscoveryResponse> {
  return requestOperatorApi<CustomMcpDiscoveryResponse>(
    "/v1/operator/mcp/discover",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function createCronJob(
  payload: {
    name: string;
    schedule: string;
    job_kind: string;
    prompt?: string;
    message?: string;
    query?: string;
    skills?: string[];
    profile_id?: string;
    elephant_id?: string;
    timezone_name?: string;
    payload?: Record<string, string | number | boolean | null>;
  },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/cron",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function setCronJobStatus(
  jobId: string,
  action: "pause" | "resume",
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/cron/${encodeURIComponent(jobId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ action }),
    },
    options,
  );
}

export function deleteCronJob(
  jobId: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/cron/${encodeURIComponent(jobId)}`,
    { method: "DELETE" },
    options,
  );
}

/**
 * Manually fire a cron job once, right now, without waiting for the next tick.
 *
 * Backs the "Verify" button on the cron panel — useful when the operator wants to
 * prove the full IM delivery pipeline (scheduler → outbound queue → gateway →
 * WeChat/Feishu/Discord) without sitting through the next scheduled tick.
 *
 * Response payload shape:
 * ```
 * {
 *   cron: {
 *     job:     CronJobRecord,
 *     run: {
 *       outcome:        "success" | "failed" | "vanished" | ...,
 *       summary:        string,   // may be "[SILENT]" when the agent chose not to speak
 *       delivered:      boolean,  // whether the IM adapter accepted the outbound row
 *       delivery_error: string | null,
 *       recorded_at:    string,
 *     }
 *   }
 * }
 * ```
 */
export function runCronJob(
  jobId: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/operator/cron/${encodeURIComponent(jobId)}/run`,
    { method: "POST", body: "{}" },
    options,
  );
}

export function setDefaultProvider(
  providerProfile: Record<string, unknown>,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/providers/default",
    {
      method: "POST",
      body: JSON.stringify({ provider_profile: providerProfile }),
    },
    options,
  );
}

export function saveProviderKey(
  referenceId: string,
  value: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/providers/keys/${encodeURIComponent(referenceId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ value }),
    },
    options,
  );
}

export function deleteProviderKey(
  referenceId: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/providers/keys/${encodeURIComponent(referenceId)}`,
    { method: "DELETE" },
    options,
  );
}

export type GatewayServiceConfigPayload = {
  accountId?: string;
  transport?: string;
  eventPath?: string;
  enabled?: boolean;
  accountEnabled?: boolean;
  allowGroupChats?: boolean;
  allowGuildIds?: string[];
  allowChannelIds?: string[];
  secrets?: Record<string, string>;
};

export function runGatewayAction(
  payload: {
    service: string;
    action: string;
    force?: boolean;
    accountId?: string;
    transport?: string;
    runtimeTarget?: string;
    sessionId?: string;
    botType?: string;
    config?: GatewayServiceConfigPayload;
  },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/operator/gateway",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function loadProviderDoctor(
  options: OperatorApiRequestOptions = {},
): Promise<ProviderDoctorResponse> {
  return requestOperatorApi<ProviderDoctorResponse>("/v1/providers/doctor", {}, options);
}

export function loadProviderSetup(
  providerId: string,
  options: OperatorApiRequestOptions = {},
): Promise<ProviderSetupResponse> {
  return requestOperatorApi<ProviderSetupResponse>(
    `/v1/providers/setup/${encodeURIComponent(providerId)}`,
    {},
    options,
  );
}

export function loadProviderModels(
  payload: { providerId: string; baseUrl?: string; apiKey?: string },
  options: OperatorApiRequestOptions = {},
): Promise<ProviderModelsResponse> {
  return requestOperatorApi<ProviderModelsResponse>(
    "/v1/providers/models",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function runProviderTest(
  prompt: string,
  options: OperatorApiRequestOptions = {},
): Promise<ProviderTestResponse> {
  return requestOperatorApi<ProviderTestResponse>(
    "/v1/providers/test",
    {
      method: "POST",
      body: JSON.stringify({ prompt }),
    },
    options,
  );
}

export function setEmbeddingProvider(
  payload: EmbeddingProviderPayload,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/providers/embeddings",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    options,
  );
}

export function triggerDiaryWrite(
  date: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/internal/diary/write",
    {
      method: "POST",
      body: JSON.stringify({ date }),
    },
    options,
  );
}

export function deleteDiaryEntry(
  entryDate: string,
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    `/v1/internal/diary/${encodeURIComponent(entryDate)}`,
    {
      method: "DELETE",
    },
    options,
  );
}

export function triggerReflectJob(
  config: { trigger?: string; features?: string },
  options: OperatorApiRequestOptions = {},
): Promise<unknown> {
  return requestOperatorApi<unknown>(
    "/v1/internal/reflect/run",
    {
      method: "POST",
      body: JSON.stringify(config),
    },
    options,
  );
}
