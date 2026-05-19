import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const desktopDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const result = spawnSync("npm", ["--prefix", "../dashboard", "run", "build"], {
  cwd: desktopDir,
  env: {
    ...process.env,
    VITE_ELEPHANT_DESKTOP: "1",
  },
  shell: process.platform === "win32",
  stdio: "inherit",
});

process.exit(result.status ?? 1);
