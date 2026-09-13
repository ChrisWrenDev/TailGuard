# TailHedge — API Specification

## 1. API conventions

Base path: `/api/v1`.

Transport: JSON over HTTPS in deployed environments; localhost HTTP permitted only in explicit development configuration.

Authentication: owner session cookie for browser/API in MVP. All endpoints except `/healthz`, `/readyz`, and login require authenticated `OWNER`.

Mutation requests require CSRF protection when authenticated by cookie.

Error envelope:

```json
{
  "error": {
    "code": "RISK_GATE_REJECTED",
    "message": "Order intent failed 2 risk checks.",
    "details": {},
    "correlation_id": "..."
  }
}
```

IDs are UUID strings. Timestamps are ISO 8601 with offsets/UTC.

Commands that can be retried accept/derive idempotency keys. Broker-facing operations never rely only on HTTP retry semantics; they reconcile broker state.

## 2. Health/auth

### `GET /healthz`
Process liveness only. No auth. Does not reveal account/data details.

Response: `{"status":"ok"}`.

### `GET /readyz`
Checks database connectivity and required local services. No broker trade action. No auth, but response is intentionally coarse.

### `POST /auth/login`
Owner login.

Body:
```json
{"username":"owner","password":"..."}
```

Errors: `AUTH_INVALID`, `AUTH_DISABLED`.

### `POST /auth/logout`
Authenticated. Revokes current session.

## 3. Portfolio

### `GET /portfolio`
**Purpose:** current logical portfolio configuration plus latest broker-derived values when available.  
**Requirements:** FR-001, FR-014.

Response shape:
```json
{
  "id":"...",
  "base_currency":"GBP",
  "valuation_ts":"...",
  "total_value":300000.00,
  "hedge_eligible_value":285000.00,
  "benchmark_equivalent_exposure":260000.00,
  "mapping_coverage_pct":0.97,
  "holdings":[...],
  "warnings":[]
}
```

### `POST /portfolio/holdings`
Create a manual holding definition and, when supplied, a current manual valuation entry.

Validation follows FR-001. A hedge-eligible non-cash holding requires benchmark and beta.

### `PUT /portfolio/holdings/{holding_id}`
Update configuration semantics for an existing holding. Current quantities/values are recorded through portfolio valuation snapshots rather than overwriting historical state.

Validation: FR-001 rules; hedge beta required for hedge-eligible non-cash holding.

Common errors: `VALIDATION_ERROR`, `HOLDING_NOT_FOUND`, `BENCHMARK_MAPPING_REQUIRED`.

### `POST /portfolio/broker-sync`
Creates an idempotent broker sync job. Does not place orders.

Response `202`:
```json
{"job_id":"...","status":"QUEUED"}
```

Errors: `BROKER_NOT_CONFIGURED`, `BROKER_AUTH_REQUIRED`.

## 4. Research datasets

### `POST /datasets/imports`
**Purpose:** register/upload/import files into a new immutable dataset revision.  
**Requirements:** FR-002, FR-003.

For large local files the API may accept server-local staged paths rather than multipart bytes; all paths must be under an allowlisted ingest directory.

Request:
```json
{
  "name":"SPX ORATS EOD 2007-2026",
  "source_vendor":"ORATS",
  "timezone":"America/New_York",
  "snapshot_time":"15:45:00",
  "files":["staged/file1.csv"],
  "mapping":{}
}
```

Response `202`: dataset ID + import job ID.

Errors: `FILE_OUTSIDE_INGEST_ROOT`, `UNSUPPORTED_SCHEMA`, `DATASET_DUPLICATE_MANIFEST`.

### `GET /datasets`
List datasets with generic health and provider-qualification state.

### `GET /datasets/{dataset_id}`
Dataset manifest and summary.

### `GET /datasets/{dataset_id}/health`
Validation results, fatal errors/warnings, coverage stats.

### `POST /datasets/{dataset_id}/validate`
Queues re-validation with current validator version. Does not mutate data.

### `GET /datasets/{dataset_id}/qualification`
Returns the provider-specific qualification status, profile version, report
artifact reference, fatal checks, warnings, coverage summary, and evidence
hashes. A generic `READY` validation state does not imply qualification `PASS`.

