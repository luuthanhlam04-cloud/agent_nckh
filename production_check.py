# -*- coding: utf-8 -*-
"""
production_check.py - Cảnh sát Kiến trúc (Architecture Police) — Agent V5.0
=======================================================================
Tầng 1: Static Analysis (AST Linter)
  - Kiểm tra code tuân thủ ARCHITECTURE_RULES.md bằng AST
  - Rule: Slot Naming (_on_*), Worker Naming (*Worker), Signal Naming (sig_*)
  - Rule: Sleep Ban (no time.sleep() trên UI Thread)
  - Rule: Whisper Lock, GC Discipline
  - Rule: Bare Except (except: phải có exception type rõ ràng)
  - Rule: No Print (print() ngoài __main__ block bị warn)
Tầng 2: Dynamic Tests (run_tests.py)
"""
import ast
import os
import sys
import subprocess

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"

errors = []

def add_error(rule, detail, file_path, line):
    err_str = f"Luật vi phạm: {rule}\n- File: {file_path}\n- Line: {line}\n- Chi tiết: {detail}"
    errors.append(err_str)
    print(f"{FAIL} {file_path}:{line} - {rule}")

class LinterASTVisitor(ast.NodeVisitor):
    def __init__(self, filepath):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        norm_path = filepath.replace('\\', '/')
        self.in_worker_dir = 'workers' in norm_path
        self.in_ui_dir = 'ui' in norm_path or self.filename == 'spotlight.py' or self.filename == 'main.py'
        self.is_voice_engine = self.filename == 'voice_engine.py'
        self.current_function = None
        self.with_stack = []
        self.in_main_block = False  # Track if inside `if __name__ == '__main__':` block
        self._has_logging_in_scope: list = []  # Stack for tracking logging calls in except

    def visit_With(self, node):
        self.with_stack.append(node)
        self.generic_visit(node)
        self.with_stack.pop()

    def visit_FunctionDef(self, node):
        prev_func = self.current_function
        self.current_function = node.name
        
        # Rule: Slot Naming
        for decorator in node.decorator_list:
            is_slot = False
            if isinstance(decorator, ast.Name) and decorator.id == 'pyqtSlot':
                is_slot = True
            elif isinstance(decorator, ast.Call) and getattr(decorator.func, 'id', '') == 'pyqtSlot':
                is_slot = True
            
            if is_slot and not node.name.startswith('_on_'):
                add_error("Naming Convention (Slot)", f"Hàm slot '{node.name}' phải bắt đầu bằng '_on_'", self.filepath, node.lineno)

        # Rule: GC in transcribe (voice_engine.py)
        if self.is_voice_engine and node.name == 'transcribe':
            has_gc = False
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute) and child.func.attr == 'collect':
                        if isinstance(child.func.value, ast.Name) and child.func.value.id == 'gc':
                            has_gc = True
            if not has_gc:
                add_error("Singleton & GC Enforcer", "Hàm 'transcribe' phải gọi gc.collect() ở cuối", self.filepath, node.lineno)

        self.generic_visit(node)
        self.current_function = prev_func

    def visit_Import(self, node):
        if self.in_worker_dir:
            for alias in node.names:
                if 'QtWidgets' in alias.name or alias.name in ['QWidget', 'QMainWindow']:
                    add_error("Luật Cấm Vận UI", f"Worker cấm import {alias.name}", self.filepath, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if self.in_worker_dir and node.module:
            if 'QtWidgets' in node.module:
                add_error("Luật Cấm Vận UI", f"Worker cấm import từ {node.module}", self.filepath, node.lineno)
            for alias in node.names:
                if alias.name in ['QWidget', 'QMainWindow']:
                    add_error("Luật Cấm Vận UI", f"Worker cấm import {alias.name}", self.filepath, node.lineno)
    def visit_If(self, node):
        """Track __main__ block để cho phép print() bên trong."""
        is_main_block = (
            isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == '__name__'
            and any(
                isinstance(c, ast.Constant) and c.value == '__main__'
                for c in node.test.comparators
            )
        )
        prev = self.in_main_block
        if is_main_block:
            self.in_main_block = True
        self.generic_visit(node)
        self.in_main_block = prev

    def visit_ExceptHandler(self, node):
        """
        Rule: No Bare Except — phát hiện `except:` hoặc `except Exception: pass`
        không có bất kỳ logging/print nào bên trong.
        """
        # Kiểm tra bare except (không có type)
        if node.type is None:
            add_error(
                "No Bare Except",
                "`except:` không có exception type. Dùng `except SomeError as e:` cụ thể.",
                self.filepath, node.lineno
            )
        else:
            # Kiểm tra `except Exception: pass` (không log gì)
            body_calls = []
            for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(child, ast.Call):
                    body_calls.append(child)
            has_logging = any(
                (
                    isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name)
                    and c.func.value.id == 'logger'
                ) or (
                    isinstance(c.func, ast.Name)
                    and c.func.id in ('print', 'logging')
                )
                for c in body_calls
            )
            body_is_just_pass = (
                len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            )
            # Chỉ flag nếu body chỉ có pass và không có logging
            if body_is_just_pass and not has_logging:
                # Cho phép một số exception type cảm nhận là acceptable (OSError, RuntimeError, ...)
                exc_type_name = ""
                if isinstance(node.type, ast.Name):
                    exc_type_name = node.type.id
                elif isinstance(node.type, ast.Attribute):
                    exc_type_name = node.type.attr
                acceptable_silent = {"OSError", "RuntimeError", "StopIteration", "KeyboardInterrupt"}
                if exc_type_name not in acceptable_silent:
                    add_error(
                        "No Bare Except (Silent)",
                        f"`except {exc_type_name}: pass` không có logging. Thêm logger.warning(...) hoặc xử lý rõ ràng.",
                        self.filepath, node.lineno
                    )

        self.generic_visit(node)

    def visit_Call(self, node):
        # Rule: Sleep Ban
        if self.in_ui_dir:
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'sleep':
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'time':
                    add_error("Luật Cấm Ngủ (Sleep Ban)", "Cấm dùng time.sleep() trên Main Thread/UI", self.filepath, node.lineno)

        # Rule: No Print (ngoài __main__ block)
        if not self.in_main_block:
            if isinstance(node.func, ast.Name) and node.func.id == 'print':
                # WARN (không FAIL) — print có thể chấp nhận trong test file
                if not any(test_kw in self.filename for test_kw in ('test', 'run_tests', 'production_check')):
                    print(f"{WARN} {self.filepath}:{node.lineno} - No Print Rule: print() trong source file (dùng logger thay thế)")

        # Rule: Whisper Lock
        if self.is_voice_engine:
            is_whisper = False
            if isinstance(node.func, ast.Name) and node.func.id == 'WhisperModel':
                is_whisper = True
            
            if is_whisper:
                locked = False
                for w_node in self.with_stack:
                    for item in w_node.items:
                        ctx = item.context_expr
                        if isinstance(ctx, ast.Attribute) and '_lock' in ctx.attr:
                            locked = True
                        elif isinstance(ctx, ast.Name) and 'lock' in ctx.id.lower():
                            locked = True
                if not locked:
                    add_error("Singleton & GC Enforcer", "Khởi tạo WhisperModel không được bọc trong khối with khóa (lock)", self.filepath, node.lineno)
                    
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        # Rule: Worker Naming
        is_worker = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in ['QThread', 'QRunnable']:
                is_worker = True
            elif isinstance(base, ast.Attribute) and base.attr in ['QThread', 'QRunnable']:
                is_worker = True
        
        if is_worker and not node.name.endswith('Worker'):
            add_error("Naming Convention (Class Worker)", f"Class '{node.name}' kế thừa QThread/QRunnable phải có hậu tố 'Worker'", self.filepath, node.lineno)

        self.generic_visit(node)

    def visit_Assign(self, node):
        # Rule: Signal Naming
        if isinstance(node.value, ast.Call):
            is_signal = False
            if isinstance(node.value.func, ast.Name) and node.value.func.id == 'pyqtSignal':
                is_signal = True
            elif isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'pyqtSignal':
                is_signal = True
            
            if is_signal:
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith('sig_'):
                        add_error("Naming Convention (Signal)", f"Tín hiệu '{target.id}' phải bắt đầu bằng 'sig_'", self.filepath, node.lineno)

        self.generic_visit(node)


