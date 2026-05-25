import {chmodSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..", "..");
const sourcePath = resolve(repoRoot, "install.sh");
const destinationPath = resolve(repoRoot, "apps", "site", "static", "install.sh");
const checkOnly = process.argv.includes("--check");

const sourceContent = readFileSync(sourcePath, "utf8");
let destinationContent = "";

try {
  destinationContent = readFileSync(destinationPath, "utf8");
} catch {
  destinationContent = "";
}

if (destinationContent !== sourceContent) {
  if (checkOnly) {
    console.error("apps/site/static/install.sh is out of sync with install.sh");
    process.exit(1);
  }
  mkdirSync(dirname(destinationPath), {recursive: true});
  writeFileSync(destinationPath, sourceContent);
}

if (!checkOnly) {
  chmodSync(destinationPath, 0o755);
}
