# Invoice Processing Agent with 3-Way Match

Agentic invoice processor with 3-way PO/delivery match, exception flagging, and mock ERP posting via

**Domain:** Agentic AI
**Language:** python
**Demonstrates:** You automate expensive enterprise workflows.

## 7-day build plan

- [ ] Day 1: Scaffold the project structure with pyproject.toml, a mock data layer (invoices, purchase orders, delivery receipts as JSON fixtures), and a DataStore class that loads and queries these fixtures in memory.
- [ ] Day 2: Build an InvoiceParser module that reads raw invoice dicts from the DataStore and normalizes them into a canonical Invoice dataclass with validated fields (vendor, line items, amounts, currency, dates).
- [ ] Day 3: Implement the ThreeWayMatcher engine that joins an Invoice with its matching PO and DeliveryReceipt by document ID, computes quantity and price tolerances, and produces a MatchResult with status (matched, partial, unmatched) and discrepancy details.
- [ ] Day 4: Create an ExceptionHandler that ingests MatchResult objects, classifies exceptions by rule (price variance >2%, quantity shortfall, missing PO, duplicate invoice), and writes structured exception records to an in-memory exception log with severity levels.
- [ ] Day 5: Build a mock MCP (Mock Control Plane) server as a local FastAPI app exposing /post_invoice and /get_status endpoints that simulate ERP acceptance, rejection, and idempotency checks, then integrate an ERPClient that calls these endpoints and requires human-in-the-loop confirmation before posting.
- [ ] Day 6: Wire everything into an InvoiceProcessingAgent orchestrator that pipelines parsing, matching, exception handling, and conditional ERP posting for a batch of invoices, with a CLI entry point (python -m agent run) that processes all fixtures and prints a structured summary report.
- [ ] Day 7: Add a pytest suite covering the parser, matcher, exception handler, and ERP client mock with edge-case fixtures (duplicate invoices, zero-quantity lines, currency mismatches), and add a config.py for tolerance thresholds and environment-variable-based settings with .env.example.

_A comprehensive README with an architecture diagram is generated on Day 7._
