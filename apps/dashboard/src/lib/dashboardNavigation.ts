import { isDesktopRuntime } from "./desktopBridge";

export type NavigationItem = {
  to: string;
  code: string;
  cluster: string;
  label: string;
  eyebrow: string;
  title: string;
  detail: string;
  advanced?: boolean;
  primary?: boolean;
};

export type NavigationGroup = {
  label: string;
  detail: string;
  items: readonly NavigationItem[];
};

const desktopMode = isDesktopRuntime();

const browserNavigation: readonly NavigationItem[] = [
  {
    to: "/",
    code: "YOU",
    cluster: "Personal",
    label: "You",
    eyebrow: "Personal Model",
    title: "Personal Model",
    detail: "What Elephant Agent understands about you, organized by identity, world, pulse, and journey.",
    primary: true,
  },
  {
    to: "/diary",
    code: "DRY",
    cluster: "Personal",
    label: "Diary",
    eyebrow: "How Elephant Agent sees you",
    title: "Diary",
    detail: "What Elephant Agent has picked up so far, with room to correct the read.",
    primary: true,
  },
  {
    to: "/herd",
    code: "CLN",
    cluster: "Personal",
    label: "Herd",
    eyebrow: "Continuity lines",
    title: "Herd",
    detail: "The named elephant lines you can open and return to.",
    primary: true,
  },
  {
    to: "/chat",
    code: "CHT",
    cluster: "Personal",
    label: "Chat",
    eyebrow: "Pick up the thread",
    title: "Talk with Elephant Agent",
    detail: "Choose an elephant and continue with the people, projects, risks, and decisions already in view.",
  },
  {
    to: "/sources",
    code: "SRC",
    cluster: "Personal",
    label: "Sources",
    eyebrow: "Context in minutes",
    title: "Sources",
    detail: "Import local projects and documents as evidence for background understanding.",
  },
  {
    to: "/questions",
    code: "QST",
    cluster: "Personal",
    label: "Curiosity",
    eyebrow: "What Elephant Agent may ask",
    title: "Curiosity",
    detail: "Lens/topic-bound questions that improve future help.",
  },
  {
    to: "/runtime",
    code: "RUN",
    cluster: "Runtime",
    label: "History",
    eyebrow: "Your history",
    title: "Conversation history",
    detail: "Every conversation Elephant Agent has held, step by step.",
  },
  {
    to: "/usage",
    code: "USG",
    cluster: "System",
    label: "Usage",
    eyebrow: "What your Elephant Agent spent",
    title: "Usage",
    detail: "A ledger of tokens, models, and trends.",
  },
  {
    to: "/providers",
    code: "PRV",
    cluster: "System",
    label: "Providers",
    eyebrow: "Where Elephant Agent thinks from",
    title: "Providers",
    detail: "The models and embeddings your Elephant Agent uses.",
  },
  {
    to: "/models",
    code: "MDL",
    cluster: "System",
    label: "Models",
    eyebrow: "Choose the voice",
    title: "Models",
    detail: "Shape how your Elephant Agent speaks and thinks.",
  },
  {
    to: "/skills",
    code: "SKL",
    cluster: "System",
    label: "Skills",
    eyebrow: "What Elephant Agent knows how to do",
    title: "Skills",
    detail: "The small crafts your Elephant Agent can lean on.",
  },
  {
    to: "/tools",
    code: "TLS",
    cluster: "System",
    label: "Tools",
    eyebrow: "What Elephant Agent can reach for",
    title: "Tools",
    detail: "The hands your Elephant Agent uses in the world.",
  },
  {
    to: "/gateway",
    code: "GTW",
    cluster: "System",
    label: "Messaging",
    eyebrow: "Where Elephant Agent meets you",
    title: "Messaging apps",
    detail: "Connect IM delivery without losing the thread.",
  },
  {
    to: "/cron",
    code: "CRN",
    cluster: "System",
    label: "Job",
    eyebrow: "Scheduled jobs",
    title: "Jobs",
    detail: "Scheduled work Elephant Agent can run on its own.",
  },
  {
    to: "/reflect",
    code: "RFL",
    cluster: "System",
    label: "Reflect",
    eyebrow: "Background understanding",
    title: "Reflect",
    detail: "Background agents that consolidate facts, questions, diary entries, and skill affinities.",
  },
  {
    to: "/settings",
    code: "SET",
    cluster: "System",
    label: "Settings",
    eyebrow: "The shape around Elephant Agent",
    title: "Settings",
    detail: "Local preferences and configuration.",
    advanced: true,
  },
  {
    to: "/logs",
    code: "LGS",
    cluster: "System",
    label: "Logs",
    eyebrow: "When something feels off",
    title: "Logs",
    detail: "The local trail your Elephant Agent leaves behind.",
    advanced: true,
  },
  {
    to: "/usage-logs",
    code: "LOG",
    cluster: "System",
    label: "Usage & Logs",
    eyebrow: "Spend and signal",
    title: "Usage & Logs",
    detail: "A combined view of spend and runtime signal.",
    advanced: true,
  },
];

