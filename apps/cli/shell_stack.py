from __future__ import annotations

import os

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.filters import Condition, has_completions
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.containers import (
        ConditionalContainer,
        HSplit,
        VSplit,
        Window,
    )
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.layout.scrollable_pane import ScrollablePane
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.layout.menus import CompletionsMenu
    from prompt_toolkit.layout.processors import BeforeInput
    from prompt_toolkit.output.defaults import create_output
    from prompt_toolkit.output.vt100 import Vt100_Output
    from prompt_toolkit.styles import Style

    PROMPT_TOOLKIT_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - minimal env fallback
    PROMPT_TOOLKIT_AVAILABLE = False

    class Completion:
        def __init__(
            self,
            text: str,
            start_position: int = 0,
            display: str | None = None,
            display_meta: str | None = None,
        ) -> None:
            self.text = text
            self.start_position = start_position
            self.display = display or text
            self.display_meta = display_meta or ""

    class Completer:
        pass

    class Document:
        def __init__(self, text: str) -> None:
            self.text_before_cursor = text

        def get_word_before_cursor(self, WORD: bool = False) -> str:
            delimiter = " " if WORD else None
            return self.text_before_cursor.split(delimiter)[-1] if self.text_before_cursor else ""

    class FormattedText(list):
        pass

    class FileHistory:
        def __init__(self, filename: str) -> None:
            self.filename = filename

    class _BindingsHandle:
        def add(self, *_keys: str):
            def decorator(func):
                return func

            return decorator

    def KeyBindings() -> _BindingsHandle:
        return _BindingsHandle()

    class _Keys:
        BracketedPaste = "<bracketed-paste>"

    Keys = _Keys()
    has_completions = None

    class Style:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class PromptSession:
        def __init__(self, **_kwargs) -> None:
            pass

        def prompt(self, prompt_text: str, **_kwargs) -> str:
            return input(prompt_text)

    def create_output(*_args, **_kwargs):
        return None

    Vt100_Output = None
    Application = None
    Buffer = None
    BufferControl = None
    Condition = None
    BeforeInput = None
    ConditionalContainer = None
    CompletionsMenu = None
    Dimension = None
    FormattedTextControl = None
    HSplit = None
    Layout = None
    ScrollablePane = None
    VSplit = None
    Window = None


def prompt_toolkit_output_without_cpr():
    if not PROMPT_TOOLKIT_AVAILABLE:
        return None
    output = create_output()
    if not getattr(output, "responds_to_cpr", False) or Vt100_Output is None:
        return output
    stdout = getattr(output, "stdout", None)
    get_size = getattr(output, "get_size", None)
    if stdout is None or get_size is None:
        return output
    try:
        color_depth = output.get_default_color_depth()
    except Exception:
        color_depth = None
    try:
        return Vt100_Output(
            stdout=stdout,
            get_size=get_size,
            term=os.environ.get("TERM"),
            default_color_depth=color_depth,
            enable_cpr=False,
        )
    except Exception:
        return output


try:
    from rich.align import Align
    from rich.cells import cell_len as rich_cell_len
    from rich.console import Console
    from rich.console import Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - minimal env fallback
    RICH_AVAILABLE = False

    def rich_cell_len(value: str) -> int:
        return len(value)

    class Text(str):
        def __new__(cls, text: str, style: str | None = None):
            return str.__new__(cls, text)

        @property
        def plain(self) -> str:
            return str(self)

    class Panel:
        def __init__(
            self,
            renderable,
            *,
            title: str | None = None,
            subtitle: str | None = None,
            border_style: str | None = None,
            padding: tuple[int, int] | None = None,
        ) -> None:
            self.renderable = renderable
            self.title = title or ""
            self.subtitle = subtitle or ""

    def _render_plain(renderable) -> str:
        if isinstance(renderable, Text):
            return renderable.plain
        if isinstance(renderable, str):
            return renderable
        if isinstance(renderable, Panel):
            parts = [renderable.title] if renderable.title else []
            parts.append(_render_plain(renderable.renderable))
            if renderable.subtitle:
                parts.append(renderable.subtitle)
            return "\n".join(part for part in parts if part)
        return str(renderable)

    class Console:
        def __init__(self, **_kwargs) -> None:
            pass

        def clear(self, home: bool = False) -> None:
            return None

        def print(self, renderable) -> None:
            print(_render_plain(renderable))

    Align = None
    Group = None
    Table = None
    Live = None
