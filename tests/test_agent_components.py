import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_memory
import evaluation
import observability
from agent_workflow import run_agent_workflow
from observability import TraceRecorder
from time_utils import app_now
from evaluation import score


class AgentComponentTests(unittest.TestCase):
    def test_live_evaluation_runs_real_workflow_with_fake_model(self):
        responses = iter([
            '{"items":[{"id":"eval-001","category":"工作","priority":"高"}]}',
            '{"items":[{"id":"eval-001","summary":"确认 Alpha 项目上线清单"}]}',
            '{"items":[{"id":"eval-001","action":"今天18点前回复确认"}]}',
        ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(evaluation, "RESULT_DIR", root / "evaluations"), patch.object(observability, "TRACE_DIR", root / "traces"):
                result = evaluation.run_live_evaluation(1, lambda _: next(responses))
        self.assertEqual(result["metrics"]["category_accuracy"], 1.0)
        self.assertEqual(result["metrics"]["action_f1"], 1.0)
        self.assertEqual(result["metrics"]["hallucination_rate"], 0.0)

    def test_default_application_timezone(self):
        with patch.dict("os.environ", {"APP_TIMEZONE": "Asia/Shanghai"}):
            self.assertEqual(app_now().strftime("%z"), "")
            self.assertGreaterEqual(app_now().hour, 0)

    def test_postgres_vector_serialization(self):
        value = agent_memory._postgres_vector([0.5, -0.25, 0.0])
        self.assertEqual(value, "[0.5,-0.25,0]")

    def test_benchmark_expands_to_one_hundred_unique_synthetic_emails(self):
        dataset = evaluation.load_dataset()
        identifiers = [str(record["email"]["id"]) for record in dataset]
        self.assertEqual(len(dataset), 100)
        self.assertEqual(len(set(identifiers)), 100)
        self.assertEqual(identifiers[0], "eval-001")
        self.assertEqual(identifiers[-1], "eval-100")

    def test_metrics(self):
        expected = [{"id": "1", "category": "工作", "priority": "高", "has_action": True}]
        predicted = [{"id": "1", "category": "工作", "priority": "高", "action": "回复"}]
        result = score(expected, predicted)
        self.assertEqual(result["category_accuracy"], 1.0)
        self.assertEqual(result["grounded_id_rate"], 1.0)

    def test_local_memory_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(agent_memory, "LOCAL_DB", Path(directory) / "memory.db"):
                # Keep this unit test isolated from a DATABASE_URL inherited from
                # Docker/CI; it is specifically validating the SQLite backend.
                memory = agent_memory.SemanticMemory(database_url="")
                memory.remember("one", "项目 Alpha 需要明天回复", {"category": "工作"})
                self.assertEqual(memory.count(), 1)
                self.assertTrue(memory.search("Alpha 项目回复"))
                memory.close()

    def test_multi_agent_workflow_keeps_source_identity(self):
        responses = iter([
            '{"items":[{"id":"mail-1","category":"工作","priority":"高"}]}',
            '{"items":[{"id":"mail-1","summary":"项目需要确认"}]}',
            '{"items":[{"id":"mail-1","action":"回复邮件"}]}',
        ])
        emails = [{"id": "mail-1", "message_key": "key-1", "from": "masked", "subject": "项目", "date": "", "body": "请确认"}]
        with tempfile.TemporaryDirectory() as directory, patch.object(observability, "TRACE_DIR", Path(directory) / "traces"):
            recorder = TraceRecorder("test")
            items, trace = run_agent_workflow(
                emails, lambda _: next(responses), enable_memory=False, require_approval=False, recorder=recorder,
            )
        self.assertEqual(items[0]["id"], "mail-1")
        self.assertEqual(items[0]["priority"], "高")
        self.assertEqual(
            [entry["agent"] for entry in trace],
            ["memory_retriever", "triage_agent", "summary_agent", "conditional_router", "action_agent", "digest_agent"],
        )


if __name__ == "__main__":
    unittest.main()
