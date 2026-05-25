"""Init link learning feature — inspect user-provided public links."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="init_links",
    tools=(
        "tool.web.search",
        "tool.web.read",
        "tool.web.extract",
        "tool.browser.navigate",
        "tool.browser.snapshot",
        "tool.browser.scroll",
        "tool.browser.images",
    ),
    sop_fragment="""\
- Only use this feature during init/init_profile learning.
- Treat public links as first-class onboarding evidence, not as search queries.
- If the evidence includes a blog, LinkedIn, Twitter/X, portfolio, GitHub, or
  personal website URL, open the user-provided URL directly before making
  link-derived claims, questions, or skill affinities.
- Prefer tool.web.extract first, then tool.web.read. Use browser tools only when
  the page is dynamic, blocked from simple read/extract, or needs a snapshot.
- IMPORTANT: do not use tool.personal_model.search to "search for" a blog,
  LinkedIn, Twitter, or website URL. PM search only checks existing claims. It
  cannot open URLs, crawl pages, or learn from a website.
- Extract only information that helps Elephant understand the user: public bio,
  roles, projects, writing topics, tools, work domains, social handles, and
  stable preferences the user intentionally made public.
- After inspecting links, use PM search only to avoid duplicates before writing
  useful findings as PM claims.""",
    constraints="""\
- Do not browse beyond user-provided links unless a linked page clearly belongs
  to the same user and is needed to understand the provided profile.
- Do not store sensitive or protected attributes inferred from external pages.
- Do not store third-party claims, engagement metrics, comments, follower counts,
  ads, recommendations, or unrelated page chrome.
- If a URL cannot be read, create a question only when the missing information
  would materially improve the early Personal Model.""",
)
