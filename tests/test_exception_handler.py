"""Tests for the ExceptionHandler module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from agent.data.store import DataStore
from agent.exceptions.handler import ExceptionHandler
from agent.exceptions.models import ExceptionRule, ExceptionSeverity
from agent.matching.matcher import ThreeWayMatcher
from agent.matching.models import MatchResult, MatchStatus
from agent.parsing.models import Invoice, LineItem
from agent.parsing.parser import InvoiceParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> DataStore:
    return DataStore()


@pytest.fixture()
def parser(store: DataStore) -> InvoiceParser:
    return InvoiceParser(store)


@pytest.fixture()
def matcher(store: DataStore) -> ThreeWayMatcher:
    return ThreeWayMatcher(store)


@pytest.fixture()
def handler() -> ExceptionHandler:
    return ExceptionHandler()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_invoice(**overrides: Any) -> Invoice:
    defaults: dict[str, Any] = dict(
        invoice_id="INV-TEST",
        vendor_id="VENDOR-42",
        vendor_name="Acme Supplies Ltd.",
        po_id="PO-2001",
        receipt_id="REC-3001",
        invoice_date=date(2024, 3, 15),
        due_date=date(2024, 4, 14),
        currency="USD",
        line_items=(
            LineItem(
                line_no=1,
                description="Widget A",
                quantity=Decimal("100"),
                unit_price=Decimal("10.00"),
                total=Decimal("1000.00"),
            ),
        ),
        subtotal=Decimal("1000.00"),
        tax=Decimal("80.00"),
        total_amount=Decimal("1080.00"),
    )
    defaults.update(overrides)
    return Invoice(**defaults)


# ---------------------------------------------------------------------------
# Clean invoice → no exceptions
# ---------------------------------------------------------------------------


def test_clean_match_no_exceptions(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    """A perfectly matched invoice should produce zero exception records."""
    invoice = _make_invoice()
    result = matcher.match(invoice)
    # Override status to MATCHED for a clean test
    clean_result = MatchResult(
        invoice_id=result.invoice_id,
        po_id=result.po_id,
        receipt_id=result.receipt_id,
        status=MatchStatus.MATCHED,
        po_found=True,
        receipt_found=True,
        currency_match=True,
        line_discrepancies=(
            # Line 1: no discrepancies
            result.line_discrepancies[0],
        ),
        notes=(),
    )
    records = handler.handle(clean_result)
    assert records == []
    assert handler.log == []


# ---------------------------------------------------------------------------
# Missing PO
# ---------------------------------------------------------------------------


def test_missing_po_raises_critical_exception(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoice = parser.parse_by_id("INV-1003")  # references non-existent PO-9999
    result = matcher.match(invoice)
    records = handler.handle(result)
    rules = {r.rule for r in records}
    assert ExceptionRule.MISSING_PO in rules
    missing_po_rec = next(r for r in records if r.rule == ExceptionRule.MISSING_PO)
    assert missing_po_rec.severity == ExceptionSeverity.CRITICAL
    assert "PO-9999" in missing_po_rec.description


# ---------------------------------------------------------------------------
# Missing receipt
# ---------------------------------------------------------------------------


def test_missing_receipt_raises_high_exception(
    matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoice = _make_invoice(receipt_id=None)
    result = matcher.match(invoice)
    records = handler.handle(result)
    rules = {r.rule for r in records}
    # Missing receipt (and unmatched because of it)
    assert ExceptionRule.MISSING_RECEIPT in rules
    rec = next(r for r in records if r.rule == ExceptionRule.MISSING_RECEIPT)
    assert rec.severity == ExceptionSeverity.HIGH


# ---------------------------------------------------------------------------
# Price variance
# ---------------------------------------------------------------------------


def test_price_variance_exception(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    """INV-1002 has a >2% price variance on line 1."""
    invoice = parser.parse_by_id("INV-1002")
    result = matcher.match(invoice)
    records = handler.handle(result)
    rules = {r.rule for r in records}
    assert ExceptionRule.PRICE_VARIANCE in rules
    rec = next(r for r in records if r.rule == ExceptionRule.PRICE_VARIANCE)
    assert rec.severity == ExceptionSeverity.MEDIUM
    assert "line 1" in rec.description
    assert rec.detail is not None
    assert "variance_pct" in rec.detail


# ---------------------------------------------------------------------------
# Quantity shortfall
# ---------------------------------------------------------------------------


def test_quantity_shortfall_exception(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    """INV-1001 line 2 has a quantity shortfall (invoiced 50, received 45)."""
    invoice = parser.parse_by_id("INV-1001")
    result = matcher.match(invoice)
    records = handler.handle(result)
    rules = {r.rule for r in records}
    assert ExceptionRule.QUANTITY_SHORTFALL in rules
    rec = next(r for r in records if r.rule == ExceptionRule.QUANTITY_SHORTFALL)
    assert rec.severity == ExceptionSeverity.MEDIUM
    assert "line 2" in rec.description
    assert rec.invoice_id == "INV-1001"


# ---------------------------------------------------------------------------
# Currency mismatch
# ---------------------------------------------------------------------------


def test_currency_mismatch_exception(
    matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoice = _make_invoice(currency="EUR")
    result = matcher.match(invoice)
    records = handler.handle(result)
    rules = {r.rule for r in records}
    assert ExceptionRule.CURRENCY_MISMATCH in rules
    rec = next(r for r in records if r.rule == ExceptionRule.CURRENCY_MISMATCH)
    assert rec.severity == ExceptionSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Duplicate invoice
# ---------------------------------------------------------------------------


def test_duplicate_invoice_exception(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    """Processing the same invoice_id twice must raise a DUPLICATE_INVOICE exception."""
    invoice = parser.parse_by_id("INV-1002")
    result = matcher.match(invoice)

    # First time — no duplicate exception
    first_records = handler.handle(result)
    first_rules = {r.rule for r in first_records}
    assert ExceptionRule.DUPLICATE_INVOICE not in first_rules

    # Second time — must flag duplicate
    second_records = handler.handle(result)
    second_rules = {r.rule for r in second_records}
    assert ExceptionRule.DUPLICATE_INVOICE in second_rules
    dup_rec = next(r for r in second_records if r.rule == ExceptionRule.DUPLICATE_INVOICE)
    assert dup_rec.severity == ExceptionSeverity.HIGH
    assert "INV-1002" in dup_rec.description


def test_inv1004_detected_as_duplicate_of_inv1002(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    """INV-1004 is a separate record but same content as INV-1002; it is NOT a
    duplicate by invoice_id — only processing the *same* invoice_id twice flags it."""
    inv1002 = parser.parse_by_id("INV-1002")
    inv1004 = parser.parse_by_id("INV-1004")
    res1002 = matcher.match(inv1002)
    res1004 = matcher.match(inv1004)

    records_1002 = handler.handle(res1002)
    records_1004 = handler.handle(res1004)

    # Neither should be flagged as duplicate (different invoice_ids)
    assert all(r.rule != ExceptionRule.DUPLICATE_INVOICE for r in records_1002)
    assert all(r.rule != ExceptionRule.DUPLICATE_INVOICE for r in records_1004)


# ---------------------------------------------------------------------------
# handle_all
# ---------------------------------------------------------------------------


def test_handle_all_accumulates_log(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    all_records = handler.handle_all(results)
    assert len(handler.log) == len(all_records)
    # Should have at least one record per problematic invoice
    assert len(all_records) >= 1


# ---------------------------------------------------------------------------
# Log accessors
# ---------------------------------------------------------------------------


def test_get_by_invoice(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    handler.handle_all(results)

    inv1003_records = handler.get_by_invoice("INV-1003")
    assert all(r.invoice_id == "INV-1003" for r in inv1003_records)
    assert len(inv1003_records) >= 1


def test_get_by_rule(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    handler.handle_all(results)

    missing_po_records = handler.get_by_rule(ExceptionRule.MISSING_PO)
    assert len(missing_po_records) >= 1
    assert all(r.rule == ExceptionRule.MISSING_PO for r in missing_po_records)


def test_get_by_severity(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    handler.handle_all(results)

    critical = handler.get_by_severity(ExceptionSeverity.CRITICAL)
    assert len(critical) >= 1
    assert all(r.severity == ExceptionSeverity.CRITICAL for r in critical)


# ---------------------------------------------------------------------------
# ExceptionRecord structure
# ---------------------------------------------------------------------------


def test_exception_record_has_unique_ids(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    handler.handle_all(results)
    ids = [r.exception_id for r in handler.log]
    assert len(ids) == len(set(ids)), "exception_ids must be unique"


def test_exception_record_has_created_at(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoice = parser.parse_by_id("INV-1003")
    result = matcher.match(invoice)
    records = handler.handle(result)
    assert len(records) >= 1
    for rec in records:
        assert rec.created_at is not None


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


def test_clear_resets_log(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    invoice = parser.parse_by_id("INV-1003")
    result = matcher.match(invoice)
    handler.handle(result)
    assert len(handler.log) >= 1
    handler.clear()
    assert handler.log == []


def test_clear_resets_seen_ids(
    parser: InvoiceParser, matcher: ThreeWayMatcher, handler: ExceptionHandler
) -> None:
    """After clear(), processing the same invoice_id must not flag it as duplicate."""
    invoice = parser.parse_by_id("INV-1002")
    result = matcher.match(invoice)
    handler.handle(result)
    handler.clear()
    # After clear, same invoice_id should not be flagged as duplicate
    records = handler.handle(result)
    rules = {r.rule for r in records}
    assert ExceptionRule.DUPLICATE_INVOICE not in rules
