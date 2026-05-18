import React from "react";

import { EmptyPanel, StatusBadge } from "../../components/primitives/DashboardPrimitives";
import { useDashboardSnapshot } from "../../hooks/useOperatorConsole";
import elephantLogo from "../../assets/brand/elephant-logo.png";
import { cx } from "../../lib/classNames";
import { compactText, formatTimestamp } from "../../lib/dashboardFormatting";
import { createDashboardSession, sendDashboardTurn } from "../../lib/dashboardApi";
import type { DashboardJson, DashboardRow, HealthTone, InternalDashboardSnapshot } from "../../types/dashboard";
import { RoutePageHeader } from "../shared/RoutePageHeader";
import styles from "./ChatPage.module.css";

const DRAFT_SESSION_ID = "draft-session";
const HISTORY_PAGE_SIZE = 8;
const STREAM_REFRESH_INTERVAL_MS = 700;
const VISIBLE_EVENT_TYPES = new Set(["user_query", "llm_answer", "final_response", "tool_call", "tool_execute"]);

type PendingTurn = {
  sessionId: string;
  prompt: string;
};

type HistoryItem = {
  id: string;
  rows: DashboardRow[];
  title: string;
  preview: string;
  eggId: string;
  eggName: string;
  status: string;
  startedAt: string;
  loopCount: string;
};

type EggOption = {
  eggId: string;
  eggName: string;
  stateId: string;
  personalModelId: string;
  status: string;
  current: boolean;
  summary: string;
};

type ComposeProfile = {
  profileId: string;
  displayName: string;
  mode: string;
  eggId?: string;
  eggName: string;
};

type ClarifyRequest = {
  stepId: string;
  question: string;
  mode: string;
  choices: string[];
  toolArguments: Record<string, unknown>;
};

type EventVisualKind = "user" | "assistant" | "tool";

function asRows(value: DashboardJson | undefined): DashboardRow[] {
  return Array.isArray(value)
    ? value.filter((item): item is DashboardRow => item !== null && typeof item === "object" && !Array.isArray(item))
    : [];
}

function valueOf(row: DashboardRow, key: string, fallback = ""): string {
  const item = row[key];
  if (item === null || item === undefined || item === "") {
    return fallback;
  }
  if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
    return String(item);
  }
  return JSON.stringify(item);
}

