import unittest
import ast
from rules.base import Severity
from rules.tier_b_quality import StructuredGatingRule, NoPrintRule

class TestTierB(unittest.TestCase):
    def check_rule(self, rule_class, code: str, filepath: str = "dummy.py"):
        tree = ast.parse(code)
        rule = rule_class()
        return rule.check(tree, filepath)

    def test_b007_structured_gating(self):
        # Case 1: JSON mime type but no schema -> WARN
        code1 = """
config = GenerateContentConfig(
    response_mime_type="application/json"
)
"""
        v1 = self.check_rule(StructuredGatingRule, code1)
        self.assertEqual(len(v1), 1)
        self.assertEqual(v1[0].rule_id, "B007")
        self.assertEqual(v1[0].severity, Severity.WARN)

        # Case 2: JSON mime type with schema -> PASS
        code2 = """
config = GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=MySchema
)
"""
        self.assertEqual(len(self.check_rule(StructuredGatingRule, code2)), 0)

        # Case 3: Not JSON -> PASS
        code3 = """
config = GenerateContentConfig(
    temperature=0.5
)
"""
        self.assertEqual(len(self.check_rule(StructuredGatingRule, code3)), 0)

        # Case 4: Alias and reversed keyword order -> PASS
        code4 = """
from google.genai import types as gt
config = gt.GenerateContentConfig(
    response_schema=Schema,
    response_mime_type="application/json"
)
"""
        self.assertEqual(len(self.check_rule(StructuredGatingRule, code4)), 0)
        
        # Case 5: Alias but NO schema -> WARN
        code5 = """
import google.genai.types as types
config = types.GenerateContentConfig(
    response_mime_type="application/json"
)
"""
        v5 = self.check_rule(StructuredGatingRule, code5)
        self.assertEqual(len(v5), 1)

    def test_b008_no_print(self):
        # FAIL case
        v = self.check_rule(NoPrintRule, "def f():\n    print('hello')", "src/core/foo.py")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].rule_id, "B008")
        self.assertEqual(v[0].severity, Severity.WARN)

        # PASS cases
        self.assertEqual(len(self.check_rule(NoPrintRule, "if __name__ == '__main__':\n    print('hello')")), 0)
        self.assertEqual(len(self.check_rule(NoPrintRule, "logger.info('hello')")), 0)

if __name__ == '__main__':
    unittest.main()
