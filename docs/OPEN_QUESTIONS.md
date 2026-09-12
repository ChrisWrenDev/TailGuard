# TailHedge — Open Questions

## Blocking questions

**None for repository foundation and synthetic-data MVP.**

The coding agent should proceed with the documented defaults. Some external choices become blocking only when the implementation reaches their integration phase.

## Non-blocking questions

### OQ-001 — Which historical options-data vendor/file format will be used first?
**Why it matters:** determines the first vendor-specific importer and available fields/history.  
**Affects:** TASK-015/TASK-016, campaign coverage.  
**Recommended default:** implement canonical CSV/Parquet importer first; add ORATS adapter if the owner obtains ORATS data, otherwise Cboe DataShop adapter. Do not block core engine on vendor selection.

### OQ-002 — What is the exact real portfolio and benchmark mapping?
**Why it matters:** basis risk and hedge sizing depend on holdings and beta to SPX.  
**Affects:** FR-001, live/shadow exposure.  
**Recommended default:** develop with a configurable broad-equity proxy and beta=1.0 synthetic example. Require explicit mapping before any paper execution based on real holdings.

### OQ-003 — Will the core investments ultimately remain at Vanguard or move to IBKR?
**Why it matters:** if held elsewhere, TailHedge needs a manual/imported portfolio value rather than broker-truth holdings; if moved to IBKR, one broker snapshot can drive both core and hedge state.  
**Affects:** portfolio sync architecture, not the research engine.  
**Recommended default:** support IBKR as the authoritative live portfolio for MVP paper/shadow integration while retaining manual portfolio definitions for research. Do not automate asset transfer.

### OQ-004 — What annual hedge budget should research treat as the owner’s preferred ceiling?
**Why it matters:** changes feasible strategies and annual bleed.  
**Affects:** campaign config, risk config.  
**Recommended default:** application safety cap 1.0%; research campaigns explicitly test 0.25%, 0.5%, 0.75%, and 1.0% as separate/frozen configurations rather than letting the agent change the cap opportunistically.

### OQ-005 — Is the default scalar research score appropriate?
**Why it matters:** Autoresearch retention depends on a scalar even though evidence is multi-objective.  
**Affects:** ADR-016, campaign scoring.  
**Recommended default:** implement the documented versioned score, always show underlying metrics, and make score profile selectable only before campaign start. Treat later score changes as new campaigns.

### OQ-006 — Which statistical multiple-testing measures should be included in MVP reports?
**Why it matters:** PBO/Deflated Sharpe/SPA can add evidence but require careful assumptions and may distract from stronger process controls.  
**Affects:** FR-011 reporting.  
**Recommended default:** MVP records complete experiment history and implements blocked OOS/holdout/robustness first. Add Deflated Sharpe and/or PBO only after return-series conventions and research campaign structure are stable.

### OQ-007 — Which external AI/coding agent will drive Autoresearch?
**Why it matters:** authentication, prompt/response format, cost limits.  
**Affects:** TASK-022.  
**Recommended default:** use `LocalCommandAgentProvider` contract so any agent can be wrapped. Use `ManualAgentProvider` in CI.

### OQ-008 — What notification channel should be used?
**Why it matters:** broker-auth failures and manual-review states need attention.  
**Affects:** FR-022/TASK-037.  
**Recommended default:** in-app + structured log first; add email or another owner-selected provider through adapter without changing domain behaviour.

### OQ-009 — Where will the private production instance run?
**Why it matters:** TWS/IB Gateway GUI authentication, disk encryption, backup, remote access.  
**Affects:** deployment/runbook.  
**Recommended default:** owner-controlled Linux desktop/mini-PC/VM with GUI access for IB Gateway authentication, encrypted disk, private LAN/VPN, no public web exposure.

