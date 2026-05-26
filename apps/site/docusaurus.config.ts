import {themes as prismThemes} from "prism-react-renderer";
import type {Config} from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

const githubRepoUrl = "https://github.com/agentic-in/elephant-agent";
const githubReadmeUrl = `${githubRepoUrl}/blob/main/README.md`;
const siteDescription =
  "Agency-first personal AI that keeps judgment, evidence, questions, and growth with the person.";
const siteKeywords = [
  "agency-first personal AI",
  "personal-model-first AI",
  "personal AI",
  "proactive curiosity",
  "AI agent",
  "CLI AI agent",
  "Personal Model",
  "claim-aware recall",
  "context recovery",
  "Elephant Agent",
].join(", ");
const canonicalSiteUrl =
  process.env.DOCUSAURUS_CANONICAL_SITE_URL || "https://elephant.agentic-in.ai";
const deployContext = process.env.CONTEXT || process.env.NETLIFY_CONTEXT || "";
const isPreviewDeploy =
  deployContext === "deploy-preview" || deployContext === "branch-deploy";
const websiteStructuredData = JSON.stringify({
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Elephant Agent",
  description: siteDescription,
  inLanguage: "en",
  url: canonicalSiteUrl,
});
const themeMetadata: {content: string; name?: string; property?: string}[] = [
  {
    name: "theme-color",
    content: "#fbf7ef",
  },
  {
    name: "application-name",
    content: "Elephant Agent",
  },
  {
    name: "apple-mobile-web-app-title",
    content: "Elephant Agent",
  },
  {
    name: "format-detection",
    content: "telephone=no",
  },
  {
    name: "keywords",
    content: siteKeywords,
  },
  {
    property: "og:site_name",
    content: "Elephant Agent",
  },
  {
    property: "og:type",
    content: "website",
  },
  {
    name: "twitter:card",
    content: "summary_large_image",
  },
  {
    name: "twitter:image:alt",
    content: siteDescription,
  },
  {
    property: "og:image:alt",
    content: siteDescription,
  },
];

if (isPreviewDeploy) {
  themeMetadata.push(
    {
      name: "robots",
      content: "noindex, nofollow",
    },
    {
      name: "googlebot",
      content: "noindex, nofollow",
    }
  );
}

const config: Config = {
  title: "Elephant Agent",
  tagline: "Understands first. Gets curious at your pace.",
  favicon: "assets/brand/favicon.png",
  url: canonicalSiteUrl,
  baseUrl: process.env.DOCUSAURUS_BASE_URL || "/",
  trailingSlash: true,
  onBrokenLinks: "throw",
  onBrokenAnchors: "ignore",
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: "throw",
    },
  },
  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },
  headTags: [
    {
      tagName: "script",
      attributes: {
        type: "application/ld+json",
      },
      innerHTML: websiteStructuredData,
    },
  ],
  presets: [
    [
      "classic",
      {
        debug: false,
        docs: {
          sidebarPath: "./sidebars.ts",
          routeBasePath: "docs",
          exclude: ["system-design/**"],
        },
        blog: {
          routeBasePath: "blog",
          blogTitle: "Elephant Agent Blog",
          blogDescription: "Research, architecture, and progress from the Elephant Agent team and Agentic Intelligence Lab.",
          postsPerPage: 10,
          blogSidebarTitle: "Recent posts",
          blogSidebarCount: "ALL",
          authorsMapPath: "authors.yml",
        },
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],
  themes: ["@docusaurus/theme-mermaid"],
  themeConfig: {
    colorMode: {
      defaultMode: "light",
      disableSwitch: true,
      respectPrefersColorScheme: false,
    },
    image: "assets/brand/social-share-card.png",
    metadata: themeMetadata,
    navbar: {
      title: "Elephant Agent",
      logo: {
        src: "assets/brand/favicon.png",
        alt: "Elephant Agent elephant mark",
      },
      hideOnScroll: false,
      items: [
        {
          to: "/docs/",
          label: "Docs",
          position: "right",
        },
        {
          to: "/paper/",
          label: "Paper",
          position: "right",
        },
        {
          to: "/blog/",
          label: "Blog",
          position: "right",
        },
        {
          to: "/skillhub/",
          label: "Skills",
          position: "right",
        },
        {
          href: githubRepoUrl,
          label: "GitHub",
          position: "right",
          className: "navbar-link-cta",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Elephant Agent",
          className: "footer-col-brand",
          items: [
            {
              html: '<span class="footer-description">Agency-first personal AI that keeps judgment, evidence, questions, and growth with the person.</span>',
            },
          ],
        },
        {
          title: "Project",
          items: [
            {label: "Docs", to: "/docs/"},
            {label: "Paper", to: "/paper/"},
            {label: "Blog", to: "/blog/"},
          ],
        },
        {
          title: "Start",
          items: [
            {label: "Quickstart", to: "/#quickstart"},
            {label: "Install", to: "/docs/getting-started/installation/"},
            {label: "CLI reference", to: "/docs/reference/cli/"},
          ],
        },
        {
          title: "Community",
          items: [
            {label: "Skills", to: "/skillhub/"},
            {
              label: "GitHub",
              href: githubRepoUrl,
              target: "_blank",
              rel: "noreferrer",
            },
            {
              label: "README",
              href: githubReadmeUrl,
              target: "_blank",
              rel: "noreferrer",
            },
          ],
        },
      ],
      copyright: "&copy; 2026 ELEPHANT. Agentic Intelligence Lab.",
    },
    docs: {
      sidebar: {
        hideable: false,
        autoCollapseCategories: false,
      },
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
