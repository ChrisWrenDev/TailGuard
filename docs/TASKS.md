# TailHedge — Implementation Backlog

Tasks are ordered for autonomous implementation. Unless marked post-MVP, each task is part of the current implementation programme.

## Foundation

### TASK-001 — Bootstrap repository and quality toolchain
**Status:** completed  
**Description:** Create Python package layout, `pyproject.toml`, formatter/linter/type checker, pytest, CI skeleton, `.gitignore`, and documented developer commands.  
**Requirements:** FR-023.  
**Dependencies:** none.  
**Acceptance criteria:** package imports; test/lint/type commands run; licensed `data/` and secrets ignored.  
**Tests:** smoke import; CI command smoke.  
**Order:** 1.

### TASK-002 — Typed configuration and environment separation
**Status:** completed  
**Description:** Implement Pydantic settings for dev/test/paper; explicitly reject live mode in MVP; add `.env.example` without secrets.  
**Requirements:** FR-021, FR-023.  
**Dependencies:** TASK-001.  
**Acceptance criteria:** invalid mode/settings fail startup clearly; secrets excluded from serialization.  
**Tests:** T-024 subset; config validation.  
**Order:** 2.

### TASK-003 — PostgreSQL persistence and migrations
**Status:** completed  
**Description:** Add SQLAlchemy/Alembic and initial operational schema foundations (user, jobs, audit, portfolio shell).  
**Requirements:** FR-001, FR-009, FR-022.  
**Dependencies:** TASK-001, TASK-002.  
**Acceptance criteria:** fresh DB migrates; schema version tracked; migration tests pass.  
**Tests:** migration integration test.  
**Order:** 3.

### TASK-004 — Owner authentication, sessions, CSRF
**Status:** completed  
**Description:** Implement single-owner login/logout, Argon2id password hashing, secure session, CSRF protection.  
**Requirements:** security requirements; FR-023.  
**Dependencies:** TASK-003.  
**Acceptance criteria:** unauthenticated protected routes rejected; state mutation requires CSRF; session cookie flags correct by environment.  
**Tests:** auth/CSRF/security integration tests.  
**Order:** 4.

### TASK-005 — Durable job queue and worker skeleton
**Status:** completed  
**Description:** Implement Postgres job/job-attempt model, lease/heartbeat/retry mechanics, worker CLI, dummy job.  
**Requirements:** FR-008, FR-013, FR-022.  
**Dependencies:** TASK-003.  
**Acceptance criteria:** one worker claims job once; expired lease recoverable; progress persisted.  
**Tests:** concurrent claim/recovery integration tests.  
**Order:** 5.

### TASK-006 — Web application shell and status UI
**Status:** completed  
**Description:** FastAPI/Jinja/HTMX shell, navigation, `/healthz`, `/readyz`, global mode/kill/broker placeholder status.  
**Requirements:** FR-020.  
**Dependencies:** TASK-004.  
**Acceptance criteria:** authenticated owner can navigate empty-state pages; accessibility baseline.  
**Tests:** Playwright login/navigation smoke.  
**Order:** 6.

## Research vertical slice

### TASK-007 — Canonical market-data schemas and manifests
**Status:** completed  
**Description:** Define canonical option/underlying schemas, schema versioning, dataset manifest hashing.  
**Requirements:** FR-002, FR-003.  
**Dependencies:** TASK-001.  
**Acceptance criteria:** schema validates required fields; deterministic manifest hash.  
**Tests:** T-002 schema/manifest unit tests.  
**Order:** 7.

### TASK-008 — Golden synthetic research fixtures
**Status:** completed  
**Description:** Create non-licensed fixtures GF-001 through GF-007 sufficient for deterministic backtest/security tests.  
**Requirements:** FR-004, FR-019.  
**Dependencies:** TASK-007.  
**Acceptance criteria:** fixtures documented with hand-calculated expected outputs.  
**Tests:** fixture validation tests.  
**Order:** 8.

### TASK-009 — Portfolio proxy and hedge exposure model
**Status:** completed  
**Description:** Implement holding definitions, benchmark mapping, beta exposure, base-currency calculation interfaces.  
**Requirements:** FR-001.  
**Dependencies:** TASK-003.  
**Acceptance criteria:** mapped exposure calculation and unmapped warnings match spec.  
**Tests:** T-001, GF-005.  
**Order:** 9.

