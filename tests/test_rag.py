import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.rag.embeddings import HashingEmbeddingModel
from back.rag.build_vector_store import _read_document
from back.rag.prompting import build_rag_prompt
from back.rag.sources import build_source_summaries
from back.rag.vector_store import JsonlVectorStore, VectorRecord, chunk_text


class RagTests(unittest.TestCase):
    def test_chunk_text_splits_with_overlap(self):
        chunks = chunk_text("abcdefghij", chunk_size=4, chunk_overlap=1)

        self.assertEqual(chunks, ["abcd", "defg", "ghij"])

    def test_hashing_embedding_is_normalized_and_deterministic(self):
        embedder = HashingEmbeddingModel(dimension=16)

        first = embedder.embed("APQP risk management")
        second = embedder.embed("APQP risk management")

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first) ** 0.5, 1.0)

    def test_jsonl_vector_store_returns_most_relevant_document(self):
        embedder = HashingEmbeddingModel(dimension=32)
        records = [
            {
                "id": "risk",
                "text": "APQP risk review should identify preventive actions.",
                "embedding": embedder.embed("APQP risk review should identify preventive actions."),
                "metadata": {"source": "risk.md", "chunk_index": 1},
            },
            {
                "id": "schedule",
                "text": "Project schedule tracking focuses on milestones and owners.",
                "embedding": embedder.embed("Project schedule tracking focuses on milestones and owners."),
                "metadata": {"source": "schedule.md", "chunk_index": 1},
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "vector_store.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

            store = JsonlVectorStore.load(path)
            results = store.search(embedder.embed("How should we review APQP risk?"), top_k=1)

        self.assertEqual(results[0].record.id, "risk")
        self.assertGreater(results[0].score, 0)

    def test_short_keyword_question_matches_relevant_apqp_document(self):
        embedder = HashingEmbeddingModel()
        doc_text = (
            "APQP 是产品质量先期策划方法，通常用于新产品开发过程中的质量策划、"
            "风险识别、过程控制和量产准备。"
        )
        store = JsonlVectorStore(
            [
                VectorRecord(
                    id="apqp",
                    text=doc_text,
                    embedding=embedder.embed(doc_text),
                    metadata={"source": "apqp.md", "chunk_index": 1},
                )
            ]
        )

        results = store.search(embedder.embed("APQP 是什么？"), top_k=1, min_score=0.05)

        self.assertEqual(results[0].record.id, "apqp")

    def test_build_rag_prompt_injects_sources_and_no_evidence_rule(self):
        prompt = build_rag_prompt(
            user_question="APQP risk review?",
            contexts=[
                {
                    "text": "Risk review should happen in early planning.",
                    "metadata": {"source": "risk.md", "chunk_index": 2},
                    "score": 0.88,
                }
            ],
        )

        self.assertIn("Risk review should happen in early planning.", prompt)
        self.assertIn("risk.md", prompt)
        self.assertIn("只有在未检索到相关资料时", prompt)
        self.assertIn("【主题】", prompt)
        self.assertIn("【结论】", prompt)
        self.assertIn("【建议】", prompt)


    def test_build_rag_prompt_limits_context_length(self):
        prompt = build_rag_prompt(
            user_question="How should a user handle APQP tasks?",
            contexts=[
                {
                    "text": "A" * 900,
                    "metadata": {"source": "manual.pdf", "chunk_index": 1},
                    "score": 0.91,
                },
                {
                    "text": "B" * 900,
                    "metadata": {"source": "manual.pdf", "chunk_index": 2},
                    "score": 0.82,
                },
            ],
            max_context_chars=600,
        )

        self.assertLess(len(prompt), 1100)
        self.assertIn("manual.pdf", prompt)
        self.assertIn("truncated", prompt)

    def test_build_source_summaries_groups_files_and_pages(self):
        results = [
            {
                "text": "[Page 1]\nAPQP start\n[Page 2]\nTask list",
                "metadata": {"source": "APQP操作手册.pdf", "chunk_index": 1},
                "score": 0.9,
            },
            {
                "text": "[Page 2]\nMore detail\n[Page 3]\nReview",
                "metadata": {"source": "APQP操作手册.pdf", "chunk_index": 2},
                "score": 0.8,
            },
            {
                "text": "No page marker",
                "metadata": {"source": "FMEA.md", "chunk_index": 1},
                "score": 0.7,
            },
        ]

        sources = build_source_summaries(results)

        self.assertEqual(sources[0]["source"], "APQP操作手册.pdf")
        self.assertEqual(sources[0]["pages"], [1, 2, 3])
        self.assertEqual(sources[0]["label"], "APQP操作手册.pdf，第 1-3 页")
        self.assertEqual(sources[1]["label"], "FMEA.md")

    def test_read_document_extracts_text_from_pdf(self):
        try:
            import fitz as pymupdf
        except ImportError:
            self.skipTest("PyMuPDF is not installed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "apqp.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "APQP PDF knowledge text")
            doc.save(path)
            doc.close()

            text = _read_document(path)

        self.assertIn("[Page 1]", text)
        self.assertIn("APQP PDF knowledge text", text)


if __name__ == "__main__":
    unittest.main()
