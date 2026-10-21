"""Tests for the ThreeWayMatcher engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from agent.data.store import DataStore
from agent.matching.matcher import ThreeWayMatcher
from agent.matching.models import MatchStatus
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


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_invoice(**overrides: Any) -> Invoice:
    """Return a minimal valid Invoice, with optional field overrides."""
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
            LineItem(
                line_no=2,
                description="Widget B",
                quantity=Decimal("50"),
                unit_price=Decimal("20.00"),
                total=Decimal("1000.00"),
            ),
        ),
        subtotal=Decimal("2000.00"),
        tax=Decimal("160.00"),
        total_amount=Decimal("2160.00"),
    )
    defaults.update(overrides)
    return Invoice(**defaults)


# ---------------------------------------------------------------------------
# Happy-path: fully matched invoice (INV-1001 vs PO-2001 / REC-3001)
# Note: REC-3001 received only 45 of 50 Widget B, so expect PARTIAL
# ---------------------------------------------------------------------------


def test_match_inv1001_returns_partial(parser: InvoiceParser, matcher: ThreeWayMatcher) -> None:
    """INV-1001 has a quantity shortfall on line 2 => PARTIAL."""
    invoice = parser.parse_by_id("INV-1001")
    result = matcher.match(invoice)
    assert result.status == MatchStatus.PARTIAL


def test_match_inv1001_po_and_receipt_found(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    invoice = parser.parse_by_id("INV-1001")
    result = matcher.match(invoice)
    assert result.po_found is True
    assert result.receipt_found is True
    assert result.currency_match is True


def test_match_inv1001_line2_quantity_discrepancy(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    """Line 2: invoiced 50, received 45 → quantity discrepancy."""
    invoice = parser.parse_by_id("INV-1001")
    result = matcher.match(invoice)
    line2 = next(d for d in result.line_discrepancies if d.line_no == 2)
    assert line2.has_quantity_discrepancy is True
    assert line2.quantity_delta == Decimal("5")  # 50 - 45


def test_match_inv1001_line1_no_discrepancy(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    """Line 1: invoiced 100, received 100, price exact."""
    invoice = parser.parse_by_id("INV-1001")
    result = matcher.match(invoice)
    line1 = next(d for d in result.line_discrepancies if d.line_no == 1)
    assert line1.has_quantity_discrepancy is False
    assert line1.has_price_discrepancy is False


# ---------------------------------------------------------------------------
# Price variance: INV-1002 invoices $55 vs PO price $53.90 (~2.04 %)
# ---------------------------------------------------------------------------


def test_match_inv1002_price_discrepancy(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    """INV-1002 unit price $55 vs PO $53.90 is > 2% → PARTIAL."""
    invoice = parser.parse_by_id("INV-1002")
    result = matcher.match(invoice)
    assert result.status == MatchStatus.PARTIAL
    line1 = result.line_discrepancies[0]
    assert line1.has_price_discrepancy is True
    assert line1.price_delta == Decimal("55.00") - Decimal("53.90")


def test_match_inv1002_within_tolerance_with_wider_threshold(
    store: DataStore, parser: InvoiceParser
) -> None:
    """With a 5% price tolerance INV-1002 should be MATCHED."""
    wide_matcher = ThreeWayMatcher(store, price_tolerance_pct=Decimal("5.0"))
    invoice = parser.parse_by_id("INV-1002")
    result = wide_matcher.match(invoice)
    assert result.status == MatchStatus.MATCHED


# ---------------------------------------------------------------------------
# Missing PO: INV-1003 references PO-9999 which does not exist
# ---------------------------------------------------------------------------


def test_match_missing_po(parser: InvoiceParser, matcher: ThreeWayMatcher) -> None:
    invoice = parser.parse_by_id("INV-1003")
    result = matcher.match(invoice)
    assert result.status == MatchStatus.UNMATCHED
    assert result.po_found is False


def test_match_missing_po_notes(parser: InvoiceParser, matcher: ThreeWayMatcher) -> None:
    invoice = parser.parse_by_id("INV-1003")
    result = matcher.match(invoice)
    assert any("PO-9999" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Missing receipt
# ---------------------------------------------------------------------------


def test_match_no_receipt_id(matcher: ThreeWayMatcher) -> None:
    invoice = _make_invoice(receipt_id=None)
    result = matcher.match(invoice)
    assert result.receipt_found is False
    assert result.status == MatchStatus.UNMATCHED


def test_match_receipt_id_not_in_store(matcher: ThreeWayMatcher) -> None:
    invoice = _make_invoice(receipt_id="REC-DOES-NOT-EXIST")
    result = matcher.match(invoice)
    assert result.receipt_found is False
    assert result.status == MatchStatus.UNMATCHED


# ---------------------------------------------------------------------------
# Currency mismatch
# ---------------------------------------------------------------------------


def test_match_currency_mismatch(matcher: ThreeWayMatcher) -> None:
    """Invoice in EUR but PO-2001 is in USD → UNMATCHED."""
    invoice = _make_invoice(currency="EUR")
    result = matcher.match(invoice)
    assert result.currency_match is False
    assert result.status == MatchStatus.UNMATCHED
    assert any("currency" in note.lower() for note in result.notes)


# ---------------------------------------------------------------------------
# Perfect match
# ---------------------------------------------------------------------------


def test_perfect_match(matcher: ThreeWayMatcher) -> None:
    """Invoice that exactly mirrors PO-2001 quantities and prices, and receipt
    delivers all quantities → MATCHED."""
    # REC-3001 delivers line1=100 (ok) but line2=45 (shortfall).
    # To get a perfect match we create an invoice only with line1.
    invoice = _make_invoice(
        invoice_id="INV-PERFECT",
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
    result = matcher.match(invoice)
    assert result.status == MatchStatus.MATCHED
    assert all(
        not d.has_price_discrepancy and not d.has_quantity_discrepancy
        for d in result.line_discrepancies
    )


# ---------------------------------------------------------------------------
# match_all
# ---------------------------------------------------------------------------


def test_match_all_returns_one_per_invoice(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    assert len(results) == len(invoices)


def test_match_all_invoice_ids(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    invoices = parser.parse_all()
    results = matcher.match_all(invoices)
    ids = {r.invoice_id for r in results}
    assert "INV-1001" in ids
    assert "INV-1002" in ids
    assert "INV-1003" in ids


# ---------------------------------------------------------------------------
# MatchResult structure
# ---------------------------------------------------------------------------


def test_match_result_has_line_discrepancies(
    parser: InvoiceParser, matcher: ThreeWayMatcher
) -> None:
    invoice = parser.parse_by_id("INV-1001")
    result = matcher.match(invoice)
    assert len(result.line_discrepancies) == len(invoice.line_items)


def test_line_discrepancy_fields(parser: InvoiceParser, matcher: ThreeWayMatcher) -> None:
    invoice = parser.parse_by_id("INV-1002")
    result = matcher.match(invoice)
    disc = result.line_discrepancies[0]
    assert disc.invoice_unit_price == Decimal("55.00")
    assert disc.po_unit_price == Decimal("53.90")
    assert disc.price_variance_pct is not None
    assert disc.price_variance_pct > Decimal("2")
