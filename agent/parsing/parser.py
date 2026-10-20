"""InvoiceParser: normalises raw invoice dicts into canonical Invoice objects."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from agent.data.store import DataStore
from agent.parsing.models import Invoice, LineItem


class InvoiceParseError(ValueError):
    """Raised when a raw invoice dict cannot be normalised."""


class InvoiceParser:
    """Reads raw invoice dicts from a DataStore and returns validated Invoice objects."""

    def __init__(self, store: DataStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_all(self) -> list[Invoice]:
        """Parse every invoice in the DataStore and return a list of Invoice objects."""
        invoices: list[Invoice] = []
        for raw in self._store.get_all_invoices():
            invoice_id = raw.get("invoice_id", "<unknown>")
            try:
                invoices.append(self.parse(raw))
            except InvoiceParseError:
                raise
            except Exception as exc:  # pragma: no cover
                raise InvoiceParseError(
                    f"Unexpected error parsing invoice {invoice_id}: {exc}"
                ) from exc
        return invoices

    def parse_by_id(self, invoice_id: str) -> Invoice:
        """Fetch invoice *invoice_id* from the store and parse it."""
        raw = self._store.get_invoice_by_id(invoice_id)
        if raw is None:
            raise InvoiceParseError(f"Invoice '{invoice_id}' not found in DataStore")
        return self.parse(raw)

    def parse(self, raw: dict[str, Any]) -> Invoice:
        """Normalise a single raw invoice dict into an Invoice dataclass.

        Raises:
            InvoiceParseError: if any required field is missing or invalid.
        """
        invoice_id = self._req_str(raw, "invoice_id")
        try:
            return Invoice(
                invoice_id=invoice_id,
                vendor_id=self._req_str(raw, "vendor_id"),
                vendor_name=self._req_str(raw, "vendor_name"),
                po_id=self._req_str(raw, "po_id"),
                receipt_id=self._opt_str(raw, "receipt_id"),
                invoice_date=self._req_date(raw, "invoice_date"),
                due_date=self._req_date(raw, "due_date"),
                currency=self._req_currency(raw, "currency"),
                line_items=self._parse_line_items(raw, invoice_id),
                subtotal=self._req_decimal(raw, "subtotal"),
                tax=self._req_decimal(raw, "tax"),
                total_amount=self._req_decimal(raw, "total_amount"),
            )
        except InvoiceParseError:
            raise
        except (TypeError, ValueError) as exc:
            raise InvoiceParseError(
                f"Validation error for invoice '{invoice_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Line-item parsing
    # ------------------------------------------------------------------

    def _parse_line_items(
        self, raw: dict[str, Any], invoice_id: str
    ) -> tuple[LineItem, ...]:
        raw_lines = raw.get("line_items")
        if not isinstance(raw_lines, list) or len(raw_lines) == 0:
            raise InvoiceParseError(
                f"Invoice '{invoice_id}' has no line_items or field is missing"
            )
        items: list[LineItem] = []
        for idx, line in enumerate(raw_lines):
            if not isinstance(line, dict):
                raise InvoiceParseError(
                    f"Invoice '{invoice_id}' line {idx}: expected a dict, got {type(line).__name__}"
                )
            try:
                items.append(
                    LineItem(
                        line_no=self._req_int(line, "line_no"),
                        description=self._req_str(line, "description"),
                        quantity=self._req_decimal(line, "quantity"),
                        unit_price=self._req_decimal(line, "unit_price"),
                        total=self._req_decimal(line, "total"),
                    )
                )
            except InvoiceParseError:
                raise
            except (TypeError, ValueError) as exc:
                raise InvoiceParseError(
                    f"Invoice '{invoice_id}' line {idx}: {exc}"
                ) from exc
        return tuple(items)

    # ------------------------------------------------------------------
    # Field extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _req_str(data: dict[str, Any], key: str) -> str:
        val = data.get(key)
        if val is None:
            raise InvoiceParseError(f"Missing required field '{key}'")
        if not isinstance(val, str):
            raise InvoiceParseError(
                f"Field '{key}' must be a string, got {type(val).__name__}"
            )
        stripped = val.strip()
        if not stripped:
            raise InvoiceParseError(f"Field '{key}' must not be blank")
        return stripped

    @staticmethod
    def _opt_str(data: dict[str, Any], key: str) -> str | None:
        val = data.get(key)
        if val is None:
            return None
        if not isinstance(val, str):
            raise InvoiceParseError(
                f"Field '{key}' must be a string or null, got {type(val).__name__}"
            )
        stripped = val.strip()
        return stripped if stripped else None

    @staticmethod
    def _req_date(data: dict[str, Any], key: str) -> date:
        val = data.get(key)
        if val is None:
            raise InvoiceParseError(f"Missing required field '{key}'")
        if isinstance(val, date):
            return val
        if not isinstance(val, str):
            raise InvoiceParseError(
                f"Field '{key}' must be a date string (YYYY-MM-DD), got {type(val).__name__}"
            )
        try:
            return date.fromisoformat(val)
        except ValueError as exc:
            raise InvoiceParseError(
                f"Field '{key}' has invalid date format '{val}': {exc}"
            ) from exc

    @staticmethod
    def _req_decimal(data: dict[str, Any], key: str) -> Decimal:
        val = data.get(key)
        if val is None:
            raise InvoiceParseError(f"Missing required field '{key}'")
        try:
            return Decimal(str(val))
        except (InvalidOperation, TypeError) as exc:
            raise InvoiceParseError(
                f"Field '{key}' cannot be converted to Decimal (got {val!r}): {exc}"
            ) from exc

    @staticmethod
    def _req_int(data: dict[str, Any], key: str) -> int:
        val = data.get(key)
        if val is None:
            raise InvoiceParseError(f"Missing required field '{key}'")
        if not isinstance(val, int):
            raise InvoiceParseError(
                f"Field '{key}' must be an integer, got {type(val).__name__}"
            )
        return val

    @staticmethod
    def _req_currency(data: dict[str, Any], key: str) -> str:
        val = InvoiceParser._req_str(data, key)
        if len(val) != 3 or not val.isalpha():
            raise InvoiceParseError(
                f"Field '{key}' must be a 3-letter ISO currency code, got '{val}'"
            )
        return val.upper()
