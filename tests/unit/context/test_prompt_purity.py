"""R1 prompt-purity guard: no runtime ids leak into the rendered prompt.

This test protects the invariant set in docs/system-design/system-layer-model.md
(184): the foreground agent sees human-readable content, not runtime-owned
identifiers that it cannot dereference. If a regression lands that embeds a
`record:…`, `evidence:…`, `work-…`, `grounding:…`, `loop:…`, `step:…`, or a
raw `session-…`/`episode:…` into the prompt render, this test will catch it.

The assertion runs against a representative assembled prompt (one with all the
non-trivial layers populated) rather than every permutation — the renderer is
a single switch, so one covering fixture is enough.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from types import SimpleNamespace
import unittest

from packages.context import (
    ContextRuntime,
    LayeredContextPlanner,
    MarkdownPromptRenderer,
)
from packages.contracts.layers import Episode
from packages.contracts.runtime import RecallEvidence


_FORBIDDEN_ID_PATTERNS = (
    re.compile(r"\brecord:[A-Za-z0-9:_.-]+"),
    re.compile(r"\bmemory-[0-9]+"),
    re.compile(r"\bmemory:[A-Za-z0-9:_.-]+"),
    re.compile(r"\bgrounding[-:][A-Za-z0-9:_.-]+"),
    re.compile(r"\bwork[-:][0-9]+"),
    re.compile(r"\bwork_item:[A-Za-z0-9:_.-]+"),
    re.compile(r"\bloop:[A-Za-z0-9:_.-]+"),
    re.compile(r"\bstep:[A-Za-z0-9:_.-]+"),
    re.compile(r"\bsession-[0-9]+"),
    re.compile(r"\bepisode:[A-Za-z0-9:_.-]+"),
    re.compile(r"\bprofile:pm-[0-9]+"),
)


def _session() -> Episode:
    return Episode(
        episode_id="session-xyz",
        state_id="state:test",
        personal_model_id="pm-foo",
        entry_surface="test",
        elephant_id="elephant-alpha",
        status="open",
        started_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        interruption_state="resume-after-gap",
    )


def _work_items() -> tuple[SimpleNamespace, ...]:
    return (
        SimpleNamespace(
            work_item_id="work-42",
            session_id="session-xyz",
            title="Finish the release review",
            status="active",
            priority="high",
            dependencies=(),
            evidence_refs=(),
        ),
    )


def _memories() -> tuple[RecallEvidence, ...]:
    ts = datetime(2026, 4, 29, tzinfo=timezone.utc)
    return (
        RecallEvidence(
            evidence_id="evidence-1",
            episode_id="session-xyz",
            kind="summary",
            content="The previous turn asked us to pause the deploy until a review finished.",
            created_at=ts,
            work_item_ids=("work-42",),
        ),
        RecallEvidence(
            evidence_id="evidence-2",
            episode_id="session-xyz",
            kind="decision",
            content="Decide to keep the current deploy strategy with extra manual gates.",
            created_at=ts,
            work_item_ids=("work-42",),
        ),
    )


class PromptPurityTest(unittest.TestCase):
    def test_rendered_prompt_has_no_runtime_ids(self) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:preserve continuity",),
        )
        detailed = runtime.assemble_detailed(
            _session(),
            _work_items(),
            _memories(),
            recent_loop_context=("user: continue with the release review",),
        )
        prompt = detailed.rendered_prompt
        for pattern in _FORBIDDEN_ID_PATTERNS:
            match = pattern.search(prompt)
            self.assertIsNone(
                match,
                msg=f"runtime id matching {pattern.pattern!r} leaked into rendered prompt: "
                f"match={match.group(0) if match else None}",
            )

    def test_prompt_contains_human_readable_titles_and_content(self) -> None:
        """Confirm that the purged ids were replaced by titles / content.

        Otherwise a future regression could silently delete all context and
        still pass the purity test.
        """
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:preserve continuity",),
        )
        detailed = runtime.assemble_detailed(
            _session(),
            _work_items(),
            _memories(),
            recent_loop_context=("user: continue with the release review",),
        )
        prompt = detailed.rendered_prompt
        self.assertIn("Finish the release review", prompt)  # work title
        self.assertIn("The previous turn asked us to pause the deploy", prompt)  # evidence content
        self.assertIn("continue with the release review", prompt)  # loop content