### OQ-010 — Should early-close days run at a different time?
**Why it matters:** fixed 15:45 ET may occur after market close on shortened sessions.  
**Affects:** FR-013 scheduler.  
**Recommended default:** skip ordinary scheduled execution on early-close days in MVP and record `MARKET_CLOSED_AT_DECISION_TIME`. Research/live timing remains aligned. Revisit only if this omission is material.

### OQ-011 — What quote freshness/spread thresholds are suitable for XSP?
**Why it matters:** hard values affect fill frequency and safety.  
**Affects:** FR-015–FR-017.  
**Recommended default:** implement configurable thresholds with conservative initial values (`max_quote_age_seconds=15`, `max_relative_spread=0.20`) and treat them as software defaults to be validated during paper operation, not financial recommendations.

### OQ-012 — What monetary per-order/day caps should paper/live use?
**Why it matters:** risk gate requires absolute limits in addition to annual percentage budget.  
**Affects:** FR-016.  
**Recommended default:** development/test values use low synthetic amounts. Before real paper operation with the owner’s account, require explicit owner configuration; do not derive a large currency cap automatically from account size.

### OQ-013 — How should FX be sourced in live and historical calculations?
**Why it matters:** GBP investor / USD option premiums and payouts.  
**Affects:** FR-004, FR-011, FR-016.  
**Recommended default:** define `FxRateProvider` interface; historical campaigns require a versioned daily GBP/USD series; live paper uses broker/current market FX snapshot where available and stores timestamp/source.

### OQ-014 — Exact portfolio return series for Vanguard holdings
**Why it matters:** adjusted close, NAV, or total-return series can materially change long-run results.  
**Affects:** research portfolio proxy.  
**Recommended default:** use total-return data where legally/technically available; otherwise adjusted close with explicit limitation in campaign manifest.

### OQ-015 — Which crisis/regime labels are canonical?
**Why it matters:** leave-one-regime-out tests need ranges chosen before evaluating a candidate.  
**Affects:** FR-011.  
**Recommended default:** store versioned regime definitions in robustness profile and select them based on market chronology before campaign results are reviewed; do not let agent create/remove regimes.

### OQ-016 — Should XSP or SPX be allowed in paper mode first?
**Why it matters:** contract size/liquidity and research-to-execution transfer.  
**Affects:** FR-016.  
**Recommended default:** XSP only initially; SPX remains research benchmark and can be enabled later by explicit risk configuration after paper evidence.

### OQ-017 — Exact strategy complexity metric
**Why it matters:** complexity penalty should discourage brittle code without rewarding obfuscation.  
**Affects:** scoring/robustness.  
**Recommended default:** count declared free parameters and AST conditional branches, cap source size, and report complexity. Keep penalty small; rely primarily on perturbation/out-of-sample stability.

### OQ-018 — What constitutes sufficient paper/shadow evidence before considering live approval mode?
**Why it matters:** future go/no-go.  
**Affects:** FR-024 only; not MVP coding.  
**Recommended default:** do not encode a time-based automatic unlock. Live mode requires a separate explicit product/security decision regardless of elapsed time.

### OQ-019 — UK tax/wrapper/account structure
**Why it matters:** where assets/options can legally/tax-efficiently sit and how gains are treated.  
**Affects:** owner’s account setup, not core software calculations unless tax modelling is later added.  
**Recommended default:** software remains tax-agnostic; owner obtains appropriate professional guidance. Do not implement tax advice/automation in MVP.

### OQ-020 — Backtest budget-cap semantics for the mechanical baseline
**Why it matters:** the fixed-put (PPUT-like) baseline enforces a budget; whether the cap applies to gross premium entries or *net* option outlay (buys minus sale/settlement proceeds) changes how often rolls are permitted.  
**Affects:** TASK-013 backtest baseline, FR-016 risk-gate configuration later.  
**Recommended default:** net option outlay per rolling year (buys − sale/settlement proceeds) against `budget_pct × portfolio value`, as implemented in `FixedPutPolicy`; rolls that would breach the allowance are skipped and the position rides to expiry. The live risk gate (TASK-032) may choose a stricter reading.
