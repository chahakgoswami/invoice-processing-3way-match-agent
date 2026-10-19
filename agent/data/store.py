"""DataStore: loads and queries mock fixture data from JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Default fixture directory relative to this file
_FIXTURES_DIR = Path(__file__).parent / "fixtures"


class DataStore:
    """In-memory data store backed by JSON fixture files.

    Loads invoices, purchase orders, and delivery receipts once at
    construction time and exposes simple query helpers.
    """

    def __init__(self, fixtures_dir: Path | str | None = None) -> None:
        self._dir = Path(fixtures_dir) if fixtures_dir else _FIXTURES_DIR
        self._invoices: list[dict[str, Any]] = self._load("invoices.json")
        self._purchase_orders: list[dict[str, Any]] = self._load("purchase_orders.json")
        self._delivery_receipts: list[dict[str, Any]] = self._load("delivery_receipts.json")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, filename: str) -> list[dict[str, Any]]:
        """Read a JSON fixture file and return its contents as a list."""
        path = self._dir / filename
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        raise ValueError(f"Expected a JSON array in {path}, got {type(data).__name__}")

    # ------------------------------------------------------------------
    # Invoice queries
    # ------------------------------------------------------------------

    def get_all_invoices(self) -> list[dict[str, Any]]:
        """Return all raw invoice dicts."""
        return list(self._invoices)

    def get_invoice_by_id(self, invoice_id: str) -> dict[str, Any] | None:
        """Return the invoice with the given ID, or None."""
        for inv in self._invoices:
            if inv.get("invoice_id") == invoice_id:
                return inv
        return None

    # ------------------------------------------------------------------
    # Purchase order queries
    # ------------------------------------------------------------------

    def get_all_purchase_orders(self) -> list[dict[str, Any]]:
        """Return all raw purchase order dicts."""
        return list(self._purchase_orders)

    def get_po_by_id(self, po_id: str) -> dict[str, Any] | None:
        """Return the purchase order with the given ID, or None."""
        for po in self._purchase_orders:
            if po.get("po_id") == po_id:
                return po
        return None

    # ------------------------------------------------------------------
    # Delivery receipt queries
    # ------------------------------------------------------------------

    def get_all_delivery_receipts(self) -> list[dict[str, Any]]:
        """Return all raw delivery receipt dicts."""
        return list(self._delivery_receipts)

    def get_receipt_by_id(self, receipt_id: str) -> dict[str, Any] | None:
        """Return the delivery receipt with the given ID, or None."""
        for rec in self._delivery_receipts:
            if rec.get("receipt_id") == receipt_id:
                return rec
        return None

    def get_receipts_for_po(self, po_id: str) -> list[dict[str, Any]]:
        """Return all delivery receipts that reference the given PO ID."""
        return [rec for rec in self._delivery_receipts if rec.get("po_id") == po_id]

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DataStore(invoices={len(self._invoices)}, "
            f"purchase_orders={len(self._purchase_orders)}, "
            f"delivery_receipts={len(self._delivery_receipts)})"
        )
