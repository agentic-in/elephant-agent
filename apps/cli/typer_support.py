from __future__ import annotations

from collections.abc import Sequence

import typer
from click.exceptions import ClickException, Exit as ClickExit


def _normalize_help_flag(argv: Sequence[str]) -> list[str]:
    """Replace ``-h`` with ``--help`` so it works as a short alias everywhere."""
    return ["--help" if arg == "-h" else arg for arg in argv]


def run_typer_app(
    app: typer.Typer,
    argv: Sequence[str] | None = None,
    *,
    prog_name: str,
) -> int:
    command = typer.main.get_command(app)
    resolved = _normalize_help_flag(argv) if argv is not None else None
    try:
        result = command.main(
            args=resolved,
            prog_name=prog_name,
            standalone_mode=False,
        )
    except ClickExit as exc:
        return int(exc.exit_code or 0)
    except ClickException as exc:
        exc.show()
        return 1
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code not in (None, 0):
            typer.echo(str(code), err=True)
            return 1
        return 0
    return int(result or 0)


__all__ = ["run_typer_app"]