### TASK-010 — Backtest accounting ledger
**Status:** completed  
**Description:** Implement core portfolio units/cash, long-put positions, expiry settlement, premium/cost flows, explicit currencies.  
**Requirements:** FR-004.  
**Dependencies:** TASK-008, TASK-009.  
**Acceptance criteria:** GF-001 ledger exactly reconciles; no unexplained cash creation/loss.  
**Tests:** T-003 + property-based cash invariants.  
**Order:** 10.

### TASK-011 — Historical execution-cost/fill model
**Status:** completed  
**Description:** Bid/ask-based base and stress fill models; quote tradability rules; commissions hook.  
**Requirements:** FR-004, FR-011.  
**Dependencies:** TASK-010.  
**Acceptance criteria:** configured spread fractions applied exactly; invalid quotes never silently midpoint-filled.  
**Tests:** unit fill cases; GF-004.  
**Order:** 11.

### TASK-012 — Hedge roll, monetisation, and reinvestment mechanics
**Status:** completed  
**Description:** Support daily strategy-directed sell-to-close, roll, cash release, and core reinvestment without intraday inference.  
**Requirements:** FR-004, FR-019.  
**Dependencies:** TASK-010, TASK-011.  
**Acceptance criteria:** GF-002/GF-003 reconcile.  
**Tests:** T-004.  
**Order:** 12.

### TASK-013 — Metrics and immutable baselines
**Status:** completed  
**Description:** CAGR, max drawdown, premium spend, drawdown reduction, tail-efficiency primitives; no-hedge, lower-equity/cash, fixed-put baselines.  
**Requirements:** FR-005, FR-020.  
**Dependencies:** TASK-010–TASK-012.  
**Acceptance criteria:** baselines use same engine/cost model; metric conventions documented.  
**Tests:** T-006; hand-calculated metrics.  
**Order:** 13.

### TASK-014 — Minimal research result UI
**Status:** completed  
**Description:** Display a synthetic baseline/backtest result and numerical evidence tables.  
**Requirements:** FR-020.  
**Dependencies:** TASK-006, TASK-013.  
**Acceptance criteria:** owner can run/view synthetic backtest; key metrics accessible without chart hover.  
**Tests:** UI E2E vertical-slice test.  
**Order:** 14.

## Data ingestion and controlled evaluator

### TASK-015 — CSV/Parquet import pipeline
**Status:** completed  
**Description:** Immutable raw file hashing, canonical normalization, Parquet partitioning, dataset DB metadata.  
**Requirements:** FR-002.  
**Dependencies:** TASK-005, TASK-007.  
**Acceptance criteria:** import creates immutable manifest and normalized dataset; duplicate manifest handled deterministically.  
**Tests:** T-002 integration.  
**Order:** 15.

### TASK-016 — Dataset validation and health UI
**Status:** completed  
**Description:** Required validation checks/reporting and Data screens.  
**Requirements:** FR-003.  
**Dependencies:** TASK-015.  
**Acceptance criteria:** fatal datasets cannot start campaigns; warnings quantified.  
**Tests:** T-002 invalid cases; Playwright data-health state.  
**Order:** 16.

### TASK-017 — DuckDB research repository
**Status:** completed  
**Description:** Query canonical Parquet by date/instrument without loading into Postgres.  
**Requirements:** FR-002, FR-004.  
**Dependencies:** TASK-015.  
**Acceptance criteria:** date/contract queries deterministic and partition-pruned where practical.  
**Tests:** integration query fixtures.  
**Order:** 17.

### TASK-018 — Time-blocked splits with purge/embargo
**Status:** completed  
**Description:** Implement train/validation/final-holdout partition object and physical allowed-range materialisation/mount lists.  
**Requirements:** FR-004, FR-010.  
**Dependencies:** TASK-017.  
**Acceptance criteria:** no overlap; purge horizon enforced; holdout excluded from ordinary evaluator input.  
**Tests:** T-005, GF-007.  
**Order:** 18.

### TASK-019 — Strategy SDK and target-plan contract
**Status:** completed  
**Description:** Versioned `StrategyContext`/`TargetHedgePlan`, allowed feature surface, schema validation.  
**Requirements:** FR-006.  
**Dependencies:** TASK-010, TASK-018.  
**Acceptance criteria:** strategy has no broker methods; prohibited output rejected.  
**Tests:** T-007 contract tests.  
**Order:** 19.

