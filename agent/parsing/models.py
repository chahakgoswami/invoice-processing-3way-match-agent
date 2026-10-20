"""Canonical dataclasses for parsed invoice data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class LineItem:
    """A single line item on an invoice."""

    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal

    def __post_init__(self) -> None:
        if self.line_no < 1:
            raise ValueError(f"line_no must be >= 1, got {self.line_no}")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if self.quantity < Decimal("0"):
            raise ValueError(f"quantity must be >= 0, got {self.quantity}")
        if self.unit_price < Decimal("0"):
            raise ValueError(f"unit_price must be >= 0, got {self.unit_price}")
        if self.total < Decimal("0"):
            raise ValueError(f"total must be >= 0, got {self.total}")


@dataclass(frozen=True)
class Invoice:
    """Canonical, validated representation of an invoice."""

    invoice_id: str
    vendor_id: str
    vendor_name: str
    po_id: str
    receipt_id: Optional[str]
    invoice_date: date
    due_date: date
    currency: str
    line_items: tuple[LineItem, ...]
    subtotal: Decimal
    tax: Decimal
    total_amount: Decimal

    def __post_init__(self) -> None:
        if not self.invoice_id.strip():
            raise ValueError("invoice_id must not be empty")
        if not self.vendor_id.strip():
            raise ValueError("vendor_id must not be empty")
        if not self.vendor_name.strip():
            raise ValueError("vendor_name must not be empty")
        if not self.po_id.strip():
            raise ValueError("po_id must not be empty")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(
                f"currency must be a 3-letter ISO code, got '{self.currency}'"
            )
        if self.due_date < self.invoice_date:
            raise ValueError(
                f"due_date {self.due_date} must not be before invoice_date {self.invoice_date}"
            )
        if not self.line_items:
            raise ValueError("Invoice must have at least one line item")
        if self.subtotal < Decimal("0"):
            raise ValueError(f"subtotal must be >= 0, got {self.subtotal}")
        if self.tax < Decimal("0"):
            raise ValueError(f"tax must be >= 0, got {self.tax}")
        if self.total_amount < Decimal("0"):
            raise ValueError(f"total_amount must be >= 0, got {self.total_amount}")
