import React, { useEffect, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import elephantLogo from "../../assets/brand/elephant-logo.png";
import { ActionButton, EmptyPanel, StatusBadge } from "../../components/primitives/DashboardPrimitives";
import { useDashboardSnapshot } from "../../hooks/useOperatorConsole";
import {
  correctPersonalModelClaim,
  createDashboardEgg,
  dismissPersonalModelQuestion,
  forgetPersonalModelClaim,
  importSourcePaths,
} from "../../lib/dashboardApi";
import { desktopCoreStatus, isDesktopRuntime, pickDesktopSourcePaths } from "../../lib/desktopBridge";
import type { DashboardRow, DesktopCoreStatus, SourceImportStatus } from "../../types/dashboard";
import styles from "./ProfileBuilderPage.module.css";

const PROFILE_COMPLETE_KEY = "elephant.desktopProfileBuilderComplete.v1";
const DESKTOP_ELEPHANT_ID_KEY = "elephant.desktopElephantId.v1";

type BuilderStep = "welcome" | "sources" | "building" | "review";

function storageValue(key: string): string {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeStorageValue(key: string, value: string): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore unavailable storage; the live app still works for this session.
  }
}

function rowText(row: DashboardRow | undefined, keys: readonly string[], fallback = ""): string {
  for (const key of keys) {
    const value = row?.[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
  }
  return fallback;
}

function rowId(row: DashboardRow | undefined, keys: readonly string[]): string {
  return rowText(row, keys, "");
}

function slugId(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 36);
}

