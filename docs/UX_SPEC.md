# TailHedge — UX Specification

## 1. Experience goals

The interface is an operational research/risk console, not a trading terminal. It should answer five questions quickly:

1. What portfolio is being protected?
2. What strategy release is active and what evidence supports it?
3. What hedge do I currently own versus what the policy wants?
4. What did the system decide today, and why?
5. Is anything unhealthy, blocked, or unsafe?

Visual styling is intentionally unspecified beyond clarity, restraint, and accessibility.

## 2. Information architecture

Primary navigation:

1. **Dashboard**
2. **Portfolio**
3. **Research**
   - Campaigns
   - Experiments
   - Candidates / Releases
4. **Operations**
   - Daily Runs
   - Orders
   - Broker Health
5. **Data**
6. **Audit Log**
7. **Settings**
   - Risk Controls
   - Schedule
   - Integrations
   - Notifications

Persistent global controls:
- current mode badge (`RESEARCH_ONLY`, `SHADOW`, `PAPER`);
- broker connection health;
- kill-switch status/control;
- unresolved critical-warning count.

## 3. Navigation model

Desktop: left navigation rail + top status bar.

Small screens: collapsible navigation drawer. Critical mode, broker health, and kill-switch status remain visible near the top of the page.

No nested navigation deeper than two levels in MVP.

## 4. Screen inventory

### UX-001 — First-run setup

**Purpose:** establish a safe runnable configuration without enabling broker writes.

**Steps**
1. Welcome / scope acknowledgement.
2. Base currency and timezone display; exchange schedule remains New York-time based.
3. Portfolio source: manual research proxy now; optional IBKR read connection later.
4. Historical dataset import or synthetic/demo dataset.
5. Hedge benchmark mapping.
6. Research defaults (annual premium cap, allowed DTE/delta ranges, baseline set).
7. Optional IBKR paper/read connection.
8. Review summary.

**Important rule:** first-run completion sets execution mode to `RESEARCH_ONLY` or `SHADOW`; never `PAPER` automatically.

### UX-002 — Dashboard

**Purpose:** current high-level state.

**Layout**
- Top status strip: mode, strategy release, broker, data health, kill switch.
- Portfolio summary: total value, hedge-eligible value, benchmark-equivalent exposure, cash.
- Hedge summary: current long-put market value, target/actual coverage estimate, rolling 365-day premium spend vs cap, nearest expiry.
- Latest daily decision card: timestamp, outcome, target changes, risk-gate status, order status if applicable.
- Research evidence card: active/promoted release, holdout status, baseline comparison, robustness pass summary.
- Alerts/warnings list.

**Empty state:** if no portfolio/dataset exists, show setup actions instead of zero-valued charts.

### UX-003 — Portfolio

**Purpose:** define what is being protected and inspect broker state.

**Components**
- Portfolio totals.
- Holdings table: symbol/name, quantity/value, currency, hedge eligible, benchmark, beta, mapped exposure, source, last updated.
- Cash balances.
- Mapping completeness summary.
- Broker snapshot timestamp.

**Actions**
- Add/edit/archive manual holding.
- Edit hedge mapping/beta.
- Sync broker now.
- Export current mapping as JSON/CSV.

**Validation**
- beta must be finite and within configurable safe editing bounds; default UI permits 0.0–2.0 and requires explicit advanced override outside range;
- benchmark required when `hedge_eligible=true`;
- cash cannot be hedge eligible;
- user must acknowledge exclusions if > configured % of non-cash portfolio is unmapped.

### UX-004 — Data

**Purpose:** import, validate, and understand research datasets.

**Components**
- Dataset list with vendor/source, date range, rows, schema version, health state.
- Provider qualification state and link to the qualification report.
- Import action.
- Data-health report: duplicates, missing dates, crossed quotes, zero bids, field coverage, contract counts by date, underlying coverage.
- Manifest/hash detail.

**Import form**
- source label/vendor adapter;
- files;
- source timezone;
- snapshot time if not encoded;
- underlying symbol mapping;
- optional field map preview.

**States**
- Uploading/ingesting.
- Validating.
- Ready with warnings.
- Blocked/fatal.
- Imported but not qualified for real-data research.

### UX-005 — Research campaigns

**Purpose:** define and run a controlled research programme.

**Campaign list columns**
ID/name, dataset, status, iterations, created, best validation score, experiment count, final holdout status.

**Create campaign form**
- name/description;
- dataset;
- dataset qualification must be `PASSED` for external real-data campaigns;
- portfolio proxy;
- train/validation period policy;
- final holdout period;
- annual premium cap;
- allowed instruments/features;
- allowed DTE range;
- allowed delta/moneyness range;
- execution cost profile;
- robustness profile;
- scoring profile;
- iteration/time/token/cost stop limits;
- agent provider.

Show a prominent notice: **campaign scoring, splits, and cost rules become immutable after start**.

### UX-006 — Campaign detail

**Purpose:** monitor Autoresearch without hiding failures.

**Components**
- campaign immutable configuration summary;
- progress/status controls;
- best/current candidate summary;
- baseline comparison;
- experiment table;
- score/metric history charts;
- failure count and categories;
- resource/cost usage if available.

**Actions**
- start/pause/stop campaign;
- open experiment;
- nominate candidate for robustness suite.

Stopping a campaign must not delete results.

### UX-007 — Experiment detail

**Purpose:** inspect one trial completely.

