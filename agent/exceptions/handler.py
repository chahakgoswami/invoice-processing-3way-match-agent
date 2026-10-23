"""ExceptionHandler: classifies MatchResult objects and logs structured exceptions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from agent.exceptions.models import (
    ExceptionRecord,
    ExceptionRule,
    ExceptionSeverity,
)
from agent.matching.models import MatchResult, MatchStatus

# Default price-variance threshold for exception classification.
# This mirrors the matcher default but can be overridden per handler instance.
_DEFAULT_PRICE_TOLERANCE_PCT = Decimal("2.0")


class ExceptionHandler:
    """Ingests :class:`~agent.matching.models.MatchResult` objects, applies
    classification rules, and appends :class:`~agent.exceptions.models.ExceptionRecord`
    entries to an in-memory exception log.

    Rules applied (in order):

    1. **duplicate_invoice** – the same ``invoice_id`` has already been processed.
    2. **missing_po** – ``po_found`` is ``False``.
    3. **missing_receipt** – ``receipt_found`` is ``False`` (and PO exists).
    4. **currency_mismatch** – ``currency_match`` is ``False``.
    5. **price_variance** – any line has ``has_price_discrepancy == True``.
    6. **quantity_shortfall** – any line has ``has_quantity_discrepancy == True``.

    Parameters
    ----------
    price_tolerance_pct:
        Price variance percentage above which a PRICE_VARIANCE exception is
        raised.  Defaults to 2 %.  This value is informational only here;
        the actual flag is set by :class:`~agent.matching.matcher.ThreeWayMatcher`.
    """

    def __init__(
        self,
        price_tolerance_pct: Decimal = _DEFAULT_PRICE_TOLERANCE_PCT,
    ) -> None:
        self._price_tol = price_tolerance_pct
        # In-memory exception log: list of ExceptionRecord, append-only.
        self._log: list[ExceptionRecord] = []
        # Track invoice IDs already processed to detect duplicates.
        self._seen_invoice_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle(self, result: MatchResult) -> list[ExceptionRecord]:
        """Classify exceptions for *result* and append them to the log.

        Returns the list of new :class:`ExceptionRecord` objects created for
        this result (may be empty if the invoice is clean).
        """
        new_records: list[ExceptionRecord] = []

        # Rule 1: duplicate invoice
        if result.invoice_id in self._seen_invoice_ids:
            new_records.append(
                self._make_record(
                    invoice_id=result.invoice_id,
                    rule=ExceptionRule.DUPLICATE_INVOICE,
                    severity=ExceptionSeverity.HIGH,
                    description=(
                        f"Invoice '{result.invoice_id}' has already been processed; "
                        "possible duplicate submission."
                    ),
                    detail=None,
                )
            )
        else:
            self._seen_invoice_ids.add(result.invoice_id)

        # Rule 2: missing PO
        if not result.po_found:
            new_records.append(
                self._make_record(
                    invoice_id=result.invoice_id,
                    rule=ExceptionRule.MISSING_PO,
                    severity=ExceptionSeverity.CRITICAL,
                    description=(
                        f"Invoice '{result.invoice_id}' references PO '{result.po_id}' "
                        "which does not exist in the system."
                    ),
                    detail=f"po_id={result.po_id}",
                )
            )

        # Rule 3: missing receipt (only meaningful when PO exists)
        if result.po_found and not result.receipt_found:
            new_records.append(
                self._make_record(
                    invoice_id=result.invoice_id,
                    rule=ExceptionRule.MISSING_RECEIPT,
                    severity=ExceptionSeverity.HIGH,
                    description=(
                        f"Invoice '{result.invoice_id}' has no matching delivery "
                        f"receipt (receipt_id={result.receipt_id!r})."
                    ),
                    detail=f"receipt_id={result.receipt_id}",
                )
            )

        # Rule 4: currency mismatch
        if not result.currency_match:
            new_records.append(
                self._make_record(
                    invoice_id=result.invoice_id,
                    rule=ExceptionRule.CURRENCY_MISMATCH,
                    severity=ExceptionSeverity.CRITICAL,
                    description=(
                        f"Invoice '{result.invoice_id}' currency does not match the "
                        "purchase order currency."
                    ),
                    detail=None,
                )
            )

        # Rules 5 & 6: line-level discrepancies
        for disc in result.line_discrepancies:
            # Price variance
            if disc.has_price_discrepancy:
                pct_str = (
                    f"{disc.price_variance_pct:.4f}%"
                    if disc.price_variance_pct is not None
                    else "unknown"
                )
                new_records.append(
                    self._make_record(
                        invoice_id=result.invoice_id,
                        rule=ExceptionRule.PRICE_VARIANCE,
                        severity=ExceptionSeverity.MEDIUM,
                        description=(
                            f"Invoice '{result.invoice_id}' line {disc.line_no} "
                            f"('{disc.description}'): unit price "
                            f"{disc.invoice_unit_price} vs PO "
                            f"{disc.po_unit_price} — variance {pct_str} exceeds "
                            f"tolerance {self._price_tol}%."
                        ),
                        detail=(
                            f"line_no={disc.line_no}, "
                            f"invoice_price={disc.invoice_unit_price}, "
                            f"po_price={disc.po_unit_price}, "
                            f"variance_pct={pct_str}"
                        ),
                    )
                )

            # Quantity shortfall
            if disc.has_quantity_discrepancy:
                delta_str = (
                    str(disc.quantity_delta)
                    if disc.quantity_delta is not None
                    else "unknown"
                )
                new_records.append(
                    self._make_record(
                        invoice_id=result.invoice_id,
                        rule=ExceptionRule.QUANTITY_SHORTFALL,
                        severity=ExceptionSeverity.MEDIUM,
                        description=(
                            f"Invoice '{result.invoice_id}' line {disc.line_no} "
                            f"('{disc.description}'): invoiced quantity "
                            f"{disc.invoice_quantity} vs received "
                            f"{disc.received_quantity} — delta {delta_str}."
                        ),
                        detail=(
                            f"line_no={disc.line_no}, "
                            f"invoiced={disc.invoice_quantity}, "
                            f"received={disc.received_quantity}, "
                            f"delta={delta_str}"
                        ),
                    )
                )

        # Append all new records to the persistent log
        self._log.extend(new_records)
        return new_records

    def handle_all(self, results: Sequence[MatchResult]) -> list[ExceptionRecord]:
        """Process a batch of MatchResult objects.

        Returns a flat list of all new ExceptionRecord objects created.
        """
        all_records: list[ExceptionRecord] = []
        for result in results:
            all_records.extend(self.handle(result))
        return all_records

    # ------------------------------------------------------------------
    # Log accessors
    # ------------------------------------------------------------------

    @property
    def log(self) -> list[ExceptionRecord]:
        """Return a snapshot of the full exception log (read-only copy)."""
        return list(self._log)

    def get_by_invoice(self, invoice_id: str) -> list[ExceptionRecord]:
        """Return all exception records for a specific invoice ID."""
        return [rec for rec in self._log if rec.invoice_id == invoice_id]

    def get_by_rule(self, rule: ExceptionRule) -> list[ExceptionRecord]:
        """Return all exception records that match the given rule."""
        return [rec for rec in self._log if rec.rule == rule]

    def get_by_severity(self, severity: ExceptionSeverity) -> list[ExceptionRecord]:
        """Return all exception records at the given severity level."""
        return [rec for rec in self._log if rec.severity == severity]

    def clear(self) -> None:
        """Clear the in-memory log and reset the seen-invoices tracker."""
        self._log.clear()
        self._seen_invoice_ids.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_record(
        invoice_id: str,
        rule: ExceptionRule,
        severity: ExceptionSeverity,
        description: str,
        detail: str | None,
    ) -> ExceptionRecord:
        return ExceptionRecord(
            exception_id=str(uuid.uuid4()),
            invoice_id=invoice_id,
            rule=rule,
            severity=severity,
            description=description,
            detail=detail,
            created_at=datetime.utcnow(),
        )
