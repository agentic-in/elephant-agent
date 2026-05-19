import React, { useMemo, useState } from "react";

import { ActionButton, EmptyPanel, StatusBadge } from "../../components/primitives/DashboardPrimitives";
import { importSourcePaths } from "../../lib/dashboardApi";
import { pickDesktopSourcePaths } from "../../lib/desktopBridge";
import type { SourceImportStatus } from "../../types/dashboard";
import styles from "./SourcesPage.module.css";

function parsePaths(value: string): string[] {
  return value
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function SourcesPage(): React.JSX.Element {
  const [pickedPaths, setPickedPaths] = useState<string[]>([]);
  const [manualPaths, setManualPaths] = useState("");
  const [status, setStatus] = useState<SourceImportStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const paths = useMemo(() => Array.from(new Set([...pickedPaths, ...parsePaths(manualPaths)])), [manualPaths, pickedPaths]);

  async function choosePaths(): Promise<void> {
    setError(null);
    const selected = await pickDesktopSourcePaths();
    if (!selected.length) {
      setError("File picker is unavailable here. Paste local paths below, one per line.");
      return;
    }
    setPickedPaths((current) => Array.from(new Set([...current, ...selected])));
  }

  async function runImport(): Promise<void> {
    setError(null);
    if (!paths.length) {
      setError("Add at least one local project folder or document path.");
      return;
    }
    setBusy(true);
    try {
      const result = await importSourcePaths({ paths, mode: "manual" });
      setStatus(result);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Source import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.page} aria-label="Sources">
      <header className={styles.header}>
        <div>
          <span>Context in minutes</span>
          <h1>Sources</h1>
          <p>Import local folders, git repositories, Markdown, text, code, and config files as reviewable evidence. Personal Model facts are produced only by background understanding.</p>
        </div>
        <StatusBadge tone={status?.status === "completed" ? "healthy" : "neutral"}>
          {status?.status ?? "ready"}
        </StatusBadge>
      </header>

      {error ? (
        <div className={styles.errorBanner}>
          <strong>Needs attention</strong>
          <p>{error}</p>
        </div>
      ) : null}

      <div className={styles.grid}>
        <article className={styles.panel}>
          <span>Local import</span>
          <h2>Add source paths</h2>
          <p>Dependencies, build outputs, binaries, large files, and secrets-like files are skipped by default.</p>
          <div className={styles.actions}>
            <ActionButton onClick={choosePaths}>Pick files or folders</ActionButton>
            <ActionButton variant="ghost" onClick={() => setPickedPaths([])} disabled={!pickedPaths.length}>
              Clear picked
            </ActionButton>
          </div>
          <label className={styles.field}>
            <span>Manual paths</span>
            <textarea
              value={manualPaths}
              onChange={(event) => setManualPaths(event.target.value)}
              placeholder="/Users/you/project&#10;/Users/you/docs/notes.md"
            />
          </label>
          <div className={styles.pathList}>
            {paths.length ? paths.map((path) => <code key={path}>{path}</code>) : <span>No sources selected</span>}
          </div>
          <ActionButton onClick={runImport} disabled={busy}>
            {busy ? "Importing" : "Import sources"}
          </ActionButton>
        </article>

        <article className={styles.panel}>
          <span>Latest import</span>
          <h2>Scan result</h2>
          {status ? (
            <>
              <div className={styles.stats}>
                <div>
                  <span>Scanned</span>
                  <strong>{status.scanned_count}</strong>
                </div>
                <div>
                  <span>Admitted</span>
                  <strong>{status.admitted_count}</strong>
                </div>
                <div>
                  <span>Skipped</span>
                  <strong>{status.skipped_count}</strong>
                </div>
              </div>
              <div className={styles.reasonList}>
                {Object.entries(status.skipped_reasons).map(([reason, count]) => (
                  <div key={reason}>
                    <span>{reason.replace(/_/g, " ")}</span>
                    <strong>{count}</strong>
                  </div>
                ))}
                {!Object.keys(status.skipped_reasons).length ? <span>No skipped files</span> : null}
              </div>
              <p>Episode: <code>{status.episode_id ?? "none"}</code></p>
              <p>Learning job: <code>{status.job_id ?? "none"}</code></p>
            </>
          ) : (
            <EmptyPanel title="No import yet" detail="Run a local import to create evidence and queue background reflect." />
          )}
        </article>
      </div>
    </section>
  );
}