const desktopNavigation: readonly NavigationItem[] = [
  {
    to: "/",
    code: "PRF",
    cluster: "Setup",
    label: "Profile Builder",
    eyebrow: "Context in minutes",
    title: "Profile Builder",
    detail: "Create an elephant, import local context, and review the first claims/questions before entering the app.",
    primary: true,
  },
  {
    to: "/wake",
    code: "WAK",
    cluster: "Setup",
    label: "Wake",
    eyebrow: "Pick up the thread",
    title: "Wake",
    detail: "Talk with the active elephant using the local core and imported context.",
    primary: true,
  },
  {
    to: "/you",
    code: "YOU",
    cluster: "Setup",
    label: "You",
    eyebrow: "Personal Model",
    title: "You",
    detail: "Review identity, world, pulse, and journey claims.",
    primary: true,
  },
  {
    to: "/sources",
    code: "SRC",
    cluster: "Setup",
    label: "Sources",
    eyebrow: "Local context",
    title: "Sources",
    detail: "Import folders, repositories, Markdown, text, code, and config files as evidence.",
    primary: true,
  },
  {
    to: "/reflect",
    code: "RFL",
    cluster: "Understanding",
    label: "Reflect",
    eyebrow: "Background learning",
    title: "Reflect",
    detail: "Run manual, diary, dream, and source-import reflect jobs.",
  },
  {
    to: "/questions",
    code: "QST",
    cluster: "Understanding",
    label: "Curiosity",
    eyebrow: "Open questions",
    title: "Curiosity",
    detail: "See the questions that would sharpen future help.",
  },
  {
    to: "/activity",
    code: "ACT",
    cluster: "Understanding",
    label: "Activity",
    eyebrow: "Presence",
    title: "Activity",
    detail: "Core, worker, episode, step, and learning activity.",
  },
  {
    to: "/settings",
    code: "SET",
    cluster: "System",
    label: "Settings",
    eyebrow: "Local app",
    title: "Settings",
    detail: "Desktop, provider, and runtime configuration.",
  },
  {
    to: "/models",
    code: "MDL",
    cluster: "System",
    label: "Models",
    eyebrow: "Advanced",
    title: "Models",
    detail: "Model/provider details for advanced setup.",
    advanced: true,
  },
  {
    to: "/tools",
    code: "TLS",
    cluster: "System",
    label: "Tools",
    eyebrow: "Advanced",
    title: "Tools",
    detail: "Tool and MCP configuration.",
    advanced: true,
  },
  {
    to: "/providers",
    code: "PRV",
    cluster: "System",
    label: "Providers",
    eyebrow: "Advanced",
    title: "Providers",
    detail: "Provider and embedding setup.",
    advanced: true,
  },
  {
    to: "/skills",
    code: "SKL",
    cluster: "System",
    label: "Skills",
    eyebrow: "Advanced",
    title: "Skills",
    detail: "Skill registry and affinities.",
    advanced: true,
  },
  {
    to: "/gateway",
    code: "GTW",
    cluster: "System",
    label: "Messaging",
    eyebrow: "Advanced",
    title: "Messaging",
    detail: "Messaging integrations.",
    advanced: true,
  },
  {
    to: "/cron",
    code: "CRN",
    cluster: "System",
    label: "Jobs",
    eyebrow: "Advanced",
    title: "Jobs",
    detail: "Scheduled jobs.",
    advanced: true,
  },
  {
    to: "/usage",
    code: "USG",
    cluster: "System",
    label: "Usage",
    eyebrow: "Advanced",
    title: "Usage",
    detail: "Model and token usage.",
    advanced: true,
  },
  {
    to: "/logs",
    code: "LGS",
    cluster: "System",
    label: "Logs",
    eyebrow: "Advanced",
    title: "Logs",
    detail: "Local logs.",
    advanced: true,
  },
  {
    to: "/usage-logs",
    code: "LOG",
    cluster: "System",
    label: "Usage & Logs",
    eyebrow: "Advanced",
    title: "Usage & Logs",
    detail: "Usage and logs.",
    advanced: true,
  },
];

