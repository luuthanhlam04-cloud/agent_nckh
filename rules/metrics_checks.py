"""
rules/metrics_checks.py — Tier C: Metrics/Open-source Readiness Checks

Các check chuẩn bị cho open-source và maintainability dài hạn.
"""
import ast
import os

from rules.base import BaseRule, RuleViolation, Severity


# ──────────────────────────────────────────────────────────────────────────────
#  M001 — Type Hint cho Public Functions
# ──────────────────────────────────────────────────────────────────────────────
class TypeHintRule(BaseRule):
    """
    Public function (không bắt đầu bằng _) nên có type annotation.
    Cải thiện IDE support và tường minh API contract.
    """
    tier = "C"
    rule_id = "M001"
    rule_name = "TypeHint"
    severity = Severity.INFO

    def _is_public(self, name: str) -> bool:
        return not name.startswith("_") and name not in {"__init__", "__repr__", "__str__"}

    def _has_type_hints(self, node: ast.FunctionDef) -> bool:
        """Kiểm tra có ít nhất return annotation hoặc tất cả args có annotation."""
        if node.returns is not None:
            return True
        args = node.args
        all_args = args.args + args.posonlyargs + args.kwonlyargs
        # Bỏ qua self, cls
        param_args = [a for a in all_args if a.arg not in ("self", "cls")]
        if not param_args:
            return True  # Không có params → không cần hint
        return any(a.annotation is not None for a in param_args)

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        # Chỉ check trong src/ — không check scripts
        if "src" not in filepath.replace("\\", "/"):
            return []

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not self._is_public(node.name):
                continue
            if not self._has_type_hints(node):
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail=f"Public function `{node.name}` missing type annotations",
                    why=(
                        "Type hints improve IDE support and make API contract explicit. "
                        "Critical for open-source readability."
                    ),
                    severity=Severity.INFO,
                ))
        return violations
