from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from packages.embeddings import EmbeddingVector
from packages.evals.cli import run_eval
from packages.evals.contracts import EvalRunConfig
from packages.evals.datasets import load_locomo_dataset


class FakeEmbeddingService:
    def embed_text(self, text: str, **kwargs: object) -> EmbeddingVector:
        del kwargs
        dimensions = 8
        buckets = [0.0] * dimensions
        for char in text.lower():
            buckets[ord(char) % dimensions] += 1.0
        total = sum(buckets) or 1.0
        return EmbeddingVector(
            text_index=0,
            values=tuple(value / total for value in buckets),
            dimensions=dimensions,
            provider_id="test",
            model_id="test-embed",
            source_text=text,
        )


class FakeAnswerRunner:
    def answer_question(self, question, hits):
        del question
        if any("oat milk" in hit.content.lower() for hit in hits):
            return "oat milk"
        return "I don't know"


class LoCoMoEvalTest(unittest.TestCase):
    def test_original_and_refined_load_into_same_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_path = root / "locomo10.json"
            original_path.write_text(
                json.dumps(
                    [
                        {
                            "sample_id": "sample-1",
                            "conversation": {
                                "speaker_a": "Alice",
                                "speaker_b": "Bob",
                                "session_1_date_time": "01 January 2024",
                                "session_1": [
                                    {"dia_id": "D1:1", "speaker": "Alice", "text": "I bought oat milk."},
                                ],
                            },
                            "qa": [
                                {
                                    "question": "What did Alice buy?",
                                    "answer": "oat milk",
                                    "evidence": ["D1:1"],
                                    "category": "single_hop",
                                }
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            refined_dir = root / "public"
            refined_dir.mkdir()
            (refined_dir / "conversations.jsonl").write_text(
                json.dumps(
                    {
                        "sample_id": "sample-1",
                        "conversation_idx": 0,
                        "speaker_a": "Alice",
                        "speaker_b": "Bob",
                        "sessions": [
                            {
                                "session_index": 1,
                                "date_time": "01 January 2024",
                                "messages": [
                                    {"dia_id": "D1:1", "speaker": "Alice", "text": "I bought oat milk."},
                                ],
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (refined_dir / "questions.jsonl").write_text(
                json.dumps(
                    {
                        "qa_id": "sample-1-q0",
                        "sample_id": "sample-1",
                        "conversation_idx": 0,
                        "qa_index": 0,
                        "question": "What did Alice buy?",
                        "answer": ["oat milk"],
                        "evidence": ["D1:1"],
                        "category": "single_hop",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            original = load_locomo_dataset(dataset="locomo", path=original_path)
            refined = load_locomo_dataset(dataset="locomo_refined", path=refined_dir)

            self.assertEqual(original.question_count, 1)
            self.assertEqual(refined.question_count, 1)
            self.assertEqual(original.conversations[0].sessions[0].messages[0].message_id, "D1:1")
            self.assertEqual(refined.conversations[0].questions[0].question_id, "sample-1-q0")

    def test_run_eval_uses_hybrid_embedding_and_model_answer_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_dir = root / "public"
            public_dir.mkdir()
            (public_dir / "conversations.jsonl").write_text(
                json.dumps(
                    {
                        "sample_id": "sample-1",
                        "conversation_idx": 0,
                        "speaker_a": "Alice",
                        "speaker_b": "Bob",
                        "sessions": [
                            {
                                "session_index": 1,
                                "date_time": "01 January 2024",
                                "messages": [
                                    {"dia_id": "D1:1", "speaker": "Alice", "text": "I bought oat milk."},
                                    {"dia_id": "D1:2", "speaker": "Bob", "text": "That works for coffee."},
                                ],
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (public_dir / "questions.jsonl").write_text(
                json.dumps(
                    {
                        "qa_id": "sample-1-q0",
                        "sample_id": "sample-1",
                        "conversation_idx": 0,
                        "qa_index": 0,
                        "question": "What did Alice buy?",
                        "answer": ["oat milk"],
                        "evidence": ["D1:1"],
                        "category": "single_hop",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output_dir = root / "out"
            output = run_eval(
                EvalRunConfig(
                    dataset="locomo_refined",
                    dataset_path=str(public_dir),
                    output_dir=str(output_dir),
                    top_k=2,
                    answer_concurrency=2,
                    answer_batch_size=2,
                ),
                embedding_service=FakeEmbeddingService(),
                answer_runner=FakeAnswerRunner(),
            )

            self.assertEqual(len(output.results), 1)
            self.assertEqual(output.results[0].predicted_answer, "oat milk")
            self.assertEqual(output.results[0].metadata["retrieval_mode"], "hybrid")
            self.assertEqual(output.results[0].metadata["answer_mode"], "model")
            self.assertTrue((output_dir / "report.json").exists())
            self.assertTrue((output_dir / "predictions.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
