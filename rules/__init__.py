"""
rules/__init__.py — Rule Registry và runner.

Đăng ký tất cả rules ở đây. production_check.py chỉ gọi run_all_rules().
Để thêm rule mới: chỉ cần import class và thêm vào ALL_RULES list.
"""
from rules.tier_a_safety import (
    SleepBanRule,
    UIImportBanRule,
    LoadDotenvOnceRule,
    NoBareExceptRule,
    GeneratorReturnRule,
    DependencyDirectionRule,
)
from rules.tier_b_quality import (
    LongFunctionRule,
    LongClassRule,
    GodFileRule,
    TodoTrackingRule,
    ConfigRuleCheck,
    LoggingRuleCheck,
    NoPrintRule,
)
from rules.tier_c_convention import (
    WorkerNamingRule,
    SignalNamingRule,
    SlotNamingRule,
    GCDisciplineRule,
)
from rules.metrics_checks import TypeHintRule
from rules.base import RuleViolation, Severity

# ─── Rule Registry ───────────────────────────────────────────────────────────
# Thứ tự: Tier A → Tier B → Tier C
ALL_RULES = [
    # Tier A — Architecture Safety
    SleepBanRule(),
    UIImportBanRule(),
    LoadDotenvOnceRule(),
    NoBareExceptRule(),
    GeneratorReturnRule(),
    DependencyDirectionRule(),

    # Tier B — Code Quality
    LongFunctionRule(),
    LongClassRule(),
    GodFileRule(),
    TodoTrackingRule(),
    ConfigRuleCheck(),
    LoggingRuleCheck(),
    NoPrintRule(),

    # Tier C — Convention
    WorkerNamingRule(),
    SignalNamingRule(),
    SlotNamingRule(),
    GCDisciplineRule(),

    # Metrics / Open-source
    TypeHintRule(),
]


def run_all_rules(tree, filepath: str, ctx=None) -> list[RuleViolation]:
    """Chạy tất cả rules trên một file và trả về danh sách vi phạm."""
    violations = []
    for rule in ALL_RULES:
        try:
            violations.extend(rule.check(tree, filepath, ctx))
        except Exception as e:
            # Rule crash không được phép dừng toàn bộ checker
            import logging
            logging.getLogger("rules").warning(
                "Rule %s crashed on %s: %s", rule.rule_name, filepath, e
            )
    return violations
