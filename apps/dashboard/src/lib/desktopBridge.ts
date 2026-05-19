import type { DesktopCoreStatus } from "../types/dashboard";

type TauriInvoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;

type DesktopWindow = Window & {
  __ELEPHANT_DESKTOP_API_BASE_URL__?: string;
  __TAURI__?: {
    core?: { invoke?: TauriInvoke };
    invoke?: TauriInvoke;
  };
  __TAURI_INTERNALS__?: {
    invoke?: TauriInvoke;
  };
};

const desktopEnvFlag = String(import.meta.env.VITE_ELEPHANT_DESKTOP ?? "").trim() === "1";

function desktopWindow(): DesktopWindow | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window as DesktopWindow;
}

export function isDesktopRuntime(): boolean {
  const currentWindow = desktopWindow();
  return Boolean(
    desktopEnvFlag
      || currentWindow?.__ELEPHANT_DESKTOP_API_BASE_URL__
      || currentWindow?.__TAURI__?.core?.invoke
      || currentWindow?.__TAURI__?.invoke
      || currentWindow?.__TAURI_INTERNALS__?.invoke,
  );
}

export async function invokeDesktopCommand<T>(
  command: string,
  args: Record<string, unknown> = {},
): Promise<T | null> {
  const currentWindow = desktopWindow();
  const invoke =
    currentWindow?.__TAURI__?.core?.invoke
    ?? currentWindow?.__TAURI__?.invoke
    ?? currentWindow?.__TAURI_INTERNALS__?.invoke;
  if (!invoke) {
    return null;
  }
  return invoke<T>(command, args);
}

let desktopApiBasePromise: Promise<string | null> | null = null;

export function clearDesktopApiBaseCache(): void {
  desktopApiBasePromise = null;
}

export async function desktopApiBaseUrl(): Promise<string | null> {
  const currentWindow = desktopWindow();
  const injected = String(currentWindow?.__ELEPHANT_DESKTOP_API_BASE_URL__ ?? "").trim().replace(/\/$/, "");
  if (injected) {
    return injected;
  }
  if (!isDesktopRuntime()) {
    return null;
  }
  if (!desktopApiBasePromise) {
    desktopApiBasePromise = invokeDesktopCommand<string>("desktop_api_base_url")
      .then((value) => String(value ?? "").trim().replace(/\/$/, "") || null)
      .catch(() => null);
  }
  return desktopApiBasePromise;
}

export async function desktopCoreStatus(): Promise<DesktopCoreStatus | null> {
  return invokeDesktopCommand<DesktopCoreStatus>("desktop_core_status");
}

export async function pickDesktopSourcePaths(): Promise<string[]> {
  const result = await invokeDesktopCommand<string[]>("desktop_pick_source_paths");
  return Array.isArray(result) ? result : [];
}

export async function revealDesktopPath(path: string): Promise<void> {
  await invokeDesktopCommand("desktop_reveal_path", { path });
}

export async function restartDesktopCore(): Promise<DesktopCoreStatus | null> {
  clearDesktopApiBaseCache();
  return invokeDesktopCommand<DesktopCoreStatus>("desktop_restart_core");
}