function jsonObject(value: DashboardJson | undefined): DashboardRow {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
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

function formatWhen(value: DashboardJson | undefined): string {
  if (typeof value !== "string" || !value.trim()) {
    return "n/a";
  }
  return Number.isNaN(new Date(value).getTime()) ? value : formatTimestamp(value);
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

function conversationContent(row: DashboardRow): string {
  return valueOf(row, "content", valueOf(row, "summary", ""));
}

function normalizedConversationContent(row: DashboardRow): string {
  return conversationContent(row).replace(/\s+/g, " ").trim();
}

function conversationRows(episode: DashboardRow): DashboardRow[] {
  const visibleRows = asRows(episode.timeline).filter((step) => VISIBLE_EVENT_TYPES.has(valueOf(step, "event_type", "")));
  if (!visibleRows.some((step) => valueOf(step, "event_type", "") === "user_query")) {
    return [];
  }

  let latestAnswer = "";
  return visibleRows.filter((step) => {
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

function detailOf(step: DashboardRow): DashboardRow {
  return jsonObject(step.detail);
}

function usageOf(step: DashboardRow): DashboardRow {
  return jsonObject(step.usage);
}

function numberOf(row: DashboardRow, key: string): number {
  const value = row[key];
  return typeof value === "number" ? value : Number.parseInt(String(value ?? "0"), 10) || 0;
}

function episodeEggId(episode: DashboardRow, dashboard: InternalDashboardSnapshot | null): string {
  const stateId = valueOf(episode, "state_id", "");
  const state = dashboard?.herd.find((elephant) => valueOf(elephant, "state_id", "") === stateId)
    ?? dashboard?.states.find((candidate) => valueOf(candidate, "state_id", "") === stateId);
  return valueOf(state ?? {}, "elephant_id", valueOf(episode, "elephant_id", stateId || "current"));
}

function eggNameForEpisode(episode: DashboardRow, dashboard: InternalDashboardSnapshot | null): string {
  const stateId = valueOf(episode, "state_id", "");
  const state = dashboard?.herd.find((elephant) => valueOf(elephant, "state_id", "") === stateId)
    ?? dashboard?.states.find((candidate) => valueOf(candidate, "state_id", "") === stateId);
  return valueOf(state ?? {}, "elephant_name", valueOf(episode, "elephant_id", "Elephant Agent"));
}

function eventVisualKind(eventType: string): EventVisualKind {
  if (eventType === "user_query") {
    return "user";
  }
  if (["tool_call", "tool_execute"].includes(eventType)) {
    return "tool";
  }
  return "assistant";
}

function eventSpeaker(eventType: string): string {
  if (eventType === "user_query") {
    return "You";
  }
  if (["tool_call", "tool_execute"].includes(eventType)) {
    return "Elephant Agent tool";
  }
  return "Elephant Agent";
}

function eventLabel(eventType: string): string {
  switch (eventType) {
    case "user_query":
      return "You";
    case "llm_answer":
    case "final_response":
      return "Elephant Agent";
    case "tool_call":
      return "Tool call";
    case "tool_execute":
      return "Tool result";
    default:
      return eventType || "Message";
  }
}

function toolLabel(step: DashboardRow): string {
  return compactText(readString(detailOf(step), ["tool_name"], "tool"), 42);
}

function stepBadges(step: DashboardRow): string[] {
  const eventType = valueOf(step, "event_type", valueOf(step, "action", "step"));
  const detail = detailOf(step);
  const usage = usageOf(step);
  const status = valueOf(step, "status", "");
  const badges = [eventLabel(eventType)];
  if (status) {
    badges.push(status);
  }
  if (eventType === "tool_call") {
    badges.push(toolLabel(step));
  }
  if (eventType === "tool_execute") {
    badges.push(toolLabel(step));
    badges.push(readString(detail, ["execution_id"], "execution") || "execution");
  }
  if (numberOf(usage, "total_tokens") > 0 && !eventType.startsWith("tool_")) {
    badges.push(`${valueOf(usage, "prompt_tokens", "0")} in / ${valueOf(usage, "completion_tokens", "0")} out`);
  }
  return badges.map((badge) => compactText(badge, 34));
}

function previewConversationTitle(episode: DashboardRow): string {
  const rows = conversationRows(episode);
  const firstUser = rows.find((row) => valueOf(row, "event_type", "") === "user_query");
  const title = conversationContent(firstUser ?? episode) || valueOf(episode, "exit_summary", "");
  return compactText(title || valueOf(episode, "episode_id", "Conversation"), 52);
}

function previewConversationBody(episode: DashboardRow): string {
  const rows = conversationRows(episode);
  const previewRow = [...rows].reverse().find((row) => {
    const eventType = valueOf(row, "event_type", "");
    return eventType === "final_response" || eventType === "llm_answer" || eventType === "user_query";
  });
  return compactText(
    conversationContent(previewRow ?? episode) || valueOf(episode, "exit_summary", "No preview yet."),
    92,
  );
}

function buildHistoryItems(dashboard: InternalDashboardSnapshot | null): HistoryItem[] {
  if (!dashboard) {
    return [];
  }
  return dashboard.runtime.episode_traces.flatMap((episode) => {
    const rows = conversationRows(episode);
    if (!rows.length) {
      return [];
    }
    return [{
      id: valueOf(episode, "episode_id", "episode"),
      rows,
      title: previewConversationTitle(episode),
      preview: previewConversationBody(episode),
      eggId: episodeEggId(episode, dashboard),
      eggName: eggNameForEpisode(episode, dashboard),
      status: valueOf(episode, "status", "active"),
      startedAt: formatWhen(episode.started_at),
      loopCount: valueOf(episode, "loop_count", String(asRows(episode.loops).length)),
    }];
  });
}

function buildEggOptions(dashboard: InternalDashboardSnapshot | null): EggOption[] {
  if (!dashboard) {
    return [];
  }
  const byKey = new Map<string, EggOption>();
  for (const row of [...dashboard.herd, ...dashboard.states]) {
    const eggId = valueOf(row, "elephant_id", valueOf(row, "state_id", ""));
    const stateId = valueOf(row, "state_id", eggId);
    const key = eggId || stateId;
    if (!key) {
      continue;
    }
    if (byKey.has(key)) {
      const existing = byKey.get(key);
      if (existing && !existing.current && row.current === true) {
        byKey.set(key, {
          ...existing,
          current: true,
          status: valueOf(row, "status", existing.status),
          summary: valueOf(row, "summary", existing.summary),
        });
      }
      continue;
    }
    byKey.set(key, {
      eggId: eggId || stateId,
      eggName: valueOf(row, "elephant_name", eggId || stateId || "Unnamed elephant"),
      stateId,
      personalModelId: valueOf(row, "personal_model_id", ""),
      status: valueOf(row, "status", "active"),
      current: row.current === true,
      summary: valueOf(row, "summary", ""),
    });
  }
  return [...byKey.values()].sort((left, right) => {
    if (left.current !== right.current) {
      return left.current ? -1 : 1;
    }
    return left.eggName.localeCompare(right.eggName);
  });
}

function renderInlineMarkdown(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\))/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={`${token}-${match.index}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(<strong key={`${token}-${match.index}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*") || token.startsWith("_")) {
      nodes.push(<em key={`${token}-${match.index}`}>{token.slice(1, -1)}</em>);
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

function splitMarkdownTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isMarkdownTableDivider(line: string): boolean {
  const cells = splitMarkdownTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function looksLikeMarkdownTableRow(line: string): boolean {
  return line.trim().startsWith("|") && line.trim().endsWith("|") && splitMarkdownTableRow(line).length > 1;
}

function MarkdownText({ text }: { text: string }): React.JSX.Element {
  const lines = text.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let unorderedItems: string[] = [];
  let orderedItems: string[] = [];
  let codeLines: string[] = [];
  let inCode = false;
  let codeLanguage = "";

  const flushUnorderedList = () => {
    if (!unorderedItems.length) {
      return;
    }
    const items = unorderedItems;
    unorderedItems = [];
    blocks.push(
      <ul key={`ul-${blocks.length}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{renderListItemMarkdown(item)}</li>
        ))}
      </ul>,
    );
  };

  const flushOrderedList = () => {
    if (!orderedItems.length) {
      return;
    }
    const items = orderedItems;
    orderedItems = [];
    blocks.push(
      <ol key={`ol-${blocks.length}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{renderListItemMarkdown(item)}</li>
        ))}
      </ol>,
    );
  };

  const flushLists = () => {
    flushUnorderedList();
    flushOrderedList();
  };

  const flushCode = () => {
    if (!codeLines.length) {
      return;
    }
    const code = codeLines.join("\n");
    codeLines = [];
    blocks.push(
      <pre key={`code-${blocks.length}`} data-language={codeLanguage || undefined}>
        {code}
      </pre>,
    );
    codeLanguage = "";
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      if (inCode) {
        inCode = false;
        flushCode();
      } else {
        flushLists();
        codeLanguage = trimmed.slice(3).trim();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    if (!trimmed) {
      flushLists();
      continue;
    }
    if (looksLikeMarkdownTableRow(line) && isMarkdownTableDivider(lines[index + 1] ?? "")) {
      flushLists();
      const headers = splitMarkdownTableRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && looksLikeMarkdownTableRow(lines[index])) {
        rows.push(splitMarkdownTableRow(lines[index]));
        index += 1;
      }
      index -= 1;
      blocks.push(
        <div key={`table-wrap-${blocks.length}`} className={styles.markdownTableWrap}>
          <table>
            <thead>
              <tr>
                {headers.map((header, cellIndex) => (
                  <th key={`${header}-${cellIndex}`}>{renderInlineMarkdown(header)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {headers.map((_header, cellIndex) => (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>{renderInlineMarkdown(row[cellIndex] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.+)$/.exec(line);
    if (bullet) {
      flushOrderedList();
      unorderedItems.push(bullet[1]);
      continue;
    }
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (ordered) {
      flushUnorderedList();
      orderedItems.push(ordered[1]);
      continue;
    }
    flushLists();
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const headingContent = renderInlineMarkdown(heading[2]);
      const headingKey = `heading-${blocks.length}`;
      if (heading[1].length === 1) {
        blocks.push(<h1 key={headingKey}>{headingContent}</h1>);
      } else if (heading[1].length === 2) {
        blocks.push(<h2 key={headingKey}>{headingContent}</h2>);
      } else if (heading[1].length === 3) {
        blocks.push(<h3 key={headingKey}>{headingContent}</h3>);
      } else if (heading[1].length === 4) {
        blocks.push(<h4 key={headingKey}>{headingContent}</h4>);
      } else if (heading[1].length === 5) {
        blocks.push(<h5 key={headingKey}>{headingContent}</h5>);
      } else {
        blocks.push(<h6 key={headingKey}>{headingContent}</h6>);
      }
      continue;
    }
    const quote = /^>\s?(.+)$/.exec(line);
    if (quote) {
      blocks.push(
        <blockquote key={`quote-${blocks.length}`}>
          <p>{renderInlineMarkdown(quote[1])}</p>
        </blockquote>,
      );
      continue;
    }
    if (/^(-{3,}|_{3,}|\*{3,})$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${blocks.length}`} />);
      continue;
    }
    blocks.push(<p key={`p-${blocks.length}`}>{renderInlineMarkdown(line)}</p>);
  }
  flushLists();
  flushCode();

  return <div className={styles.markdownText}>{blocks.length ? blocks : <p>No content persisted.</p>}</div>;
}

function ToolDisclosure({ label, text, fallback }: { label: string; text: string; fallback: string }): React.JSX.Element {
  return (
    <details className={styles.disclosure}>
      <summary className={styles.disclosureSummary}>
        <span>{label}</span>
        <strong>{compactText(text || fallback, 180)}</strong>
      </summary>
      <div className={styles.disclosureBody}>
        <MarkdownText text={text || fallback} />
      </div>
    </details>
  );
}

function ToolField({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className={styles.toolField}>
      <span>{label}</span>
      {children}
    </div>
  );
}

function ToolCallPanel({
  eventType,
  row,
  content,
}: {
  eventType: string;
  row: DashboardRow;
  content: string;
}): React.JSX.Element {
  const detail = detailOf(row);
  const toolName = readString(detail, ["tool_name"], "tool");
  const toolArguments = readString(detail, ["tool_arguments"], "");
  const toolResult = readString(detail, ["tool_result"], "") || (eventType === "tool_execute" ? content : "");
  const executionId = readString(detail, ["execution_id"], "");
  const status = valueOf(row, "status", "");
  const outcome = valueOf(row, "outcome", "");

  return (
    <section className={styles.toolCallPanel}>
      <header className={styles.toolCallPanelHeader}>
        <span>{eventType === "tool_execute" ? "Executed" : "Call"}</span>
        {eventType === "tool_execute" ? <strong className={styles.toolSourceName}>{toolName}</strong> : <code>{toolName}</code>}
        {status ? <small>{status}</small> : null}
        {outcome && outcome !== status ? <small>{outcome}</small> : null}
      </header>
      {toolArguments ? (
        <ToolField label="Arguments">
          <pre>{toolArguments}</pre>
        </ToolField>
      ) : (
        <ToolField label="Arguments">
          <code>No arguments persisted.</code>
        </ToolField>
      )}
      {eventType === "tool_execute" ? (
        <ToolField label="Result">
          <MarkdownText text={toolResult || "No tool result persisted."} />
        </ToolField>
      ) : null}
      {executionId ? (
        <ToolField label="Execution">
          <code>{executionId}</code>
        </ToolField>
      ) : null}
    </section>
  );
}

function resolveComposeProfile(dashboard: InternalDashboardSnapshot | null, preferredEggId: string | null): ComposeProfile {
  const eggOptions = buildEggOptions(dashboard);
  const currentEgg = eggOptions.find((elephant) => elephant.eggId === preferredEggId)
    ?? eggOptions.find((elephant) => elephant.current)
    ?? eggOptions[0];
  const eggModelId = currentEgg?.personalModelId ?? "";
  const targetModelId = eggModelId || (dashboard?.overview.current_personal_model_id ?? "");
  const currentModel = dashboard?.personal_models.find(
    (row) => valueOf(row, "personal_model_id", "") === targetModelId,
  ) ?? dashboard?.personal_models[0];

  return {
    profileId:
      eggModelId
      || dashboard?.overview.current_personal_model_id
      || valueOf(currentModel ?? {}, "personal_model_id", "")
      || "profile-dashboard-chat",
    displayName: valueOf(currentModel ?? {}, "display_name", currentEgg?.eggName ?? "Elephant Agent"),
    mode: valueOf(currentModel ?? {}, "mode", "companion") || "companion",
    eggId: currentEgg?.eggId || undefined,
    eggName: currentEgg?.eggName ?? "Current elephant",
  };
}

function makeSessionId(): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
  return `session-dashboard-${Date.now().toString(36)}-${suffix}`;
}

function conversationScrollSignature(rows: DashboardRow[]): string {
  return rows.map((row) => {
    const content = conversationContent(row);
    return [
      valueOf(row, "step_id", valueOf(row, "event_type", "step")),
      valueOf(row, "event_type", ""),
      valueOf(row, "status", ""),
      valueOf(row, "outcome", ""),
      content.length,
      content.slice(-240),
    ].join("::");
  }).join("\n");
}

function lineValue(text: string, key: string): string {
  const match = new RegExp(`^${key}:\\s*(.+)$`, "im").exec(text);
  return match?.[1]?.trim() ?? "";
}

function argumentStringValue(text: string, key: string): string {
  const match = new RegExp(`["']${key}["']\\s*:\\s*["']([^"']+)["']`).exec(text);
  return match?.[1]?.trim() ?? "";
}

function argumentStringChoices(text: string): string[] {
  const match = /["']choices["']\s*:\s*\[([^\]]*)\]/.exec(text);
  if (!match?.[1]) {
    return [];
  }
  return match[1]
    .split(",")
    .map((item) => item.trim().replace(/^['"]|['"]$/g, ""))
    .filter(Boolean);
}

function summaryChoices(text: string): string[] {
  const lines = text.split(/\r?\n/);
  const choices: string[] = [];
  let readingChoices = false;
  for (const line of lines) {
    if (/^choices:\s*$/i.test(line.trim())) {
      readingChoices = true;
      continue;
    }
    if (readingChoices && /^\w[\w-]*:\s*/.test(line.trim())) {
      break;
    }
    if (readingChoices) {
      const choice = /^-\s+(.+)$/.exec(line.trim())?.[1]?.trim();
      if (choice) {
        choices.push(choice);
      }
    }
  }
  return choices;
}

function latestClarifyRequest(rows: DashboardRow[]): ClarifyRequest | null {
  let pending: ClarifyRequest | null = null;
  for (const row of rows) {
    const eventType = valueOf(row, "event_type", valueOf(row, "action", "step"));
    const detail = detailOf(row);
    const toolName = readString(detail, ["tool_name"], "");
    if (eventType !== "tool_execute" || toolName !== "tool.clarify") {
      continue;
    }
    const outcome = valueOf(row, "outcome", valueOf(row, "status", "")).toLowerCase();
    if (outcome !== "needs_input") {
      pending = null;
      continue;
    }
    const content = conversationContent(row);
    const toolArgumentsText = readString(detail, ["tool_arguments"], "");
    const question = lineValue(content, "question") || argumentStringValue(toolArgumentsText, "question");
    const mode = lineValue(content, "mode") || argumentStringValue(toolArgumentsText, "mode") || "open";
    const choices = summaryChoices(content).length ? summaryChoices(content) : argumentStringChoices(toolArgumentsText);
    pending = {
      stepId: valueOf(row, "step_id", valueOf(detail, "execution_id", "clarify")),
      question: question || "Elephant Agent needs clarification before it can continue.",
      mode,
      choices,
      toolArguments: {
        question: question || "Elephant Agent needs clarification before it can continue.",
        mode,
        ...(choices.length ? { choices } : {}),
      },
    };
  }
  return pending;
}

function MessageAvatar({ kind }: { kind: EventVisualKind }): React.JSX.Element {
  if (kind === "user") {
    return (
      <div className={cx(styles.messageAvatar, styles.messageAvatarUser)} aria-hidden="true">
        <span>You</span>
      </div>
    );
  }
  return (
    <div className={cx(styles.messageAvatar, kind === "tool" && styles.messageAvatarTool)} aria-hidden="true">
      <img src={elephantLogo} alt="" />
    </div>
  );
}

function ChatMessage({ row }: { row: DashboardRow }): React.JSX.Element {
  const eventType = valueOf(row, "event_type", valueOf(row, "action", "step"));
  const visualKind = eventVisualKind(eventType);
  const content = conversationContent(row) || "No content persisted.";
  const detail = detailOf(row);
  const toolArguments = readString(detail, ["tool_arguments"], "");
  const headerLabel = visualKind === "tool" ? `${eventLabel(eventType)} · ${toolLabel(row)}` : eventLabel(eventType);

  return (
    <article
      className={cx(
        styles.messageRow,
        visualKind === "user" && styles.messageRowUser,
        visualKind === "assistant" && styles.messageRowAssistant,
        visualKind === "tool" && styles.messageRowTool,
      )}
    >
      {visualKind !== "user" ? <MessageAvatar kind={visualKind} /> : null}
      <div
        className={cx(
          styles.messageBubble,
          visualKind === "user" && styles.messageBubbleUser,
          visualKind === "assistant" && styles.messageBubbleAssistant,
          visualKind === "tool" && styles.messageBubbleTool,
        )}
      >
        <div className={styles.messageBubbleHeader}>
          <div className={styles.messageBubbleHeading}>
            <span>{eventSpeaker(eventType)}</span>
            <strong>{headerLabel}</strong>
          </div>
          <div className={styles.messageBadgeRow}>
            {stepBadges(row).map((badge) => (
              <small key={badge}>{badge}</small>
            ))}
          </div>
        </div>

        {visualKind === "tool" && toolArguments ? (
          <div className={styles.toolArgumentStrip}>
            <span>Arguments</span>
            <code>{compactText(toolArguments, 180)}</code>
          </div>
        ) : null}

        {visualKind === "tool" ? (
          <ToolCallPanel eventType={eventType} row={row} content={content} />
        ) : (
          <MarkdownText text={content} />
        )}

        {eventType === "tool_call" && toolArguments ? (
          <ToolDisclosure label="Exact tool payload" text={toolArguments} fallback="No tool arguments persisted." />
        ) : null}
      </div>
      {visualKind === "user" ? <MessageAvatar kind={visualKind} /> : null}
    </article>
  );
}

function PendingStream({ prompt, showPrompt }: { prompt: string; showPrompt: boolean }): React.JSX.Element {
  return (
    <>
      {showPrompt ? (
        <article className={cx(styles.messageRow, styles.messageRowUser)} data-pending-user>
          <div className={cx(styles.messageBubble, styles.messageBubbleUser, styles.messageBubblePending)}>
            <div className={styles.messageBubbleHeader}>
              <div className={styles.messageBubbleHeading}>
                <span>You</span>
                <strong>Sent</strong>
              </div>
              <div className={styles.messageBadgeRow}>
                <small>queued</small>
              </div>
            </div>
            <MarkdownText text={prompt} />
          </div>
          <MessageAvatar kind="user" />
        </article>
      ) : null}
      <article className={cx(styles.messageRow, styles.messageRowAssistant)}>
        <MessageAvatar kind="assistant" />
        <div className={cx(styles.messageBubble, styles.messageBubbleAssistant, styles.messageBubbleStreaming)}>
          <div className={styles.messageBubbleHeader}>
            <div className={styles.messageBubbleHeading}>
              <span>Elephant Agent</span>
              <strong>Thinking</strong>
            </div>
            <div className={styles.messageBadgeRow}>
              <small>live</small>
              <small>Elephant Agent is working</small>
            </div>
          </div>
          <div className={styles.streamSkeleton} aria-label="Elephant Agent is thinking">
            <span />
            <span />
            <span />
          </div>
        </div>
      </article>
    </>
  );
}

export function ChatPage(): React.JSX.Element {
  const { dashboard, loading, error, refresh } = useDashboardSnapshot("chat");
  const historyItems = React.useMemo(() => buildHistoryItems(dashboard), [dashboard]);
  const eggOptions = React.useMemo(() => buildEggOptions(dashboard), [dashboard]);
  const [selectedSessionId, setSelectedSessionId] = React.useState<string | null>(null);
  const [selectedEggId, setSelectedEggId] = React.useState<string | null>(null);
  const [historyQuery, setHistoryQuery] = React.useState("");
  const [historyCollapsed, setHistoryCollapsed] = React.useState(true);
  const [historyPage, setHistoryPage] = React.useState(0);
  const [composer, setComposer] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [pendingTurn, setPendingTurn] = React.useState<PendingTurn | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const messageViewportRef = React.useRef<HTMLDivElement | null>(null);
  const scrollStateRef = React.useRef({ sessionId: "", signature: "", pendingKey: "" });
  const submitInFlightRef = React.useRef(false);

  const filteredHistory = React.useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    if (!query) {
      return historyItems;
    }
    return historyItems.filter((item) =>
      [item.title, item.preview, item.eggName, item.status, item.startedAt].some((field) => field.toLowerCase().includes(query)),
    );
  }, [historyItems, historyQuery]);

  const totalHistoryPages = Math.max(1, Math.ceil(filteredHistory.length / HISTORY_PAGE_SIZE));
  const currentHistoryPage = Math.min(historyPage, totalHistoryPages - 1);
  const pagedHistory = filteredHistory.slice(
    currentHistoryPage * HISTORY_PAGE_SIZE,
    currentHistoryPage * HISTORY_PAGE_SIZE + HISTORY_PAGE_SIZE,
  );

  React.useEffect(() => {
    setHistoryPage(0);
  }, [historyQuery]);

  React.useEffect(() => {
    if (historyPage > totalHistoryPages - 1) {
      setHistoryPage(totalHistoryPages - 1);
    }
  }, [historyPage, totalHistoryPages]);

  React.useEffect(() => {
    if (!historyItems.length) {
      if (!selectedSessionId) {
        setSelectedSessionId(DRAFT_SESSION_ID);
      }
      return;
    }
    if (!selectedSessionId) {
      setSelectedSessionId(historyItems[0].id);
      return;
    }
    if (selectedSessionId === DRAFT_SESSION_ID || pendingTurn?.sessionId === selectedSessionId) {
      return;
    }
    if (!historyItems.some((item) => item.id === selectedSessionId)) {
      setSelectedSessionId(historyItems[0].id);
    }
  }, [historyItems, pendingTurn, selectedSessionId]);

  React.useEffect(() => {
    if (!eggOptions.length) {
      return;
    }
    const selectedConversation = historyItems.find((item) => item.id === selectedSessionId) ?? null;
    if (selectedConversation) {
      setSelectedEggId((current) => (current === selectedConversation.eggId ? current : selectedConversation.eggId));
      return;
    }
    if (!selectedEggId || !eggOptions.some((elephant) => elephant.eggId === selectedEggId)) {
      const fallback = eggOptions.find((elephant) => elephant.current) ?? eggOptions[0];
      setSelectedEggId(fallback?.eggId ?? null);
    }
  }, [eggOptions, historyItems, selectedEggId, selectedSessionId]);

  React.useEffect(() => {
    if (!pendingTurn) {
      return;
    }
    let cancelled = false;
    let timeoutId: number | null = null;
    const tick = async () => {
      try {
        await refresh({ silent: true });
      } finally {
        if (!cancelled) {
          timeoutId = window.setTimeout(() => {
            void tick();
          }, STREAM_REFRESH_INTERVAL_MS);
        }
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [pendingTurn, refresh]);

  const selectedConversation = historyItems.find((item) => item.id === selectedSessionId) ?? null;
  const selectedRows = selectedConversation?.rows ?? [];
  const selectedRowSignature = React.useMemo(() => conversationScrollSignature(selectedRows), [selectedRows]);

  React.useLayoutEffect(() => {
    const viewport = messageViewportRef.current;
    if (!viewport) {
      return;
    }
    const pendingKey = pendingTurn ? `${pendingTurn.sessionId}:${pendingTurn.prompt}` : "";
    const previous = scrollStateRef.current;
    const sessionChanged = previous.sessionId !== (selectedSessionId ?? "");
    const contentChanged = previous.signature !== selectedRowSignature;
    const pendingChanged = previous.pendingKey !== pendingKey;
    if (!sessionChanged && !contentChanged && !pendingChanged) {
      return;
    }
    scrollStateRef.current = {
      sessionId: selectedSessionId ?? "",
      signature: selectedRowSignature,
      pendingKey,
    };
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: sessionChanged ? "auto" : "smooth" });
  }, [pendingTurn, selectedRowSignature, selectedSessionId]);
  const isDraft = selectedSessionId === DRAFT_SESSION_ID || (!selectedConversation && !pendingTurn);
  const selectedEgg = eggOptions.find((item) => item.eggId === selectedEggId) ?? null;
  const sessionEggLocked = Boolean(selectedConversation);
  const composeProfile = React.useMemo(
    () => resolveComposeProfile(dashboard, selectedConversation?.eggId ?? selectedEggId),
    [dashboard, selectedEggId, selectedConversation?.eggId],
  );
  const selectedEggName = selectedConversation?.eggName ?? composeProfile.eggName;
  const activeSessionId = selectedConversation?.id ?? pendingTurn?.sessionId ?? selectedSessionId ?? DRAFT_SESSION_ID;
  const currentTitle = isDraft ? "New conversation" : selectedConversation?.title ?? "Conversation";
  const isStreaming = Boolean(pendingTurn) || sending;
  const clarifyRequest = React.useMemo(() => latestClarifyRequest(selectedRows), [selectedRows]);
  const isClarifyReply = Boolean(clarifyRequest && selectedConversation);

  const handleStartNewConversation = React.useCallback(() => {
    setSelectedSessionId(DRAFT_SESSION_ID);
    setComposer("");
    setHistoryCollapsed(true);
    setNotice("New draft ready.");
    setSubmitError(null);
  }, []);

  const handleSubmit = React.useCallback(async () => {
    const prompt = composer.trim();
    if (!prompt || sending || submitInFlightRef.current || !dashboard) {
      return;
    }

    const previousSelection = selectedSessionId;
    const existingSessionId = selectedConversation?.id ?? (selectedSessionId && selectedSessionId !== DRAFT_SESSION_ID ? selectedSessionId : null);
    const targetSessionId = existingSessionId ?? makeSessionId();

    submitInFlightRef.current = true;
    setSending(true);
    setSubmitError(null);
    setNotice(null);
    setPendingTurn({ sessionId: targetSessionId, prompt });
    setSelectedSessionId(targetSessionId);
    setComposer("");

    try {
      if (!existingSessionId) {
        await createDashboardSession({
          profile_id: composeProfile.profileId,
          display_name: composeProfile.displayName,
          mode: composeProfile.mode,
          elephant_id: composeProfile.eggId,
          episode_id: targetSessionId,
        });
      }
      await sendDashboardTurn(
        targetSessionId,
        isClarifyReply && clarifyRequest
          ? {
            prompt,
            tool_name: "tool.clarify",
            tool_arguments: {
              ...clarifyRequest.toolArguments,
              user_response: prompt,
            },
          }
          : { prompt },
      );
      await refresh();
      setNotice(
        isClarifyReply
          ? "Clarification sent as a tool result."
          : existingSessionId ? "Response complete." : `Conversation started on ${composeProfile.eggName}.`,
      );
    } catch (nextError) {
      setComposer(prompt);
      setSelectedSessionId(previousSelection ?? DRAFT_SESSION_ID);
      setSubmitError(nextError instanceof Error ? nextError.message : "Unable to send the prompt right now.");
    } finally {
      submitInFlightRef.current = false;
      setPendingTurn(null);
      setSending(false);
    }
  }, [clarifyRequest, composer, composeProfile, dashboard, isClarifyReply, refresh, selectedConversation, selectedSessionId, sending]);

  const pendingPromptVisible = Boolean(pendingTurn) && selectedRows.some((row) => valueOf(row, "event_type", "") === "user_query" && normalizedConversationContent(row) === pendingTurn?.prompt.trim());
  const isClosed = selectedConversation?.status === "closed";
  const submitDisabled = sending || !composer.trim() || !dashboard || (!selectedConversation && !composeProfile.eggId) || isClosed;

  return (
    <div className={styles.pageStack}>
      <section className={cx(styles.chatSurface, historyCollapsed && styles.chatSurfaceCollapsed)} aria-label="Dashboard chat workbench">
        {historyCollapsed ? (
          <aside className={styles.historyRail} aria-label="Collapsed conversation history">
            <button className={cx(styles.chatButton, styles.iconButton)} type="button" onClick={() => setHistoryCollapsed(false)} aria-label="Open history">
              <span>☰</span>
            </button>
            <button className={cx(styles.chatButton, styles.railNewButton)} type="button" onClick={handleStartNewConversation} aria-label="New chat">
              New
            </button>
            <div className={styles.railCounter}>
              <strong>{historyItems.length}</strong>
              <span>Chats</span>
            </div>
          </aside>
        ) : (
          <aside className={styles.sidebar}>
            <div className={styles.sidebarHeader}>
              <div>
                <span className={styles.sectionLabel}>Conversations</span>
                <strong>History</strong>
              </div>
              <div className={styles.sidebarActions}>
                <button className={cx(styles.chatButton, styles.chatButtonPrimary)} type="button" onClick={handleStartNewConversation}>
                  New chat
                </button>
                <button className={cx(styles.chatButton, styles.iconButton)} type="button" onClick={() => setHistoryCollapsed(true)} aria-label="Collapse history">
                  ‹
                </button>
              </div>
            </div>

            <label className={styles.searchField}>
              <span className={styles.sectionLabel}>Filter</span>
              <input
                type="search"
                value={historyQuery}
                onChange={(event) => setHistoryQuery(event.target.value)}
                placeholder="Search conversations"
              />
            </label>

            <div className={styles.sidebarStats}>
              <div>
                <span className={styles.sectionLabel}>Chats</span>
                <strong>{String(filteredHistory.length)}</strong>
              </div>
              <div>
                <span className={styles.sectionLabel}>Herd</span>
                <strong>{String(eggOptions.length)}</strong>
              </div>
            </div>

            <div className={styles.historyList}>
              <button
                type="button"
                className={cx(styles.historyItem, isDraft && styles.historyItemActive, styles.historyItemDraft)}
                onClick={handleStartNewConversation}
              >
                <span className={styles.historyItemMeta}>New</span>
                <strong>Start a fresh chat</strong>
                <p>Pick a ELEPHANT and start a focused Elephant Agent chat.</p>
              </button>

              {pagedHistory.length ? (
                pagedHistory.map((item) => {
                  const active = item.id === selectedSessionId;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={cx(styles.historyItem, active && styles.historyItemActive)}
                      onClick={() => {
                        setSelectedSessionId(item.id);
                        setSelectedEggId(item.eggId);
                        setSubmitError(null);
                      }}
                    >
                      <div className={styles.historyItemTopline}>
                        <span>{item.startedAt}</span>
                        <StatusBadge tone={toneForStatus(item.status)}>{item.status}</StatusBadge>
                      </div>
                      <strong>{item.title}</strong>
                      <p>{item.preview}</p>
                      <div className={styles.historyItemFooter}>
                        <small>{item.eggName}</small>
                        <small>{item.loopCount} loop(s)</small>
                      </div>
                    </button>
                  );
                })
              ) : (
                <EmptyPanel
                  title={historyItems.length ? "No matching conversation" : "No conversation yet"}
                  detail={historyItems.length ? "Try another keyword." : "Send the first prompt to create a conversation."}
                />
              )}
            </div>

            <div className={styles.historyPager}>
              <button className={styles.chatButton} type="button" disabled={currentHistoryPage <= 0} onClick={() => setHistoryPage((page) => Math.max(0, page - 1))}>
                Previous
              </button>
              <span>{currentHistoryPage + 1}/{totalHistoryPages}</span>
              <button className={styles.chatButton} type="button" disabled={currentHistoryPage >= totalHistoryPages - 1} onClick={() => setHistoryPage((page) => Math.min(totalHistoryPages - 1, page + 1))}>
                Next
              </button>
            </div>
          </aside>
        )}

        <section className={styles.chatPane}>
          <header className={styles.chatPaneHeader}>
            <div className={styles.chatPaneTitle}>
              <span className={styles.sectionLabel}>Live chat</span>
              <strong>{currentTitle}</strong>
              <p>{isDraft ? "A focused personal AI chat with tool work shown inline." : `${selectedEggName} · ${compactText(activeSessionId, 36)}`}</p>
            </div>
            <div className={styles.chatPaneControls}>
              <label className={styles.eggField}>
                <span className={styles.sectionLabel}>ELEPHANT</span>
                <span className={styles.eggControlRow}>
                  <select
                    value={selectedEggId ?? ""}
                    onChange={(event) => setSelectedEggId(event.target.value || null)}
                    disabled={sending || sessionEggLocked || !eggOptions.length}
                  >
                    {!eggOptions.length ? <option value="">No elephant available</option> : null}
                    {eggOptions.map((elephant) => (
                      <option key={elephant.eggId} value={elephant.eggId}>
                        {elephant.current ? "● " : ""}
                        {elephant.eggName} · {elephant.status}
                      </option>
                    ))}
                  </select>
                  <span className={cx(styles.streamPill, isStreaming && styles.streamPillLive)} aria-label={isStreaming ? "Elephant Agent is thinking" : "Elephant Agent is idle"}>
                    <span className={styles.streamDot} />
                    <strong>{isStreaming ? "Thinking" : "Idle"}</strong>
                  </span>
                </span>
              </label>
            </div>
          </header>

          <div className={styles.noticeStack} aria-live="polite">
            {clarifyRequest ? (
              <div className={cx(styles.notice, styles.clarifyNotice)}>
                <strong>Clarification needed</strong>
                <span>{clarifyRequest.question}</span>
                {clarifyRequest.choices.length ? <small>{clarifyRequest.choices.join(" · ")}</small> : null}
              </div>
            ) : null}
            {notice ? <div className={styles.notice}>{notice}</div> : null}
            {submitError ? <div className={cx(styles.notice, styles.noticeError)}>{submitError}</div> : null}
            {error && !isStreaming ? <div className={cx(styles.notice, styles.noticeError)}>{error}</div> : null}
            {loading && !dashboard ? <div className={styles.notice}>Loading runtime snapshot…</div> : null}
          </div>

          <div ref={messageViewportRef} className={styles.messageViewport}>
            {selectedRows.length ? (
              <div className={styles.messageList}>
                {selectedRows.map((row, index) => (
                  <ChatMessage key={`${valueOf(row, "step_id", valueOf(row, "event_type", "step"))}-${index}`} row={row} />
                ))}
                {pendingTurn && pendingTurn.sessionId === activeSessionId ? <PendingStream prompt={pendingTurn.prompt} showPrompt={!pendingPromptVisible} /> : null}
              </div>
            ) : pendingTurn && pendingTurn.sessionId === activeSessionId ? (
              <div className={styles.messageList}>
                <PendingStream prompt={pendingTurn.prompt} showPrompt />
              </div>
            ) : (
              <div className={styles.emptyThread}>
                <EmptyPanel
                  title={isDraft ? "Ready when you are" : "No visible chat messages"}
                  detail={isDraft ? "Pick a ELEPHANT and send the first message." : "This thread has no user, Elephant Agent, or tool messages yet."}
                />
              </div>
            )}
          </div>

          <form
            className={styles.composer}
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit();
            }}
          >
            <label className={styles.composerField}>
              <textarea
                value={composer}
                onChange={(event) => setComposer(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleSubmit();
                  }
                }}
                placeholder={isClarifyReply ? "Answer the clarification…" : "Message Elephant Agent…"}
                rows={3}
              />
            </label>
            <div className={styles.composerFooter}>
              <div className={styles.composerHints}>
                {isClosed ? (
                  <span>This conversation is closed. Start a new one to continue.</span>
                ) : (
                  <span>{isClarifyReply ? "Next send becomes the clarify tool result" : sessionEggLocked ? `Pinned to ${selectedEggName}` : `Next chat uses ${selectedEgg?.eggName ?? composeProfile.eggName}`}</span>
                )}
                <small>Enter sends · Shift + Enter for newline</small>
              </div>
              <div className={styles.composerActions}>
                <button className={styles.chatButton} type="button" onClick={() => setComposer("")} disabled={sending || !composer}>
                  Clear
                </button>
                <button className={cx(styles.chatButton, styles.chatButtonPrimary)} type="submit" disabled={submitDisabled}>
                  {sending ? "Streaming…" : isClarifyReply ? "Send clarify" : isDraft ? "Start stream" : "Send"}
                </button>
              </div>
            </div>
          </form>
        </section>
      </section>
    </div>
  );
}
