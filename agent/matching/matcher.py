"""ThreeWayMatcher: joins Invoice, PO, and DeliveryReceipt and produces a MatchResult."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from agent.data.store import DataStore
from agent.matching.models import LineDiscrepancy, MatchResult, MatchStatus
from agent.parsing.models import Invoice, LineItem

# Default tolerances (can be overridden per instance)
_DEFAULT_PRICE_TOLERANCE_PCT = Decimal("2.0")   # 2 %
_DEFAULT_QTY_TOLERANCE_PCT = Decimal("0.0")     # 0 % — exact by default


class ThreeWayMatcher:
    """Performs three-way matching between an Invoice, its Purchase Order,
    and the associated Delivery Receipt(s).

    Parameters
    ----------
    store:
        DataStore instance used to look up POs and receipts.
    price_tolerance_pct:
        Maximum allowed price variance percentage before flagging a discrepancy.
    qty_tolerance_pct:
        Maximum allowed quantity variance percentage before flagging a discrepancy.
    """

    def __init__(
        self,
        store: DataStore,
        price_tolerance_pct: Decimal = _DEFAULT_PRICE_TOLERANCE_PCT,
        qty_tolerance_pct: Decimal = _DEFAULT_QTY_TOLERANCE_PCT,
    ) -> None:
        self._store = store
        self._price_tol = price_tolerance_pct
        self._qty_tol = qty_tolerance_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match(self, invoice: Invoice) -> MatchResult:
        """Match *invoice* against its referenced PO and DeliveryReceipt.

        Returns a :class:`MatchResult` with status and discrepancy details.
        """
        notes: list[str] = []

        # ----------------------------------------------------------------
        # 1. Fetch PO
        # ----------------------------------------------------------------
        raw_po = self._store.get_po_by_id(invoice.po_id)
        po_found = raw_po is not None
        if not po_found:
            notes.append(f"Purchase order '{invoice.po_id}' not found.")

        # ----------------------------------------------------------------
        # 2. Fetch DeliveryReceipt
        # ----------------------------------------------------------------
        raw_receipt: Optional[dict[str, Any]] = None
        receipt_found = False
        if invoice.receipt_id:
            raw_receipt = self._store.get_receipt_by_id(invoice.receipt_id)
            receipt_found = raw_receipt is not None
            if not receipt_found:
                notes.append(
                    f"Delivery receipt '{invoice.receipt_id}' not found."
                )
        else:
            notes.append("No receipt_id on invoice — cannot verify delivery.")

        # ----------------------------------------------------------------
        # 3. Currency check (invoice vs PO)
        # ----------------------------------------------------------------
        currency_match = True
        if raw_po is not None:
            po_currency = (raw_po.get("currency") or "").upper()
            if po_currency and po_currency != invoice.currency:
                currency_match = False
                notes.append(
                    f"Currency mismatch: invoice={invoice.currency}, PO={po_currency}."
                )

        # ----------------------------------------------------------------
        # 4. Build line-level lookup maps from PO and receipt
        # ----------------------------------------------------------------
        po_lines_by_no: dict[int, dict[str, Any]] = {}
        if raw_po is not None:
            for line in raw_po.get("line_items", []):
                po_lines_by_no[line["line_no"]] = line

        receipt_lines_by_no: dict[int, dict[str, Any]] = {}
        if raw_receipt is not None:
            for line in raw_receipt.get("line_items", []):
                receipt_lines_by_no[line["line_no"]] = line

        # ----------------------------------------------------------------
        # 5. Match each invoice line
        # ----------------------------------------------------------------
        line_discrepancies: list[LineDiscrepancy] = []
        for inv_line in invoice.line_items:
            disc = self._match_line(
                inv_line=inv_line,
                po_line=po_lines_by_no.get(inv_line.line_no),
                receipt_line=receipt_lines_by_no.get(inv_line.line_no),
                notes=notes,
            )
            line_discrepancies.append(disc)

        # ----------------------------------------------------------------
        # 6. Determine overall status
        # ----------------------------------------------------------------
        status = self._derive_status(
            po_found=po_found,
            receipt_found=receipt_found,
            currency_match=currency_match,
            line_discrepancies=line_discrepancies,
        )

        return MatchResult(
            invoice_id=invoice.invoice_id,
            po_id=invoice.po_id,
            receipt_id=invoice.receipt_id,
            status=status,
            po_found=po_found,
            receipt_found=receipt_found,
            currency_match=currency_match,
            line_discrepancies=tuple(line_discrepancies),
            notes=tuple(notes),
        )

    def match_all(self, invoices: list[Invoice]) -> list[MatchResult]:
        """Match a batch of invoices and return a list of MatchResult objects."""
        return [self.match(inv) for inv in invoices]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _match_line(
        self,
        inv_line: LineItem,
        po_line: Optional[dict[str, Any]],
        receipt_line: Optional[dict[str, Any]],
        notes: list[str],
    ) -> LineDiscrepancy:
        """Compute discrepancy details for a single invoice line."""

        # ---- PO price comparison ----------------------------------------
        po_unit_price: Optional[Decimal] = None
        price_delta: Optional[Decimal] = None
        price_variance_pct: Optional[Decimal] = None
        has_price_discrepancy = False

        if po_line is not None:
            po_unit_price = Decimal(str(po_line.get("unit_price", 0)))
            price_delta = inv_line.unit_price - po_unit_price
            if po_unit_price != Decimal("0"):
                price_variance_pct = (
                    abs(price_delta) / po_unit_price * Decimal("100")
                ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            else:
                price_variance_pct = Decimal("0") if price_delta == Decimal("0") else None

            if price_variance_pct is not None and price_variance_pct > self._price_tol:
                has_price_discrepancy = True
                notes.append(
                    f"Line {inv_line.line_no}: price variance "
                    f"{price_variance_pct:.4f}% exceeds tolerance "
                    f"{self._price_tol}% "
                    f"(invoice={inv_line.unit_price}, PO={po_unit_price})."
                )
        else:
            notes.append(
                f"Line {inv_line.line_no}: no matching PO line found."
            )

        # ---- PO quantity ------------------------------------------------
        po_quantity: Optional[Decimal] = None
        if po_line is not None:
            po_quantity = Decimal(str(po_line.get("quantity", 0)))

        # ---- Receipt quantity comparison --------------------------------
        received_quantity: Optional[Decimal] = None
        quantity_delta: Optional[Decimal] = None
        quantity_variance_pct: Optional[Decimal] = None
        has_quantity_discrepancy = False

        if receipt_line is not None:
            received_quantity = Decimal(
                str(receipt_line.get("quantity_received", 0))
            )
            quantity_delta = inv_line.quantity - received_quantity

            ref_qty = po_quantity if po_quantity is not None else received_quantity
            if ref_qty and ref_qty != Decimal("0"):
                quantity_variance_pct = (
                    abs(quantity_delta) / ref_qty * Decimal("100")
                ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            else:
                quantity_variance_pct = (
                    Decimal("0") if quantity_delta == Decimal("0") else None
                )

            if quantity_variance_pct is not None and quantity_variance_pct > self._qty_tol:
                has_quantity_discrepancy = True
                notes.append(
                    f"Line {inv_line.line_no}: quantity shortfall/excess — "
                    f"invoiced={inv_line.quantity}, received={received_quantity} "
                    f"(variance {quantity_variance_pct:.4f}%)."
                )
        else:
            if receipt_line is None and po_line is not None:
                notes.append(
                    f"Line {inv_line.line_no}: no delivery receipt line found."
                )

        return LineDiscrepancy(
            line_no=inv_line.line_no,
            description=inv_line.description,
            invoice_quantity=inv_line.quantity,
            po_quantity=po_quantity,
            received_quantity=received_quantity,
            quantity_delta=quantity_delta,
            quantity_variance_pct=quantity_variance_pct,
            invoice_unit_price=inv_line.unit_price,
            po_unit_price=po_unit_price,
            price_delta=price_delta,
            price_variance_pct=price_variance_pct,
            has_quantity_discrepancy=has_quantity_discrepancy,
            has_price_discrepancy=has_price_discrepancy,
        )

    @staticmethod
    def _derive_status(
        po_found: bool,
        receipt_found: bool,
        currency_match: bool,
        line_discrepancies: list[LineDiscrepancy],
    ) -> MatchStatus:
        """Determine the overall MatchStatus from component results."""
        # Unmatched: critical documents missing or currency wrong
        if not po_found or not receipt_found or not currency_match:
            return MatchStatus.UNMATCHED

        any_discrepancy = any(
            d.has_price_discrepancy or d.has_quantity_discrepancy
            for d in line_discrepancies
        )
        if any_discrepancy:
            return MatchStatus.PARTIAL

        return MatchStatus.MATCHED