### `POST /datasets/{dataset_id}/qualify`
Queues the configured provider-specific qualification profile. The operation
does not mutate raw or canonical dataset content. A qualification failure
blocks the dataset from real-data campaign use until a new immutable result
passes.

## 5. Research campaigns

### `POST /campaigns`
**Requirements:** FR-007.

Creates `DRAFT` campaign.

Request includes dataset ID, proxy config, split config, scoring profile, execution-cost profile, robustness profile, feature allowlist, strategy bounds, agent provider, stop limits.

Validation:
- dataset must be `READY` or explicit warnings accepted;
- external datasets must also have a passing provider-specific qualification result;
- final holdout must not overlap train/validation;
- purge horizon must satisfy configured minimum;
- annual premium cap > 0 and within application safety configuration;
- allowed strategy bounds must be internally consistent.

### `POST /campaigns/{id}/start`
Freezes/hash campaign config, transitions to `RUNNING`, creates research job.

Errors: `CAMPAIGN_NOT_DRAFT`, `DATASET_NOT_READY`, `DATASET_NOT_QUALIFIED`, `CONFIG_HASH_FAILED`.

### `POST /campaigns/{id}/pause`
Requests cooperative pause after current experiment persists.

### `POST /campaigns/{id}/stop`
Stops future iterations; existing results remain.

### `GET /campaigns`
Filter: `status`, `dataset_id`, date range.

### `GET /campaigns/{id}`
Campaign config/status/summary. Immutable fields are marked as such.

### `GET /campaigns/{id}/experiments`
Pagination/filter/sort.  
Allowed sort fields: sequence, robust score, CAGR delta, drawdown improvement, premium spend, complexity, created time.

### `GET /experiments/{id}`
Full permitted experiment detail, excluding secret holdout data.

## 6. Robustness, release, holdout

### `POST /experiments/{id}/robustness-runs`
**Requirements:** FR-011.
Queues fixed robustness profile for candidate.

Request may select one of preconfigured profile IDs. It may not submit arbitrary ad-hoc tests under the guise of the canonical gate.

### `POST /strategy-releases`
**Requirements:** FR-012.

Request:
```json
{
  "experiment_id":"...",
  "name":"tailhedge-v1-candidate-01",
  "permitted_modes":["SHADOW","PAPER"],
  "override_failed_gate":false,
  "override_reason":null
}
```

Validation:
- candidate evaluation complete;
- canonical robustness run complete;
- if gate failed, explicit override reason and owner confirmation are required;
- live modes rejected in MVP.

### `GET /strategy-releases/{id}`
Returns provenance/evidence and holdout status.

### `POST /strategy-releases/{id}/holdout-run`
**Requirements:** FR-010, FR-012.

Consumes final holdout for this release/campaign evidence context.

Request:
```json
{"confirm_consume_holdout":true}
```

Errors: `HOLDOUT_ALREADY_CONSUMED`, `HOLDOUT_NOT_CONFIGURED`, `ROBUSTNESS_NOT_COMPLETE`.

The resulting holdout metrics are available to the owner after completion but are never included in agent feedback endpoints.

## 7. Daily operations

### `POST /daily-runs`
Manual trigger for a daily evaluation; scheduled runs use the same application service.

Request:
```json
{
  "strategy_release_id":"...",
  "mode":"SHADOW",
  "effective_time":null,
  "reason":"MANUAL_RUN"
}
```

Rules:
- `PAPER` requires configured paper broker account;
- live modes rejected in MVP;
- default `effective_time` is now; historical replay is a separate research operation, not this endpoint.

Response `202`: run/job ID.

### `GET /daily-runs`
Filter by date, mode, status, decision code, strategy release.

### `GET /daily-runs/{id}`
Returns broker snapshot refs, exposure calculation, target plan, risk checks, intents, order/fill states, final status.

### `POST /daily-runs/{id}/retry`
Allowed only for explicitly retryable pre-order stages. If any order may have been submitted, this endpoint queues **reconciliation**, not blind re-execution.

Errors: `RUN_NOT_RETRYABLE`, `RECONCILIATION_REQUIRED`.

## 8. Broker state

### `GET /broker/status`
Returns configured environment/account alias, connected/authenticated boolean, last sync, and coarse errors. No secrets/full account identifiers.

### `POST /broker/reconcile`
Queues full positions/open-orders/recent-executions reconciliation.

