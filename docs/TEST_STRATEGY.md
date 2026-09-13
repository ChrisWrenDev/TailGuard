# TailHedge — Test Strategy

## 1. Testing goals

The test programme must establish:

1. research results are reproducible and do not leak future/holdout data;
2. portfolio/backtest accounting is correct;
3. the Autoresearch agent cannot modify protected evaluator/risk behaviour;
4. broker actions are deterministic, bounded, idempotent, and reconciled from broker truth;
5. failures lead to no trade rather than unsafe fallback;
6. daily scheduling remains correct across timezones/DST and market closures;
7. the UI accurately exposes evidence, failures, and safety state.

## 2. Test layers

### 2.1 Unit tests
Fast, deterministic, no network/database unless specifically repository-unit tested.

Required modules:
- money/currency arithmetic;
- portfolio benchmark-equivalent exposure;
- hedge-beta mapping;
- option payoff/expiry settlement;
- contract eligibility/ranking;
- discrete sizing/over-coverage logic;
- execution fill model;
- rolling premium budget accounting;
- backtest cash/unit ledger;
- CAGR/max drawdown/tail metrics;
- split purge/embargo logic;
- scoring/gates/complexity penalty;
- target-plan schema validation;
- target-to-order translation;
- risk gate;
- idempotency key generation;
- limit repricing caps;
- scheduler timezone/DST logic;
- kill switch semantics.

### 2.2 Property-based tests
Use Hypothesis for invariants where valuable.

Examples:
- long put payoff is never negative at expiration before premium/cost accounting;
- sell-to-close quantity never exceeds verified owned available quantity;
- increasing buy quantity cannot reduce required premium under identical positive prices;
- risk gate never passes `SELL_TO_CLOSE` above owned quantity;
- if kill switch is engaged, no generated executable intent passes;
- same run inputs always produce same idempotency keys;
- no simulated transaction creates/loses cash except explicit trade/cost/FX/reinvestment flows.

### 2.3 Integration tests
Use PostgreSQL test container and real Parquet/DuckDB fixtures.

Required:
- CSV -> canonical Parquet -> manifest -> validation;
- ORATS-format sample mapping and real-SPX qualification report;
- resumable archive acquisition, raw ZIP hashing, and SPX/SPXW filtering;
- contract settlement metadata and expiry-settlement coverage;
- campaign freeze immutability;
- worker job lease/recovery;
- experiment persistence after evaluator result;
- evaluator container restrictions/timeout;
- final holdout absent from research mount/request;
- strategy release provenance;
- fake broker sync -> daily run -> risk -> shadow result;
- fake broker paper order lifecycle including partial fills/disconnects;
- audit events created for safety actions.

### 2.4 End-to-end tests
Use browser automation plus fake broker/evaluator fixtures.

Critical E2E flows:
1. first-run -> import synthetic dataset -> baseline backtest -> campaign -> experiment visible;
2. nominate candidate -> robustness -> freeze release -> shadow daily run;
3. switch to paper test environment -> valid paper order -> fill -> post-trade reconciliation;
4. kill switch -> pending order cancellation -> new order blocked;
5. broker disconnect after simulated submit -> system enters reconciliation/manual-review instead of duplicate submission;
6. final holdout confirmation -> result visible to owner -> remains absent from subsequent agent request fixture.

## 3. Golden test data

Create small deterministic fixtures committed to repository; no licensed vendor data.

### GF-001 — Simple option payoff
Five daily snapshots, one put, known expiration and premium. Expected cash ledger hand-calculated.

### GF-002 — Roll case
Two expiries; target policy rolls at known DTE. Expected close/buy and spend accounting.

### GF-003 — Crash + monetisation
Underlying drops sharply; put becomes ITM; daily policy sells configured fraction and reinvests cash. Expected combined-portfolio units/value known.

### GF-004 — Wide/stale quote
Candidate contract otherwise ideal but quote violates spread/freshness. Expected no eligible order.

### GF-005 — Basis-risk portfolio
Two holdings with different SPX beta. Expected benchmark-equivalent exposure exact.

### GF-006 — GBP/USD
Known FX path to verify premium/payout conversion.

### GF-007 — Split leakage trap
Construct data where future feature would make performance unrealistically perfect. Evaluator must prevent strategy access to future rows.

### GF-008 — Duplicate broker order recovery
Fake broker receives order but client process “crashes” before acknowledgement. Reconciliation must discover existing order/fill and not resubmit.

## 4. Requirement-mapped critical tests

