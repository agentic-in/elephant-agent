import React, {useEffect, useRef, useState} from "react";
import Head from "@docusaurus/Head";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";

import {githubRepoUrl} from "../components/siteData";
import {useLandingEffects} from "../components/useLandingEffects";

const installCommand = "curl -fsSL https://elephant.agentic-in.ai/install.sh | bash";
const releaseUrl = `${githubRepoUrl}/releases/latest`;
const pageTitle = "Agency-First Personal AI";
const pageTitleWithSite = `${pageTitle} | Elephant Agent`;
const pageDescription =
  "Elephant Agent is agency-first personal AI with a correctable Personal Model, user-paced curiosity, and visible local runtime surfaces.";
const pageKeywords = [
  "agency-first personal AI",
  "personal-model-first AI",
  "personal AI agent",
  "macOS AI app",
  "proactive curiosity",
  "AI desktop app",
  "personal model",
  "CLI AI agent",
  "claim-aware recall",
  "Elephant Agent",
].join(", ");
const homepageUrl = "https://elephant.agentic-in.ai/";
const structuredData = JSON.stringify({
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Elephant Agent",
  alternateName: pageTitle,
  description: pageDescription,
  applicationCategory: "ProductivityApplication",
  operatingSystem: "macOS, Linux",
  url: homepageUrl,
  downloadUrl: releaseUrl,
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
  },
});

const productSlides = [
  {
    eyebrow: "macOS desktop app",
    title: "Home starts from the Personal Model",
    body:
      "The recommended surface shows the map, current context, and next useful question before it asks you to delegate work.",
    image: "/assets/screenshots/macos-home.jpg",
    alt: "Elephant Agent macOS Home screen with Personal Model map",
  },
  {
    eyebrow: "Wake",
    title: "Return to the same path",
    body:
      "Wake is the daily chat surface. It carries the same elephant forward instead of starting every session from a blank prompt.",
    image: "/assets/screenshots/macos-wake.jpg",
    alt: "Elephant Agent Wake chat surface",
  },
  {
    eyebrow: "Personal Model",
    title: "Correctable claims, not hidden memory",
    body:
      "Identity, World, Pulse, and Journey stay visible so the user can inspect what Elephant Agent thinks it knows.",
    image: "/assets/screenshots/macos-personal-model.jpg",
    alt: "Elephant Agent Personal Model map",
  },
  {
    eyebrow: "Providers",
    title: "Model choice stays explicit",
    body:
      "OpenAI, Ollama, Claude, Gemini, local embeddings, and other providers are visible settings, not hidden routing magic.",
    image: "/assets/screenshots/macos-providers.jpg",
    alt: "Elephant Agent model provider settings",
  },
  {
    eyebrow: "Skills and tools",
    title: "Capabilities stay governed",
    body:
      "Skills and operator tools sit around the Personal Model. Providers, MCP servers, and local actions remain inspectable.",
    image: "/assets/screenshots/macos-skills.jpg",
    alt: "Elephant Agent Skills screen",
  },
  {
    eyebrow: "CLI",
    title: "Wake also works from the terminal",
    body:
      "Linux, cloud, SSH, and terminal-first macOS users can use the CLI as the daily work surface.",
    image: "/assets/screenshots/cli-wake.jpg",
    alt: "Elephant Agent CLI Wake session",
  },
  {
    eyebrow: "Dashboard",
    title: "Visual inspection for remote setups",
    body:
      "Dashboard keeps Personal Model, evidence, jobs, skills, and runtime state visible outside the native app.",
    image: "/assets/screenshots/dashboard-personal-model.jpg",
    alt: "Elephant Agent Dashboard Personal Model map",
  },
];

