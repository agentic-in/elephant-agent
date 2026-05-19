# ruff: noqa: E402

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.shell_clipboard import (
    build_path_attachment,
    build_text_attachment,
    compile_submission,
    import_system_clipboard,
)


class ShellClipboardTest(unittest.TestCase):
    def test_build_text_attachment_uses_compact_label_and_full_payload(self) -> None:
        attachment = build_text_attachment("alpha\nbeta")

        self.assertIsNotNone(attachment)
        assert attachment is not None
        self.assertEqual(attachment.kind, "text")
        self.assertEqual(attachment.display_label, "[Pasted Content 10 chars]")
        self.assertEqual(attachment.prompt_fragment, "[Clipboard text]\nalpha\nbeta")

    def test_build_path_attachment_uses_filename_but_preserves_absolute_path(
        self,
    ) -> None:
        attachment = build_path_attachment("./notes/design.md")

        self.assertIsNotNone(attachment)
        assert attachment is not None
        self.assertEqual(attachment.kind, "file")
        self.assertEqual(attachment.display_label, "[design.md]")
        self.assertTrue(attachment.prompt_fragment.startswith("@file:"))
        self.assertIn("design.md", attachment.prompt_fragment)
        self.assertTrue(Path(attachment.prompt_fragment.split(":", 1)[1]).is_absolute())

    def test_compile_submission_keeps_visible_summary_separate_from_full_prompt(
        self,
    ) -> None:
        text_attachment = build_text_attachment("full copied text payload")
        file_attachment = build_path_attachment("./notes/design.md")
        assert text_attachment is not None
        assert file_attachment is not None

        submission = compile_submission(
            "what is in the file and copy text",
            (file_attachment, text_attachment),
        )

        self.assertEqual(
            submission.display_command,
            "what is in the file and copy text\n\n[design.md]\n\nfull copied text payload",
        )
        self.assertIn("what is in the file and copy text", submission.command)
        self.assertIn("@file:", submission.command)
        self.assertIn("full copied text payload", submission.command)
        self.assertEqual(submission.event_payload["message"], submission.display_command)
        self.assertIn("full copied text payload", submission.event_payload["message"])

    def test_compile_submission_ignores_clipboard_attachments_for_slash_commands(
        self,
    ) -> None:
        attachment = build_text_attachment("keep out of slash command")
        assert attachment is not None

        submission = compile_submission("/status", (attachment,))

        self.assertEqual(submission.command, "/status")
        self.assertEqual(submission.display_command, "/status")
        self.assertEqual(submission.event_payload, {})

    def test_import_system_clipboard_reads_text_payload_from_macos_probe(self) -> None:
        completed = mock.Mock(stdout='{"kind":"text","text":"clipboard body"}\n', stderr="")
        with (
            mock.patch("apps.cli.shell_clipboard.sys.platform", "darwin"),
            mock.patch("apps.cli.shell_clipboard.subprocess.run", return_value=completed),
        ):
            attachments = import_system_clipboard(storage_dir=Path("/tmp/elephant-clipboard-test"))

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].display_label, "[Pasted Content 14 chars]")
        self.assertIn("clipboard body", attachments[0].prompt_fragment)

    def test_import_system_clipboard_reads_image_path_from_macos_probe(self) -> None:
        completed = mock.Mock(stdout='{"kind":"image","path":"/tmp/clip.png"}\n', stderr="")
        with (
            mock.patch("apps.cli.shell_clipboard.sys.platform", "darwin"),
            mock.patch("apps.cli.shell_clipboard.subprocess.run", return_value=completed),
        ):
            attachments = import_system_clipboard(storage_dir=Path("/tmp/elephant-clipboard-test"))

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].kind, "image")
        self.assertEqual(attachments[0].display_label, "[clip.png]")
        self.assertEqual(attachments[0].prompt_fragment, f"@image:{Path('/tmp/clip.png').resolve()}")


if __name__ == "__main__":
    unittest.main()