export const navigation: readonly NavigationItem[] = desktopMode ? desktopNavigation : browserNavigation;

function collectNavigationItems(paths: readonly string[]): readonly NavigationItem[] {
  return paths.map((to) => {
    const item = navigation.find((candidate) => candidate.to === to);
    if (!item) {
      throw new Error(`Missing dashboard navigation item for route "${to}".`);
    }
    return item;
  });
}

export const navigationGroups: readonly NavigationGroup[] = desktopMode
  ? [
      {
        label: "Start",
        detail: "Profile, Wake, You, and Sources.",
        items: collectNavigationItems(["/", "/wake", "/you", "/sources"]),
      },
      {
        label: "Understand",
        detail: "Background learning, questions, and activity.",
        items: collectNavigationItems(["/reflect", "/questions", "/activity"]),
      },
      {
        label: "System",
        detail: "Local app settings and advanced tools.",
        items: collectNavigationItems(["/settings", "/models", "/tools"]),
      },
    ]
  : [
      {
        label: "Personal",
        detail: "Your Personal Model, diary, questions, herd, sources, and conversation.",
        items: collectNavigationItems(["/", "/diary", "/chat", "/sources", "/questions", "/herd"]),
      },
      {
        label: "Agent",
        detail: "The model it thinks in, the skills it knows, the tools it can reach for.",
        items: collectNavigationItems(["/models", "/skills", "/tools", "/usage"]),
      },
      {
        label: "System",
        detail: "Runtime history, messaging, reflect, and local settings.",
        items: collectNavigationItems(["/gateway", "/cron", "/reflect", "/runtime", "/settings"]),
      },
    ];

const desktopRouteAliases = new Map<string, string>([
  ["/profile-builder", "/"],
  ["/chat", "/wake"],
  ["/diary", "/you"],
  ["/personal-models", "/you"],
  ["/runtime", "/activity"],
  ["/states", "/you"],
  ["/herd", "/you"],
  ["/palace", "/you"],
]);

const browserRouteAliases = new Map<string, string>([
  ["/personal-models", "/diary"],
  ["/you", "/diary"],
  ["/states", "/herd"],
  ["/usage-logs", "/usage"],
  ["/palace", "/"],
]);

const routeAliases = desktopMode ? desktopRouteAliases : browserRouteAliases;

export function resolveNavigation(to: string): NavigationItem {
  const canonical = routeAliases.get(to) ?? to;
  const exact = navigation.find((item) => item.to === canonical);
  if (exact) {
    return exact;
  }
  throw new Error(`Missing dashboard navigation item for route "${to}".`);
}

export function resolveNavigationGroup(to: string): NavigationGroup | null {
  const item = resolveNavigation(to);
  return navigationGroups.find((group) => group.items.some((candidate) => candidate.to === item.to)) ?? null;
}
