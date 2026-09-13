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

## ADR-028 — Strategy context exposes only explicitly enabled features, enforced at the boundary
**Context:** FR-006 and TECHNICAL_ARCHITECTURE.md §8.1 require `StrategyContext` to contain only explicitly enabled features. The initial SDK declared a feature allowlist but did not enforce that disabled-feature data was absent; `underlying_close` was also always populated despite the `UNDERLYING_CLOSE` feature flag.  
**Chosen approach:** `StrategyContext` construction fails closed if data for a disabled feature is present (portfolio, positions, option chain, budget fields, and now an optional `underlying_close` gated by `UNDERLYING_CLOSE`). The evaluator entrypoint is the data-access boundary: it strips data for disabled features before building the context, and schema-validates the returned `TargetHedgePlan` (in addition to the prohibited-field check) before emitting result JSON.  
**Alternatives:** Rely on strategy code to call `require_feature` before access — rejected: untrusted code must not be trusted to honour conventions.  
**Reasoning:** The project prevents leakage at the data-access boundary, not by convention; the trusted builder must be unable to silently over-share.  
**Consequences:** Campaign feature configuration determines exactly what a candidate sees; misconfigured contexts raise at construction instead of leaking data. `StrategyContext.underlying_close` is now `float | None`.

## ADR-029 — Campaign manifest hash covers the full frozen config, canonical JSON encoding
**Context:** FR-007 requires that starting a campaign freezes and hashes dataset version, portfolio proxy, split scheme, scoring profile, cost model, feature allowlist, strategy bounds, agent config (minus credentials), and evaluator version; any change must create a new campaign rather than silently mutating prior results.  
**Chosen approach:** `research_campaign.campaign_manifest_sha256` is a SHA-256 over the canonical JSON encoding (sorted keys, compact separators) of all frozen config columns, including the dataset ID (dataset content is additionally pinned by the immutable dataset manifest hash per FR-002) and `annual_premium_cap`. The hash is computed only at `start`; DRAFT campaigns are freely editable. Updating a frozen field on a non-DRAFT campaign raises and the documented path is `POST /campaigns/{id}/clone`, which creates a new DRAFT campaign with `cloned_from_campaign_id` provenance and leaves the source and its results untouched. The evaluator OCI image digest is recorded at start when a container runtime is available; its absence (CI, no Docker) does not block start because the logical evaluator version remains part of the manifest.  
**Alternatives:** Hashing only a subset of fields; re-hashing on every read; mutating in place with revision numbers — rejected: any subset risks an unrecorded config change, and in-place mutation conflicts with "must not silently mutate prior results".  
**Reasoning:** One deterministic hash over everything that can change evaluation semantics makes hash verification (SB-002 step 5) a single comparison.  
**Consequences:** Agents/evaluators verify the manifest before every iteration; a changed config produces a different manifest and therefore a different campaign identity. The default scoring profile (TECHNICAL_ARCHITECTURE.md §10 weights) is implemented as versioned `ScoringProfile` configuration, an explicit implementation assumption per ADR-016/OQ-005.

Implementation notes (TASK-021 review hardening):
- `annual_premium_cap` is a first-class frozen field carried on `CampaignConfig` (default: the application safety cap, 1.0% per OQ-004/ADR-024), validated positive and within the cap at create/update/start, and included in the manifest hash. It is not embedded inside `split_config_json`/`portfolio_proxy_json`.
- The manifest hash is a unique identity (DATA_MODEL §4.1): starting a campaign whose manifest already exists on another campaign fails closed with `CONFIG_HASH_FAILED` (409) rather than a raw DB IntegrityError — e.g. the clone-unchanged-then-start flow.
- SB-002 "scoring/cost/robustness profiles are valid" is enforced at create/update/start: scoring JSON must rebuild a valid `ScoringProfile`; execution-cost JSON keys must be a subset of `backtest.fill_model.FillConfig` fields with numeric values in valid ranges; robustness JSON suite entries must be canonical case names (arbitrary ad-hoc cases rejected per API_SPEC §6).
- Secret rejection in `agent_config_redacted_json` is recursive (nested objects/lists included).
- Canonical JSON conversion is explicit (UUID → string, Decimal → float); non-serialisable values raise instead of being silently stringified.
- Documented deviations from DATA_MODEL §4.1: `campaign_manifest_sha256` is nullable until `start` (a DRAFT campaign has no manifest yet), and `created_by` is optional until an owner/auth linking exists. The DB `UNIQUE` constraint on the manifest plus the pre-commit collision check enforce identity; `annual_premium_cap` is stored as `float`/`FLOAT` (percentage precision, not currency).

## ADR-030 — Qualify a real SPX dataset before Autoresearch
**Context:** Generic importer, synthetic fixtures, and the controlled evaluator can pass while a vendor dataset still has ambiguous ticker/root semantics, incomplete snapshot coverage, side-misaligned Greeks, or missing expiry settlement values. The supplied ORATS sample is useful for format work but is not itself SPX evidence.  
**Chosen approach:** Add a real-dataset qualification gate before real-data campaign conclusions. ORATS is the first qualification target; it is not treated as the permanent historical source until SPX/SPXW coverage, timestamp and field semantics, settlement data, acquisition behaviour, licensing, and deterministic static-backtest checks pass.  
**Alternatives:** Start Autoresearch against the first parsed external file; select a vendor solely from advertised history, price, or request quota.  
**Reasoning:** Data provenance and semantic correctness are prerequisites for research validity. A parser success cannot establish that the data represents the intended instrument or executable historical observations.  
**Consequences:** `TASK-022` through `TASK-024` and `docs/DATASET_QUALIFICATION.md` are required before real-data Autoresearch is considered ready. Licensed data remains local and ignored; the sample does not enter repository history.  

## ADR-031 — ORATS Near End-of-day archive is the primary MVP source
**Context:** ORATS has confirmed that its Near End-of-day historical package covers the complete US equity-options universe, including SPX and SPXW, but the one-time package is limited to Strikes data and excludes closing prices and API-only indicators. The Data API adds request-limit, acquisition, subscription, and retention dependencies.  
**Chosen approach:** Use the Near End-of-day archive as the canonical MVP research source. Download the daily ZIP objects through a resumable, one-time S3 workflow, preserve their hashes locally, extract the SPX/SPXW subset into the vendor-neutral store, and use `spot_px` as the SPX cash underlying price. Treat the API as an optional pilot or supplement only.  
**Alternatives:** Use the API as the primary source; purchase broader API products; defer exact options research in favour of aggregate PPUT/VIX proxies.  
**Reasoning:** The archive provides a stable, content-addressable research input with full advertised history and avoids making reproducibility depend on an active API subscription. Strikes data contains the core quote/contract inputs required by the backtester; API-only indicators are not required MVP features.  
**Consequences:** `TASK-022` through `TASK-024` must qualify archive completeness, daily-object acquisition, timestamp inference, SPX-specific handling, Greek semantics, and expiry settlement availability. The 14-day S3 access window and monitored-download limit require a preflighted one-time acquisition; credentials never enter application state. Closing prices and portfolio total-return series must come from separate explicitly versioned data. No claim may use the Near EOD snapshot as a closing observation.  
