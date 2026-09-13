# TailHedge — Product Requirements Document

## 1. Product goals

- **G-001 Research credibility:** determine whether a systematic long-put hedge improves the user’s combined portfolio under conservative, reproducible assumptions.
- **G-002 Robust strategy discovery:** find simple policies that survive time-blocked out-of-sample tests, cost stress, parameter perturbation, and withheld crises.
- **G-003 Operational translation:** convert a frozen strategy into a daily broker-independent target hedge plan.
- **G-004 Safe automation path:** support shadow and paper operation first, with architecture that can later support approval-gated and bounded autonomous live execution.
- **G-005 Auditability:** make every experiment, decision, order, and configuration change reproducible from stored inputs and versions.

## 2. User type

### U-001 Owner / Researcher
The only MVP user. The owner configures the portfolio, imports data, runs research campaigns, reviews evidence, promotes strategy releases, connects IBKR, controls execution mode, and engages the kill switch.

No adviser/client, admin/member, or public-user roles exist in MVP.

## 3. Primary user journeys

### J-001 — Establish research data
1. Owner creates or selects a research dataset.
2. Owner imports historical option-chain files and underlying/portfolio series.
3. System validates timestamps, duplicates, bid/ask sanity, contract identity, missingness, and coverage.
4. For external SPX research, the system runs provider-specific qualification and verifies settlement semantics and representative coverage.
5. System produces data-health and qualification reports and refuses campaign creation if required invariants fail.

### J-002 — Run a research campaign
1. Owner chooses dataset, portfolio proxy, allowed features, budget cap, baseline set, train/validation/holdout partition policy, and fixed evaluator profile.
2. System freezes campaign configuration and hashes evaluator/code/data manifests.
3. Agent proposes one candidate at a time.
4. System evaluates the candidate in an isolated runtime.
5. System stores all results, including failures.
6. Agent receives only permitted train/validation feedback and proposes the next candidate.
7. Campaign stops by user request, iteration limit, cost limit, or safety/error condition.

### J-003 — Promote a candidate
1. Owner selects a promising candidate.
2. System runs mandatory robustness suite.
3. If gates pass, owner may freeze the candidate as a strategy release.
4. Final holdout may be run once for that release.
5. Holdout results are stored as consumed evidence and must not silently become tuning data.

### J-004 — Daily shadow operation
1. Scheduler starts a daily run at the configured exchange-local time.
2. System syncs actual broker positions/cash/orders.
3. System obtains current option-chain/underlying quotes.
4. Frozen strategy release produces a target hedge plan.
5. Deterministic risk engine validates the plan and calculates broker order intents.
6. In shadow mode, intents are logged only.

### J-005 — Daily paper operation
Same as J-004, but validated order intents are sent to the configured IBKR paper account as limit orders, monitored, reconciled, and audited.

### J-006 — Emergency stop
Owner engages the kill switch. System cancels any cancellable pending TailHedge-created orders and prevents new TailHedge order submission until explicitly re-enabled. Existing positions are not liquidated automatically.

---

## 4. Functional requirements

### FR-001 — Portfolio definition and hedge mapping `[MVP]`
The system shall maintain one logical portfolio containing holdings, cash, base currency, and a mapping from hedge-eligible holdings to a benchmark exposure/beta.

**Acceptance criteria**
- Owner can add/edit/archive a holding or import a current broker snapshot.
- Each hedge-eligible holding has a benchmark mapping and hedge beta; cash is excluded by default.
- System calculates portfolio value, hedge-eligible value, benchmark-equivalent exposure, and mapping coverage.
- Unmapped non-cash holdings are surfaced as warnings and excluded from hedge sizing unless explicitly mapped.

### FR-002 — Normalised historical option data import `[MVP]`
The system shall import daily option-chain snapshots into a canonical Parquet schema independent of vendor format.

Required canonical fields: trade date/time, underlying/root, expiration, strike, option type, bid, ask, bid size when available, ask size when available, volume when available, open interest when available, underlying price/reference, source, and ingest metadata. IV/Greeks are optional.

