"""Data models for exception records produced by the ExceptionHandler."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ExceptionSeverity(str, Enum):
    """Severity level of an exception record."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionRule(str, Enum):
    """Classification rule that triggered the exception."""

    PRICE_VARIANCE = "price_variance"
    QUANTITY_SHORTFALL = "quantity_shortfall"
    MISSING_PO = "missing_po"
    MISSING_RECEIPT = "missing_receipt"
    CURRENCY_MISMATCH = "currency_mismatch"
    DUPLICATE_INVOICE = "duplicate_invoice"


@dataclass(frozen=True)
class ExceptionRecord:
    """A single structured exception entry written to the in-memory log."""

    exception_id: str
    invoice_id: str
    rule: ExceptionRule
    severity: ExceptionSeverity
    description: str
    # Optional contextual detail (e.g., line number, variance %).
    detail: Optional[str]
    created_at: datetime = field(default_factory=datetime.utcnow)