| Test ID | Requirement(s) | Test |
|---|---|---|
| T-001 | FR-001 | Portfolio exposure and unmapped-holding warnings are correct. |
| T-002 | FR-002, FR-003 | Canonical importer produces deterministic manifest and blocks crossed/invalid required data. |
| T-003 | FR-004 | Golden payoff ledger matches hand-calculated result. |
| T-004 | FR-004, FR-019 | Crash monetisation/reinvestment accounting conserves cash and units. |
| T-005 | FR-004, FR-010 | Strategy receives no future/holdout rows. |
| T-006 | FR-005 | No-hedge and fixed-put baselines run through same accounting/cost engine. |
| T-007 | FR-006, FR-008 | Candidate can only emit schema-valid target plan; protected files remain unchanged. |
| T-008 | FR-007 | Started campaign immutable fields reject update; clone path works. |
| T-009 | FR-009 | Failed/timeout experiment remains in ledger and counts toward attempt history. |
| T-010 | FR-010 | Holdout path/metrics absent from agent request and sandbox during campaign. |
| T-011 | FR-011 | Robustness profile runs all mandatory perturbations and cannot report pass if a required test errors. |
| T-012 | FR-012 | Release hash/provenance immutable after creation. |
| T-013 | FR-013 | Scheduler creates one run at correct New York-local decision time across DST transitions. |
| T-014 | FR-014 | Incomplete broker snapshot blocks executable run. |
| T-015 | FR-015 | Wrong multiplier/stale/wide quote rejects contract. |
| T-016 | FR-016 | Every hard risk rule has pass/fail unit coverage; unknown state fails. |
| T-017 | FR-016 | Sell-to-open/naked quantity is impossible even with malicious target plan. |
| T-018 | FR-017 | Limit executor never emits market order or exceeds configured max price. |
| T-019 | FR-018 | Ambiguous post-submit disconnect reconciles before any retry. |
| T-020 | FR-018 | Duplicate scheduler/API invocation yields one run/order intent. |
| T-021 | FR-020 | Dashboard shows latest decision, budget, evidence, and critical warnings. |
| T-022 | FR-021 | Kill switch blocks all new submissions and does not auto-liquidate positions. |
| T-023 | FR-022 | Required operational events persist and critical notifications deduplicate. |
| T-024 | FR-023 | Secrets never appear in config serialization/log snapshot tests. |
| T-025 | FR-002, FR-003, FR-004, FR-010 | Real-dataset qualification acquires and hashes raw daily objects, filters SPX/SPXW with source provenance, and produces complete fatal-check, settlement, no-look-ahead, and deterministic static-backtest evidence. |

## 5. Research-engine correctness tests

### 5.1 No-look-ahead
Instrument the strategy context so every row/feature has an `as_of` timestamp. Test harness asserts `feature.as_of <= decision_ts`.

Any precomputed feature must record its maximum source timestamp. Feature pipeline fails if it crosses decision time.

### 5.2 Real-dataset qualification

The qualification fixture may exercise the ORATS paired call/put CSV shape, but
licensed external data must not be committed to CI. The manual/controlled
qualification run must additionally prove:

- the selected source actually contains the intended SPX/SPXW roots;
- side-specific prices, sizes, volume, open interest, and Greeks are mapped correctly;
- observed snapshot timestamps and timezone semantics are recorded;
- contract multiplier, exercise, settlement, and expiration semantics are verified;
- official expiry settlement coverage exists for all expiry trades used;
- missing/untradeable rows are reported rather than silently repaired;
- the qualification and static backtest can be repeated from identical hashes.

The supplied samples under `data/` are local and ignored. The generic
`ORATS_SMV_Strikes_20240103.csv` is not evidence of SPX coverage; the
`SMVquotesSPX20150717snippet.csv` file provides a one-date SPX format fixture
but is not sufficient historical coverage for a qualified backtest.

### 5.3 Split leakage
For each fold:
- positions opened in train may not leak future realized outcome into validation selection;
- purge horizon removes overlapping holding/lookback dependencies per campaign config;
- final holdout is physically excluded from campaign evaluator mounts.

### 5.4 Fill model
Test bid/ask fractions exactly and mandatory stress variants. A zero/crossed/missing quote follows explicit data-quality/tradability rule, never silent midpoint substitution.

### 5.5 Metrics
Compare CAGR and max drawdown against independent hand/third-party calculations on tiny fixtures. Use explicit annualisation convention and document it in code/tests.

