# TailHedge — Implementation Plan

## Planning principles

- Build vertical slices that remain runnable.
- Use synthetic/golden data and `FakeBroker` before paid data or IBKR.
- Do not build live-money capability in MVP.
- Implement deterministic correctness and provenance before Autoresearch sophistication.
- Safety-critical broker code comes only after research architecture and shadow operation are stable.

## Phase 0 — Foundation

### Goal
Create a reproducible repository, typed configuration, database, test harness, and minimal web/worker process with no financial behaviour yet.

### Tasks
- Repository/package structure.
- Python tooling, lint/type/test commands.
- PostgreSQL + Alembic.
- Typed settings/environment separation.
- Structured logging/correlation IDs.
- Owner authentication/session/CSRF skeleton.
- Durable jobs table/worker skeleton.
- Minimal health/ready endpoints and application shell.

### Dependencies
None.

### Expected outputs
Runnable web app, worker, scheduler skeleton, DB migrations, CI baseline.

### Relevant requirements
FR-022, FR-023; security prerequisites for all.

### Definition of done
- `dev` stack starts from documented commands.
- One migration creates initial core tables.
- Owner can log in to an empty application shell.
- Worker can claim/complete a dummy durable job.
- Automated baseline tests pass.

---

## Phase 1 — Core research vertical slice

### Goal
Prove the core product loop without external data or AI: synthetic option data -> static strategy -> deterministic combined-portfolio backtest -> evidence displayed.

### Tasks
- Canonical option/underlying schemas.
- Golden synthetic fixtures.
- Portfolio proxy/exposure model.
- Backtest ledger/accounting.
- Conservative execution-cost model.
- Option expiry/settlement/roll mechanics.
- No-hedge and static long-put baseline.
- Core metrics (CAGR, max drawdown, premium spend, drawdown reduction).
- Minimal Research screen showing run result.

### Dependencies
Phase 0.

### Relevant requirements
FR-001, FR-004, FR-005, FR-019, FR-020.

### Definition of done
- GF-001/GF-002/GF-003 expected cash ledgers pass.
- Same run is byte/metric reproducible from same inputs.
- UI displays baseline and hedged metrics from a committed synthetic fixture.
- No external broker/data dependency.

---

## Phase 2 — Real historical-data ingestion and controlled evaluation

### Goal
Make historical options research credible and vendor-independent.

### Tasks
- CSV/Parquet importer interface.
- At least one generic/canonical importer; vendor adapter only if sample/licence available.
- Immutable manifests/hashes.
- Data health validation/reporting.
- DuckDB query layer over Parquet.
- Time-blocked split service with purge/embargo.
- Strategy SDK/context/target-plan schema.
- Evaluator container image and sandbox runner.
- Immutable campaign configuration/scoring profile.
- Baseline comparison report.

### Dependencies
Phase 1.

### Relevant requirements
FR-002–FR-007, FR-010.

### Definition of done
- Licensed/sample dataset can be normalised without modifying raw files.
- Fatal bad data blocks campaigns.
- Final-holdout partitions are not mounted into ordinary evaluator runs.
- Static strategy runs in the same isolated strategy interface later used by Autoresearch.

---

## Phase 3 — Autoresearch loop and experiment ledger

### Goal
Implement the autonomous iterative research mechanism while preserving evaluator immutability and complete trial history.

### Tasks
- `AgentProvider` interface.
- Deterministic `ManualAgentProvider` test implementation.
- `LocalCommandAgentProvider` integration.
- Candidate response/source validation.
- Campaign orchestrator loop.
- Parent selection/keep-or-revert policy.
- Persist every experiment, including failures/timeouts.
- Campaign progress/status UI.
- Experiment detail/source diff UI.
- Resource/iteration stop conditions.

### Dependencies
Phase 2.

### Relevant requirements
FR-006–FR-010, FR-020, FR-022.

### Definition of done
- A local command agent can perform a 20+ iteration synthetic campaign.
- Only strategy candidate source changes between iterations.
- Protected hashes are verified each run.
- Failed experiments are visible and counted.
- Restart resumes from last persisted experiment without duplication.

---

## Phase 4 — Robustness, red team, and release evidence

### Goal
Make “promising historically” materially harder to achieve through overfit.

