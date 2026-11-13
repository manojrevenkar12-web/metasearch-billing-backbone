# Decisions

**D1. Measure against a simulated truth, not against the pipeline's own numbers.** A billing pipeline that
checks itself only proves it is consistent. The world in `src/mbb/world/` knows which clicks were billable
and at what price; the pipeline never sees that, and `scripts/evaluate.py` is the only reader. The cost: the
world is mine, so it holds the problems I thought of. The held-out world (D9) is the guard against tuning to it.

**D2. Load a file only when its manifest is in and matches; load a path and a content hash once.** Brands ship
hourly files that can land half-uploaded, late, or twice under another name. Loading what is there "now" is the
classic silent under-bill. The manifest rule costs a delay of one run for a half-uploaded file.

**D3. The partner's clock decides the month.** A click at 22:30 UTC on 30 September is October in Berlin and
September in New York. Months and rate dates are taken in the partner's billing time zone with DST, from the
contract, not from a fixed offset.

**D4. The rate card is bi-temporal.** A rate has a date it applies from and a time it was recorded. Pricing uses
the contract as known at the run, turned into date intervals once (`int_rate_versions`) and joined by range,
instead of ranking every candidate rate per click. Same rows; on DuckDB only 1.3× faster, because its optimizer
handles the ranked version well (`reports/bench.json`). The interval form is kept for readability and for engines
that do not.

**D5. An invoice waits while a blocking check fails, up to a limit.** Missing hours, values outside the schema
contract, unpriced clicks and a fact that does not add up to its lines hold the partner's invoice. After the
10th of the month it goes out anyway, with the open checks written on it, because a late invoice has a cost too.

**D6. Invoices are only added.** A change after issue (late files, a late amendment) is a credit or debit note
with its own document id. Overwriting an issued invoice makes the ledger disagree with what the partner holds.

**D7. Unknown values are held, not dropped.** A brand that starts sending `MOBILE_APP` before it updates its
schema contract would silently lose those clicks if unknown values were filtered. They go to `stg_quarantine`,
hold the affected invoices, and come back when the contract lists them.

**D8. One SQL for DuckDB and Trino.** Models are written once and translated with sqlglot; CI runs every model
on a real Trino and requires the same rows. Anything engine-specific (file reading, typing timestamps) happens
at load time, outside the models.

**D9. Every safeguard can be switched off, and the evaluation does it.** The README's table is the backbone with
one safeguard off at a time, so each one's worth is a measured number, including the ones that turn out to be
worth little on this data. The held-out world (another seed, other incidents) was run once with the settings
frozen; its numbers stay as they first came out.

**D10. The self-service reader proposes, the catalog decides.** "Ask the billing data" turns a question into a
plan (metric, dimensions, filters, period). The catalog accepts only certified metrics and their dimensions,
writes the SQL itself and binds every value. A question no metric answers is refused. The rule-based reader is
what is measured; the Claude reader uses the same plan and the same checks and is optional.

**D11. What this does not solve.** Bots behind residential proxies clicking at human pace look like people in
redirect logs; the rules do not catch them and the backbone bills them. Closing that gap needs signals these
logs do not carry (conversion feedback from partners, device fingerprints), so it is listed, not hidden.
