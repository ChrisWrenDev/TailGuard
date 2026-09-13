# TailHedge — Project Overview

## Working title

**TailHedge** — a single-user research and execution system for maintaining a rules-based long-put tail-risk hedge around a long-term equity portfolio.

## Product summary

TailHedge is a local-first application that helps an individual investor research whether a systematic equity-index put overlay can improve the long-run behaviour of a predominantly equity portfolio, then safely operate the resulting policy through Interactive Brokers (IBKR). The research system downloads or imports historical option-chain snapshots, backtests candidate hedge policies, runs an Autoresearch-style iterative strategy search, and subjects promising candidates to multiple-testing controls, regime holdouts, perturbation tests, and execution-cost stress tests. The live system is deliberately separate: it reads the actual portfolio, applies a frozen strategy release, produces a target hedge plan, checks hard risk limits, and—initially only in shadow/paper mode—places or simulates long-put orders. The project is inspired by the objective of tail-risk insurance, not by an attempt to reproduce Universa Investments’ proprietary strategy.

## Problem being solved

A long-horizon investor may want convex protection against severe equity drawdowns without continuously sacrificing so much premium that the hedge damages compound returns. The difficult questions are not whether a put has a convex payoff, but:

- how much annual premium can be spent sustainably;
- which expiries, strikes/deltas, roll schedule, tranche structure, and sizing rules are most robust;
- how the hedge behaves across different crash shapes and volatility regimes;
- how and when hedge profits should be monetised and reinvested;
- whether a historical result survives realistic spreads, slippage, basis risk, and multiple-testing corrections;
- how a researched policy can be translated into deterministic, bounded broker actions without giving an AI model direct control of capital.

## Target user

Initial target: **one technically capable individual investor** who:

- owns a long-term equity portfolio, likely broad-market Vanguard or similar funds/ETFs;
- can use or open an IBKR account with the required options permissions;
- is willing to pay for historical options data if needed;
- wants a research-driven insurance overlay rather than discretionary market timing;
- can operate a local or personally controlled server.

This is not a multi-user advisory platform, brokerage, robo-adviser, or consumer SaaS product.

## Primary user outcomes

1. Determine whether a systematic tail hedge is economically useful for the user’s portfolio under conservative assumptions.
2. Identify a **simple, robust region of strategy space**, not merely the best historical parameter combination.
3. Quantify annual hedge spend, coverage, drawdown reduction, premium bleed, basis risk, and long-run combined-portfolio performance.
4. Maintain a frozen hedge policy on a daily schedule without requiring the user to watch the market continuously.
5. Make every proposed or executed trade explainable, bounded, auditable, and reproducible.
6. Prevent the research agent from modifying the evaluator, broker safety rules, secret holdout data, or live trading logic.

## Product principles

### P-001 — Combined portfolio, not option P&L
Success is measured on **core portfolio + hedge + cash + reinvestment**, not on whether individual puts make money.

### P-002 — Robustness over optimisation
Prefer broad parameter plateaus, stable out-of-sample behaviour, and simple rules over sharp historical optima.

### P-003 — Research and execution are separate trust domains
The Autoresearch component may propose strategy code/policies. It may never directly place broker orders or modify live risk controls.

### P-004 — Fail closed
If market data, broker state, contract identity, cash, pricing, or risk checks are uncertain, the live engine must take no new risk and must not place an order.

### P-005 — Reconcile from broker truth
Every live/paper run starts from current broker positions/orders/cash. It must never rely only on yesterday’s assumed state.

### P-006 — No hidden holdout leakage
Final holdout results are inaccessible to the research agent during optimisation. A holdout becomes “used” after it is inspected for strategy selection.

### P-007 — Daily first
The MVP uses one option-chain decision snapshot per trading day. Intraday crash monetisation is explicitly deferred until daily research proves useful.

### P-008 — Long-option safety boundary
MVP and first live-capable release support **long puts only** for hedge positions. No naked short options, leverage to fund option premiums, or market orders.