### TASK-020 — Evaluator OCI sandbox
**Status:** completed  
**Description:** Build evaluator image/runner with no network, read-only mounts, dropped capabilities and resource limits.  
**Requirements:** FR-006, FR-008, FR-010.  
**Dependencies:** TASK-019.  
**Acceptance criteria:** malicious fixture cannot access network/secrets/holdout/write protected mounts; timeout works.  
**Tests:** sandbox security suite; T-007/T-010.  
**Order:** 20.

### TASK-021 — Campaign model, frozen config, scoring profile
**Status:** completed  
**Description:** Campaign CRUD/start with immutable hashed evaluator/split/cost/score config and default score from architecture spec.  
**Requirements:** FR-007.  
**Dependencies:** TASK-003, TASK-018, TASK-020.  
**Acceptance criteria:** started campaign immutable; config change requires clone.  
**Tests:** T-008.  
**Order:** 21.

## Real dataset qualification

### TASK-022 — ORATS archive acquisition and provenance
**Status:** pending  
**Description:** Acquire the ORATS Near End-of-day daily ZIP archive through a resumable, one-time S3 workflow and establish immutable raw-data provenance.  
**Requirements:** FR-002, FR-003, FR-023.  
**Dependencies:** TASK-005, TASK-007, TASK-015.  
**Acceptance criteria:** expected S3 object keys are captured before download; available disk and access-window preflight passes; completed objects are not unnecessarily redownloaded; raw daily ZIPs are retained and SHA-256 hashed; acquisition status and source metadata are persisted; credentials never enter the repository, database, logs, or job payloads; no licensed data is committed.  
**Tests:** T-002 provenance subset; acquisition resume/hash tests; manual source/licence checklist.  
**Order:** 22.

### TASK-023 — ORATS SPX/SPXW filtering and canonical import
**Status:** pending  
**Description:** Stream acquired ORATS daily ZIPs, filter to SPX/SPXW before expansion, map paired call/put fields, and write canonical option Parquet with source provenance.  
**Requirements:** FR-002, FR-003.  
**Dependencies:** TASK-022.  
**Acceptance criteria:** non-SPX/SPXW rows are excluded deterministically; paired calls and puts become separate canonical rows without cross-wiring; `spot_px` is used as the SPX cash underlying price and `stkPx` is retained only as an expiry-specific forward reference; source dates and embedded filename dates are checked; canonical partitions link to raw ZIP hashes; invalid rows are reported or quarantined rather than silently repaired.  
**Tests:** T-002 importer/validation; ORATS mapping fixture tests; negative non-SPX and mismatched-date tests.  
**Order:** 23.

### TASK-024 — Real-data qualification gate and static backtest
**Status:** pending  
**Description:** Verify SPX/SPXW contract semantics, settlement coverage, timestamp policy, archive completeness, and deterministic static backtest readiness for the filtered dataset.  
**Requirements:** FR-002, FR-003, FR-004, FR-010.  
**Dependencies:** TASK-018–TASK-023.  
**Acceptance criteria:** qualification status/report/version are persisted; a non-passing external dataset cannot create a real-data campaign; fatal validation checks pass for the selected interval; coverage, quote quality, timestamps, contract identity, settlement, and missing/untradeable rows are reported; static baselines and strategy evaluation pass accounting/no-look-ahead/holdout checks; identical inputs produce identical outputs; closing prices are not inferred from Near End-of-day data.  
**Tests:** T-005, T-006, T-025; qualification integration and deterministic static-backtest tests; manual representative-date checklist.  
**Order:** 24.

## Autoresearch and robustness

### TASK-025 — AgentProvider interface and test providers
**Status:** pending  
**Description:** Add `ManualAgentProvider` and vendor-neutral `LocalCommandAgentProvider`; redact request content.  
**Requirements:** FR-008, FR-023.  
**Dependencies:** TASK-021, TASK-024.  
**Acceptance criteria:** malformed agent response fails safely; no secrets/holdout in request.  
**Tests:** T-007, T-010, T-024 relevant.  
**Order:** 25.

### TASK-026 — Autoresearch campaign orchestrator
**Status:** pending  
**Description:** Iteration loop, parent candidate selection, keep/reject, stop limits, checkpoints.  
**Requirements:** FR-008.  
**Dependencies:** TASK-025.  
**Acceptance criteria:** 20+ deterministic test iterations resume after worker restart.  
**Tests:** campaign integration/recovery.  
**Order:** 26.

