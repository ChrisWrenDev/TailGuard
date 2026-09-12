# TailHedge — Decision Log

## ADR-001 — Product is a research-and-execution system, not a Universa clone
**Context:** The project is inspired by tail-risk insurance concepts associated with Universa/Nassim Taleb, but the proprietary implementation is unknown.  
**Chosen approach:** Build a transparent, rules-based long-put research platform that tests whether convex protection improves the user’s own combined portfolio.  
**Alternatives:** Attempt to infer/replicate Universa; build generic options trader.  
**Reasoning:** Replication would be speculative and unverifiable; a portfolio-specific research objective is testable.  
**Consequences:** Product language must avoid claiming to implement Universa’s strategy.

## ADR-002 — MVP stops at shadow and IBKR paper trading
**Context:** The owner ultimately wants automated actions, but research validity and operational safety must be proven first.  
**Chosen approach:** MVP supports research-only, shadow, and paper modes. Live approval/autonomy are post-MVP.  
**Alternatives:** Build live trading from day one.  
**Reasoning:** Live execution adds downside without helping answer the first question: whether the hedge is robust/economically useful.  
**Consequences:** `LIVE_*` modes are rejected in MVP configuration/API.

## ADR-003 — Long puts only in MVP and first execution path
**Context:** The desired use is insurance, not premium-selling.  
**Chosen approach:** Broker intents are only buy long put or sell-to-close owned long put.  
**Alternatives:** Put spreads, collars, naked/covered short options, futures.  
**Reasoning:** Limits loss to paid premium and sharply reduces broker/risk complexity.  
**Consequences:** Target-plan and risk-gate schemas reject short-opening actions.

## ADR-004 — Research and broker execution are separate trust domains
**Context:** Autoresearch agent-generated code can be wrong, adversarial, or overfit.  
**Chosen approach:** Agent proposes strategy source; isolated evaluator produces a declarative target hedge plan; deterministic trusted code performs risk checks/order translation.  
**Alternatives:** Give agent IBKR API/tool access.  
**Reasoning:** AI should not possess unrestricted financial authority.  
**Consequences:** No direct agent-to-broker interface exists.

## ADR-005 — Daily decision frequency for MVP
**Context:** Initial historical dataset is one option-chain snapshot per day; user does not need intraday hedge maintenance.  
**Chosen approach:** One canonical daily decision. Intraday crash monitoring is future scope.  
**Alternatives:** Minute/tick backtesting and continuous live monitor.  
**Reasoning:** Daily data is cheaper, easier to validate, and aligned with medium-duration put hedges.  
**Consequences:** MVP cannot make evidence-based claims about intraday monetisation.

## ADR-006 — Default decision time is 15:45 America/New_York
**Context:** Cboe DataShop’s Option EOD Summary provides a 15:45 US Eastern NBBO snapshot, while XSP regular trading continues after that snapshot on normal days.  
**Chosen approach:** Research/live default decision timestamp is 15:45 ET.  
**Alternatives:** 17:00 UK, 20:00 UK, market close.  
**Reasoning:** Aligns research and live observation time and leaves time for order execution. Exchange-local timezone avoids DST mistakes.  
**Consequences:** Early-close days may be skipped in MVP rather than changing timestamp dynamically. Re-verify Cboe hours before live release.

## ADR-007 — Research uses independent historical options data, not IBKR history
**Context:** IBKR currently documents that expired-option historical data is unavailable through normal APIs.  
**Chosen approach:** Import licensed historical data (Cboe/ORATS/custom) into a vendor-neutral canonical schema. Use IBKR for current account/market data and execution only.  
**Alternatives:** Pull full backtest history from IBKR.  
**Reasoning:** Research requires expired option chains.  
**Consequences:** Data import/licensing is a first-class concern; broker/data adapters remain separate.

## ADR-008 — Parquet + DuckDB for historical market data
**Context:** Option history is large, columnar, mostly analytical, and does not need transactional updates.  
**Chosen approach:** Immutable Parquet datasets queried by DuckDB; PostgreSQL stores manifests/metadata/results.  
**Alternatives:** Put every option row in PostgreSQL; use a cloud data warehouse.  
**Reasoning:** Local, fast, cheap, simple, reproducible.  
**Consequences:** Data-layer code must preserve manifest/version integrity across files and DB metadata.

## ADR-009 — PostgreSQL for operational state
**Context:** Web, workers, scheduler, campaigns, and broker operations need durable concurrent state.  
**Chosen approach:** PostgreSQL from the start.  
**Alternatives:** SQLite initially.  
**Reasoning:** Avoid future migration/locking problems for a modest infrastructure cost.  
**Consequences:** Local development uses Compose or local Postgres.

## ADR-010 — Server-rendered UI, not SPA
**Context:** Single-user operational console with forms/tables/status, not consumer app.  
**Chosen approach:** FastAPI + Jinja2 + HTMX/vanilla JS.  
**Alternatives:** React/Vue SPA.  
**Reasoning:** Fewer moving parts and easier end-to-end auditing/testing.  
**Consequences:** Browser holds no authoritative financial calculations.

