from __future__ import annotations

from pathlib import Path
from unittest import mock

from apps.cli.runtime import CliRuntime
from packages.skills import FetchedSkillBundle
from tests.e2e.cli.cli_surface_test_base import CliSurfaceE2ETestBase


class CliSurfaceSkillsE2ETest(CliSurfaceE2ETestBase):
    def test_launcher_skills_surface_views_local_skill(self) -> None:
        viewed = self._run_launcher("skills", "view", "search-skill")
        self.assertIn("Elephant Agent skills", viewed.stdout)
        self.assertIn("Detail for Search Skill.", viewed.stdout)
        self.assertIn("skill_id · search-skill", viewed.stdout)
        self.assertIn("Search before editing.", viewed.stdout)

    def test_runtime_skill_install_persists_provenance_and_distinguishes_refresh_from_migration(
        self,
    ) -> None:
        runtime = CliRuntime.create(state_dir=self.state_dir)
        session = runtime.create_elephant(elephant_id="atlas")
        github_dir = self.root / "remote-github"
        github_dir.mkdir()
        (github_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Search Skill",
                    "skill_id: search-skill",
                    "description: GitHub packaged search skill.",
                    "---",
                    "",
                    "# Search Skill",
                    "",
                    "Use GitHub search guidance.",
                ]
            ),
            encoding="utf-8",
        )
        clawhub_dir = self.root / "remote-clawhub"
        clawhub_dir.mkdir()
        (clawhub_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Search Skill",
                    "skill_id: search-skill",
                    "description: ClawHub packaged search skill.",
                    "---",
                    "",
                    "# Search Skill",
                    "",
                    "Use ClawHub search guidance.",
                ]
            ),
            encoding="utf-8",
        )

        with mock.patch.object(
            runtime.skill_search_hub,
            "fetch",
            side_effect=[
                FetchedSkillBundle(
                    skill_id="search-skill",
                    source_id="github",
                    source_label="GitHub",
                    reference="github:openai/skills/search-skill",
                    install_reference="github:openai/skills/search-skill",
                    package_path=str(github_dir),
                    trust_level="trusted",
                    metadata={
                        "canonical_id": "openai/skills/search-skill",
                        "repo_url": "https://github.com/openai/skills",
                    },
                ),
                FetchedSkillBundle(
                    skill_id="search-skill",
                    source_id="skills-sh",
                    source_label="Skills.sh",
                    reference="skills-sh:openai/skills/search-skill",
                    install_reference="github:openai/skills/search-skill",
                    package_path=str(github_dir),
                    trust_level="trusted",
                    metadata={
                        "canonical_id": "openai/skills/search-skill",
                        "detail_url": "https://skills.sh/openai/skills/search-skill",
                        "repo_url": "https://github.com/openai/skills",
                    },
                ),
                FetchedSkillBundle(
                    skill_id="search-skill",
                    source_id="clawhub",
                    source_label="ClawHub",
                    reference="clawhub:search-skill",
                    install_reference="clawhub:search-skill",
                    package_path=str(clawhub_dir),
                    trust_level="community",
                    metadata={
                        "canonical_id": "search-skill",
                        "detail_url": "https://clawhub.ai/skills/search-skill",
                        "version": "2.0.0",
                    },
                ),
            ],
        ):
            installed = runtime.install_skill_source(
                "github:openai/skills/search-skill",
                session_id=session.episode_id,
            )
            refreshed = runtime.install_skill_source(
                "skills-sh:openai/skills/search-skill",
                session_id=session.episode_id,
            )
            migrated = runtime.install_skill_source(
                "clawhub:search-skill",
                session_id=session.episode_id,
            )

        inspected = runtime.inspect_skill("search-skill", session_id=session.episode_id)

        self.assertEqual(installed.metadata.get("install_action"), "install")
        self.assertEqual(installed.metadata.get("source_id"), "github")
        self.assertEqual(refreshed.metadata.get("install_action"), "refresh")
        self.assertEqual(refreshed.metadata.get("source_id"), "skills-sh")
        self.assertEqual(migrated.metadata.get("install_action"), "migrate")
        self.assertEqual(migrated.metadata.get("install_requester"), "operator")
        self.assertEqual(
            migrated.metadata.get("previous_install_reference"),
            "github:openai/skills/search-skill",
        )
        self.assertEqual(inspected.metadata.get("source_id"), "clawhub")
        self.assertEqual(inspected.metadata.get("trust_level"), "community")
        self.assertEqual(
            inspected.metadata.get("install_reference"), "clawhub:search-skill"
        )
        self.assertEqual(inspected.metadata.get("install_action"), "migrate")
        self.assertEqual(inspected.metadata.get("install_requester"), "operator")
        self.assertEqual(inspected.metadata.get("source_version"), "2.0.0")
        self.assertEqual(
            Path(inspected.entry_path).resolve(),
            (
                self.root
                / "skills"
                / "installed"
                / "clawhub"
                / "search-skill"
                / "SKILL.md"
            ).resolve(),
        )
        self.assertFalse(
            (self.root / "skills" / "installed" / "github" / "search-skill")
            .resolve()
            .exists()
        )

    def test_noninteractive_grow_surfaces_skill_management_guidance(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "aeon",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        searched_skills = self._run(
            "wake", "--message", "search skills for bounded retrieval"
        )
        installed_skill = self._run("wake", "--message", "install skill search-skill")
        listed_skills = self._run("wake", "--message", "what skills do you have?")

        self.assertIn(
            "execution · Use /skills search bounded retrieval",
            searched_skills.stdout,
        )
        self.assertIn(
            "execution · Use /skills install search-skill",
            installed_skill.stdout,
        )
        self.assertIn(
            "execution · I have built-in skill packages like Apple Notes",
            listed_skills.stdout,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