### TASK-027 — Complete experiment ledger and campaign UI
**Status:** pending  
**Description:** Persist every attempt/source/hash/metrics/error; Campaign/Experiment pages, filters/sorts.  
**Requirements:** FR-009, FR-020.  
**Dependencies:** TASK-026.  
**Acceptance criteria:** failed trials visible/countable; no delete-winners-only path.  
**Tests:** T-009; UI filter tests.  
**Order:** 27.

### TASK-028 — Canonical robustness suite
**Status:** pending  
**Description:** Implement required perturbations, leave-one-regime-out, basis/FX, cost/delay and dominant-event removal.  
**Requirements:** FR-011.  
**Dependencies:** TASK-026.  
**Acceptance criteria:** required test error prevents pass; full per-test report persisted.  
**Tests:** T-011.  
**Order:** 28.

### TASK-029 — Synthetic crash scenario generator
**Status:** pending  
**Description:** Parameterized path generator varying depth/speed/volatility/skew/recovery without pretending to be observed historical quotes.  
**Requirements:** FR-011.  
**Dependencies:** TASK-010, TASK-028.  
**Acceptance criteria:** scenarios reproducible by seed/config; clearly labelled synthetic.  
**Tests:** deterministic scenario/unit tests.  
**Order:** 29.

### TASK-030 — Strategy release and final-holdout workflow
**Status:** pending  
**Description:** Freeze immutable release, evidence report, permitted modes, one-way holdout consumption.  
**Requirements:** FR-010, FR-012.  
**Dependencies:** TASK-028.  
**Acceptance criteria:** release immutable; holdout result never enters agent feedback; consumed status durable.  
**Tests:** T-010, T-012; E2E holdout confirmation.  
**Order:** 30.

## Shadow/paper operations

### TASK-031 — BrokerAdapter and FakeBroker
**Status:** pending  
**Description:** Define complete broker interface and fault-programmable fake implementation.  
**Requirements:** FR-014, FR-015, FR-017, FR-018.  
**Dependencies:** TASK-003.  
**Acceptance criteria:** fake simulates all documented lifecycle/failure states.  
**Tests:** FakeBroker suite.  
**Order:** 31.

### TASK-032 — IBKR read-only adapter
**Status:** pending  
**Description:** TWS API connection/status, account summary, positions, open orders, recent executions, contracts, option chain, snapshots. No submit method enabled in this task.  
**Requirements:** FR-014, FR-015.  
**Dependencies:** TASK-031.  
**Acceptance criteria:** paper account read smoke works; pacing/reconnect handled; account alias/environment verified.  
**Tests:** T-014/T-015 using fake; manual paper read smoke.  
**Order:** 32.

### TASK-033 — Portfolio configuration and broker mapping UI
**Status:** pending  
**Description:** Holdings table/mapping forms, broker sync, exposure/mapping completeness.  
**Requirements:** FR-001, FR-014, FR-020.  
**Dependencies:** TASK-009, TASK-032.  
**Acceptance criteria:** actual snapshot can be mapped; unmapped exposure warning visible.  
**Tests:** T-001 UI/integration.  
**Order:** 33.

### TASK-034 — Deterministic target-to-intent contract selection
**Status:** pending  
**Description:** Current XSP eligible-chain selection, discrete sizing, actual-vs-target delta, TailHedge position ownership rules.  
**Requirements:** FR-013, FR-015.  
**Dependencies:** TASK-019, TASK-031, TASK-033.  
**Acceptance criteria:** no silent bound relaxation; no eligible contract returns explicit reason.  
**Tests:** contract/sizing unit tests; GF-004.  
**Order:** 34.

### TASK-035 — Versioned deterministic risk gate
**Status:** pending  
**Description:** Implement all FR-016 checks and risk configuration persistence/UI.  
**Requirements:** FR-016, FR-023.  
**Dependencies:** TASK-034.  
**Acceptance criteria:** every check emits observed/threshold/reason; unknown fails; malicious plan cannot create short/naked intent.  
**Tests:** T-016, T-017; property tests.  
**Order:** 35.

