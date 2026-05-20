from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from apps.api.api_runtime_chat_section import _chat_runtime_traces


@dataclass(frozen=True)
class _Episode:
    episode_id: str
    started_at: str = "2026-05-20T00:00:00Z"
    status: str = "open"


@dataclass(frozen=True)
class _Loop:
    loop_id: str
    episode_id: str
    started_at: str


@dataclass(frozen=True)
class _Step:
    step_id: str
    loop_id: str
    episode_id: str
    sequence: int
    action: str
    created_at: str
    status: str = "completed"
    summary: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


class ChatRuntimeTraceTests(unittest.TestCase):
    def test_chat_trace_caps_timeline_and_does_not_duplicate_steps_inside_loops(self) -> None:
        episode = _Episode("episode-1")
        loops = tuple(_Loop(f"loop-{index}", episode.episode_id, f"2026-05-20T00:{index:02d}:00Z") for index in range(50))
        steps = {
            loop.loop_id: tuple(
                _Step(
                    step_id=f"{loop.loop_id}-step-{offset}",
                    loop_id=loop.loop_id,
                    episode_id=episode.episode_id,
                    sequence=offset,
                    action="call_model",
                    created_at=f"{loop.started_at}.{offset}",
                    metadata={"assistant_response": f"answer {loop.loop_id} {offset}"},
                )
                for offset in range(6)
            )
            for loop in loops
        }

        trace = _chat_runtime_traces(
            episodes=(episode,),
            loops_by_episode={episode.episode_id: loops},
            steps_by_loop=steps,
        )[0]

        self.assertEqual(trace["loop_count"], 50)
        self.assertEqual(trace["step_count"], 300)
        self.assertEqual(len(trace["loops"]), 24)
        self.assertTrue(trace["loops_truncated"])
        self.assertNotIn("steps", trace["loops"][0])
        self.assertEqual(len(trace["timeline"]), 120)
        self.assertTrue(trace["timeline_truncated"])
        self.assertEqual(trace["timeline_omitted_steps"], 180)


if __name__ == "__main__":
    unittest.main()