## ADR-011 — Agent provider is vendor-neutral
**Context:** No specific LLM/provider was selected.  
**Chosen approach:** `AgentProvider` interface; MVP includes manual fixture and local-command adapter.  
**Alternatives:** Hard-code OpenAI/Anthropic/etc. API.  
**Reasoning:** Keeps research loop testable and avoids provider lock-in/credentials before necessary.  
**Consequences:** Direct provider API integration is optional later.

## ADR-012 — Execute generated strategy code only in isolated OCI sandbox
**Context:** Autoresearch requires strategy code changes; generated Python is untrusted.  
**Chosen approach:** Container with no network, read-only mounts, non-root user, dropped capabilities, resource/time limits.  
**Alternatives:** In-process `exec`, Python import restrictions, declarative-only DSL.  
**Reasoning:** Python is useful for research flexibility; process-level isolation is required.  
**Consequences:** OCI runtime is a system dependency for agent-generated strategy evaluation.

## ADR-013 — Strategy returns desired state, never broker orders
**Context:** A research strategy should specify economic intent, not execution details.  
**Chosen approach:** `TargetHedgePlan` is broker-independent and declarative. Trusted application code selects current contracts, sizes integer quantities, and creates limit intents.  
**Alternatives:** Strategy chooses exact broker contract/order.  
**Reasoning:** Allows current quote validation and safety checks; reduces stale recommendations.  
**Consequences:** Target-plan schema/version is a core contract.

## ADR-014 — Hidden holdout is physically isolated and one-way evidence
**Context:** Repeatedly checking a holdout lets an optimiser fit it indirectly.  
**Chosen approach:** Holdout partitions are not mounted/returned during campaign research. Running/viewing final holdout marks it consumed.  
**Alternatives:** Show aggregate holdout score after every iteration.  
**Reasoning:** Preserves the only genuinely unseen historical evidence.  
**Consequences:** Revised strategy after seeing holdout needs new truly unseen evidence to make the same claim.

## ADR-015 — Complete experiment ledger, including failures
**Context:** Autoresearch may try thousands of hypotheses; winner-only reporting hides multiple testing.  
**Chosen approach:** Persist every trial, error, timeout, metric, hash, and selection decision.  
**Alternatives:** Keep only improving candidates.  
**Reasoning:** Research breadth is evidence needed to assess overfit.  
**Consequences:** Storage grows with experiments; experiment IDs are immutable.

## ADR-016 — Robustness gates before scalar ranking
**Context:** Pure CAGR/drawdown maximisation is easy to game.  
**Chosen approach:** Fixed hard gates + a versioned scalar rank for surviving candidates; always report underlying metrics.  
**Alternatives:** One unconstrained objective.  
**Reasoning:** Keeps annual budget and safety/reproducibility constraints non-negotiable.  
**Consequences:** Scoring profile is campaign-frozen and versioned. Exact default weights are an implementation assumption, not financial truth.

## ADR-017 — Prefer stable parameter regions over sharp optima
**Context:** A strategy that collapses with tiny parameter changes is likely overfit.  
**Chosen approach:** Canonical robustness suite includes neighbouring parameter perturbations and complexity reporting/penalty.  
**Alternatives:** Select absolute best historical parameter point.  
**Reasoning:** Robust plateaus are more credible for live use.  
**Consequences:** “Best score” alone is insufficient for release promotion.

## ADR-018 — Combined portfolio includes monetisation/reinvestment
**Context:** Tail-hedge value can arise from converting convex payoff into cash and buying depressed core assets.  
**Chosen approach:** Backtester explicitly models daily hedge monetisation and reinvestment.  
**Alternatives:** Evaluate option P&L separately; hold payout cash forever.  
**Reasoning:** Objective is long-run wealth/drawdown of the complete portfolio.  
**Consequences:** Reinvestment timing convention is part of campaign config/provenance.

## ADR-019 — SPX research benchmark, XSP preferred execution instrument initially
**Context:** SPX has deeper historical research availability; XSP is 1/10 the index level with a $100 multiplier and finer contract sizing.  
**Chosen approach:** Canonical research benchmark may be SPX; paper/live allowed underlying defaults to XSP.  
**Alternatives:** Research only XSP; execute SPX only; use SPY options.  
**Reasoning:** Separates policy research from personal portfolio sizing.  
**Consequences:** Must quantify basis/contract-liquidity differences and never assume SPX backtest equals XSP execution exactly.

## ADR-020 — Broker truth is authoritative before every executable action
**Context:** Local state may be stale after manual trades, fills, disconnects, or crashes.  
**Chosen approach:** Every paper/live-capable run fetches positions, open orders, cash, and recent executions before computing deltas.  
**Alternatives:** Continue from yesterday’s local state.  
**Reasoning:** Prevents duplicate/incorrect trades.  
**Consequences:** Broker unavailability blocks execution.

