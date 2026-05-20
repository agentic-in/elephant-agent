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
- If the init evidence contains public links such as blog, LinkedIn, Twitter/X,
  portfolio, GitHub, or personal website URLs, inspect the user-provided URLs.
- Prefer tool.web.extract or tool.web.read for public pages. Use browser tools
  only when the page is dynamic, blocked from simple read, or needs a snapshot.
- Extract information that helps build the Personal Model: public bio, roles,
  projects, writing topics, tools, work domains, social handles, and stable
  preferences the user intentionally made public.
- Write useful findings as PM claims through tool.personal_model.update, after
  checking existing inventory/search results for duplicates.""",
    constraints="""\
- Do not browse beyond user-provided links unless a linked page clearly belongs
  to the same user and is needed to understand the provided profile.
- Do not store sensitive or protected attributes inferred from external pages.
- Do not store third-party claims, engagement metrics, comments, follower counts,
  ads, recommendations, or unrelated page chrome.
- If a URL cannot be read, create a question only when the missing information
  would materially improve the early Personal Model.""",
)