### TASK-036 — Daily scheduler and shadow-run orchestration
**Status:** pending  
**Description:** New-York-time scheduler, unique run key, current broker sync, strategy sandbox call, intent/risk persistence, Daily Runs UI.  
**Requirements:** FR-013–FR-016, FR-020.  
**Dependencies:** TASK-030, TASK-032, TASK-035.  
**Acceptance criteria:** one scheduled shadow run/day where eligible; DST tests; early/closed market safely skipped/blocked.  
**Tests:** T-013–T-016; shadow E2E.  
**Order:** 36.

### TASK-037 — Order-intent idempotency and reconciliation engine
**Status:** pending  
**Description:** Persistent intent keys, broker-order refs, recent-execution reconciliation, restart recovery state machine.  
**Requirements:** FR-018.  
**Dependencies:** TASK-031, TASK-036.  
**Acceptance criteria:** GF-008 no duplicate after ambiguous submit.  
**Tests:** T-019, T-020; fault injection.  
**Order:** 37.

### TASK-038 — IBKR paper limit-order executor
**Status:** pending  
**Description:** Enable paper-only order placement, bounded limit repricing, cancel/timeouts, partial fills.  
**Requirements:** FR-017, FR-018.  
**Dependencies:** TASK-032, TASK-037.  
**Acceptance criteria:** paper environment hard checked; no market order; limit cap enforced; partial fills reconciled.  
**Tests:** T-018/T-019; FakeBroker + manual IBKR paper smoke.  
**Order:** 38.

### TASK-039 — Kill switch and broker safety UI
**Status:** pending  
**Description:** Global kill switch, cancellations of TailHedge-owned orders, safe disengage, global status display.  
**Requirements:** FR-021, FR-022.  
**Dependencies:** TASK-037, TASK-038.  
**Acceptance criteria:** engagement blocks new submission immediately; no automatic position liquidation.  
**Tests:** T-022 E2E/integration.  
**Order:** 39.

### TASK-040 — Notifications and audit-log UI
**Status:** pending  
**Description:** Persistent required events, deduplicated critical notifications, audit filters. First notifier may be local UI/log adapter.  
**Requirements:** FR-022.  
**Dependencies:** TASK-005, TASK-036–TASK-039.  
**Acceptance criteria:** required event categories visible; duplicate outage alerts suppressed by policy.  
**Tests:** T-023.  
**Order:** 40.

## Hardening/release

### TASK-041 — Security hardening and secret/redaction review
**Status:** pending  
**Description:** CSP/security headers, import-path hardening, login backoff, sandbox regression, secret scans.  
**Requirements:** FR-023 and security spec.  
**Dependencies:** all prior MVP tasks.  
**Acceptance criteria:** security tests pass; no live mode path; no arbitrary broker-order API.  
**Tests:** security suite/T-024.  
**Order:** 41.

### TASK-042 — Backup/restore and operational runbook
**Status:** pending  
**Description:** PostgreSQL + artifact/data-manifest backup procedure, restore drill, IB Gateway reconnect/re-auth runbook.  
**Requirements:** FR-014, FR-018, FR-022.  
**Dependencies:** TASK-038.  
**Acceptance criteria:** test restore reproduces campaign/release/order provenance; runbook verified.  
**Tests:** manual automated restore check where practical.  
**Order:** 42.

### TASK-043 — Performance/accessibility/release validation
**Status:** pending  
**Description:** Representative backtest profile, dashboard p95 checks, Playwright accessibility pass, complete traceability/test run.  
**Requirements:** all MVP.  
**Dependencies:** TASK-041, TASK-042.  
**Acceptance criteria:** release criteria in `TEST_STRATEGY.md` pass; no severity-1 safety defect.  
**Tests:** full MVP suite.  
**Order:** 43.

## Post-MVP — do not implement now

### TASK-044 — Live approval mode `[POST-MVP]`
**Status:** pending  
**Requirements:** FR-024.  
Prerequisites: explicit owner/product approval and live security review.

### TASK-045 — Bounded autonomous live mode `[POST-MVP]`
**Status:** pending  
**Requirements:** FR-025.  
Prerequisites: successful approval-mode period and new go/no-go decision.

### TASK-046 — Intraday crash monitor and intraday historical evaluator `[FUTURE]`
**Status:** pending  
**Requirements:** FR-026.  
Prerequisite: intraday dataset and evidence that daily-only system justifies added complexity.
