import React, {useEffect, useRef, useState} from "react";
import Head from "@docusaurus/Head";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";

import {githubRepoUrl} from "../components/siteData";
import {useLandingEffects} from "../components/useLandingEffects";

const installCommand = "curl -fsSL https://elephant.agentic-in.ai/install.sh | bash";
const releaseUrl = `${githubRepoUrl}/releases/latest`;
const pageTitle = "L4 Personal AI for Human Growth";
const pageTitleWithSite = `${pageTitle} | Elephant Agent`;
const pageDescription =
  "Elephant Agent is a Mother Elephant that grows to understand you, then helps shape living Paths with Learning Summaries across work, health, habits, learning, relationships, and long-term growth.";
const pageKeywords = [
  "human-first personal AI",
  "L4 personal AI",
  "human growth AI",
  "AI for humans",
  "agency-first personal AI",
  "personal-model-first AI",
  "personal AI paths",
  "AI learning loop",
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
    title: "Home starts from the person",
    body:
      "The recommended surface starts with what Mother understands, what is alive now, and what might deserve the next Path.",
    image: "/assets/screenshots/macos-home.jpg",
    alt: "Elephant Agent macOS Home screen with Personal Model map",
  },
  {
    eyebrow: "Wake",
    title: "Talk to Mother",
    body:
      "Wake is the daily chat surface. It carries the same Mother Elephant forward instead of starting every session from a blank prompt.",
    image: "/assets/screenshots/macos-wake.jpg",
    alt: "Elephant Agent Wake chat surface",
  },
  {
    eyebrow: "Paths",
    title: "Long-running arcs become visible",
    body:
      "A Path can be a codebase, fitness plan, habit reset, learning arc, relationship repair, or any direction you want to keep moving.",
    image: "/assets/screenshots/macos-home.jpg",
    alt: "Elephant Agent macOS Home screen as the entry to living Paths",
  },
  {
    eyebrow: "Personal Model",
    title: "Understanding stays correctable",
    body:
      "Identity, World, Pulse, and Journey stay visible so the user can inspect what Mother thinks she understands.",
    image: "/assets/screenshots/macos-personal-model.jpg",
    alt: "Elephant Agent Personal Model map",
  },
  {
    eyebrow: "Herd",
    title: "Baby elephants help with bounded Steps",
    body:
      "Mother can bring in babies when useful, while the user still sees the assignments, limits, and results.",
    image: "/assets/screenshots/macos-herd.jpg",
    alt: "Elephant Agent Herd screen",
  },
  {
    eyebrow: "Calendar",
    title: "Routines and long-running work stay inspectable",
    body:
      "Reminders, routines, and scheduled agent work remain visible instead of becoming hidden background automation.",
    image: "/assets/screenshots/macos-calendar.jpg",
    alt: "Elephant Agent Calendar screen",
  },
  {
    eyebrow: "CLI",
    title: "Wake also works from the terminal",
    body:
      "Linux, cloud, SSH, and terminal-first macOS users can use the CLI as the daily terminal surface.",
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

const pathCards = [
  {
    title: "Work paths",
    body:
      "Repositories, research, writing, launches, and maintenance can still look like projects when that is useful.",
  },
  {
    title: "Life paths",
    body:
      "Fitness, weight loss, habits, learning, relationships, recovery, and personal resets should not be forced into issue language.",
  },
  {
    title: "Growth paths",
    body:
      "Mother can notice lessons, risks, pressure patterns, and stale directions, then help shape the next move.",
  },
];

const motherLoop = [
  {
    title: "Understands",
    body:
      "Mother starts from Identity, World, Pulse, and Journey instead of a blank prompt or a task queue.",
  },
  {
    title: "Shapes Paths",
    body:
      "She proposes living Paths and breaks them into Steps only after the direction is clear enough.",
  },
  {
    title: "Brings the Herd",
    body:
      "Baby elephants can take bounded Steps with explicit skills, runtime posture, and visible event trails.",
  },
  {
    title: "Returns to judgment",
    body:
      "Checkpoints and Learning Summaries bring decisions and understanding back to the human.",
  },
];

const learningLoopCards = [
  {
    title: "The baby explains the work",
    body:
      "Every completed Step returns what happened, why that approach was chosen, how it was done, and what context mattered.",
  },
  {
    title: "The human checks understanding",
    body:
      "The loop asks for an Understanding Check, so the person can say: I understand this Step before it disappears into Done.",
  },
  {
    title: "Mother learns what should carry forward",
    body:
      "Useful lessons become candidates for Journey, Path history, baby skills, and future Mother planning.",
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
    title: "Grows the human.",
    body:
      "Mother understands the person, shapes Paths, and keeps judgment, evidence, questions, and growth with the human.",
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
                  L4 personal AI for human growth.
                </p>
                <p>
                  Mother grows to understand you, then helps shape the Paths you want to move.
                </p>
                <div className="pill-row">
                  <span className="info-pill info-pill-highlight">Mother understands</span>
                  <span className="info-pill info-pill-highlight">Paths after understanding</span>
                  <span className="info-pill info-pill-highlight">Judgment stays yours</span>
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
                The four levels stay central: L1 executes, L2 carries context,
                L3 improves procedures, and L4 helps the human grow.
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

        <section id="paths" className="section section-rule">
          <div className="container">
            <div className="section-head">
              <div>
                <span className="label" data-reveal>
                  From understanding to Paths
                </span>
                <h2 data-reveal>Not just projects. Paths for life.</h2>
              </div>
              <p data-reveal>
                Once Mother understands enough, she can help turn work, health,
                learning, habits, relationships, research, and recovery into
                living Paths with visible Steps and Checkpoints.
              </p>
            </div>

            <div className="path-card-grid">
              {pathCards.map((card) => (
                <article key={card.title} className="path-card" data-reveal>
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="mother-loop" className="section section-rule">
          <div className="container">
            <div className="section-head">
              <div>
                <span className="label" data-reveal>
                  Mother loop
                </span>
                <h2 data-reveal>Chat stays simple. The shape stays visible.</h2>
              </div>
              <p data-reveal>
                You can talk to Mother in chat, answer Checkpoints when judgment
                matters, or drag Steps directly when Flow is the clearer surface.
              </p>
            </div>

            <div className="mother-loop-grid">
              {motherLoop.map((item, index) => (
                <article key={item.title} className="mother-loop-card" data-reveal>
                  <span className="mother-loop-index">{String(index + 1).padStart(2, "0")}</span>
                  <h3>{item.title}</h3>
                  <p>{item.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="learning-loop" className="section section-rule">
          <div className="container">
            <div className="section-head">
              <div>
                <span className="label" data-reveal>
                  Learning loop
                </span>
                <h2 data-reveal>Do more without thinking less.</h2>
              </div>
              <p data-reveal>
                A baby does not only mark work as done. It returns a Learning
                Summary, then asks for the human understanding needed to close
                the loop.
              </p>
            </div>

            <div className="path-card-grid">
              {learningLoopCards.map((card) => (
                <article key={card.title} className="path-card" data-reveal>
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="trust" className="section section-rule">
          <div className="container">
            <div className="section-head install-head">
              <div>
                <span className="label" data-reveal>
                  Trust modes
                </span>
                <h2 data-reveal>Two simple postures.</h2>
              </div>
              <p data-reveal>
                The product should feel clear at the chat box: Mother can ask
                first, or keep moving inside a trusted boundary.
              </p>
            </div>

            <div className="trust-grid" data-reveal>
              <article className="trust-card">
                <span className="card-kicker">Ask First</span>
                <h3>Mother plans, then asks.</h3>
                <p>
                  She can draft Paths, Steps, and Herd assignments, but waits
                  before applying important changes or taking external action.
                </p>
              </article>
              <article className="trust-card trust-card-strong">
                <span className="card-kicker">Trust Mother</span>
                <h3>Mother keeps moving within your boundaries.</h3>
                <p>
                  She can create Steps, move Flow state, and assign babies inside
                  trusted limits while risky choices still become Checkpoints.
                </p>
              </article>
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
                <h2 data-reveal>Mother in chat. Paths in view.</h2>
              </div>
              <p data-reveal>
                The macOS app is the default experience. CLI and Dashboard keep
                Linux, cloud, SSH, and terminal-first workflows supported without
                turning runtime controls into the product center.
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
                <h2 data-reveal>Start where your path is.</h2>
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
                <p>Wake, Paths, Personal Model, Herd, skills, messaging, calendar, usage, and settings in one native workspace.</p>
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
              <Link to="/docs/philosophy/paths/">Paths</Link>
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
                  questions, evidence, Paths, Steps, Checkpoints, skills, baby
                  elephants, local agents, and semantic recall.
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