**Acceptance criteria**
- CSV and Parquet import are supported through a common importer interface.
- Vendor-specific columns are transformed without changing raw source files.
- Imported dataset has a manifest containing source, date range, row count, schema version, file hashes, and timezone.
- A provider-specific qualification report records the source mapping, observed timestamp semantics, and unresolved assumptions before the dataset is used for real-data research.

### FR-003 — Historical data validation `[MVP]`
The system shall validate research data before it can be used in a campaign.

Mandatory checks: unique contract snapshot key, bid >= 0, ask >= bid for tradable quotes, expiry >= observation date, valid put/call value, no impossible strike/expiry types, deterministic timezone normalisation, duplicate detection, and coverage summary.

**Acceptance criteria**
- Fatal validation errors block campaign use.
- Warnings are quantified by date and field.
- The health report is persisted and reproducible.
- SPX research datasets additionally verify root identity, contract settlement metadata, expiry settlement coverage, and side-specific field mappings before backtest use.

### FR-004 — Deterministic backtest engine `[MVP]`
The system shall simulate the combined portfolio using only information available at each historical decision timestamp.

The engine shall model: core portfolio return, hedge premium/cash flows, contract selection, option exits/expiry settlement, transaction costs, contract granularity, FX conversion when configured, monetisation/reinvestment rules, and cash balances.

**Acceptance criteria**
- Re-running with identical code/config/data/seed produces identical results.
- No strategy call receives future rows or final-holdout labels.
- Positions and cash reconcile at every simulated step.
- A synthetic fixture with known option payoffs matches expected cash flows within configured tolerance.

### FR-005 — Baseline strategies `[MVP]`
The evaluator shall include immutable comparison baselines:
1. no hedge;
2. lower-equity/cash allocation baseline;
3. fixed mechanical put hedge with configurable DTE/moneyness or delta, roll rule, and budget;
4. at least one Cboe-PPUT-like mechanical policy represented from the available dataset without claiming exact index replication unless methodology/data match.

### FR-006 — Strategy interface `[MVP]`
Research strategies shall implement a versioned pure-policy interface that consumes only permitted `StrategyContext` fields and returns a `TargetHedgePlan`.

A strategy must not receive broker credentials, secret holdout data, evaluator internals, filesystem paths outside its sandbox, or network access.

### FR-007 — Frozen campaign configuration `[MVP]`
When a campaign starts, the system shall freeze and hash:
- dataset manifest/version;
- portfolio proxy definition;
- train/validation/holdout scheme;
- scoring profile;
- transaction-cost model;
- allowed strategy features;
- robustness suite version;
- agent configuration except credentials;
- evaluator/backtester version.

Changing any item creates a new campaign revision or campaign; it must not silently mutate prior results.

### FR-008 — Autoresearch iteration loop `[MVP]`
The system shall support an iterative loop where an agent receives the current permitted strategy representation plus allowed experiment feedback and proposes a replacement candidate.

**Acceptance criteria**
- Only the candidate strategy artifact can change during an iteration.
- Before evaluation, the system verifies immutable component hashes.
- Invalid candidate output is recorded as a failed experiment and cannot modify campaign state.
- Iteration continues according to campaign stop conditions.

### FR-009 — Complete experiment ledger `[MVP]`
Every attempted experiment shall be persisted, including rejected/failed experiments.

Persist at minimum: sequence number, parent candidate, strategy source/hash, agent rationale if supplied, start/end time, evaluator version, metrics, errors, resource use, train/validation fold results, and selection outcome.

### FR-010 — Final holdout isolation `[MVP]`
The final holdout shall be inaccessible to the agent and ordinary campaign feedback.

**Acceptance criteria**
- Holdout data path/rows are not mounted into the strategy runtime during research.
- Holdout score is not returned to the agent.
- A strategy release records whether the holdout has been consumed.
- A consumed holdout cannot be relabelled as untouched for later claims.

### FR-011 — Robustness and red-team suite `[MVP]`
Promising candidates shall be testable under a fixed suite including:
- worse fills/spreads;
- increased option premium/cost assumptions;
- one-decision-period execution delay;
- parameter perturbations;
- leave-one-crisis/regime-out tests;
- benchmark beta/basis-risk perturbation;
- FX perturbation when applicable;
- synthetic crash paths with varied speed, depth, volatility/skew shock, and recovery;
- removal of individual historically dominant payoff events.

