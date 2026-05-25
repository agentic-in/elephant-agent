import {execFileSync} from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const scriptRoot = dirname(fileURLToPath(import.meta.url));
const siteRoot = dirname(scriptRoot);
const repoRoot = dirname(dirname(siteRoot));
const docsRoot = join(siteRoot, "docs", "skillhub");
const libraryRoot = join(docsRoot, "library");
const pageLibraryRoot = join(siteRoot, "src", "pages", "skillhub", "library");
const generatedRoot = join(siteRoot, "src", "generated");
const generatedCatalogPath = join(generatedRoot, "skillhubCatalog.ts");
const checkOnly = process.argv.includes("--check");
const catalogPrefix = "export const skillHubCatalog: SkillHubCatalogData = ";
const catalogSuffix =
  ";\n\nexport const skillHubCatalogById: Record<string, SkillHubSiteEntry> = Object.fromEntries(";

const rawCatalog = execFileSync(
  "python3",
  [
    "-c",
    [
      "from packages.skills.site_projection import build_skillhub_site_catalog",
      "print(build_skillhub_site_catalog().to_json())",
    ].join("; "),
  ],
  {
    cwd: repoRoot,
    encoding: "utf8",
  }
);
const catalog = JSON.parse(rawCatalog);
preserveGeneratedAtWhenCatalogIsUnchanged(catalog);
const generatedFiles = renderGeneratedFiles(catalog);

if (checkOnly) {
  const mismatches = findGeneratedFileMismatches(generatedFiles);
  if (mismatches.length > 0) {
    console.error("SkillHub generated content is out of sync. Run `npm --prefix apps/site run sync:content`.");
    for (const mismatch of mismatches) {
      console.error(`- ${mismatch}`);
    }
    process.exit(1);
  }
  process.exit(0);
}

mkdirSync(generatedRoot, {recursive: true});
mkdirSync(libraryRoot, {recursive: true});
mkdirSync(pageLibraryRoot, {recursive: true});

for (const stalePath of listManagedGeneratedFiles()) {
  if (!generatedFiles.has(stalePath)) {
    rmSync(stalePath, {force: true});
  }
}

for (const [filePath, content] of generatedFiles.entries()) {
  writeFileIfChanged(filePath, content);
}

function renderGeneratedFiles(payload) {
  const files = new Map();
  files.set(generatedCatalogPath, renderCatalogModule(payload));
  files.set(join(docsRoot, "index.mdx"), renderIndexDoc());
  for (const entry of payload.entries) {
    files.set(join(libraryRoot, `${entry.slug}.mdx`), renderDetailDoc(entry));
    files.set(join(pageLibraryRoot, `${entry.slug}.tsx`), renderDetailPage(entry));
  }
  return files;
}

function findGeneratedFileMismatches(expectedFiles) {
  const mismatches = [];
  for (const [filePath, expectedContent] of expectedFiles.entries()) {
    if (!existsSync(filePath)) {
      mismatches.push(`missing ${relativeRepoPath(filePath)}`);
      continue;
    }
    if (readFileSync(filePath, "utf8") !== expectedContent) {
      mismatches.push(`outdated ${relativeRepoPath(filePath)}`);
    }
  }
  for (const filePath of listManagedGeneratedFiles()) {
    if (!expectedFiles.has(filePath)) {
      mismatches.push(`stale ${relativeRepoPath(filePath)}`);
    }
  }
  return mismatches.sort();
}

function listManagedGeneratedFiles() {
  return [
    generatedCatalogPath,
    ...listFilesRecursively(docsRoot),
    ...listFilesRecursively(pageLibraryRoot),
  ];
}

function listFilesRecursively(root) {
  if (!existsSync(root)) {
    return [];
  }
  const files = [];
  for (const entry of readdirSync(root, {withFileTypes: true})) {
    const entryPath = join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...listFilesRecursively(entryPath));
    } else if (entry.isFile()) {
      files.push(entryPath);
    }
  }
  return files;
}

function preserveGeneratedAtWhenCatalogIsUnchanged(nextCatalog) {
  const previousCatalog = readExistingCatalogPayload();
  if (!previousCatalog?.generated_at) {
    return;
  }
  const previousComparable = {...previousCatalog, generated_at: "<generated>"};
  const nextComparable = {...nextCatalog, generated_at: "<generated>"};
  if (JSON.stringify(previousComparable) === JSON.stringify(nextComparable)) {
    nextCatalog.generated_at = previousCatalog.generated_at;
  }
}

