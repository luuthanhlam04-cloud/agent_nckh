"""
rules/base.py — Foundation classes cho tất cả AST rules.

Mọi rule đều kế thừa BaseRule và trả về list[RuleViolation].
"""
import ast
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Severity(Enum):
    FAIL = "FAIL"   # CI blocks — Tier A hoặc Tier B critical
    WARN = "WARN"   # Advisory — Tier B quality hoặc Tier C convention
    INFO = "INFO"   # Informational — Tier C style


@dataclass
class RuleViolation:
    """Một vi phạm rule được phát hiện bởi AST analysis."""
    rule_id: str            # Ví dụ: "A001", "B003", "C001"
    rule_name: str          # Ví dụ: "SleepBan", "LongFunction"
    tier: str               # "A", "B", "C"
    severity: Severity
    file_path: str
    line: int
    detail: str             # Mô tả vi phạm cụ thể
    why: str                # Hậu quả nếu vi phạm — bắt buộc có

    def format(self) -> str:
        icon = {"FAIL": "❌", "WARN": "⚠ ", "INFO": "💡"}.get(self.severity.value, "?")
        return (
            f"{icon} {self.severity.value:<4}  {self.file_path}:{self.line}\n"
            f"         [{self.rule_name}] {self.detail}\n"
            f"         WHY: {self.why}"
        )


class BaseRule:
    """
    Base class cho tất cả AST rules.

    Subclass phải định nghĩa:
        tier: str          — "A", "B", hoặc "C"
        rule_id: str       — Unique ID, ví dụ "A001"
        rule_name: str     — Human-readable name
        severity: Severity — Mặc định của rule

    Và implement method:
        check(tree, filepath, ctx) -> list[RuleViolation]
    """
    tier: str = "B"
    rule_id: str = "B000"
    rule_name: str = "BaseRule"
    severity: Severity = Severity.WARN

    def check(
        self,
        tree: ast.AST,
        filepath: str,
        ctx: Optional[dict] = None,
    ) -> list[RuleViolation]:
        """
        Chạy rule check trên AST tree của một file.

        Args:
            tree    : Parsed AST của file Python
            filepath: Đường dẫn tuyệt đối đến file
            ctx     : Context bổ sung (ví dụ: LAYER_ORDER map)

        Returns:
            Danh sách vi phạm tìm thấy (rỗng nếu không có)
        """
        raise NotImplementedError(
            f"Rule {self.rule_name} must implement check()"
        )

    def _violation(
        self,
        filepath: str,
        line: int,
        detail: str,
        why: str,
        severity: Optional[Severity] = None,
    ) -> RuleViolation:
        """Helper tạo RuleViolation với đầy đủ metadata."""
        return RuleViolation(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            tier=self.tier,
            severity=severity or self.severity,
            file_path=filepath,
            line=line,
            detail=detail,
            why=why,
        )
