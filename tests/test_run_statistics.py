import unittest
from unittest import mock

import run_statistics


class FakeCore:
    def failure_reasons(self, limit=2000):
        self.limit = limit
        return [
            "You've hit your weekly limit",
            "connection reset",
            "tool executable not found",
            "invalid structured result",
            "missing required source",
            "unexpected crash",
        ]


class RunStatisticsTests(unittest.TestCase):
    def test_summary_groups_existing_failure_facts_without_persisting_statistics(self):
        core = FakeCore()
        with mock.patch.object(run_statistics.automations, "failure_reasons", return_value=[
                "provider unavailable", "not logged in", "rate limit exceeded"]):
            result = run_statistics.summary(core)

        self.assertEqual(core.limit, 2000)
        self.assertEqual(result["total"], 9)
        self.assertEqual(result["reasons"], [
            {"reason": "模型额度不足", "count": 2},
            {"reason": "网络或服务暂时不可用", "count": 2},
            {"reason": "模型渠道未连接", "count": 1},
            {"reason": "能力或工具不可用", "count": 1},
            {"reason": "交付格式无效", "count": 1},
            {"reason": "缺少运行条件", "count": 1},
            {"reason": "其他运行错误", "count": 1},
        ])


if __name__ == "__main__":
    unittest.main()