### P-009 — Negative results are valid
The project succeeds if it credibly demonstrates that the hedge is not worth its cost. The system must not be designed to force a “winning” strategy.

## Scope of the initial release

The first release is a **research + shadow/paper system**, not autonomous real-money trading.

Mandatory MVP scope:

- import normalised daily historical option-chain snapshots;
- import/configure a portfolio benchmark or proxy series;
- store research data in Parquet and query it locally;
- deterministic historical backtester with no-look-ahead controls;
- conservative configurable execution-cost model;
- simple benchmark strategies, including no hedge and fixed mechanical long-put policies;
- Autoresearch-style loop that can only change the strategy candidate surface;
- immutable scoring configuration per campaign;
- complete experiment ledger, including failed trials;
- rolling/blocked validation, purge/embargo around split boundaries, and leave-one-regime-out tests;
- robustness tests for fills, timing, parameter perturbation, basis risk, and crash-path scenarios;
- candidate freezing and one-time final holdout evaluation;
- portfolio/strategy dashboard;
- IBKR read-only portfolio sync;
- scheduled once-daily policy evaluation at **15:45 America/New_York** by default, matching a common historical options-data snapshot and leaving regular-session time for execution;
- shadow mode (record what would be done);
- IBKR paper mode with deterministic long-put limit-order execution and reconciliation;
- kill switch and hard risk limits;
- audit log of research, decisions, orders, fills, configuration changes, and errors.

## Explicit non-goals for the initial release

- Reproducing Universa Investments’ proprietary strategy.
- Providing investment, tax, legal, or regulated financial advice.
- Guaranteeing that the portfolio is “fully insured” or that the hedge will profit in every crash.
- Intraday/0DTE trading or high-frequency decision-making.
- Machine-learning prediction of market direction.
- Short-option strategies, naked options, premium-selling, futures, CFDs, or leveraged hedge financing.
- Automatic real-money execution.
- Multi-broker support.
- Multi-user/team workflows.
- Automated tax calculation or ISA/SIPP eligibility determination.
- Mobile-native applications.
- Automatic transfer of Vanguard assets to IBKR.
- Optimising visual design beyond a clear, accessible operational UI.

## Key terminology and domain concepts

| Term | Definition |
|---|---|
| Core portfolio | Long-term investment assets being protected. |
| Hedge overlay | Long-put positions held in addition to the core portfolio. |
| Hedge budget | Maximum premium spend permitted, normally expressed as % of portfolio value per year. |
| Hedge exposure | Approximate equity-market exposure the system intends to protect after applying portfolio weights/beta mappings. |
| Coverage ratio | Actual hedge target exposure divided by desired hedge exposure; a diagnostic, not a guarantee of loss reimbursement. |
| Basis risk | Mismatch between the behaviour of the user’s holdings and the SPX/XSP hedge instrument. |
| Strategy policy | Pure research logic that maps observable market/portfolio state to a desired hedge plan. |
| Target hedge plan | Broker-independent desired positions/characteristics generated from a strategy release. |
| Strategy release | Frozen, versioned strategy code + parameters + data/scoring provenance approved for shadow/paper/live evaluation. |
| Campaign | A research run with fixed dataset partitions, evaluator, scoring profile, cost model, and agent permissions. |
| Experiment | One candidate strategy evaluation within a campaign. |
| Validation fold | Time-blocked out-of-sample slice visible to the research process according to campaign rules. |
| Final holdout | Data never exposed to the research agent or used for tuning before strategy freeze. |
| Monetisation | Reducing a profitable hedge position during/after a drawdown. |
| Reinvestment | Deploying monetised hedge proceeds into the core portfolio according to a tested rule. |
| Shadow mode | Live market/broker observation with decisions logged but no orders sent. |
| Paper mode | Orders sent only to an IBKR paper account. |
| Live approval mode | Post-MVP mode where real-money orders require explicit user approval. |
| Live autonomous mode | Post-MVP bounded real-money execution under hard limits. |
| Fail closed | Defaulting to no trade when an invariant or dependency cannot be verified. |

