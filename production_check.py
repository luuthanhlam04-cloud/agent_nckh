# -*- coding: utf-8 -*-
"""
production_check.py — Architecture Police v2.0 (Modular Rules Engine)
======================================================================
Entry point của Static Analysis pipeline.

Phase 1: Static Analysis (AST Linter) — các rule trong rules/
Phase 2: Dynamic Tests              — run_tests.py

Cấu trúc rules/:
  tier_a_safety.py    — Tier A: Architecture Safety  → FAIL
  tier_b_quality.py   — Tier B: Code Quality         → FAIL/WARN
  tier_c_convention.py— Tier C: Convention           → WARN/INFO
  metrics_checks.py   — Metrics / Open-source        → INFO

Để thêm rule mới: tạo class trong file tier tương ứng,
kế thừa BaseRule, đăng ký trong rules/__init__.py.
"""
import ast
import os
import sys
import subprocess

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Thêm root vào path để import rules/
sys.path.insert(0, os.path.dirname(__file__))

from rules import ALL_RULES, run_all_rules
from rules.base import Severity, RuleViolation

# ─── Console colors ───────────────────────────────────────────────────────────
_RED   = "\033[91m"
_GREEN = "\033[92m"
_YELLOW= "\033[93m"
_CYAN  = "\033[96m"
_RESET = "\033[0m"
_BOLD  = "\033[1m"

PASS = f"{_GREEN}[PASS]{_RESET}"
FAIL_TAG = f"{_RED}[FAIL]{_RESET}"
WARN_TAG = f"{_YELLOW}[WARN]{_RESET}"
INFO_TAG = f"{_CYAN}[INFO]{_RESET}"


def _collect_python_files() -> list[str]:
    """Thu thập tất cả .py files trong src/ và main.py."""
    root = os.path.dirname(__file__)
    files: list[str] = []

    main_py = os.path.join(root, "main.py")
    if os.path.exists(main_py):
        files.append(main_py)

    src_dir = os.path.join(root, "src")
    if os.path.exists(src_dir):
        for dirpath, _, filenames in os.walk(src_dir):
            for fname in filenames:
                if fname.endswith(".py"):
                    files.append(os.path.join(dirpath, fname))

    return files


def _print_tier_header(tier: str) -> None:
    labels = {
        "A": "TIER A — ARCHITECTURE SAFETY",
        "B": "TIER B — CODE QUALITY",
        "C": "TIER C — CONVENTION & METRICS",
    }
    label = labels.get(tier, f"TIER {tier}")
    print(f"\n{'═' * 56}")
    print(f"  {_BOLD}{label}{_RESET}")
    print(f"{'═' * 56}")


def _print_violation(v: RuleViolation) -> None:
    icon = {
        Severity.FAIL: f"{_RED}❌ FAIL{_RESET}",
        Severity.WARN: f"{_YELLOW}⚠  WARN{_RESET}",
        Severity.INFO: f"{_CYAN}💡 INFO{_RESET}",
    }.get(v.severity, "?")
    short_path = v.file_path.replace(os.path.dirname(__file__), "").lstrip("\\/")
    print(f"{icon}  {short_path}:{v.line}")
    print(f"         [{v.rule_name}] {v.detail}")
    print(f"         WHY: {v.why}")


