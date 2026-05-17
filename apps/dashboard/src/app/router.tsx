import { createBrowserRouter } from "react-router-dom";

import {
  CronPage,
  QuestionsPage,
  GatewayPage,
  ModelsPage,
  PersonalModelsPage,
  ProvidersPage,
  ReflectPage,
  RuntimePage,
  SettingsPage,
  SkillsPage,
  StatesPage,
  SystemPage,
  ToolsPage,
  LogsPage,
  UsagePage,
  UsageLogsPage,
} from "../routes/console/ConsolePages";
import { PersonalModelMapPage } from "../routes/console/PersonalModelMapPage";
import { ChatPage } from "../routes/chat/ChatPage";
import { DashboardShell } from "../shell/DashboardShell";

export const router = createBrowserRouter(
  [
    {
      path: "/",
    element: <DashboardShell />,
    children: [
      { index: true, element: <PersonalModelMapPage /> },
      { path: "palace", element: <PersonalModelMapPage /> },
      { path: "you", element: <PersonalModelsPage /> },
      { path: "diary", element: <PersonalModelsPage /> },
      { path: "personal-models", element: <PersonalModelsPage /> },
      { path: "herd", element: <StatesPage /> },
      { path: "states", element: <StatesPage /> },
      { path: "runtime", element: <RuntimePage /> },
      { path: "chat", element: <ChatPage /> },
      { path: "questions", element: <QuestionsPage /> },
      { path: "providers", element: <ProvidersPage /> },
      { path: "models", element: <ModelsPage /> },
      { path: "skills", element: <SkillsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "gateway", element: <GatewayPage /> },
      { path: "cron", element: <CronPage /> },
      { path: "reflect", element: <ReflectPage /> },
      { path: "usage", element: <UsagePage /> },
      { path: "logs", element: <LogsPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "usage-logs", element: <UsageLogsPage /> },
    ],
  },
  ],
  { basename: "/dashboard" },
);