### 5.6 Multiple research attempts
Ensure ledger includes every attempted candidate and summary trial count cannot be filtered to winners for canonical evidence report.

## 6. Strategy sandbox tests

Automated checks in CI where container runtime is available:
- network request fails;
- attempt to read broker/env secret path fails;
- attempt to write evaluator/data mount fails;
- infinite loop times out;
- fork bomb/process flood blocked by PID/resource limit;
- excessive memory allocation terminates candidate safely;
- candidate cannot access final holdout mount;
- output larger than configured size rejected.

CI environments without OCI support must still run contract/unit tests; release pipeline requires sandbox integration suite.

## 7. Broker integration tests

### FakeBroker (mandatory CI)
Simulate:
- normal read sync;
- auth failure;
- position mismatch;
- stale quotes;
- market closed;
- order ack;
- rejection;
- partial fill;
- fill before ack;
- disconnect before/after submit;
- duplicate client ref;
- cancellation failure;
- delayed execution report.

### IBKR paper smoke suite (manual/scheduled, not required on every PR)
- connect to configured paper account;
- read positions/account summary;
- resolve XSP contract details;
- obtain quote with entitlement;
- place/cancel tiny permitted paper limit order where operationally appropriate;
- verify callbacks/reconciliation.

Never run automated CI against a live account.

## 8. Security tests

- auth/session/CSRF tests;
- login rate-limit/backoff;
- path traversal and symlink escape on imports;
- malicious HTML in rationale rendered escaped;
- secret redaction snapshot tests;
- API rejects `LIVE_*` modes in MVP;
- API has no arbitrary broker-order endpoint;
- account/environment mismatch blocks order;
- risk config absolute-bound validation;
- audit entries for all safety-setting mutations.

## 9. Failure-mode / fault-injection tests

At minimum:
- PostgreSQL unavailable before/after broker submit;
- worker killed mid-experiment;
- worker killed after order submit;
- IBKR disconnect/reconnect;
- duplicate scheduler firing;
- corrupted Parquet partition;
- disk full during experiment result write;
- evaluator image digest mismatch;
- agent provider returns malformed source/JSON;
- strategy times out or throws exception;
- notification provider fails.

Safety expectation: no scenario may result in silent duplicate broker submission.

## 10. UI/accessibility tests

Automated Playwright for critical journeys plus static accessibility checks:
- keyboard navigation for primary forms/dialogs;
- visible focus;
- labels/error association;
- kill-switch confirmation;
- final-holdout irreversible-evidence confirmation;
- risk-control old/new confirmation;
- text alternatives for key chart metrics.

## 11. Performance tests

Use a representative synthetic/non-licensed dataset approximating 15–20 years of daily SPX option snapshots.

Track:
- import throughput;
- baseline backtest duration;
- DuckDB query memory;
- experiment startup overhead;
- dashboard query p95;
- daily target-plan/risk computation;
- broker request pacing.

Performance regression threshold may be set after first baseline implementation; no premature micro-optimisation.

## 12. AI/research evaluations

The “AI” component is evaluated on process compliance as much as strategy quality.

Checks:
- agent request contains only allowed fields;
- no holdout values;
- no secrets;
- candidate source is sole mutable research artifact;
- malformed/disallowed candidate becomes failed experiment rather than changing evaluator;
- campaign resource/iteration limit is enforced;
- agent rationale is stored but never trusted as evidence.

Strategy quality is judged only by immutable evaluator metrics/robustness, not by LLM self-assessment.

## 13. Minimum automated suite before a task/feature is complete

Every implementation task must pass:
1. formatter/linter/type checks selected by repository;
2. all unit tests in touched domain;
3. relevant integration tests;
4. migrations up/down or forward compatibility test when schema changes;
5. no-secret scan;
6. requirement-mapped test(s) specified in `TASKS.md`.

Before MVP release/paper operation, additionally require:
- full unit/integration suite;
- critical Playwright E2E suite;
- evaluator sandbox security suite;
- all T-001 through T-025 applicable to MVP;
- FakeBroker fault-injection suite;
- manual IBKR paper smoke test;
- restore/recovery drill from a test backup;
- no open severity-1 safety defect.

## 14. Definition of a passing safety-critical feature

For risk gate, reconciliation, order executor, kill switch, or strategy sandbox, “works on happy path” is insufficient. Feature is complete only when:
- happy path passes;
- defined failure modes pass;
- restart/idempotency behaviour passes;
- audit evidence is correct;
- an explicit negative test proves the prohibited action cannot occur.
