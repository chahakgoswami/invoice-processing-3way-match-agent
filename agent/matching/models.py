"""Data models for three-way match results."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class MatchStatus(str, Enum):
    """Overall status of a three-way match."""

    MATCHED = "matched"
    PARTIAL = "partial"
    UNMATCHED = "unmatched"


@dataclass(frozen=True)
class LineDiscrepancy:
    """Discrepancy details for a single line item."""

    line_no: int
    description: str
    # Quantity fields
    invoice_quantity: Decimal
    po_quantity: Optional[Decimal]
    received_quantity: Optional[Decimal]
    quantity_delta: Optional[Decimal]          # invoice_qty - received_qty
    quantity_variance_pct: Optional[Decimal]   # abs delta / po_qty * 100
    # Price fields
    invoice_unit_price: Decimal
    po_unit_price: Optional[Decimal]
    price_delta: Optional[Decimal]             # invoice_price - po_price
    price_variance_pct: Optional[Decimal]      # abs delta / po_price * 100
    # Flags
    has_quantity_discrepancy: bool
    has_price_discrepancy: bool


@dataclass(frozen=True)
class MatchResult:
    """Result of a three-way match for one invoice."""

    invoice_id: str
    po_id: str
    receipt_id: Optional[str]
    status: MatchStatus
    # Document-level flags
    po_found: bool
    receipt_found: bool
    currency_match: bool
    # Line-level discrepancies (one per invoice line)
    line_discrepancies: tuple[LineDiscrepancy, ...] = field(default_factory=tuple)
    # Human-readable summary of all issues
    notes: tuple[str, ...] = field(default_factory=tuple)