function readExistingCatalogPayload() {
  if (!existsSync(generatedCatalogPath)) {
    return null;
  }
  try {
    const moduleContent = readFileSync(generatedCatalogPath, "utf8");
    const start = moduleContent.indexOf(catalogPrefix);
    if (start < 0) {
      return null;
    }
    const payloadStart = start + catalogPrefix.length;
    const payloadEnd = moduleContent.indexOf(catalogSuffix, payloadStart);
    if (payloadEnd < 0) {
      return null;
    }
    return JSON.parse(moduleContent.slice(payloadStart, payloadEnd));
  } catch {
    return null;
  }
}

function writeFileIfChanged(filePath, content) {
  let currentContent = "";
  try {
    currentContent = readFileSync(filePath, "utf8");
  } catch {
    currentContent = "";
  }
  if (currentContent === content) {
    return;
  }
  mkdirSync(dirname(filePath), {recursive: true});
  writeFileSync(filePath, content, "utf8");
}

function relativeRepoPath(filePath) {
  return filePath.startsWith(`${repoRoot}/`) ? filePath.slice(repoRoot.length + 1) : filePath;
}

function renderCatalogModule(payload) {
  return `/* This file is generated by apps/site/scripts/sync-skillhub-content.mjs. */

export type SkillHubSiteEntry = {
  skill_id: string;
  slug: string;
  display_name: string;
  summary: string;
  reference: string;
  section_id: string;
  section_display_name: string;
  detail_doc_id: string;
  detail_path: string;
  source_id: string;
  source_label: string;
  source_kind: string;
  storage_tier: string;
  default_enabled: boolean;
  default_enabled_label: string;
  source_reference: string;
  install_reference: string;
  install_command: string;
  trust_level: string;
  packaging_posture: string;
  install_posture: string;
  operator_install_posture: string;
  source_detail_url: string;
  source_repo_url: string;
  aliases: string[];
  trigger_phrases: string[];
  keywords: string[];
  platforms: string[];
  requires_tools: string[];
  requires_toolsets: string[];
  required_environment_variables: string[];
};

export type SkillHubSiteExternalSource = {
  source_id: string;
  display_name: string;
  summary: string;
  trust_posture: string;
  reference_pattern: string;
  search_command: string;
  install_command: string;
};

export type SkillHubSiteSection = {
  section_id: string;
  display_name: string;
  summary: string;
  entry_count: number;
  entries: SkillHubSiteEntry[];
};

export type SkillHubCatalogData = {
  generated_at: string;
  headline: string;
  summary: string;
  builtin_posture: string;
  curated_origin_posture: string;
  operator_install_posture: string;
  stats: Record<string, number>;
  external_sources: SkillHubSiteExternalSource[];
  sections: SkillHubSiteSection[];
  entries: SkillHubSiteEntry[];
};

export const skillHubCatalog: SkillHubCatalogData = ${JSON.stringify(payload, null, 2)};

export const skillHubCatalogById: Record<string, SkillHubSiteEntry> = Object.fromEntries(
  skillHubCatalog.entries.map((entry) => [entry.skill_id, entry])
);
`;
}

function renderIndexDoc() {
  return `---
title: "Skills"
description: "Bundled Elephant Agent skills and the external sources Elephant Agent can install from."
---

import {SkillHubCatalog} from "@site/src/components/skillhub/SkillHubCatalog";
import {skillHubCatalog} from "@site/src/generated/skillhubCatalog";

<SkillHubCatalog catalog={skillHubCatalog} />
`;
}

function renderDetailDoc(entry) {
  return `---
title: "${escapeFrontmatter(entry.display_name)}"
description: "${escapeFrontmatter(entry.summary)}"
---

import {SkillHubDetail} from "@site/src/components/skillhub/SkillHubDetail";
import {skillHubCatalogById} from "@site/src/generated/skillhubCatalog";

<SkillHubDetail entry={skillHubCatalogById["${escapeJsString(entry.skill_id)}"]} />
`;
}

function renderDetailPage(entry) {
  const componentName = `SkillHub${toPascalCase(entry.slug)}Page`;
  return `import React from "react";

import {SkillHubDetailPage} from "../../../components/skillhub/SkillHubDetailPage";
import {skillHubCatalogById} from "../../../generated/skillhubCatalog";

export default function ${componentName}(): React.JSX.Element {
  return <SkillHubDetailPage entry={skillHubCatalogById["${escapeJsString(entry.skill_id)}"]} />;
}
`;
}

function escapeFrontmatter(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll("\"", "\\\"");
}

function escapeJsString(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll("\"", "\\\"");
}

function toPascalCase(value) {
  const collapsed = String(value)
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join("");
  return collapsed || "Entry";
}
