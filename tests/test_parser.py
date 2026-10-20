"""Tests for the InvoiceParser module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from agent.data.store import DataStore
from agent.parsing.models import Invoice, LineItem
from agent.parsing.parser import InvoiceParseError, InvoiceParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> DataStore:
    return DataStore()


@pytest.fixture()
def parser(store: DataStore) -> InvoiceParser:
    return InvoiceParser(store)


_VALID_RAW: dict[str, Any] = {
    "invoice_id": "INV-TEST",
    "vendor_id": "VENDOR-99",
    "vendor_name": "Test Vendor",
    "po_id": "PO-9999",
    "receipt_id": "REC-8888",
    "invoice_date": "2024-01-01",
    "due_date": "2024-01-31",
    "currency": "USD",
    "line_items": [
        {
            "line_no": 1,
            "description": "Widget",
            "quantity": 10,
            "unit_price": 5.00,
            "total": 50.00,
        }
    ],
    "subtotal": 50.00,
    "tax": 4.00,
    "total_amount": 54.00,
}


def _raw(**overrides: Any) -> dict[str, Any]:
    """Return a copy of _VALID_RAW with overrides applied."""
    d = dict(_VALID_RAW)
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_parse_returns_invoice(parser: InvoiceParser) -> None:
    invoice = parser.parse(_VALID_RAW)
    assert isinstance(invoice, Invoice)


def test_parse_fields(parser: InvoiceParser) -> None:
    invoice = parser.parse(_VALID_RAW)
    assert invoice.invoice_id == "INV-TEST"
    assert invoice.vendor_id == "VENDOR-99"
    assert invoice.vendor_name == "Test Vendor"
    assert invoice.po_id == "PO-9999"
    assert invoice.receipt_id == "REC-8888"
    assert invoice.invoice_date == date(2024, 1, 1)
    assert invoice.due_date == date(2024, 1, 31)
    assert invoice.currency == "USD"
    assert invoice.subtotal == Decimal("50.00")
    assert invoice.tax == Decimal("4.00")
    assert invoice.total_amount == Decimal("54.00")


def test_parse_line_items(parser: InvoiceParser) -> None:
    invoice = parser.parse(_VALID_RAW)
    assert len(invoice.line_items) == 1
    item = invoice.line_items[0]
    assert isinstance(item, LineItem)
    assert item.line_no == 1
    assert item.description == "Widget"
    assert item.quantity == Decimal("10")
    assert item.unit_price == Decimal("5.00")
    assert item.total == Decimal("50.00")


def test_parse_null_receipt_id(parser: InvoiceParser) -> None:
    raw = _raw(receipt_id=None)
    invoice = parser.parse(raw)
    assert invoice.receipt_id is None


def test_currency_uppercased(parser: InvoiceParser) -> None:
    raw = _raw(currency="usd")
    invoice = parser.parse(raw)
    assert invoice.currency == "USD"


def test_parse_all_returns_invoices(parser: InvoiceParser) -> None:
    invoices = parser.parse_all()
    assert len(invoices) >= 1
    assert all(isinstance(inv, Invoice) for inv in invoices)


def test_parse_all_invoice_ids(parser: InvoiceParser) -> None:
    invoices = parser.parse_all()
    ids = {inv.invoice_id for inv in invoices}
    assert "INV-1001" in ids
    assert "INV-1002" in ids


def test_parse_by_id(parser: InvoiceParser) -> None:
    invoice = parser.parse_by_id("INV-1001")
    assert invoice.invoice_id == "INV-1001"
    assert invoice.vendor_name == "Acme Supplies Ltd."
    assert invoice.currency == "USD"


def test_parse_by_id_multi_line(parser: InvoiceParser) -> None:
    invoice = parser.parse_by_id("INV-1001")
    assert len(invoice.line_items) == 2


def test_parse_invoice_with_missing_po(parser: InvoiceParser) -> None:
    """INV-1003 references a non-existent PO — parser should still succeed."""
    invoice = parser.parse_by_id("INV-1003")
    assert invoice.po_id == "PO-9999"
    assert invoice.receipt_id is None


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


def test_parse_by_id_not_found(parser: InvoiceParser) -> None:
    with pytest.raises(InvoiceParseError, match="not found"):
        parser.parse_by_id("INV-DOES-NOT-EXIST")


def test_missing_invoice_id(parser: InvoiceParser) -> None:
    raw = _raw()
    del raw["invoice_id"]
    with pytest.raises(InvoiceParseError, match="invoice_id"):
        parser.parse(raw)


def test_missing_vendor_id(parser: InvoiceParser) -> None:
    raw = _raw()
    del raw["vendor_id"]
    with pytest.raises(InvoiceParseError, match="vendor_id"):
        parser.parse(raw)


def test_missing_line_items(parser: InvoiceParser) -> None:
    raw = _raw()
    del raw["line_items"]
    with pytest.raises(InvoiceParseError, match="line_items"):
        parser.parse(raw)


def test_empty_line_items(parser: InvoiceParser) -> None:
    raw = _raw(line_items=[])
    with pytest.raises(InvoiceParseError, match="line_items"):
        parser.parse(raw)


def test_invalid_date_format(parser: InvoiceParser) -> None:
    raw = _raw(invoice_date="15-01-2024")
    with pytest.raises(InvoiceParseError, match="invoice_date"):
        parser.parse(raw)


def test_due_date_before_invoice_date(parser: InvoiceParser) -> None:
    raw = _raw(invoice_date="2024-02-01", due_date="2024-01-01")
    with pytest.raises((InvoiceParseError, ValueError)):
        parser.parse(raw)


def test_invalid_currency_too_long(parser: InvoiceParser) -> None:
    raw = _raw(currency="USDD")
    with pytest.raises(InvoiceParseError, match="currency"):
        parser.parse(raw)


def test_invalid_currency_numeric(parser: InvoiceParser) -> None:
    raw = _raw(currency="U5D")
    with pytest.raises(InvoiceParseError, match="currency"):
        parser.parse(raw)


def test_invalid_decimal_field(parser: InvoiceParser) -> None:
    raw = _raw(subtotal="not-a-number")
    with pytest.raises(InvoiceParseError, match="subtotal"):
        parser.parse(raw)


def test_blank_vendor_name(parser: InvoiceParser) -> None:
    raw = _raw(vendor_name="   ")
    with pytest.raises(InvoiceParseError, match="vendor_name"):
        parser.parse(raw)
