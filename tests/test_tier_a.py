import unittest
import ast
from rules.base import Severity
from rules.tier_a_safety import (
    SleepBanRule, UIImportBanRule, LoadDotenvOnceRule,
    NoBareExceptRule, GeneratorReturnRule, DependencyDirectionRule,
    PureRouterRule
)

class TestTierA(unittest.TestCase):
    def check_rule(self, rule_class, code: str, filepath: str = "dummy.py"):
        tree = ast.parse(code)
        rule = rule_class()
        return rule.check(tree, filepath)

    def test_a001_sleep_ban(self):
        # FAIL case
        v = self.check_rule(SleepBanRule, "import time\ntime.sleep(1)", "main.py")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].rule_id, "A001")
        self.assertEqual(v[0].severity, Severity.FAIL)

        # PASS cases
        self.assertEqual(len(self.check_rule(SleepBanRule, "import asyncio\nawait asyncio.sleep(1)")), 0)
        self.assertEqual(len(self.check_rule(SleepBanRule, "foo.sleep(1)")), 0)
        self.assertEqual(len(self.check_rule(SleepBanRule, "time['sleep'](1)")), 0)
        # Excluded files
        self.assertEqual(len(self.check_rule(SleepBanRule, "time.sleep(1)", "test_foo.py")), 0)

    def test_a002_no_ui_in_worker(self):
        # FAIL case
        v = self.check_rule(UIImportBanRule, "from PyQt6.QtWidgets import QApplication", "C:/app/src/core/workers.py")
        self.assertTrue(len(v) >= 1)
        self.assertEqual(v[0].rule_id, "A002")
        self.assertEqual(v[0].severity, Severity.FAIL)
        
        # PASS case (allowed in src/ui)
        self.assertEqual(len(self.check_rule(UIImportBanRule, "from PyQt6 import QtWidgets", "C:/app/src/ui/foo.py")), 0)
        # PASS case (allowed in main)
        self.assertEqual(len(self.check_rule(UIImportBanRule, "import PyQt6", "main.py")), 0)

    def test_a003_load_dotenv_once(self):
        # FAIL case
        v = self.check_rule(LoadDotenvOnceRule, "from dotenv import load_dotenv\nload_dotenv()", "src/utils/foo.py")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].rule_id, "A003")
        self.assertEqual(v[0].severity, Severity.FAIL)
        
        # PASS case
        self.assertEqual(len(self.check_rule(LoadDotenvOnceRule, "load_dotenv()", "main.py")), 0)
        # PASS case (allowed in test runner blocks)
        self.assertEqual(len(self.check_rule(LoadDotenvOnceRule, "if __name__ == '__main__':\n    load_dotenv()", "test_foo.py")), 0)

    def test_a004_no_bare_except(self):
        # FAIL cases
        v1 = self.check_rule(NoBareExceptRule, "try: pass\nexcept: pass")
        self.assertEqual(len(v1), 1)
        self.assertEqual(v1[0].rule_id, "A004")
        
        v2 = self.check_rule(NoBareExceptRule, "try: pass\nexcept Exception: pass")
        self.assertEqual(len(v2), 1)
        
        # PASS cases
        # Allowed exception types (silent pass)
        self.assertEqual(len(self.check_rule(NoBareExceptRule, "try: pass\nexcept StopIteration: pass")), 0)
        # Exception logged
        self.assertEqual(len(self.check_rule(NoBareExceptRule, "try: pass\nexcept Exception as e:\n    logger.error(e)")), 0)
        # Not bare pass
        self.assertEqual(len(self.check_rule(NoBareExceptRule, "try: pass\nexcept Exception:\n    fallback()")), 0)

    def test_a005_generator_return(self):
        # FAIL case
        v = self.check_rule(GeneratorReturnRule, "def f():\n    yield 1\n    return 2")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].rule_id, "A005")
        
        # PASS cases
        self.assertEqual(len(self.check_rule(GeneratorReturnRule, "def f():\n    yield 1\n    return")), 0)
        self.assertEqual(len(self.check_rule(GeneratorReturnRule, "def f():\n    return 2")), 0)

    def test_a006_dependency_direction(self):
        # FAIL case: core importing db
        v = self.check_rule(DependencyDirectionRule, "import src.db.foo", "C:/app/src/core/bar.py")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].rule_id, "A006")
        
        # PASS case: core importing interfaces
        self.assertEqual(len(self.check_rule(DependencyDirectionRule, "from src.core.interfaces import IFoo", "C:/app/src/core/bar.py")), 0)
        # PASS case: main importing anything
        self.assertEqual(len(self.check_rule(DependencyDirectionRule, "import src.db.foo", "main.py")), 0)

    def test_a008_pure_router(self):
        filename = "semantic_interceptor.py"
        banned = ["subprocess", "yt_dlp", "googleapiclient", "webbrowser"]
        
        for mod in banned:
            # FAIL cases
            v = self.check_rule(PureRouterRule, f"import {mod}", filename)
            self.assertEqual(len(v), 1, f"Failed to catch import {mod}")
            self.assertEqual(v[0].rule_id, "A008")
            self.assertEqual(v[0].severity, Severity.FAIL)
            
            v2 = self.check_rule(PureRouterRule, f"from {mod} import something", filename)
            self.assertEqual(len(v2), 1, f"Failed to catch from {mod} import")
            
            # PASS cases (wrong file)
            self.assertEqual(len(self.check_rule(PureRouterRule, f"import {mod}", "main.py")), 0)
            
        # OS Startfile check
        v3 = self.check_rule(PureRouterRule, "import os\nos.startfile('x')", filename)
        self.assertEqual(len(v3), 1)
        
        self.assertEqual(len(self.check_rule(PureRouterRule, "os.path.join('a', 'b')", filename)), 0)

if __name__ == '__main__':
    unittest.main()