## ADR-021 — Limit orders only with bounded repricing
**Context:** Far-OTM options can have wide spreads; market orders can fill badly.  
**Chosen approach:** Limit orders with explicit maximum price and finite repricing attempts; never fallback to market.  
**Alternatives:** Market order for guaranteed completion.  
**Reasoning:** Missing a routine hedge adjustment is safer than paying unbounded spread.  
**Consequences:** Some intents will remain unfilled and be retried only on a new/reconciled decision.

## ADR-022 — Kill switch cancels orders but does not liquidate positions
**Context:** Emergency safety control should stop new actions without creating an unresearched forced liquidation.  
**Chosen approach:** Block new submissions; attempt cancellation of TailHedge-created open orders; leave positions intact.  
**Alternatives:** Immediately sell all options/core holdings.  
**Reasoning:** Automatic liquidation could worsen risk during stressed markets.  
**Consequences:** Owner may need separate manual broker action for emergency liquidation.

## ADR-023 — IB Gateway/TWS operational model is accepted, not bypassed
**Context:** IBKR currently requires supported GUI authentication and periodic re-authentication; TWS/IB Gateway can auto-restart during the week but not operate as a completely unsupported headless credential bypass.  
**Chosen approach:** Monitor authentication/connection health, notify owner, block execution when unavailable, reconcile after reconnect.  
**Alternatives:** Automate credential entry or unsupported login bypass.  
**Reasoning:** Security/supportability.  
**Consequences:** System is highly automated but not maintenance-free; owner periodically re-authenticates.

## ADR-024 — Default hedge-budget safety cap is 1.0% rolling 365 days
**Context:** A starting safety limit is required before user-specific research has chosen a budget.  
**Chosen approach:** 1.0% default cap, configurable downward/upward only within app absolute bounds and audit controls.  
**Alternatives:** No default cap; fixed currency amount.  
**Reasoning:** Percentage scales with portfolio and matches the project’s “controlled annual insurance spend” framing.  
**Consequences:** It is a software safety default, explicitly not an investment recommendation.

## ADR-025 — Historical fill fraction applies to the full quoted spread
**Context:** The implementation initially applied the spread fraction to the half-spread (mid + 12.5% of spread for the documented "25%" case), contradicting TECHNICAL_ARCHITECTURE.md §9 and FR-017 ("midpoint + 25% of spread") and making the 50% stress case equal to the documented live base case.  
**Chosen approach:** Align code to the documented convention: a spread fraction applies to the full ask-bid spread (base buy fill = mid + 0.25 × (ask − bid)); tick-rounded fills are clamped inside the quoted band so a buy never exceeds the ask (FR-017 cap). Golden-fixture expected ledgers use this same frozen fill profile.  
**Alternatives:** Keep the half-spread reading and document the backtest as more optimistic than live — rejected: backtests must not flatter live behaviour.  
**Reasoning:** Backtest base fills must be at least as conservative as the live limit-pricing convention, and the robustness ladder (midpoint/25%/50%/100%) must actually be worse than the base case.  
**Consequences:** Backtest results are slightly more conservative than the earlier implementation; all fixture hand calculations were recomputed accordingly.

## ADR-026 — Backtest ledger fails closed on malformed or infeasible input
**Context:** The accounting ledger previously accepted non-positive quantities (a negative-quantity buy was structurally identical to sell-to-open), negative prices/premiums, purchases beyond available cash (silent borrowing), and post-expiry settlement priced at a later underlying value.  
**Chosen approach:** The ledger validates quantity > 0, premium/price ≥ 0, cash sufficiency for purchases/reinvestments/costs, and settlement exactly on the expiry date; positions whose expiry was missed raise instead of being priced with current data. Units bought via reinvestment are tracked and independently conserved. Property-based tests recompute final cash independently of ledger internals.  
**Alternatives:** Leave validation to a higher engine layer — rejected: the ledger is the last line of defence for the "no sell-to-open / no borrowing" invariants.  
**Consequences:** Some flexible-but-unsafe usages now raise; the engine and strategy layers pass fill-model prices and charge commissions explicitly.

## ADR-027 — Portfolio exposure refuses mixed currencies without explicit FX input
**Context:** Exposure summation silently combined market values in different currencies, violating INV-010 ("never mix currencies without explicit FX input").  
**Chosen approach:** `calculate_portfolio_exposure` requires an `fx_to_base` mapping whenever any holding's currency differs from the portfolio base currency; missing rates for present currencies raise. Weighted average beta is weighted over *mapped* eligible value only so eligible-but-unmapped holdings cannot dilute it (they remain surfaced as warnings).  
**Reasoning:** Fail closed on ambiguous financial state; unmapped exposure must be visible, not absorbed into averages.  
**Consequences:** Callers with multi-currency books must supply explicit FX rates (GF-006-style input).
