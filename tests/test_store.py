"""Basic smoke tests for the DataStore."""

from __future__ import annotations

import pytest

from agent.data.store import DataStore


@pytest.fixture()
def store() -> DataStore:
    return DataStore()


def test_loads_invoices(store: DataStore) -> None:
    invoices = store.get_all_invoices()
    assert len(invoices) >= 1
    assert all("invoice_id" in inv for inv in invoices)


def test_loads_purchase_orders(store: DataStore) -> None:
    pos = store.get_all_purchase_orders()
    assert len(pos) >= 1
    assert all("po_id" in po for po in pos)


def test_loads_delivery_receipts(store: DataStore) -> None:
    receipts = store.get_all_delivery_receipts()
    assert len(receipts) >= 1
    assert all("receipt_id" in rec for rec in receipts)


def test_get_invoice_by_id_found(store: DataStore) -> None:
    inv = store.get_invoice_by_id("INV-1001")
    assert inv is not None
    assert inv["vendor_name"] == "Acme Supplies Ltd."


def test_get_invoice_by_id_not_found(store: DataStore) -> None:
    assert store.get_invoice_by_id("DOES-NOT-EXIST") is None


def test_get_po_by_id_found(store: DataStore) -> None:
    po = store.get_po_by_id("PO-2001")
    assert po is not None
    assert po["vendor_id"] == "VENDOR-42"


def test_get_po_by_id_not_found(store: DataStore) -> None:
    assert store.get_po_by_id("PO-9999") is None


def test_get_receipt_by_id_found(store: DataStore) -> None:
    rec = store.get_receipt_by_id("REC-3001")
    assert rec is not None
    assert rec["po_id"] == "PO-2001"


def test_get_receipts_for_po(store: DataStore) -> None:
    receipts = store.get_receipts_for_po("PO-2002")
    assert len(receipts) == 1
    assert receipts[0]["receipt_id"] == "REC-3002"


def test_get_receipts_for_po_empty(store: DataStore) -> None:
    assert store.get_receipts_for_po("PO-UNKNOWN") == []