Results shall be reported individually; no test may be hidden because it is unfavourable.

### FR-012 — Candidate freeze and release provenance `[MVP]`
The owner shall be able to freeze a candidate as a versioned strategy release after required gates pass or with an explicit recorded override.

A release contains exact strategy artifact/hash, campaign ID, evaluator/scoring version, evidence summary, holdout status, and permitted operation modes.

### FR-013 — Daily policy evaluation `[MVP]`
The system shall run a frozen strategy release on a configurable once-per-trading-day schedule. Default decision time: 15:45 `America/New_York`.

Each run shall generate a complete decision record even when the action is `NO_ACTION`.

### FR-014 — IBKR read-only account reconciliation `[MVP]`
The system shall retrieve the selected account’s positions, cash, open orders, and relevant account state before producing an executable action.

If broker state cannot be reconciled, the run fails closed.

### FR-015 — Current market/contract validation `[MVP]`
Before generating any broker order intent, the system shall refresh current contract definitions and quotes and validate instrument identity, expiration, right, multiplier, quote freshness, bid/ask sanity, and liquidity thresholds.

### FR-016 — Deterministic live risk gate `[MVP]`
All paper order intents must pass a non-AI risk gate.

Default hard rules:
- hedge orders may only increase/decrease existing **long put** positions;
- no sell-to-open;
- no naked options;
- no market orders;
- no intentional borrowing/margin use to fund premium;
- rolling 365-day hedge premium spend must not exceed configured cap (default 1.0% of reference portfolio value) without manual configuration change;
- per-order and per-day premium caps must be configured;
- minimum quote freshness and maximum spread threshold must pass;
- sufficient settled/available cash buffer must exist;
- target contract must be in allowed underlyings (`XSP` initially; `SPX` only if explicitly enabled);
- kill switch must be disengaged.

**Acceptance criteria**
- Risk gate produces machine-readable pass/fail reasons.
- Agent/strategy code cannot override a failed rule.
- Any unknown rule state is treated as failure.

### FR-017 — Paper limit-order execution `[MVP]`
In paper mode, validated intents may be submitted to IBKR paper trading as limit orders.

The executor shall use a bounded repricing policy and shall never fall back to a market order.

Default buy behaviour:
1. require valid NBBO and spread threshold;
2. place at midpoint + 25% of spread, rounded to valid tick;
3. if unfilled after configured interval, re-quote and optionally step to midpoint + 50% of current spread;
4. do not exceed the lower of current ask and the configured reference-price tolerance;
5. cancel after the configured attempt/time limit.

Sell-to-close is symmetrical. Exact values are configuration, frozen in an execution-policy version.

### FR-018 — Idempotency and broker-truth reconciliation `[MVP]`
Daily runs and order submission shall be idempotent.

**Acceptance criteria**
- A deterministic daily-run key prevents duplicate scheduled processing.
- Each broker order intent has an idempotency key derived from run, contract, side, quantity, and intent revision.
- Restarting the service after submission but before acknowledgement reconciles open orders/fills before any new order is sent.
- Unknown broker state causes `MANUAL_REVIEW_REQUIRED`, not a duplicate order.

### FR-019 — Monetisation and reinvestment modelling `[MVP research]`
Research strategies may define daily decision-point rules for reducing profitable hedge positions and allocating released cash to the simulated core portfolio.

MVP shall not claim or simulate intraday monetisation from daily snapshots.

### FR-020 — Dashboard and evidence reporting `[MVP]`
The UI shall show:
- current portfolio and hedge state;
- current execution mode;
- hedge budget and rolling spend;
- actual vs target hedge plan;
- next relevant expiries/roll status;
- latest daily decision and reasons;
- research campaign status;
- candidate/baseline comparison;
- CAGR, max drawdown, premium spend, drawdown reduction, tail-efficiency metrics, and robustness results;
- data/broker health;
- unresolved warnings.

### FR-021 — Operation modes and kill switch `[MVP + future]`
Supported mode enum:
- `RESEARCH_ONLY`
- `SHADOW`
- `PAPER`
- `LIVE_APPROVAL` `[post-MVP]`
- `LIVE_AUTONOMOUS` `[post-MVP]`

MVP UI/API must not permit selection of live modes unless a later release explicitly enables them in configuration and code.