### `GET /broker/snapshots/{id}`
Owner-only redacted snapshot detail.

No generic `POST /broker/order` endpoint exists. Orders can only be produced through a validated daily-run workflow.

## 9. Orders

### `GET /orders`
Filter by run ID, status, symbol, date.

### `GET /orders/{id}`
Internal intent + broker attempts/fills.

### `POST /orders/{id}/cancel`
May cancel only an open TailHedge-owned broker order.

Validation:
- intent belongs to configured account;
- order status cancellable;
- cancellation is idempotent.

No endpoint permits arbitrary symbol/side/quantity order creation.

## 10. Risk controls and kill switch

### `GET /risk-config`
Returns active version and effective thresholds.

### `PUT /risk-config`
**Requirements:** FR-016, FR-023.
Creates a new immutable risk-config version.

Request example:
```json
{
  "annual_premium_cap_pct":0.01,
  "max_premium_per_order_gbp":1000,
  "max_premium_per_day_gbp":1500,
  "min_cash_buffer_gbp":2500,
  "allowed_underlyings":["XSP"],
  "max_overcoverage_ratio":1.15,
  "max_quote_age_seconds":15,
  "max_relative_spread":0.20
}
```

Validation must use application-level absolute maximums so an API caller cannot set nonsensical/infinite values.

### `GET /kill-switch`
Returns current state/reason/timestamp.

### `POST /kill-switch/engage`
Immediately engages; queues cancellation of TailHedge-owned open orders.

Body optional reason.

### `POST /kill-switch/disengage`
Requires explicit confirmation body and recent owner authentication where supported.

No automatic position liquidation occurs.

## 11. Jobs

### `GET /jobs/{id}`
Status/progress for imports, campaigns, robustness, holdout, broker sync, daily run.

Response:
```json
{
  "id":"...",
  "type":"RESEARCH_CAMPAIGN",
  "status":"RUNNING",
  "progress":{"completed":143,"target":500},
  "last_checkpoint_at":"...",
  "error":null
}
```

## 12. Audit

### `GET /audit-events`
Filters: date range, severity, type, entity type/id, correlation ID.

Audit events are read-only through API.

## 13. Internal interfaces

These are Python interfaces, not public HTTP endpoints.

### `BrokerAdapter`

```text
status()
get_account_snapshot()
get_positions()
get_open_orders()
get_recent_executions(since)
resolve_contract(query)
get_option_chain(underlying, expirations/range)
get_quotes(contract_ids)
place_limit_order(order_request)
modify_limit_order(order_ref, new_price)
cancel_order(order_ref)
```

### `AgentProvider`

```text
propose_candidate(AgentResearchRequest) -> AgentCandidateResponse
```

The request explicitly excludes final-holdout metrics/data and secrets.

### `StrategyRuntime`

```text
evaluate(strategy_release_or_source, StrategyContext) -> TargetHedgePlan
```

Runtime response is schema-validated JSON. Exceptions/timeouts mean no trade.

### `RiskGate`

```text
evaluate(
  target_plan,
  portfolio_state,
  broker_state,
  current_quotes,
  rolling_spend,
  risk_config
) -> RiskDecision
```

Pure deterministic function; no AI/network calls.

## 14. Representative reason/error codes

```text
BROKER_AUTH_REQUIRED
BROKER_STATE_INCOMPLETE
BROKER_ENVIRONMENT_MISMATCH
DATASET_NOT_READY
DATASET_NOT_QUALIFIED
DATA_VALIDATION_FAILED
STRATEGY_TIMEOUT
STRATEGY_OUTPUT_INVALID
NO_ELIGIBLE_CONTRACT
QUOTE_STALE
QUOTE_INVALID
SPREAD_TOO_WIDE
INSUFFICIENT_CASH
ANNUAL_BUDGET_EXHAUSTED
PER_ORDER_LIMIT_EXCEEDED
OVER_COVERAGE_LIMIT
KILL_SWITCH_ENGAGED
RISK_GATE_REJECTED
ORDER_REJECTED
ORDER_STATE_UNKNOWN
RECONCILIATION_REQUIRED
HOLDOUT_ALREADY_CONSUMED
LIVE_MODE_DISABLED
```

Reason codes are stable API contracts; human-readable messages may evolve.
