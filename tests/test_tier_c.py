import unittest
import ast
from rules.base import Severity
from rules.tier_c_convention import WorkerNamingRule

class TestTierC(unittest.TestCase):
    def check_rule(self, rule_class, code: str, filepath: str = "dummy.py"):
        tree = ast.parse(code)
        rule = rule_class()
        return rule.check(tree, filepath)

    def test_c001_worker_naming(self):
        # WARN case: class extending QThread without Worker suffix
        v = self.check_rule(WorkerNamingRule, "class MyTask(QThread):\n    pass")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].rule_id, "C001")
        self.assertEqual(v[0].severity, Severity.WARN)
        
        # PASS case: class extending QThread with Worker suffix
        self.assertEqual(len(self.check_rule(WorkerNamingRule, "class MyTaskWorker(QThread):\n    pass")), 0)
        
        # PASS case: non-thread class
        self.assertEqual(len(self.check_rule(WorkerNamingRule, "class MyTask:\n    pass")), 0)

if __name__ == '__main__':
    unittest.main()
