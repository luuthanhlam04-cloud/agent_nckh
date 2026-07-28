"""
rules/tier_a_safety.py — Tier A: Architecture Safety Rules

Vi phạm bất kỳ rule nào trong file này = CI FAIL ngay lập tức.
Lý do: các vi phạm này gây crash, UI freeze, hoặc data corruption.
"""
import ast
import os
from pathlib import Path

from rules.base import BaseRule, RuleViolation, Severity
from rules.dependency_map import (
    LAYER_ORDER, get_layer, get_import_layer, is_internal_import
)


# ──────────────────────────────────────────────────────────────────────────────
#  A001 — Sleep Ban
# ──────────────────────────────────────────────────────────────────────────────
class SleepBanRule(BaseRule):
    """
    Phát hiện time.sleep() trong UI/Main Thread files.
    Hậu quả: Qt Event Loop đứng → Windows "Not Responding".
    """
    tier = "A"
    rule_id = "A001"
    rule_name = "SleepBan"
    severity = Severity.FAIL

    _UI_FILES = {"spotlight.py", "main.py"}
    _UI_DIRS = {"ui"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        filename = os.path.basename(filepath)
        norm_path = filepath.replace("\\", "/")
        in_ui = (
            filename in self._UI_FILES
            or any(f"/src/{d}/" in norm_path for d in self._UI_DIRS)
        )
        if not in_ui:
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "sleep"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "time"
                ):
                    violations.append(self._violation(
                        filepath, node.lineno,
                        detail="time.sleep() detected on Main/UI Thread",
                        why="Qt Event Loop will block → Windows reports 'Not Responding'",
                    ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  A002 — UI Import Ban in Workers
# ──────────────────────────────────────────────────────────────────────────────
class UIImportBanRule(BaseRule):
    """
    Phát hiện Worker import QWidget/QMainWindow.
    Hậu quả: GUI call từ worker thread → crash không debug được.
    """
    tier = "A"
    rule_id = "A002"
    rule_name = "UIImportBan"
    severity = Severity.FAIL

    _BANNED_NAMES = {"QWidget", "QMainWindow", "QApplication", "QDialog"}
    _BANNED_MODULES = {"QtWidgets"}

    def _is_worker_file(self, filepath: str) -> bool:
        norm = filepath.replace("\\", "/")
        filename = os.path.basename(filepath)
        return "workers" in norm or filename in {"workers.py"}

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        if not self._is_worker_file(filepath):
            return []
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self._BANNED_NAMES:
                        violations.append(self._violation(
                            filepath, node.lineno,
                            detail=f"Worker imports forbidden UI class: {alias.name}",
                            why="GUI calls from worker thread cause unpredictable crashes",
                        ))
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(m in (node.module or "") for m in self._BANNED_MODULES):
                    violations.append(self._violation(
                        filepath, node.lineno,
                        detail=f"Worker imports from forbidden UI module: {node.module}",
                        why="GUI calls from worker thread cause unpredictable crashes",
                    ))
                for alias in node.names:
                    if alias.name in self._BANNED_NAMES:
                        violations.append(self._violation(
                            filepath, node.lineno,
                            detail=f"Worker imports forbidden UI class: {alias.name}",
                            why="GUI calls from worker thread cause unpredictable crashes",
                        ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  A003 — Load Dotenv Once
# ──────────────────────────────────────────────────────────────────────────────
class LoadDotenvOnceRule(BaseRule):
    """
    Phát hiện load_dotenv() ở module-level trong các file con (không phải main.py).
    Hậu quả: silent config override → bug không reproduce được.
    Cho phép: load_dotenv() bên trong `if __name__ == '__main__'` block (test runner).
    """
    tier = "A"
    rule_id = "A003"
    rule_name = "LoadDotenvOnce"
    severity = Severity.FAIL

    def _collect_main_block_lines(self, tree: ast.AST) -> set[int]:
        """Thu thập tất cả line numbers bên trong if __name__ == '__main__' blocks."""
        main_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
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
                for child in ast.walk(node):
                    if hasattr(child, "lineno"):
                        main_lines.add(child.lineno)
        return main_lines

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        filename = os.path.basename(filepath)
        # Chỉ cho phép gọi ở entry points
        if filename in {"main.py", "whisper_server.py"}:
            return []

        main_block_lines = self._collect_main_block_lines(tree)
        violations = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name == "load_dotenv":
                # Cho phép nếu nằm trong __main__ block (test runner)
                if node.lineno in main_block_lines:
                    continue
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail="load_dotenv() called at module level outside main.py",
                    why=(
                        "Multiple load_dotenv() calls can silently override config. "
                        "Only call in main.py. For standalone testing, wrap in "
                        "`if __name__ == '__main__':` block."
                    ),
                ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  A004 — No Bare Except (critical form)
# ──────────────────────────────────────────────────────────────────────────────
class NoBareExceptRule(BaseRule):
    """
    Phát hiện `except:` không có exception type.
    Phát hiện `except Exception: pass` không có logging.
    Hậu quả: bug bị ẩn hoàn toàn, không có traceback.
    """
    tier = "A"
    rule_id = "A004"
    rule_name = "NoBareExcept"
    severity = Severity.FAIL

    # Exception types mà `pass` im lặng là chấp nhận được
    _SILENT_OK = {"OSError", "RuntimeError", "StopIteration", "KeyboardInterrupt"}

    def _has_logging(self, handler_body: list) -> bool:
        for node in ast.walk(ast.Module(body=handler_body, type_ignores=[])):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "logger":
                            return True
                if isinstance(node.func, ast.Name):
                    if node.func.id in ("print", "logging"):
                        return True
        return False

    def _get_exc_name(self, node: ast.ExceptHandler) -> str:
        if isinstance(node.type, ast.Name):
            return node.type.id
        if isinstance(node.type, ast.Attribute):
            return node.type.attr
        return ""

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                # Bare except: (không có type)
                violations.append(self._violation(
                    filepath, node.lineno,
                    detail="`except:` without exception type",
                    why="Catches ALL exceptions including SystemExit, hides bugs completely",
                ))
            else:
                # except SomeError: pass (không log)
                is_just_pass = (
                    len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                )
                if is_just_pass and not self._has_logging(node.body):
                    exc_name = self._get_exc_name(node)
                    if exc_name not in self._SILENT_OK:
                        violations.append(self._violation(
                            filepath, node.lineno,
                            detail=f"`except {exc_name}: pass` without logging",
                            why="Exception silently swallowed — add logger.warning() at minimum",
                        ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  A005 — Generator Return (không dùng return <value> trong generator)
# ──────────────────────────────────────────────────────────────────────────────
class GeneratorReturnRule(BaseRule):
    """
    Phát hiện `return <value>` trong Generator function (có yield).
    Hậu quả: message lỗi không bao giờ đến caller.
    """
    tier = "A"
    rule_id = "A005"
    rule_name = "GeneratorReturn"
    severity = Severity.FAIL

    def _is_generator(self, func_node: ast.FunctionDef) -> bool:
        """Kiểm tra hàm có yield statement không (chỉ ở top-level, không vào nested func)."""
        for child in ast.iter_child_nodes(func_node):
            for node in ast.walk(child):
                if isinstance(node, (ast.Yield, ast.YieldFrom)):
                    return True
        return False

    def _find_direct_returns(self, func_node: ast.FunctionDef) -> list[ast.Return]:
        """
        Tìm return statements trực tiếp trong function body.
        Không đi vào nested function definitions.
        """
        results = []
        # Duyệt qua body statements của function
        nodes_to_visit = list(ast.iter_child_nodes(func_node))
        while nodes_to_visit:
            node = nodes_to_visit.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Không đi vào nested function — chúng có scope riêng
                continue
            if isinstance(node, ast.Return) and node.value is not None:
                results.append(node)
            nodes_to_visit.extend(ast.iter_child_nodes(node))
        return results

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not self._is_generator(node):
                continue
            for ret in self._find_direct_returns(node):
                violations.append(self._violation(
                    filepath, ret.lineno,
                    detail=f"return <value> in generator function `{node.name}`",
                    why=(
                        "In a generator, `return <value>` raises StopIteration silently. "
                        "Use `yield <value>` to pass data to caller."
                    ),
                ))
        return violations


# ──────────────────────────────────────────────────────────────────────────────
#  A006 — Dependency Direction
# ──────────────────────────────────────────────────────────────────────────────
class DependencyDirectionRule(BaseRule):
    """
    Kiểm tra file không import từ layer cao hơn của chính nó.
    Ví dụ: src/db (layer 3) không được import src/ui (layer 4).
    """
    tier = "A"
    rule_id = "A006"
    rule_name = "DependencyDirection"
    severity = Severity.FAIL

    def check(self, tree: ast.AST, filepath: str, ctx=None) -> list[RuleViolation]:
        violations = []
        file_layer = get_layer(filepath)
        if file_layer <= 0:
            # Foundation hoặc file ngoài src/ → không kiểm tra
            return []

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.lineno, node.module))

        for lineno, module_name in imports:
            if not is_internal_import(module_name):
                continue
            imported_layer = get_import_layer(module_name)
            if imported_layer <= 0:
                continue  # Import Foundation — luôn hợp lệ
            if imported_layer > file_layer:
                violations.append(self._violation(
                    filepath, lineno,
                    detail=(
                        f"Layer {file_layer} ({filepath}) imports from "
                        f"layer {imported_layer} ({module_name})"
                    ),
                    why=(
                        "Higher layer importing lower layer violates Clean Architecture. "
                        "Use interfaces (src/core/interfaces.py) for cross-layer dependencies."
                    ),
                ))
        return violations
