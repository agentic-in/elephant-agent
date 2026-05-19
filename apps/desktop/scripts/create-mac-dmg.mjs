import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, symlinkSync } from "node:fs";
import { cp, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const desktopDir = join(scriptDir, "..");
const packageJson = JSON.parse(await readFile(join(desktopDir, "package.json"), "utf8"));
const productName = "Elephant Agent";
const appPath = join(desktopDir, "src-tauri", "target", "release", "bundle", "macos", `${productName}.app`);
const dmgDir = join(desktopDir, "src-tauri", "target", "release", "bundle", "dmg");
const stagingDir = join(dmgDir, "staging");
const targetArch = process.arch === "arm64" ? "aarch64" : process.arch;
const dmgPath = join(dmgDir, `${productName}_${packageJson.version}_${targetArch}.dmg`);

if (process.platform !== "darwin") {
  throw new Error("Mac DMG packaging requires macOS.");
}

if (!existsSync(appPath)) {
  throw new Error(`Missing macOS app bundle at ${appPath}. Run tauri build --bundles app first.`);
}

execFileSync("codesign", [
  "--force",
  "--deep",
  "--sign",
  "-",
  appPath,
], { stdio: "inherit" });

rmSync(stagingDir, { recursive: true, force: true });
rmSync(dmgPath, { force: true });
mkdirSync(stagingDir, { recursive: true });

await cp(appPath, join(stagingDir, `${productName}.app`), {
  recursive: true,
  preserveTimestamps: true,
});
symlinkSync("/Applications", join(stagingDir, "Applications"));

execFileSync("hdiutil", [
  "create",
  "-volname",
  productName,
  "-srcfolder",
  stagingDir,
  "-ov",
  "-format",
  "UDZO",
  dmgPath,
], { stdio: "inherit" });

rmSync(stagingDir, { recursive: true, force: true });
console.log(`Created ${dmgPath}`);