## Major assumptions

**A-001 — Single owner.** The application serves one owner and one logical investment portfolio in the MVP.

**A-002 — Portfolio benchmark.** Research initially treats the S&P 500/SPX as the hedge benchmark and explicitly models basis risk to the actual portfolio.

**A-003 — Research instrument vs execution instrument.** Historical research may use SPX option history because of data depth. XSP is the preferred initial live/paper execution instrument when its smaller contract size is appropriate. XSP is 1/10 the SPX index level, uses a $100 multiplier, is cash-settled, and uses European exercise.

**A-004 — Daily decision snapshot.** The canonical research/live decision time is 15:45 US Eastern. This is an implementation default, not an assertion that 15:45 is financially optimal.

**A-005 — Historical data ownership.** The user will obtain appropriately licensed data. The application may include vendor adapters, but it will not redistribute paid datasets.

**A-006 — Research data resolution.** Daily snapshots are sufficient for MVP hedge maintenance and daily monetisation research. Intraday claims must not be inferred from daily data.

**A-007 — Hedge budget default.** The default campaign/live safety cap is 1.0% of portfolio value per rolling 365 days unless the user configures a lower value. This is a safety default, not investment advice.

**A-008 — Live rollout.** Real-money automation is intentionally outside MVP and requires a later explicit product decision, additional tests, and user enablement.

## Known constraints

1. **Sparse tail events.** A long history contains relatively few independent severe drawdowns; apparent precision can be misleading.
2. **Multiple testing.** An automated research loop can overfit by trying thousands of policies. All experiments must be recorded and strategy selection must account for research breadth.
3. **Historical-data limits at IBKR.** IBKR is not the research history source for expired options; the system uses independent historical option data.
4. **Data licensing.** Historical options datasets may be paid and subject to redistribution/use restrictions.
5. **Execution differences.** Backtest marks, paper fills, and live fills can differ materially, especially for far-OTM options during stress.
6. **Basis risk.** SPX/XSP cannot perfectly hedge a global or otherwise non-SPX portfolio.
7. **FX risk.** A GBP-based investor buying USD-denominated index options has GBP/USD effects on premiums and payouts.
8. **Broker session availability.** IBKR TWS/IB Gateway sessions require operational monitoring, periodic restart/re-authentication, and reconnect logic.
9. **Contract granularity.** XSP still imposes discrete contract sizing; small portfolios may be over- or under-hedged relative to a continuous target.
10. **Market-hours/DST complexity.** Schedules must use exchange time zones rather than hard-coded UK clock times.
11. **No guaranteed protection.** A put overlay protects only according to its strikes, expiries, sizing, path, and monetisation policy; it is not equivalent to an insurance contract covering all portfolio losses.

## External implementation facts to re-verify before live release

As of 2026-09-12:

- Cboe documents XSP as 1/10 of SPX, $100 multiplier, cash-settled, European exercise, with regular hours extending to 15:15 Chicago time for non-expiring contracts.
- Cboe DataShop Option EOD Summary provides a 15:45 US Eastern snapshot and end-of-day data, with historical coverage from January 2012; IV/Greeks are optional calculated fields.
- ORATS documents historical end-of-day option data back to 2007; the project
  uses its Near End-of-day archive as the primary qualification source, subject
  to SPX handling, settlement, licensing, and deterministic import checks.
- IBKR documents API access for market/account data and order placement; current IBKR documentation states expired-options historical market data is unavailable through its normal interfaces.
- IBKR documents that TWS/IB Gateway require GUI authentication, can auto-restart during the week, and generally need re-authentication after the weekend reset.

These are external dependencies, not permanent product invariants. Re-verify them during implementation and before any live-money release.
