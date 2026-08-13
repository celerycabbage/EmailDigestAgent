import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_memory
from agent_workflow import run_agent_workflow
from time_utils import app_now
from evaluation import score


class AgentComponentTests(unittest.TestCase):
    def test_default_application_timezone(self):
        with patch.dict("os.environ", {"APP_TIMEZONE": "Asia/Shanghai"}):
            self.assertEqual(app_now().strftime("%z"), "")
            self.assertGreaterEqual(app_now().hour, 0)

    def test_postgres_vector_serialization(self):
        value = agent_memory._postgres_vector([0.5, -0.25, 0.0])
        self.assertEqual(value, "[0.5,-0.25,0]")

    def test_metrics(self):
        expected = [{"id": "1", "category": "工作", "priority": "高", "has_action": True}]
        predicted = [{"id": "1", "category": "工作", "priority": "高", "action": "回复"}]
        result = score(expected, predicted)
        self.assertEqual(result["category_accuracy"], 1.0)
        self.assertEqual(result["grounded_id_rate"], 1.0)

    def test_local_memory_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(agent_memory, "LOCAL_DB", Path(directory) / "memory.db"):
                memory = agent_memory.SemanticMemory()
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
        items, trace = run_agent_workflow(emails, lambda _: next(responses), enable_memory=False, require_approval=False)
        self.assertEqual(items[0]["id"], "mail-1")
        self.assertEqual(items[0]["priority"], "高")
        self.assertEqual([entry["agent"] for entry in trace], ["triage_agent", "summary_agent", "action_agent", "digest_agent"])


if __name__ == "__main__":
    unittest.main()
