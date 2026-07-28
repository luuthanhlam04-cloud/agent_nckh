"""
rules/tier_c_convention.py — Tier C: Convention Rules

Vi phạm chỉ phát sinh WARN/INFO.
Conventions đảm bảo consistency — ngoại lệ được phép nếu có lý do kiến trúc.
"""
import ast
import os

from rules.base import BaseRule, RuleViolation, Severity


# ──────────────────────────────────────────────────────────────────────────────
#  C001 — Worker Naming (* Worker suffix)
# ──────────────────────────────────────────────────────────────────────────────
class WorkerNamingRule(BaseRule):
    """
    QThread/QRunnable class nên có hậu tố *Worker.
    Convention — không phải safety rule.
    Ngoại lệ: thêm comment '# noqa: C001' hoặc document trong docstring.
    """
    tier = "C"
    rule_id = "C001"
    rule_name = "WorkerNaming"
    severity = Severity.WARN

    _THREAD_BASES = {"QThread", "QRunnable"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            is_worker = False
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name in self._THREAD_BASES:
                    is_worker = True
                    break
            if is_worker and not node.name.endswith("Worker"):
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail=f"Class `{node.name}` extends QThread/QRunnable but lacks `Worker` suffix",
                    why=(
                        "Convention: Worker suffix signals cross-thread risk at a glance. "
                        "Exception allowed if documented in class docstring."
                    ),
                    severity=Severity.WARN,
                ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  C002 — Signal Naming (sig_* prefix)
# ──────────────────────────────────────────────────────────────────────────────
class SignalNamingRule(BaseRule):
    """
    pyqtSignal instances nên có tiền tố sig_.
    Convention — giúp nhận biết data đang cross-thread.
    """
    tier = "C"
    rule_id = "C002"
    rule_name = "SignalNaming"
    severity = Severity.INFO

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            is_signal = False
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "pyqtSignal":
                is_signal = True
            elif isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "pyqtSignal":
                is_signal = True
            if not is_signal:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("sig_"):
                    violations.append(self._violation(
                        filepath, node.lineno,
                        detail=f"Signal `{target.id}` should start with `sig_`",
                        why=(
                            "Convention: sig_ prefix marks data crossing thread boundaries. "
                            "Makes cross-thread communication visible at a glance."
                        ),
                        severity=Severity.INFO,
                    ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  C003 — Slot Naming (_on_* prefix)
# ──────────────────────────────────────────────────────────────────────────────
class SlotNamingRule(BaseRule):
    """
    @pyqtSlot handler nên có tiền tố _on_.
    Convention — giúp nhận biết method được trigger từ thread khác.
    Ngoại lệ: handle_*() hoặc on_*() với lý do được document.
    """
    tier = "C"
    rule_id = "C003"
    rule_name = "SlotNaming"
    severity = Severity.INFO

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                is_slot = (
                    (isinstance(decorator, ast.Name) and decorator.id == "pyqtSlot")
                    or (
                        isinstance(decorator, ast.Call)
                        and (
                            (isinstance(decorator.func, ast.Name) and decorator.func.id == "pyqtSlot")
                            or (isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "pyqtSlot")
                        )
                    )
                )
                if is_slot and not node.name.startswith("_on_"):
                    violations.append(self._violation(
                        filepath, node.lineno,
                        detail=f"Slot `{node.name}` should start with `_on_`",
                        why=(
                            "Convention: _on_ prefix indicates method is triggered cross-thread. "
                            "Exception: document reason in docstring if deviating."
                        ),
                        severity=Severity.INFO,
                    ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  C004 — GC Discipline (transcribe phải gọi gc.collect)
# ──────────────────────────────────────────────────────────────────────────────
class GCDisciplineRule(BaseRule):
    """
    Hàm transcribe trong voice_engine.py phải gọi gc.collect() sau khi xử lý xong.
    Giải phóng audio buffer để tránh memory leak.
    """
    tier = "C"
    rule_id = "C004"
    rule_name = "GCDiscipline"
    severity = Severity.WARN

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        filename = os.path.basename(filepath)
        if filename != "voice_engine.py":
            return []

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != "transcribe":
                continue
            has_gc = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "collect"
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "gc"
                for child in ast.walk(node)
            )
            if not has_gc:
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail="Function `transcribe` missing gc.collect() call",
                    why=(
                        "STT processing holds audio buffer in memory. "
                        "gc.collect() after transcription prevents memory accumulation."
                    ),
                ))
        return violations