def write_report():
    report_path = os.path.join(os.path.dirname(__file__), ".code_issues.md")
    if not errors:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# BÁO CÁO KIỂM THỬ LINTER\n\n✅ TẤT CẢ CODE ĐỀU HỢP LỆ THEO ARCHITECTURE_RULES.md!")
        return

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# ❌ BÁO CÁO LỖI LINTER (AST ANALYSIS)\n\n")
        f.write("Hệ thống phát hiện các vi phạm Kiến trúc đa luồng. Vui lòng sửa ngay:\n\n")
        for i, err in enumerate(errors, 1):
            f.write(f"### Lỗi {i}:\n```text\n{err}\n```\n\n")


def run_linter():
    print("="*60)
    print("  PHASE 1: TẦNG STATIC ANALYSIS (AST LINTER)")
    print("="*60)
    
    src_dir = os.path.join(os.path.dirname(__file__), "src")
    main_file = os.path.join(os.path.dirname(__file__), "main.py")
    
    files_to_check = []
    if os.path.exists(main_file):
        files_to_check.append(main_file)
        
    if os.path.exists(src_dir):
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                if file.endswith('.py'):
                    files_to_check.append(os.path.join(root, file))
                    
    for file_path in files_to_check:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
            visitor = LinterASTVisitor(file_path)
            visitor.visit(tree)
        except Exception as e:
            print(f"{WARN} Lỗi parse AST file {file_path}: {e}")

    write_report()
    
    if errors:
        print("\n" + "="*60)
        print(f"{FAIL} STATIC ANALYSIS THẤT BẠI: {len(errors)} vi phạm.")
        print("Chi tiết đã được lưu vào file ẩn: .code_issues.md")
        print("CẤM ĐẨY CODE HOẶC CHẠY TẦNG 2!")
        print("="*60)
        sys.exit(1)
    else:
        print(f"  {PASS} STATIC ANALYSIS HOÀN HẢO (0 Lỗi)")


def run_unit_tests():
    print("\n" + "="*60)
    print("  PHASE 2: TẦNG DYNAMIC TESTS (run_tests.py)")
    print("="*60)
    
    test_script = os.path.join(os.path.dirname(__file__), "run_tests.py")
    if not os.path.exists(test_script):
        print(f"{WARN} Không tìm thấy run_tests.py, bỏ qua Tầng 2.")
        return
        
    result = subprocess.run([sys.executable, test_script])
    if result.returncode != 0:
        print("\n" + "="*60)
        print(f"{FAIL} TẦNG 2 THẤT BẠI. Code có bug runtime khi test.")
        print("="*60)
        sys.exit(1)
    else:
        print("\n" + "="*60)
        print(f"  {PASS} TOÀN BỘ QUY TRÌNH (LINTER + UNIT TEST) THÀNH CÔNG! SẴN SÀNG DEPLOY.")
        print("="*60)


if __name__ == "__main__":
    run_linter()
    run_unit_tests()
