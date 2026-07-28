"""
rules/tier_b_quality.py — Tier B: Code Quality Rules

Vi phạm có thể là FAIL hoặc WARN tùy rule.
Các rule này không crash app ngay nhưng tích lũy thành technical debt nghiêm trọng.
"""
import ast
import os
from pathlib import Path

from rules.base import BaseRule, RuleViolation, Severity


# ──────────────────────────────────────────────────────────────────────────────
#  B001 — Long Function
# ──────────────────────────────────────────────────────────────────────────────
class LongFunctionRule(BaseRule):
    """Phát hiện hàm dài hơn MAX_LINES dòng."""
    tier = "B"
    rule_id = "B001"
    rule_name = "LongFunction"
    severity = Severity.WARN
    MAX_LINES = 80

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.end_lineno:
                continue
            length = node.end_lineno - node.lineno
            if length > self.MAX_LINES:
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail=f"Function `{node.name}` is {length} lines (limit: {self.MAX_LINES})",
                    why="Long functions are hard to test, debug, and violate Single Responsibility",
                ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  B002 — Long Class
# ──────────────────────────────────────────────────────────────────────────────
class LongClassRule(BaseRule):
    """Phát hiện class dài hơn MAX_LINES dòng (God Object)."""
    tier = "B"
    rule_id = "B002"
    rule_name = "LongClass"
    severity = Severity.WARN
    MAX_LINES = 500

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.end_lineno:
                continue
            length = node.end_lineno - node.lineno
            if length > self.MAX_LINES:
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail=f"Class `{node.name}` is {length} lines (limit: {self.MAX_LINES})",
                    why="God Object — consider splitting by responsibility",
                ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  B003 — God File
# ──────────────────────────────────────────────────────────────────────────────
class GodFileRule(BaseRule):
    """Phát hiện file có tổng số dòng vượt ngưỡng."""
    tier = "B"
    rule_id = "B003"
    rule_name = "GodFile"
    severity = Severity.WARN
    MAX_LINES = 1000

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        try:
            with open(filepath, encoding="utf-8") as f:
                lines = sum(1 for _ in f)
        except OSError:
            return []

        if lines > self.MAX_LINES:
            return [self._violation(
                filepath, 1,
                detail=f"File has {lines} lines (limit: {self.MAX_LINES})",
                why="Large files cause merge conflicts and slow down team velocity",
            )]
        return []


# ──────────────────────────────────────────────────────────────────────────────
#  B004 — TODO/FIXME/HACK tracker
# ──────────────────────────────────────────────────────────────────────────────
class TodoTrackingRule(BaseRule):
    """Phát hiện TODO/FIXME/HACK comments chưa được track."""
    tier = "B"
    rule_id = "B004"
    rule_name = "TodoTracking"
    severity = Severity.WARN

    _MARKERS = {"TODO", "FIXME", "HACK", "XXX"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        try:
            with open(filepath, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    upper = line.upper()
                    for marker in self._MARKERS:
                        if f"# {marker}" in upper or f"#{marker}" in upper:
                            violations.append(self._violation(
                                filepath, lineno,
                                detail=f"{marker} comment found: {line.strip()[:60]}",
                                why="Untracked debt — should be filed as issue within 7 days",
                            ))
                            break
        except OSError:
            pass
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  B005 — Config Rule (os.getenv ngoài config.py)
# ──────────────────────────────────────────────────────────────────────────────
class ConfigRuleCheck(BaseRule):
    """
    Phát hiện os.getenv() được gọi ngoài src/shared/config.py.
    Config tập trung để validate và dễ thay đổi.
    """
    tier = "B"
    rule_id = "B005"
    rule_name = "ConfigRule"
    severity = Severity.WARN

    _ALLOWED_FILES = {"config.py", "settings.py"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        filename = os.path.basename(filepath)
        if filename in self._ALLOWED_FILES:
            return []

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail="os.getenv() called outside src/shared/config.py",
                    why=(
                        "Config scattered across files is hard to validate and change. "
                        "All os.getenv() must be centralized in src/shared/config.py"
                    ),
                ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  B006 — Logging Rule (không tự basicConfig)
# ──────────────────────────────────────────────────────────────────────────────
class LoggingRuleCheck(BaseRule):
    """
    Phát hiện logging.basicConfig() gọi trong file con.
    Phát hiện thiếu `logger = logging.getLogger(...)` trong Worker files.
    """
    tier = "B"
    rule_id = "B006"
    rule_name = "LoggingRule"
    severity = Severity.WARN

    _ALLOWED_BASIC_CONFIG = {"main.py", "production_check.py", "run_tests.py"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        filename = os.path.basename(filepath)
        violations = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Phát hiện logging.basicConfig() trong file con
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "basicConfig"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logging"
            ):
                if filename not in self._ALLOWED_BASIC_CONFIG:
                    violations.append(self._violation(
                        filepath, node.lineno,
                        detail="logging.basicConfig() called in non-entry-point file",
                        why=(
                            "basicConfig() overrides the app-wide log config. "
                            "Use logging.getLogger(__name__) instead."
                        ),
                    ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  B007 — No Print (ngoài __main__ block)
# ──────────────────────────────────────────────────────────────────────────────
class NoPrintRule(BaseRule):
    """Phát hiện print() trong source files (ngoài __main__ block)."""
    tier = "B"
    rule_id = "B007"
    rule_name = "NoPrint"
    severity = Severity.WARN

    _EXEMPT_FILES = {"production_check.py", "run_tests.py"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        filename = os.path.basename(filepath)
        if any(kw in filename for kw in ("test", "check")):
            return []

        violations = []
        in_main_block = False

        class MainBlockVisitor(ast.NodeVisitor):
            def visit_If(self_, node):
                nonlocal in_main_block
                is_main = (
                    isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__"
                    and any(
                        isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in node.test.comparators
                    )
                )
                if is_main:
                    in_main_block = True
                    self_.generic_visit(node)
                    in_main_block = False
                else:
                    self_.generic_visit(node)

            def visit_Call(self_, node):
                nonlocal in_main_block
                if not in_main_block:
                    if isinstance(node.func, ast.Name) and node.func.id == "print":
                        violations.append(self._violation(
                            filepath, node.lineno,
                            detail="print() in source file (outside __main__ block)",
                            why=(
                                "print() output is lost in multi-thread logging. "
                                "Use logger.info/debug/warning instead."
                            ),
                        ))
                self_.generic_visit(node)

        MainBlockVisitor().visit(tree)
        return violations
