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

export const navigation: readonly NavigationItem[] = [
  {
    to: "/",
    code: "YOU",
    cluster: "Personal",
    label: "You",
    eyebrow: "Personal Model",
    title: "Personal Model",
    detail: "What Elephant Agent understands about you, organized by four lenses — identity, world, pulse, and journey.",
    primary: true,
  },
  {
    to: "/diary",
    code: "DRY",
    cluster: "Personal",
    label: "Diary",
    eyebrow: "How Elephant Agent sees you",
    title: "Diary",
    detail: "What Elephant Agent has picked up about you so far. Nothing here is fixed — it shifts as we keep talking.",
    primary: true,
  },
  {
    to: "/herd",
    code: "CLN",
    cluster: "Personal",
    label: "Herd",
    eyebrow: "Continuity lines",
    title: "Herd",
    detail: "The named herd you can open and return to — each one a thread of Elephant Agent you've kept steady over time.",
    primary: true,
  },
  {
    to: "/chat",
    code: "CHT",
    cluster: "Personal",
    label: "Chat",
    eyebrow: "Pick up the thread",
    title: "Talk with Elephant Agent",
    detail: "A place to keep talking with Elephant Agent. Choose an elephant and continue with the people, projects, risks, and decisions already in view.",
  },
  {
    to: "/questions",
    code: "QST",
    cluster: "Personal",
    label: "Curiosity",
    eyebrow: "What Elephant Agent may ask",
    title: "Curiosity",
    detail: "Lens/topic-bound questions Elephant Agent may ask only when the answer would improve future help.",
  },
  {
    to: "/runtime",
    code: "RUN",
    cluster: "Runtime",
    label: "History",
    eyebrow: "Your history",
    title: "Conversation history",
    detail: "Every conversation Elephant Agent has held with you, step by step — for when you want to look back and see how a thread unfolded.",
  },
  {
    to: "/usage",
    code: "USG",
    cluster: "System",
    label: "Usage",
    eyebrow: "What your Elephant Agent spent",
    title: "Usage",
    detail: "A calm ledger of what it took to keep your Elephant Agent alive today — tokens, models, and trends, in one quiet view.",
  },
  {
    to: "/providers",
    code: "PRV",
    cluster: "System",
    label: "Providers",
    eyebrow: "Where Elephant Agent thinks from",
    title: "Providers",
    detail: "The models and embeddings your Elephant Agent leans on to stay sharp, ground its memory, and feel present when you return.",
  },
  {
    to: "/models",
    code: "MDL",
    cluster: "System",
    label: "Models",
    eyebrow: "Choose the voice",
    title: "Models",
    detail: "Shape how your Elephant Agent speaks and thinks — choose the model it reaches for, and make sure the path home is clear.",
  },
  {
    to: "/skills",
    code: "SKL",
    cluster: "System",
    label: "Skills",
    eyebrow: "What Elephant Agent knows how to do",
    title: "Skills",
    detail: "The small crafts your Elephant Agent can lean on — switch them on as it grows into your rhythms, leave them off until the moment fits.",
  },
  {
    to: "/tools",
    code: "TLS",
    cluster: "System",
    label: "Tools",
    eyebrow: "What Elephant Agent can reach for",
    title: "Tools",
    detail: "The hands your Elephant Agent uses in the world — kept visible, so nothing it touches is a surprise.",
  },
  {
    to: "/gateway",
    code: "GTW",
    cluster: "System",
    label: "Messaging",
    eyebrow: "Where Elephant Agent meets you",
    title: "Messaging apps",
    detail: "Let your Elephant Agent reach you in the places you already live — Feishu, Discord, WeChat, and more — without losing its thread.",
  },
  {
    to: "/cron",
    code: "CRN",
    cluster: "System",
    label: "Jobs",
    eyebrow: "Scheduled jobs",
    title: "Jobs",
    detail: "The scheduled work your Elephant Agent can run on its own — nudges, reminders, reviews, and recurring prompts.",
  },
  {
    to: "/reflect",
    code: "RFL",
    cluster: "System",
    label: "Reflect",
    eyebrow: "Background reflect agents",
    title: "Reflect",
    detail: "Background agents that learn from conversations, consolidate facts, write diary entries, audit your Personal Model, and maintain skill matching.",
  },
  {
    to: "/settings",
    code: "SET",
    cluster: "System",
    label: "Settings",
    eyebrow: "The shape around Elephant Agent",
    title: "Settings",
    detail: "The quiet preferences that hold your Elephant Agent's world together — adjust the edges without touching what it remembers.",
    advanced: true,
  },
  {
    to: "/logs",
    code: "LGS",
    cluster: "System",
    label: "Logs",
    eyebrow: "When something feels off",
    title: "Logs",
    detail: "The local trail your Elephant Agent leaves behind — a place to look when a surface stumbles and you want to understand why.",
    advanced: true,
  },
  {
    to: "/usage-logs",
    code: "LOG",
    cluster: "System",
    label: "Usage & Logs",
    eyebrow: "Spend and signal",
    title: "Usage & Logs",
    detail: "A single calm view of what it took to keep your Elephant Agent alive, and what to read when a surface stumbles.",
    advanced: true,
  },
];

function collectNavigationItems(paths: readonly string[]): readonly NavigationItem[] {
  return paths.map((to) => {
    const item = navigation.find((candidate) => candidate.to === to);
    if (!item) {
      throw new Error(`Missing dashboard navigation item for route "${to}".`);
    }
    return item;
  });
}

export const navigationGroups: readonly NavigationGroup[] = [
  {
    label: "Personal",
    detail: "Your Personal Model, diary, questions, herd, and conversation.",
    items: collectNavigationItems(["/", "/diary", "/chat", "/questions", "/herd"]),
  },
  {
    label: "Agent",
    detail: "The model it thinks in, the skills it knows, the tools it can reach for.",
    items: collectNavigationItems(["/models", "/skills", "/tools", "/usage"]),
  },
  {
    label: "System",
    detail: "Runtime history, messaging, sources, and local settings.",
    items: collectNavigationItems(["/gateway", "/cron", "/reflect", "/runtime", "/settings"]),
  },
];

const routeAliases = new Map<string, string>([
  ["/personal-models", "/diary"],
  ["/you", "/diary"],
  ["/states", "/herd"],
  ["/usage-logs", "/usage"],
  ["/palace", "/"],
]);

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