Kill switch stops new broker submissions in any execution-capable mode and attempts cancellation of TailHedge-created open orders. It never liquidates positions automatically.

### FR-022 — Audit and notification events `[MVP]`
The system shall persist material events and surface them in the UI. Critical failures shall support at least one configurable notification adapter.

Required notification categories: scheduled run failed, broker authentication unavailable, reconciliation mismatch, risk-gate rejection requiring attention, paper order unfilled/cancelled, kill switch changed, final holdout consumed.

Email/SMS/push providers are not mandated; the first adapter may be local/log/web UI.

### FR-023 — Configuration and secrets `[MVP]`
Non-secret settings shall be validated typed configuration. Credentials/API keys/tokens shall be loaded from environment or OS/container secrets and never committed or displayed in logs.

### FR-024 — Live approval execution `[post-MVP]`
A later release may allow validated real-money order intents to require explicit owner approval after a fresh quote/reconciliation check. Approval must expire after a short configurable interval.

### FR-025 — Bounded autonomous live execution `[post-MVP]`
A later release may allow automatic real-money long-put execution under stricter risk thresholds and release gating. Autoresearch/LLM components remain physically and logically unable to call the broker executor directly.

### FR-026 — Intraday crash monitor `[future]`
A future enhancement may monitor predefined market/hedge thresholds and trigger an additional deterministic evaluation. It is not part of MVP and requires intraday historical validation before use.

---

## 5. Research business rules

### BR-001 — No random time split
Train/test partitions must preserve chronology. Random row-level splitting is prohibited.

### BR-002 — Purge/embargo
Fold boundaries must purge enough history to prevent positions/lookback windows from crossing from training into evaluation. Default purge horizon is `max(strategy lookback, maximum allowed DTE/holding horizon)` unless the evaluator proves a shorter non-leaking horizon.

### BR-003 — Hidden holdout is one-way evidence
Once humans inspect a holdout result and use it to change the policy, that dataset is no longer a final holdout for the revised policy.

### BR-004 — Campaign scoring profile is immutable
The agent cannot change its scoring function, budget cap, cost model, or robustness thresholds within a campaign.

### BR-005 — Complexity is observable
Candidate complexity (parameters, branches, permitted feature count) is recorded and may be penalised. A strategy that only works at a single sharp parameter point must be flagged as fragile.

### BR-006 — Backtest fills are conservative
The default research fill model is not midpoint-only. Base case shall use a configurable fraction of bid/ask spread; mandatory stress cases include worse fills.

### BR-007 — Report all attempted research
Do not delete losing trials from the experiment ledger.

### BR-008 — Research success need not imply hedge adoption
The system may conclude that no candidate materially improves the portfolio after cost.

## 6. Live/paper business rules

### BR-009 — Broker state first
No executable daily decision is made until current broker state is reconciled.

### BR-010 — Strategy produces targets, not orders
Strategy code outputs a target hedge plan. Only deterministic application code may translate targets to orders.

### BR-011 — Quote revalidation
A target determined earlier in the run must be re-priced immediately before order submission.

### BR-012 — No stale recommendation execution
If quote/portfolio conditions breach configured tolerances, regenerate or abort; never execute a stale order merely because it was proposed earlier.

### BR-013 — No implicit live trading
Live modes require explicit future enablement. Paper credentials/account IDs must not be interchangeable with live configuration silently.

## 7. Permissions and roles

MVP has one application role: `OWNER`.

`OWNER` may manage portfolio configuration, datasets, campaigns, strategy releases, broker connection settings, risk limits, execution mode within enabled modes, and kill switch.

Research strategy/agent processes are **not users** and receive capability-limited inputs only.

## 8. Edge cases