const levelCards = [
  {
    level: "L1",
    title: "Executes tasks.",
    body:
      "Claude Code, Cursor, Devin, and Codex-style agents make execution cheaper and faster.",
  },
  {
    level: "L2",
    title: "Carries context.",
    body:
      "OpenClaw publicly emphasizes local agents, persistent memory, full system access, skills, plugins, and integrations.",
    product: "OpenClaw",
  },
  {
    level: "L3",
    title: "Improves procedures.",
    body:
      "Hermes Agent publicly positions itself around a self-improving learning loop, skill creation, recall, and user modeling.",
    product: "Hermes Agent",
  },
  {
    level: "L4",
    title: "Elephant Agent's product position.",
    body:
      "Personal AI should help the user keep judgment, evidence, questions, and growth.",
    product: "Elephant Agent",
    featured: true,
  },
];

export default function HomePage(): React.JSX.Element {
  useLandingEffects();
  const carouselRef = useRef<HTMLDivElement | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);

  const scrollToSlide = (index: number, behavior: ScrollBehavior = "smooth") => {
    const carousel = carouselRef.current;
    const slide = carouselRef.current?.children.item(index) as HTMLElement | null;
    if (!carousel || !slide) {
      return;
    }
    carousel.scrollTo({
      left: slide.offsetLeft - carousel.offsetLeft,
      behavior,
    });
    setActiveSlide(index);
  };

  useEffect(() => {
    const shouldReduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (shouldReduceMotion) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      setActiveSlide((current) => {
        const next = (current + 1) % productSlides.length;
        const carousel = carouselRef.current;
        const slide = carouselRef.current?.children.item(next) as HTMLElement | null;
        if (carousel && slide) {
          carousel.scrollTo({
            left: slide.offsetLeft - carousel.offsetLeft,
            behavior: "smooth",
          });
        }
        return next;
      });
    }, 4600);

    return () => window.clearInterval(timer);
  }, []);

  return (
    <Layout
      title={pageTitle}
      description={pageDescription}
    >
      <Head>
        <meta name="keywords" content={pageKeywords} />
        <meta property="og:title" content={pageTitleWithSite} />
        <meta property="og:description" content={pageDescription} />
        <meta property="og:url" content={homepageUrl} />
        <meta name="twitter:title" content={pageTitleWithSite} />
        <meta name="twitter:description" content={pageDescription} />
        <script type="application/ld+json">{structuredData}</script>
      </Head>
      <canvas id="dither-canvas" aria-hidden="true" />

      <main id="top" className="page-shell">
        <section className="manifesto-section">
          <div className="container">
            <div className="grid manifesto-grid">
              <div className="manifesto-title-wrap">
                <h1 className="manifesto-title" data-reveal>
                  <span>Elephant Agent</span>
                </h1>
              </div>

              <div className="manifesto-copy" data-reveal>
                <p className="manifesto-hook">
                  Do more without thinking less.
                </p>
                <p>
                  Agency-first personal AI, build around You.
                </p>
                <div className="pill-row">
                  <span className="info-pill info-pill-highlight">Personal Model first</span>
                  <span className="info-pill info-pill-highlight">Judgment stays yours</span>
                  <span className="info-pill info-pill-highlight">Curiosity at your pace</span>
                </div>
                <div className="cta-row">
                  <a className="btn-pill btn-pill-strong" href="#quickstart">
                    Install
                  </a>
                  <a
                    className="btn-pill"
                    href={githubRepoUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    GitHub
                  </a>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="levels" className="section section-rule">
          <div className="container">
            <div className="section-head product-position-head">
              <div>
                <span className="label" data-reveal>
                  Personal agent levels
                </span>
                <h2 data-reveal>Where Elephant Agent sits.</h2>
              </div>
              <p data-reveal>
                The cards state the product distinction. The image keeps the
                map easy to scan.
              </p>
            </div>

            <div className="level-card-grid" aria-label="Personal AI agent level definitions">
              {levelCards.map((card) => (
                <article
                  key={card.level}
                  className={`level-card${card.featured ? " level-card-featured" : ""}`}
                  data-reveal
                >
                  <span className="level-card-index">{card.level}</span>
                  {card.product ? <span className="level-card-product">{card.product}</span> : null}
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                </article>
              ))}
            </div>

            <div className="levels-visual" data-reveal>
              <img
                src="/assets/brand/agent-levels-positioning.png"
                alt="Four levels of personal AI with Elephant Agent positioned at L4"
              />
            </div>

          </div>
        </section>

        <section id="product" className="section section-rule">
          <div className="container">
            <div className="section-head">
              <div>
                <span className="label" data-reveal>
                  Product surfaces
                </span>
                <h2 data-reveal>Desktop first. Terminal when you need it.</h2>
              </div>
              <p data-reveal>
                The macOS app is the default experience. CLI and Dashboard keep
                Linux, cloud, SSH, and terminal-first workflows supported.
              </p>
            </div>

            <div
              ref={carouselRef}
              className="product-carousel"
              aria-label="Elephant Agent product screenshots"
            >
              {productSlides.map((slide) => (
                <article key={slide.title} className="product-slide" data-reveal>
                  <img src={slide.image} alt={slide.alt} loading="lazy" />
                  <div className="product-slide-copy">
                    <span className="card-kicker">{slide.eyebrow}</span>
                    <h3>{slide.title}</h3>
                    <p>{slide.body}</p>
                  </div>
                </article>
              ))}
            </div>

            <div className="product-carousel-dots" aria-label="Product carousel controls">
              {productSlides.map((slide, index) => (
                <button
                  key={slide.title}
                  type="button"
                  aria-label={`Show ${slide.eyebrow}`}
                  aria-current={activeSlide === index}
                  onClick={() => scrollToSlide(index)}
                />
              ))}
            </div>
          </div>
        </section>

        <section id="quickstart" className="section section-rule">
          <div className="container">
            <div className="section-head install-head">
              <div>
                <span className="label" data-reveal>
                  Install
                </span>
                <h2 data-reveal>Start where you work.</h2>
              </div>
              <p data-reveal>
                Use the macOS app for the full desktop workspace. Use CLI plus
                Dashboard for Linux, cloud, SSH, and terminal-first setups.
              </p>
            </div>

            <div className="install-strip" data-reveal>
              <div className="install-strip-primary">
                <span className="card-kicker">Recommended</span>
                <strong>macOS desktop app</strong>
                <p>Wake, Personal Model, providers, skills, tools, herd, messaging, reminders, and usage in one native workspace.</p>
                <a
                  className="btn-pill btn-pill-strong"
                  href={releaseUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download macOS app
                </a>
              </div>
              <div className="install-strip-command">
                <span className="card-kicker">Linux / Cloud</span>
                <strong>CLI + Dashboard</strong>
                <span className="command-snippet">{installCommand}</span>
                <p>Use <code>elephant dashboard --no-open</code> on remote machines.</p>
              </div>
            </div>

            <div className="quickstart-links" data-reveal>
              <Link to="/docs/getting-started/installation/">Install guide</Link>
              <Link to="/docs/getting-started/quickstart/">Quickstart</Link>
              <Link to="/docs/getting-started/providers/">Provider setup</Link>
              <Link to="/docs/reference/cli/">CLI reference</Link>
            </div>
          </div>
        </section>

        <section className="section section-rule">
          <div className="container">
            <div className="closing-grid">
              <div>
                <span className="label" data-reveal>
                  Open source
                </span>
                <h2 data-reveal>Personal AI should be inspectable.</h2>
              </div>
              <div className="closing-copy" data-reveal>
                <p>
                  Elephant Agent keeps the personal layer visible: claims,
                  questions, evidence, providers, reminders, logs, tools,
                  skills, local agents, and semantic recall.
                </p>
                <div className="cta-row">
                  <a className="btn-pill" href="#quickstart">
                    Install
                  </a>
                  <Link className="btn-pill" to="/docs/">
                    Documentation
                  </Link>
                  <a
                    className="btn-pill btn-pill-strong"
                    href={githubRepoUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    GitHub
                  </a>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