### Tasks
- Parameter-neighbour perturbation.
- Worse-fill/premium-cost stress.
- One-decision delay.
- Leave-one-regime/crisis-out.
- Dominant-event removal.
- Basis/beta and FX perturbation.
- Synthetic crash path generator.
- Canonical robustness gate/report.
- Strategy release freeze/provenance.
- Final-holdout one-way workflow.
- Candidate/release evidence UI.

### Dependencies
Phase 3.

### Relevant requirements
FR-010–FR-012, FR-019, FR-020.

### Definition of done
- Canonical suite reports every required test independently.
- Gate cannot pass if a mandatory robustness test is missing/error.
- Frozen release is content-addressed/immutable.
- Final holdout is never supplied to agent feedback and is marked consumed after viewing.

---

## Phase 5 — Shadow operations with IBKR reads

### Goal
Apply a frozen strategy to the user’s actual account/quotes once per day without order authority.

### Tasks
- `BrokerAdapter` and `FakeBroker` complete read interface.
- IBKR TWS API adapter: status, account, positions, open orders, recent executions, contract lookup, option chain, quotes.
- Broker snapshot persistence.
- Portfolio holding mapping/beta UI.
- Daily scheduler using New York timezone.
- Daily-run orchestration.
- Current contract eligibility/selection.
- Target-plan -> order-intent translation (not submission).
- Full deterministic risk gate.
- Shadow daily-run UI and alerts.
- Broker health/re-authentication status.

### Dependencies
Phase 4.

### Relevant requirements
FR-001, FR-013–FR-016, FR-018, FR-020–FR-023.

### Definition of done
- Daily run reconciles FakeBroker and produces explainable `NO_ACTION`/intents.
- IBKR paper account can be read without orders.
- DST/schedule tests pass.
- Any incomplete broker/quote state fails closed.
- At least several days of shadow operation can be recorded without manual database changes.

---

## Phase 6 — IBKR paper execution

### Goal
Safely submit only validated long-put paper orders and recover correctly from failures.

### Tasks
- Order-intent idempotency.
- Paper environment/account verification.
- Limit-order executor/repricing policy.
- Broker callback/status persistence.
- Partial-fill handling.
- Post-submit reconciliation/restart recovery.
- Kill switch and cancellation path.
- Rolling premium accounting from actual intents/fills.
- Paper order UI.
- Fault-injection suite.

### Dependencies
Phase 5.

### Relevant requirements
FR-016–FR-018, FR-021–FR-023.

### Definition of done
- No market-order code path exists.
- FakeBroker post-submit crash test proves no duplicate.
- Sell-to-close cannot exceed verified owned quantity.
- Kill switch blocks submissions and cancels eligible open TailHedge orders without liquidating positions.
- Manual IBKR paper smoke test succeeds.

---

## Phase 7 — Hardening and MVP release preparation

### Goal
Make the research+shadow+paper system dependable enough for ongoing personal use.

### Tasks
- Security review and dependency scanning.
- Sandbox escape/control tests.
- Backup/restore procedure and drill.
- Data/licence directory policy.
- Operational runbook for IB Gateway authentication/restarts.
- Performance profiling on representative dataset.
- UI accessibility pass.
- Notification adapter for critical events.
- Documentation consistency/traceability pass.
- Paper-mode soak test.

### Dependencies
Phases 0–6.

### Relevant requirements
All MVP requirements.

### Definition of done
- Minimum suite in `TEST_STRATEGY.md` passes.
- No open severity-1 safety defect.
- Backup restore verified.
- Paper/shadow operation has a documented runbook.
- Live execution remains unavailable.

---

## Phase 8 — Post-MVP controlled live approval (not part of current implementation scope)

### Goal
Only after an explicit future decision, add user-approved real-money orders.

Prerequisites before implementation:
- successful paper/shadow evidence period;
- renewed IBKR/Cboe API/market-hours verification;
- account/legal/tax/wrapper decisions resolved by owner;
- live-specific security/fault review;
- explicit monetary limits.

Relevant requirements: FR-024.

No Phase-8 code should be added during MVP “just in case” beyond clean interfaces already required for paper mode.

---

## Phase 9 — Future autonomous live / intraday monitor

FR-025 and FR-026 only. Requires separate product approval and historical intraday validation. Not part of present backlog definition of done.
