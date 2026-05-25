"""Contract inventory tests for the Personal-Model-first public surface.

This test pins the public contract surface as emitted by
``packages.contracts.__all__``: four-lens Facts, OpenQuestions, semantic index
entries, and the core system-layer records. Anything that
referred to the old 6-component taxonomy (CoreMemory, BigFiveTraitSignal,
PersonalityStyleModel, PersonalKnowledge, EpisodicIndex, ProceduralMemory,
relationship projections) or the legacy Record/Grounding/Observation path has been
removed and should no longer be reachable.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import packages.contracts as contracts
from packages.capabilities import CAPABILITY_SURFACES
from packages.capabilities.runtime import (
    AuthProviderCapability,
    CapabilityDescriptor,
    CapabilityHealth,
    CapabilityRegistry,
    ContextCapability,
    DeliveryAdapterCapability,
    RecallCapability,
    ModelProviderCapability,
    SkillCapability,
    StorageBackendCapability,
    TelemetrySinkCapability,
    ToolCapability,
)
from packages.contracts import (
    ActiveProviderSelection,
    CONTRACT_SURFACES,
    Episode,
    Fact,
    GenerationProviderConfig,
    Loop,
    OpenQuestion,
    PersonalModel,
    SemanticIndexEntry,
    State,
    Step,
)


REMOVED_PUBLIC_CONTRACT_SURFACES = (
    "BigFiveTraitSignal",
    "PersonalityStyleModel",
    "CoreMemory",
    "PersonalKnowledge",
    "EpisodicIndex",
    "ProceduralMemory",
    "RelationshipMemory",
    "BigFiveProfile",
    "PersonalityProfile",
    "BIG_FIVE_AXES",
    "big_five_to_mapping",
    "blend_big_five",
    "parse_big_five_mapping",
    "Record",
    "Grounding",
    "MemoryEntry",
    "ReflectionProposal",
    "Observation",
    "ALLOWED_OBSERVATION_SOURCES",
    "ALLOWED_OBSERVATION_STATUSES",
)


class ContractInventoryTest(unittest.TestCase):
    def test_contract_inventory_matches_current_design(self) -> None:
        # The four-lens design keeps Facts and OpenQuestions as the public
        # durable understanding contract. Steps are evidence; semantic index
        # entries are retrieval metadata.
        self.assertEqual(
            CONTRACT_SURFACES,
            (
                "PersonalModel",
                "State",
                "Episode",
                "Loop",
                "Step",
                "SemanticIndexEntry",
                "Fact",
                "OpenQuestion",
                "GenerationProviderConfig",
                "ActiveProviderSelection",
            ),
        )

    def test_contract_root_all_includes_new_types(self) -> None:
        self.assertIn("Fact", contracts.__all__)
        self.assertIn("OpenQuestion", contracts.__all__)
        self.assertIn("ALLOWED_LENSES", contracts.__all__)
        self.assertIn("ALLOWED_FACT_SOURCES", contracts.__all__)

    def test_removed_public_surfaces_are_not_importable(self) -> None:
        for surface in REMOVED_PUBLIC_CONTRACT_SURFACES:
            with self.subTest(surface=surface):
                self.assertNotIn(surface, CONTRACT_SURFACES)
                self.assertNotIn(surface, contracts.__all__)
                self.assertFalse(hasattr(contracts, surface))

    def test_capability_inventory_is_stable(self) -> None:
        self.assertEqual(
            CAPABILITY_SURFACES,
            (
                "CapabilityDescriptor",
                "CapabilityHealth",
                "CapabilityRegistry",
                "RecallCapability",
                "ContextCapability",
                "ModelProviderCapability",
                "AuthProviderCapability",
                "ToolCapability",
                "SkillCapability",
                "DeliveryAdapterCapability",
                "StorageBackendCapability",
                "TelemetrySinkCapability",
            ),
        )

    def test_contract_shapes_are_dataclasses(self) -> None:
        for contract_type in (
            PersonalModel,
            State,
            Episode,
            Loop,
            Step,
            SemanticIndexEntry,
            Fact,
            OpenQuestion,
            GenerationProviderConfig,
            ActiveProviderSelection,
        ):
            self.assertTrue(is_dataclass(contract_type), contract_type.__name__)

    def test_episode_exposes_session_id_compatibility_alias(self) -> None:
        episode = Episode(
            episode_id="episode-compat",
            state_id="state-compat",
            personal_model_id="pm-compat",
            entry_surface="cli",
            status="open",
            started_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        )

        self.assertEqual(episode.session_id, episode.episode_id)

    def test_capability_ports_expose_registry_and_health_contracts(self) -> None:
        descriptor = CapabilityDescriptor(
            capability_id="model.openai",
            kind="model_provider",
            version="1.0.0",
        )
        health = CapabilityHealth(status="healthy", checked_at=datetime(2026, 1, 1))

        self.assertEqual(descriptor.capability_id, "model.openai")
        self.assertEqual(health.status, "healthy")
        self.assertTrue(issubclass(CapabilityRegistry, object))
        for protocol in (
            RecallCapability,
            ContextCapability,
            ModelProviderCapability,
            AuthProviderCapability,
            ToolCapability,
            SkillCapability,
            DeliveryAdapterCapability,
            StorageBackendCapability,
            TelemetrySinkCapability,
        ):
            self.assertTrue(hasattr(protocol, "__dict__"), protocol.__name__)


class FactOpenQuestionShapeTest(unittest.TestCase):
    """Smoke-tests for the Fact / OpenQuestion pair."""

    def test_fact_is_active_and_confident_by_default(self) -> None:
        now = datetime.now(timezone.utc)
        fact = Fact(
            fact_id="fact-1",
            personal_model_id="pm-1",
            lens="journey",
            text="Plans carefully before shipping",
            confidence=0.8,
            committed_at=now,
            source="pm_agent_promote",
        )
        self.assertEqual(fact.status, "active")
        self.assertGreaterEqual(fact.confidence, 0.6)

    def test_open_question_defaults_to_open_status(self) -> None:
        now = datetime.now(timezone.utc)
        question = OpenQuestion(
            question_id="oq-1",
            personal_model_id="pm-1",
            lens="pulse",
            sub_lens="current_chapter",
            text="What are you working on these days?",
            rationale="coverage_gap: no facts yet under chapter.current_chapter",
            priority=0.8,
            sensitivity="low",
            source="coverage_gap",
            created_at=now,
        )
        self.assertEqual(question.status, "open")
        self.assertEqual(question.asked_count, 0)


if __name__ == "__main__":
    unittest.main()
