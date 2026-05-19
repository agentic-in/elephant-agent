"""Interactive clarify support for the CLI shell."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from packages.contracts.runtime import ExecutionResult
from packages.tools.surfaces import ClarifySurface

from .shell_stack import (
    Condition,
    ConditionalContainer,
    FormattedText,
    FormattedTextControl,
    Window,
)

if TYPE_CHECKING:
    from .shell import ProductizedShell


@dataclass(slots=True)
class ShellClarifyState:
    question: str
    mode: str
    choices: tuple[str, ...]
    response_queue: Queue[str]


class ShellInteractiveClarifySurface(ClarifySurface):
    """Clarify surface that blocks tool execution until the shell receives input."""

    def __init__(self, shell: ProductizedShell, *, timeout_seconds: float = 120.0) -> None:
        self.shell = shell
        self.timeout_seconds = timeout_seconds

    def request_clarification(
        self,
        *,
        session_id: str,
        question: str,
        mode: str,
        choices: tuple[str, ...] = (),
    ) -> ExecutionResult:
        response_queue: Queue[str] = Queue(maxsize=1)
        state = ShellClarifyState(
            question=question,
            mode=mode,
            choices=tuple(choices),
            response_queue=response_queue,
        )
        with self.shell._clarify_lock:
            if self.shell._clarify_state is not None:
                raise RuntimeError("another clarification request is already pending")
            self.shell._clarify_state = state
        _invalidate_clarify(self.shell)
        try:
            try:
                answer = response_queue.get(timeout=self.timeout_seconds)
            except Empty:
                answer = (
                    "The user did not provide a response within the time limit. "
                    "Use your best judgement to make the choice and proceed."
                )
            return ExecutionResult(
                execution_id=f"clarify:{session_id}:{uuid4().hex[:8]}",
                episode_id=session_id,
                outcome="success",
                summary="\n".join(
                    [
                        f"question: {question}",
                        f"mode: {mode}",
                        f"user_response: {answer}",
                    ]
                ),
                side_effects=("clarify",),
            )
        finally:
            with self.shell._clarify_lock:
                if self.shell._clarify_state is state:
                    self.shell._clarify_state = None
            _invalidate_clarify(self.shell)


def set_clarify_invalidator(shell: ProductizedShell, invalidator: Callable[[], None] | None) -> None:
    shell._clarify_invalidator = invalidator


def route_clarify_answer(shell: ProductizedShell, raw_answer: str) -> bool:
    with shell._clarify_lock:
        state = shell._clarify_state
    if state is None:
        return False
    answer = _normalize_answer(raw_answer, state.choices)
    try:
        state.response_queue.put_nowait(answer)
    except Exception:
        return True
    _invalidate_clarify(shell)
    return True


def build_clarify_window(shell: ProductizedShell):
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: render_clarify_fragments(shell)),
            wrap_lines=True,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: shell._clarify_state is not None),
    )


def render_clarify_fragments(shell: ProductizedShell) -> FormattedText:
    with shell._clarify_lock:
        state = shell._clarify_state
    if state is None:
        return FormattedText([])
    fragments: list[tuple[str, str]] = [
        ("class:clarify-title", "Clarification needed 🤔"),
        ("", "\n"),
        ("class:clarify-question", state.question),
    ]
    if state.choices:
        fragments.append(("", "\n"))
        for index, choice in enumerate(state.choices, start=1):
            fragments.append(("class:clarify-choice", f"\n{index}. {choice}"))
        fragments.append(("", "\n"))
        fragments.append(
            (
                "class:clarify-hint",
                "Type a number or a custom answer, then press Enter.",
            )
        )
        fragments.append(("", "\n"))
    else:
        fragments.append(("", "\n"))
        fragments.append(("class:clarify-hint", "Type your answer, then press Enter."))
        fragments.append(("", "\n"))
    return FormattedText(fragments)


def _normalize_answer(raw_answer: str, choices: tuple[str, ...]) -> str:
    answer = raw_answer.strip()
    if choices and answer.isdigit():
        index = int(answer) - 1
        if 0 <= index < len(choices):
            return choices[index]
    return answer


def _invalidate_clarify(shell: ProductizedShell) -> None:
    invalidator = getattr(shell, "_clarify_invalidator", None)
    if invalidator is None:
        return
    try:
        invalidator()
    except Exception:
        return
