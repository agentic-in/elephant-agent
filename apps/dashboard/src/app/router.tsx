import type { ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";

import { DashboardShell } from "../shell/DashboardShell";

type RouteComponent = ComponentType<Record<string, never>>;
type LazyRoute = () => Promise<{ Component: RouteComponent }>;
type ConsolePagesModule = typeof import("../routes/console/ConsolePages");
type ConsolePageName = keyof ConsolePagesModule;

function lazyConsolePage(name: ConsolePageName): LazyRoute {
  return async () => {
    const module = await import("../routes/console/ConsolePages");
    return { Component: module[name] as RouteComponent };
  };
}

const lazyPersonalModelMapPage: LazyRoute = async () => {
  const module = await import("../routes/console/PersonalModelMapPage");
  return { Component: module.PersonalModelMapPage };
};

const lazyChatPage: LazyRoute = async () => {
  const module = await import("../routes/chat/ChatPage");
  return { Component: module.ChatPage };
};

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <DashboardShell />,
      children: [
        { index: true, lazy: lazyPersonalModelMapPage },
        { path: "palace", lazy: lazyPersonalModelMapPage },
        { path: "you", lazy: lazyConsolePage("PersonalModelsPage") },
        { path: "diary", lazy: lazyConsolePage("PersonalModelsPage") },
        { path: "personal-models", lazy: lazyConsolePage("PersonalModelsPage") },
        { path: "herd", lazy: lazyConsolePage("StatesPage") },
        { path: "states", lazy: lazyConsolePage("StatesPage") },
        { path: "runtime", lazy: lazyConsolePage("RuntimePage") },
        { path: "chat", lazy: lazyChatPage },
        { path: "questions", lazy: lazyConsolePage("QuestionsPage") },
        { path: "providers", lazy: lazyConsolePage("ProvidersPage") },
        { path: "models", lazy: lazyConsolePage("ModelsPage") },
        { path: "skills", lazy: lazyConsolePage("SkillsPage") },
        { path: "tools", lazy: lazyConsolePage("ToolsPage") },
        { path: "gateway", lazy: lazyConsolePage("GatewayPage") },
        { path: "cron", lazy: lazyConsolePage("CronPage") },
        { path: "reflect", lazy: lazyConsolePage("ReflectPage") },
        { path: "usage", lazy: lazyConsolePage("UsagePage") },
        { path: "logs", lazy: lazyConsolePage("LogsPage") },
        { path: "settings", lazy: lazyConsolePage("SettingsPage") },
        { path: "usage-logs", lazy: lazyConsolePage("UsageLogsPage") },
      ],
    },
  ],
  { basename: "/dashboard" },
);