Show:
- experiment ID/sequence/parent;
- strategy source diff from parent;
- agent rationale/hypothesis if supplied;
- train/validation metrics by fold;
- baseline deltas;
- premium spend;
- drawdowns;
- trade count/turnover;
- complexity metrics;
- evaluation errors/warnings;
- selection decision and reason.

Do not show final-holdout metrics here unless this exact frozen release has explicitly consumed the holdout.

### UX-008 — Candidate / strategy release

**Purpose:** decide whether a candidate is credible enough to freeze.

**Components**
- evidence summary;
- parameter-neighbour heatmap/table;
- leave-one-regime-out results;
- execution-stress table;
- synthetic crash scenarios;
- basis/FX sensitivity;
- comparison to baselines;
- complexity summary;
- holdout status.

**Actions**
- run/re-run fixed robustness suite;
- freeze release;
- run final holdout once;
- mark release eligible for shadow/paper.

**Confirmation for final holdout:** explicitly state that viewing/using this result consumes untouched-holdout status for future tuning.

### UX-009 — Daily runs

**Purpose:** explain every scheduled decision.

List columns: date/time, mode, release, broker snapshot state, decision, order count, risk status, final status.

Run detail sections:
1. broker state snapshot;
2. portfolio exposure calculation;
3. current hedge positions;
4. strategy target hedge plan;
5. delta between target/actual;
6. contract candidates considered;
7. risk-gate checks;
8. generated intents;
9. broker order/fill lifecycle;
10. final reconciled state.

`NO_ACTION` must include human-readable reasons.

### UX-010 — Orders

**Purpose:** inspect TailHedge-created broker actions.

Table: internal intent ID, broker order ID, run ID, account alias, symbol/expiry/strike/right, side, qty, limit, status, filled qty/avg price, submitted/updated timestamps.

Only TailHedge-owned orders may expose cancel controls through the application.

### UX-011 — Broker health

**Purpose:** answer whether automation can safely run.

Show:
- configured account alias/environment (`PAPER`/`LIVE` if future-enabled);
- authenticated/connected state;
- last successful sync;
- position/cash/order snapshot freshness;
- market-data entitlement/quote status where detectable;
- scheduled restart/re-authentication guidance;
- recent broker/API errors.

Never display full credentials or raw sensitive tokens.

### UX-012 — Risk controls

**Purpose:** inspect/change hard safety limits.

Fields:
- annual premium cap %;
- max premium/order;
- max premium/day;
- minimum cash buffer;
- allowed underlying(s);
- max over-coverage ratio;
- max quote age;
- max relative spread;
- limit-order repricing policy;
- permitted execution mode.

Every save requires re-authenticated owner session and creates an audit event. If values are loosened, confirmation shows old/new values.

### UX-013 — Settings / schedule

Show decision schedule using exchange-local timezone and next five planned runs. Prevent the user from accidentally thinking `20:45 London` is invariant across DST mismatches.

### UX-014 — Audit log

Immutable chronological view of material events. Filters: date, actor, type, campaign/run/order/release ID, severity.

## 5. Important interaction patterns

### Pattern A — Explain before action
Any proposed broker action shows:
- what position change is desired;
- why the strategy requested it;
- what risk checks passed/failed;
- expected premium/cash effect;
- remaining budget.

### Pattern B — Destructive/irreversible evidence confirmation
Running the final holdout requires a confirmation explaining that the evidence will be considered consumed for this research programme.

### Pattern C — Kill switch
The kill switch is visible but protected against accidental activation/deactivation.

Engage flow:
1. click `Engage kill switch`;
2. confirmation states new orders stop and existing positions are not liquidated;
3. on confirmation, switch engages immediately and cancellation requests are sent for TailHedge-owned cancellable orders.

Disengage requires owner authentication and explicit confirmation.

### Pattern D — No hidden automatic “fix”
When a risk rule fails, the UI must not offer a one-click action that silently weakens the threshold. User must edit the risk setting in the dedicated screen with audit logging.

## 6. Loading, success, empty, and failure states

- Long research jobs: persistent job state with last completed experiment and progress counters; page reload must be safe.
- Broker actions: show states `PREPARING`, `SUBMITTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `UNKNOWN_RECONCILIATION_REQUIRED`.
- Dataset ingestion: show file-level and validation progress.
- Never use indefinite spinner without status text after 5 seconds; surface the job/run ID.
- Failure pages show actionable reason plus correlation/event ID for logs.

## 7. Responsive behaviour

Desktop is primary. On narrow screens:
- tables may switch to stacked rows/cards for critical fields;
- detailed experiment matrices may scroll horizontally;
- broker order placement is not a mobile-first use case, but all safety controls remain usable;
- no essential information appears only in hover tooltips.

## 8. Accessibility behaviour

- Status icons include text.
- Charts include table alternative or downloadable data.
- Modals trap focus correctly and return focus to trigger.
- Validation errors are associated with fields and summarised at form top.
- Use accessible names for symbols such as `XSP 650 Put, expiration ...` rather than relying on compressed broker notation alone.

## 9. First-run default values

These are implementation assumptions and must be visibly labelled as defaults, not recommendations:

- mode: `RESEARCH_ONLY`;
- decision time: 15:45 America/New_York;
- annual hedge budget safety cap: 1.0%;
- allowed live/paper hedge underlying: XSP only;
- strategy research DTE search range: 60–180 days initially;
- strategy delta search range: absolute put delta 0.03–0.20 initially;
- no intraday monitor;
- market orders disabled permanently in MVP;
- final holdout action disabled until a candidate is frozen and robustness suite has completed.