function parseManualPaths(value: string): string[] {
  return value
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function ProfileBuilderPage(): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const desktop = isDesktopRuntime();
  const alreadyComplete = storageValue(PROFILE_COMPLETE_KEY) === "1";
  const [step, setStep] = useState<BuilderStep>("welcome");
  const [displayName, setDisplayName] = useState("Elephant Desktop");
  const [paths, setPaths] = useState<string[]>([]);
  const [manualPaths, setManualPaths] = useState("");
  const [importStatus, setImportStatus] = useState<SourceImportStatus | null>(null);
  const [coreStatus, setCoreStatus] = useState<DesktopCoreStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { dashboard, refresh } = useDashboardSnapshot("questions");

  useEffect(() => {
    let active = true;
    if (!desktop) {
      return () => {
        active = false;
      };
    }
    desktopCoreStatus()
      .then((status) => {
        if (active) {
          setCoreStatus(status);
        }
      })
      .catch(() => {
        if (active) {
          setCoreStatus(null);
        }
      });
    return () => {
      active = false;
    };
  }, [desktop]);

  const effectivePaths = useMemo(
    () => Array.from(new Set([...paths, ...parseManualPaths(manualPaths)])),
    [manualPaths, paths],
  );

  if (desktop && alreadyComplete && location.pathname === "/") {
    return <Navigate to="/wake" replace />;
  }

  async function choosePaths(): Promise<void> {
    setError(null);
    const selected = await pickDesktopSourcePaths();
    if (!selected.length) {
      setError("File picker is unavailable here. Paste local paths below, one per line.");
      return;
    }
    setPaths((current) => Array.from(new Set([...current, ...selected])));
  }

  async function buildProfile(): Promise<void> {
    setError(null);
    if (!effectivePaths.length) {
      setError("Add at least one local project folder or document path.");
      return;
    }
    setBusy(true);
    setStep("building");
    try {
      const storedElephantId = storageValue(DESKTOP_ELEPHANT_ID_KEY);
      let elephantId = storedElephantId;
      if (!elephantId) {
        elephantId = `${slugId(displayName) || "desktop"}-${Date.now().toString(36)}`;
        const created = await createDashboardEgg({
          display_name: displayName,
          elephant_id: elephantId,
          mode: "companion",
          initiative: "gentle",
        });
        const createdPayload = created as { elephant?: { elephant_id?: unknown } };
        const createdId = String(createdPayload.elephant?.elephant_id ?? "").trim();
        elephantId = createdId || elephantId;
        writeStorageValue(DESKTOP_ELEPHANT_ID_KEY, elephantId);
      }
      const result = await importSourcePaths({
        paths: effectivePaths,
        elephant_id: elephantId,
        mode: "profile_builder",
      });
      setImportStatus(result);
      await refresh({ silent: true });
      setStep("review");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Profile Builder failed.");
      setStep("sources");
    } finally {
      setBusy(false);
    }
  }

  async function forgetClaim(row: DashboardRow): Promise<void> {
    const claimRef = rowId(row, ["fact_id", "claim_ref", "ref"]);
    if (!claimRef) return;
    await forgetPersonalModelClaim(claimRef, { reason: "profile_builder_review" });
    await refresh();
  }

  async function correctClaim(row: DashboardRow): Promise<void> {
    const claimRef = rowId(row, ["fact_id", "claim_ref", "ref"]);
    if (!claimRef) return;
    const currentText = rowText(row, ["text", "claim", "value"], "");
    const nextText = window.prompt("Correct this claim", currentText);
    if (!nextText?.trim()) return;
    await correctPersonalModelClaim(claimRef, {
      text: nextText.trim(),
      lens: rowText(row, ["lens"], "identity"),
      topic: rowText(row, ["topic", "sub_lens"], "profile_builder"),
      reason: "profile_builder_review",
    });
    await refresh();
  }

  async function dismissQuestion(row: DashboardRow): Promise<void> {
    const questionId = rowId(row, ["question_id", "id"]);
    if (!questionId) return;
    await dismissPersonalModelQuestion(questionId, "profile_builder_review");
    await refresh();
  }

  function enterApp(): void {
    writeStorageValue(PROFILE_COMPLETE_KEY, "1");
    navigate("/wake");
  }

  const facts = dashboard?.questions.facts ?? [];
  const questions = dashboard?.questions.waiting_questions ?? [];
  const lensCounts = facts.reduce<Record<string, number>>((counts, row) => {
    const lens = rowText(row, ["lens"], "unknown");
    counts[lens] = (counts[lens] ?? 0) + 1;
    return counts;
  }, {});

  if (step === "building") {
    return (
      <section className={styles.buildingScreen} aria-label="Building your profile">
        <div className={styles.buildingCard}>
          <div className={styles.orb}>
            <img src={elephantLogo} alt="" />
          </div>
          <h1>Building your profile...</h1>
          <p>This will only take a moment.</p>
          <div className={styles.skeletonStack} aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.page} aria-label="Elephant Profile Builder">
      <div className={styles.hero}>
        <div className={styles.heroCopy}>
          <span>Elephant Desktop v1</span>
          <h1>Profile Builder</h1>
          <p>
            Start from local context: create an elephant, import projects and documents as evidence,
            then review the first claims and questions before entering Wake.
          </p>
        </div>
        <div className={styles.presenceCard}>
          <img src={elephantLogo} alt="" />
          <div>
            <strong>Presence</strong>
            <span>{coreStatus ? `${coreStatus.coreStatus} · ${coreStatus.workerStatus}` : desktop ? "Desktop core starting" : "Browser preview mode"}</span>
          </div>
        </div>
      </div>

      {error ? (
        <div className={styles.errorBanner}>
          <strong>Needs attention</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {step === "welcome" ? (
        <div className={styles.setupGrid}>
          <article className={styles.panel}>
            <span>Step 1</span>
            <h2>Create your elephant</h2>
            <p>Choose the local continuity line that will receive imported evidence and background reflect jobs.</p>
            <label className={styles.field}>
              <span>Name</span>
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
            <ActionButton onClick={() => setStep("sources")}>Continue</ActionButton>
          </article>
          <article className={styles.panel}>
            <span>What ships in v1</span>
            <ul className={styles.featureList}>
              <li>Local project/document import for context in minutes</li>
              <li>Background reflect job after import</li>
              <li>Reviewable claims and questions before entering Wake</li>
            </ul>
          </article>
        </div>
      ) : null}

      {step === "sources" ? (
        <div className={styles.setupGrid}>
          <article className={styles.panel}>
            <span>Step 2</span>
            <h2>Add local sources</h2>
            <p>Folders, git repos, Markdown, text, common code files, and config files are admitted. Secrets, binaries, dependencies, build output, and large files are skipped.</p>
            <div className={styles.actionRow}>
              <ActionButton onClick={choosePaths}>Pick files or folders</ActionButton>
              <ActionButton variant="ghost" onClick={() => setPaths([])} disabled={!paths.length}>
                Clear picked
              </ActionButton>
            </div>
            <label className={styles.field}>
              <span>Manual paths</span>
              <textarea
                value={manualPaths}
                onChange={(event) => setManualPaths(event.target.value)}
                placeholder="/Users/you/project&#10;/Users/you/notes/README.md"
              />
            </label>
            <div className={styles.pathList}>
              {effectivePaths.length ? effectivePaths.map((path) => <code key={path}>{path}</code>) : <span>No sources selected</span>}
            </div>
            <div className={styles.actionRow}>
              <ActionButton onClick={buildProfile} disabled={busy}>
                Build profile
              </ActionButton>
              <ActionButton variant="ghost" onClick={() => setStep("welcome")} disabled={busy}>
                Back
              </ActionButton>
            </div>
          </article>
          <article className={styles.panel}>
            <span>Import policy</span>
            <h2>Evidence first</h2>
            <p>Imported sources create Episode/Step/SemanticIndexEntry records and queue learning. They do not directly write durable Personal Model truth.</p>
          </article>
        </div>
      ) : null}

      {step === "review" ? (
        <div className={styles.reviewGrid}>
          <article className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <span>Step 3</span>
                <h2>Review claims</h2>
              </div>
              <StatusBadge tone={facts.length ? "healthy" : "neutral"}>{facts.length} claims</StatusBadge>
            </div>
            <div className={styles.lensGrid}>
              {["identity", "world", "pulse", "journey"].map((lens) => (
                <div key={lens}>
                  <span>{lens}</span>
                  <strong>{lensCounts[lens] ?? 0}</strong>
                </div>
              ))}
            </div>
            <div className={styles.reviewList}>
              {facts.slice(0, 8).map((fact, index) => {
                const ref = rowId(fact, ["fact_id", "claim_ref", "ref"]) || `fact-${index}`;
                return (
                  <article key={ref} className={styles.reviewItem}>
                    <div>
                      <span>{rowText(fact, ["lens"], "claim")}</span>
                      <strong>{rowText(fact, ["text", "claim", "value"], "Claim pending review")}</strong>
                    </div>
                    <div className={styles.itemActions}>
                      <ActionButton variant="ghost" onClick={() => correctClaim(fact)}>Correct</ActionButton>
                      <ActionButton variant="ghost" onClick={() => forgetClaim(fact)}>Forget</ActionButton>
                    </div>
                  </article>
                );
              })}
              {!facts.length ? (
                <EmptyPanel
                  title="No claims yet"
                  detail="The source import has queued background learning. Return to Reflect or Activity after the worker finishes."
                />
              ) : null}
            </div>
          </article>

          <article className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <span>Questions</span>
                <h2>Open loops</h2>
              </div>
              <StatusBadge tone={questions.length ? "attention" : "neutral"}>{questions.length} pending</StatusBadge>
            </div>
            <div className={styles.reviewList}>
              {questions.slice(0, 6).map((question, index) => {
                const questionId = rowId(question, ["question_id", "id"]) || `question-${index}`;
                return (
                  <article key={questionId} className={styles.reviewItem}>
                    <div>
                      <span>{rowText(question, ["lens"], "question")}</span>
                      <strong>{rowText(question, ["text", "question"], "Question pending review")}</strong>
                    </div>
                    <ActionButton variant="ghost" onClick={() => dismissQuestion(question)}>Dismiss</ActionButton>
                  </article>
                );
              })}
              {!questions.length ? <EmptyPanel title="No open questions" detail="There is nothing waiting for review right now." /> : null}
            </div>

            <div className={styles.importStats}>
              <div>
                <span>Scanned</span>
                <strong>{importStatus?.scanned_count ?? 0}</strong>
              </div>
              <div>
                <span>Admitted</span>
                <strong>{importStatus?.admitted_count ?? 0}</strong>
              </div>
              <div>
                <span>Skipped</span>
                <strong>{importStatus?.skipped_count ?? 0}</strong>
              </div>
            </div>

            <ActionButton onClick={enterApp}>Enter Wake</ActionButton>
          </article>
        </div>
      ) : null}
    </section>
  );
}
