from __future__ import annotations

import unittest

from apps.cli.shell import (
    BRAND_LIGHT,
    BRAND_MUTED,
    Console,
    ELEPHANT_STAGE_ROWS,
    GROWTH_HIGHLIGHT_FG,
    HATCHLING_HEAD_ROWS,
    HATCHLING_STAGE_ROWS,
    RICH_AVAILABLE,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    TranscriptEntry,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    _centered_elephant_rows,
    _display_width,
)
from apps.cli.shell_ui import GROWTH_MARK_CANVAS_WIDTH, visual_centered_rows
from tests.unit.cli.shell_test_support import ShellTestBase, StubConsole as _StubConsole


class ShellVisualLayoutTest(ShellTestBase):
    def test_user_history_rows_expand_to_console_width(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        padded_prompt = shell._pad_history_line("› hello from wake shell")
        padded_meta = shell._pad_history_line("  sent just now")
        self.assertEqual(_display_width(padded_prompt), shell._history_row_width())
        self.assertEqual(_display_width(padded_meta), shell._history_row_width())
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="user",
                title="You",
                body="hello from wake shell",
                meta="sent just now",
            )
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        lines = plain.splitlines()
        self.assertEqual(len(lines), 2)
        if RICH_AVAILABLE:
            self.assertEqual(lines[0], padded_prompt)
            self.assertEqual(lines[1], padded_meta)
        else:
            self.assertEqual(lines[0], "hello from wake shell")
            self.assertEqual(lines[1], "sent just now")

    def test_growth_rows_use_gray_history_background_with_selective_yellow_text(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="growth",
                title="Elephant Agent",
                body="Something settled into the Personal Model — checkpoint 1 in Evidence I. I'll carry it forward.",
                meta="understanding · checkpoint",
            )
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        lines = plain.splitlines()
        self.assertEqual(len(lines), 2)
        if RICH_AVAILABLE:
            self.assertEqual(
                lines[0],
                shell._pad_history_line(
                    "› Something settled into the Personal Model — checkpoint 1 in Evidence I. I'll carry it forward."
                ),
            )
            self.assertEqual(
                lines[1], shell._pad_history_line("  understanding · checkpoint")
            )
            styles = {str(span.style) for span in rendered.spans}
            self.assertIn(f"{USER_HISTORY_FG} on {USER_HISTORY_BG}", styles)
            self.assertIn(f"{BRAND_MUTED} on {USER_HISTORY_BG}", styles)
            self.assertIn(f"{GROWTH_HIGHLIGHT_FG} on {USER_HISTORY_BG}", styles)
        else:
            self.assertEqual(
                lines[0],
                "Something settled into the Personal Model — checkpoint 1 in Evidence I. I'll carry it forward.",
            )
            self.assertEqual(lines[1], "understanding · checkpoint")

    def test_composer_divider_tracks_console_width_without_old_cap(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(140)
        divider = shell._composer_divider()
        self.assertEqual(len(divider), 139)
        self.assertGreater(len(divider), 116)

    def test_growth_stage_rows_use_one_current_elephant_logo(self) -> None:
        self.assertIs(SEED_STAGE_ROWS, ELEPHANT_STAGE_ROWS)
        self.assertIs(HATCHLING_STAGE_ROWS, ELEPHANT_STAGE_ROWS)
        self.assertIs(SCOUT_STAGE_ROWS, ELEPHANT_STAGE_ROWS)
        self.assertEqual(
            HATCHLING_HEAD_ROWS, ELEPHANT_STAGE_ROWS[: len(HATCHLING_HEAD_ROWS)]
        )

    def test_growth_stage_rows_fit_canonical_canvas(self) -> None:
        stage_rows = (
            ELEPHANT_STAGE_ROWS,
            SEED_STAGE_ROWS,
            HATCHLING_STAGE_ROWS,
            SCOUT_STAGE_ROWS,
            ELEPHANT_STAGE_ROWS,
        )
        for rows in stage_rows:
            self.assertLessEqual(
                max(len(row) for row in rows), GROWTH_MARK_CANVAS_WIDTH
            )
            self.assertTrue(all(row.strip() for row in rows))

    def test_elephant_stage_rows_keep_ascii_side_profile_readable(self) -> None:
        self.assertEqual(
            ELEPHANT_STAGE_ROWS,
            (
                "        /  \\~~~/  \\",
                "      (     ..    )---.",
                "       \\__     __/    \\",
                "        )|  /)         |",
                "       / | / /~~~\\    /",
                "      '-'-'     `---'",
            ),
        )

    def test_elephant_rows_match_current_ascii_logo(self) -> None:
        joined = "\n".join(ELEPHANT_STAGE_ROWS)
        self.assertIn(
            "/  \\~~~/  \\",
            joined,
            msg="ear and head line should survive terminal rendering",
        )
        self.assertIn("..", joined, msg="eye dots should survive terminal rendering")
        self.assertIn(
            "`---'", joined, msg="body tail line should survive terminal rendering"
        )
        centered_rows = _centered_elephant_rows()
        self.assertEqual(centered_rows, ELEPHANT_STAGE_ROWS)
        self.assertTrue(centered_rows[0].strip())
        self.assertTrue(centered_rows[1].strip())
        self.assertEqual(centered_rows[-1].strip(), ELEPHANT_STAGE_ROWS[-1].strip())

    def test_elephant_mark_renders_full_centered_stage(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_elephant_mark()
        if not RICH_AVAILABLE:
            plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            self.assertEqual(plain, "[Elephant Agent elephant]")
            return
        plain_lines = rendered.plain.splitlines()
        self.assertEqual(len(plain_lines), len(ELEPHANT_STAGE_ROWS))
        self.assertEqual(tuple(plain_lines), ELEPHANT_STAGE_ROWS)
        self.assertTrue(rendered.plain.strip())
        self.assertIn("/  \\~~~/  \\", rendered.plain)
        styles = {str(span.style) for span in rendered.spans}
        self.assertEqual(str(rendered.style), BRAND_LIGHT)
        self.assertFalse(styles)

    def test_elephant_rows_keep_sticker_optically_centered(self) -> None:
        centered = _centered_elephant_rows()
        self.assertEqual(centered, ELEPHANT_STAGE_ROWS)
        visible = [
            index for row in centered for index, cell in enumerate(row) if cell != " "
        ]
        self.assertTrue(visible)

    def test_growth_levels_reuse_unified_elephant_mark(self) -> None:
        shell = self._make_shell()
        elephant = shell._render_growth_mark("seed", level=0)
        seed = shell._render_growth_mark("seed", level=1)
        if not RICH_AVAILABLE:
            self.assertEqual(
                elephant.plain if hasattr(elephant, "plain") else str(elephant),
                "[Elephant Agent elephant]",
            )
            self.assertEqual(
                seed.plain if hasattr(seed, "plain") else str(seed),
                "[Elephant Agent seed]",
            )
            return
        elephant_lines = elephant.plain.splitlines()
        seed_lines = seed.plain.splitlines()
        self.assertEqual(elephant.plain, seed.plain)
        self.assertEqual(tuple(elephant_lines), ELEPHANT_STAGE_ROWS)
        self.assertEqual(tuple(seed_lines), ELEPHANT_STAGE_ROWS)

    def test_shell_frame_centers_elephant_mark_without_brand_column_drift(self) -> None:
        if not RICH_AVAILABLE:
            self.skipTest("rich is required for shell frame rendering")
        shell = self._make_shell()
        console = Console(width=120, record=True, force_terminal=True)
        console.print(shell._render_shell_frame())
        exported_lines = console.export_text(styles=False).splitlines()
        for row in ELEPHANT_STAGE_ROWS:
            self.assertTrue(
                any(row.strip() in line for line in exported_lines), msg=row
            )

    def test_growth_stage_rows_center_visible_pixels(self) -> None:
        for label, rows in (
            ("elephant", ELEPHANT_STAGE_ROWS),
            ("seed", SEED_STAGE_ROWS),
            ("elephant", HATCHLING_STAGE_ROWS),
            ("scout", SCOUT_STAGE_ROWS),
            ("elephant", HATCHLING_STAGE_ROWS),
        ):
            centered = visual_centered_rows(rows, width=GROWTH_MARK_CANVAS_WIDTH)
            self.assertEqual({len(row) for row in centered}, {GROWTH_MARK_CANVAS_WIDTH})
            visible = [
                index
                for row in centered
                for index, cell in enumerate(row)
                if cell != " "
            ]
            self.assertTrue(visible, msg=label)
            visible_center = (min(visible) + max(visible)) / 2
            canvas_center = (GROWTH_MARK_CANVAS_WIDTH - 1) / 2
            self.assertLessEqual(abs(visible_center - canvas_center), 0.5, msg=label)

    def test_shell_frame_uses_your_own_elephant_branding(self) -> None:
        shell = self._make_shell()
        frame = shell._render_shell_frame()
        self.assertIn("Elephant Agent", str(getattr(frame, "title", "")))
        self.assertIn(
            "Personal Model first · curious at your pace",
            str(getattr(frame, "subtitle", "")),
        )


if __name__ == "__main__":
    unittest.main()
