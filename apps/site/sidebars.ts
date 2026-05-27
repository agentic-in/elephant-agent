import type {SidebarsConfig} from "@docusaurus/plugin-content-docs";

const sidebars: SidebarsConfig = {
  docs: [
    "intro",
    {
      type: "category",
      label: "Start",
      collapsible: false,
      collapsed: false,
      items: [
        "getting-started/quickstart",
        "getting-started/installation",
        "getting-started/providers",
      ],
    },
    {
      type: "category",
      label: "Product Surfaces",
      collapsible: false,
      collapsed: false,
      items: [
        "user-interface/macos",
        "user-interface/cli-tui",
        "user-interface/dashboard",
      ],
    },
    {
      type: "category",
      label: "Understanding",
      collapsible: false,
      collapsed: false,
      items: [
        "philosophy/overview",
        "philosophy/paths",
        "philosophy/design-principles",
        "philosophy/system-model",
        "learning/correctable",
        "learning/proactive",
        "learning/background",
      ],
    },
    {
      type: "category",
      label: "Capacities",
      collapsible: false,
      collapsed: false,
      items: [
        "capacities/skills",
        "capacities/tools",
        "capacities/messaging",
        "capacities/embeddings",
        "capacities/memory",
        "capacities/continuity",
      ],
    },
    {
      type: "category",
      label: "Reference",
      collapsible: false,
      collapsed: false,
      items: ["reference/cli"],
    },
    {
      type: "category",
      label: "Help",
      collapsible: false,
      collapsed: false,
      items: ["help/troubleshooting"],
    },
  ],
};

export default sidebars;