- Market holiday or early close: schedule resolves exchange calendar; no normal run if instrument market is closed.
- DST transition: schedule uses `America/New_York`, never fixed UTC or London time.
- No suitable option within target DTE/delta/liquidity range: action is `NO_TRADE_NO_ELIGIBLE_CONTRACT`.
- Portfolio drops enough that one XSP contract over-hedges target materially: system reports sizing granularity and does not exceed configured over-coverage limit.
- Missing underlying price: fail current run.
- Bid = 0 / wide ask on far-OTM option: reject as untradeable under configured liquidity rules.
- Existing broker position not created by TailHedge: include in account truth; require explicit ownership/mapping before system may close it.
- Partial fill: reconcile filled quantity and recompute residual intent before any retry.
- Broker disconnect after submission: query open orders/executions on reconnect before submitting anything else.
- Annual budget exhausted: maintain existing positions; no new premium spend unless a sell/roll action is budget-neutral under defined accounting.
- Negative/zero cash availability: no premium-buying order.
- Data revision: existing campaign remains tied to old manifest; new data requires new campaign/revision.
- Strategy exception/timeout: mark run failed; do not trade.
- Candidate requests prohibited instrument/action: evaluator rejects candidate output.

## 9. Error and empty states

- No dataset: guide owner to import data; research actions disabled.
- Dataset invalid: show failing checks and affected dates/rows; campaigns disabled for that dataset.
- Dataset not qualified: show the qualification report and keep real-data campaign actions disabled.
- No campaign: show baseline research start action.
- No strategy release: shadow/paper execution disabled.
- Broker unauthenticated: show `BROKER_OFFLINE`; scheduled run records failure; no orders.
- No hedge needed: show explicit `NO_ACTION` and reasons, not a blank screen.
- Risk gate reject: show exact rule(s), values, thresholds, and whether user action is required.
- Holdout already consumed: warn that further tuning invalidates “untouched holdout” status.

## 10. Notifications/background behaviour

- Scheduled daily evaluation default at 15:45 America/New_York on eligible trading days.
- Research campaigns may run as background jobs and must persist progress after each experiment.
- Notifications are event-driven, not periodic spam.
- Repeated identical broker-offline alerts should be deduplicated within a configurable suppression window.

## 11. Search/filter/sort

Research experiment table shall support:
- filter by campaign, status, promoted/not promoted, date, strategy hash, and robustness pass/fail;
- sort by experiment sequence, score, CAGR delta, max-drawdown improvement, premium spend, complexity, and created time;
- text search over experiment ID and agent rationale.

Orders/audit tables shall support date range, status, symbol, run ID, and event type filters.

## 12. Accessibility

- All critical states must have text labels; colour alone may not encode pass/fail/risk.
- Keyboard access for navigation, forms, tables, modal confirmations, and kill switch.
- Semantic headings/landmarks and labelled form controls.
- Focus is moved to validation/error summary after failed form submission.
- Charts require adjacent numerical/table summaries for key metrics.
- Target WCAG 2.1 AA for application-owned UI where practical.

## 13. Security/privacy requirements

See `SECURITY_AND_PRIVACY.md`. Product-level minimums:
- local/private deployment by default;
- authenticated owner session for any state-changing UI/API;
- CSRF protection for browser mutations;
- no secrets in source, database plaintext fields, experiment prompts, or logs;
- research agent has no broker credentials and no network in strategy execution sandbox;
- live mode disabled in MVP build;
- full audit trail for risk settings, mode changes, strategy promotion, and broker actions.

## 14. Performance expectations

- Portfolio/dashboard read: p95 < 1 second on local network for ordinary pages excluding chart-heavy historical queries.
- Current daily decision excluding broker/network latency: target < 30 seconds for portfolio/contract selection and risk checks.
- Historical backtest performance: a representative 15–20 year daily dataset for one benchmark strategy should complete in < 2 minutes on a modern 8-core developer machine after data is normalised; implementation should profile rather than prematurely optimise.
- Experiment persistence must occur after every trial so process failure loses at most the currently running experiment.

## 15. Analytics / telemetry

No third-party product analytics in MVP. Persist operational telemetry locally:
- campaign iteration counts/durations/errors;
- backtest runtime and memory;
- data-quality counts;
- scheduled run success/failure;
- broker request/order lifecycle latency;
- risk-gate rejection counts;
- notification delivery status.

Telemetry must not include credentials or full sensitive account identifiers.

## 16. Out-of-scope functionality

The non-goals in `PROJECT_OVERVIEW.md` are binding for MVP. In particular, autonomous live trading, intraday crash trading, short options, multi-user SaaS, market prediction, tax optimisation, and arbitrary AI access to the broker are not to be implemented in the initial release.