def run_linter() -> int:
    """
    Chạy tất cả rules trên toàn bộ source files.

    Returns:
        Số lượng Tier A FAIL violations (>0 = block CI).
    """
    print("=" * 56)
    print(f"  {_BOLD}PHASE 1: STATIC ANALYSIS (AST LINTER){_RESET}")
    print("=" * 56)

    files = _collect_python_files()
    all_violations: list[RuleViolation] = []

    for filepath in files:
        try:
            with open(filepath, encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            violations = run_all_rules(tree, filepath)
            all_violations.extend(violations)
        except SyntaxError as e:
            print(f"{FAIL_TAG} Syntax error in {filepath}: {e}")
            all_violations.append(RuleViolation(
                rule_id="A000", rule_name="SyntaxError", tier="A",
                severity=Severity.FAIL, file_path=filepath, line=e.lineno or 0,
                detail=str(e), why="File cannot be parsed — fix syntax first",
            ))
        except Exception as e:
            print(f"{WARN_TAG} Cannot parse {filepath}: {e}")

    # ─── Group by tier và in report ──────────────────────────────────────────
    tier_order = ["A", "B", "C"]
    violations_by_tier: dict[str, list[RuleViolation]] = {t: [] for t in tier_order}
    for v in all_violations:
        tier = v.tier if v.tier in tier_order else "C"
        violations_by_tier[tier].append(v)

    has_tier_a_violations = False
    total_fail = total_warn = total_info = 0

    for tier in tier_order:
        tier_violations = violations_by_tier[tier]
        if not tier_violations:
            continue
        _print_tier_header(tier)
        for v in tier_violations:
            _print_violation(v)
            print()
            if v.severity == Severity.FAIL:
                total_fail += 1
                if tier == "A":
                    has_tier_a_violations = True
            elif v.severity == Severity.WARN:
                total_warn += 1
            else:
                total_info += 1

    # ─── Write .code_issues.md ───────────────────────────────────────────────
    _write_report(all_violations)

    # ─── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'═' * 56}")
    if all_violations:
        print(
            f"  SUMMARY: "
            f"{_RED}{total_fail} FAIL{_RESET}  "
            f"{_YELLOW}{total_warn} WARN{_RESET}  "
            f"{_CYAN}{total_info} INFO{_RESET}"
        )
    if has_tier_a_violations:
        print(f"\n  {_RED}{_BOLD}Status: ❌ BLOCKED — Fix Tier A violations before proceeding{_RESET}")
        print(f"  Details saved to .code_issues.md")
    else:
        if total_fail + total_warn + total_info == 0:
            print(f"  {PASS} All checks passed — {len(files)} files scanned")
        else:
            print(f"  {_GREEN}Status: ✅ CLEAR — No Tier A violations (WARN/INFO advisory only){_RESET}")
    print(f"{'═' * 56}")

    return 1 if has_tier_a_violations else 0


def _write_report(violations: list[RuleViolation]) -> None:
    report_path = os.path.join(os.path.dirname(__file__), ".code_issues.md")
    if not violations:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# ✅ LINTER REPORT\n\nAll checks passed — no violations found.")
        return

    lines = ["# ❌ LINTER REPORT — AST Analysis\n\n"]
    for tier in ["A", "B", "C"]:
        tier_violations = [v for v in violations if v.tier == tier]
        if not tier_violations:
            continue
        tier_labels = {"A": "Architecture Safety", "B": "Code Quality", "C": "Convention"}
        lines.append(f"## Tier {tier} — {tier_labels.get(tier, '')}\n\n")
        for i, v in enumerate(tier_violations, 1):
            lines.append(
                f"### {i}. [{v.rule_name}] `{v.file_path}:{v.line}`\n"
                f"- **Severity:** {v.severity.value}\n"
                f"- **Detail:** {v.detail}\n"
                f"- **Why:** {v.why}\n\n"
            )

    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def run_unit_tests() -> None:
    print(f"\n{'=' * 56}")
    print(f"  {_BOLD}PHASE 2: DYNAMIC TESTS (run_tests.py){_RESET}")
    print(f"{'=' * 56}")

    test_script = os.path.join(os.path.dirname(__file__), "run_tests.py")
    if not os.path.exists(test_script):
        print(f"{WARN_TAG} run_tests.py not found — skipping Phase 2")
        return

    result = subprocess.run([sys.executable, test_script])
    if result.returncode != 0:
        print(f"\n{FAIL_TAG} Phase 2 failed — runtime bugs detected")
        sys.exit(1)
    else:
        print(f"\n  {PASS} All phases complete — ready to deploy")


if __name__ == "__main__":
    exit_code = run_linter()
    if exit_code != 0:
        sys.exit(exit_code)
    run_unit_tests()
