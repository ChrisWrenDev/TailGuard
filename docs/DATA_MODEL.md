# TailHedge — Data Model

## 1. Modelling principles

1. Operational/account/audit state belongs in PostgreSQL.
2. Large historical market data belongs in immutable Parquet datasets with manifests stored in PostgreSQL.
3. Financial actions are append-oriented. Do not hard-delete orders, fills, daily runs, experiments, releases, risk events, or audit events.
4. Every research result must identify the exact data/evaluator/strategy/config versions that produced it.
5. Every broker action must identify the daily run and risk decision that authorized it.
6. External account IDs are treated as sensitive and displayed through aliases/masked values.

Types below are logical/PostgreSQL-oriented. IDs are UUID unless stated otherwise.

## 2. Core operational entities

### 2.1 `app_user`
Single-owner authentication record.

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| username | text | yes | unique |
| password_hash | text | yes | Argon2id |
| role | text | yes | fixed `OWNER` in MVP |
| is_active | boolean | yes | default true |
| created_at | timestamptz | yes | |
| updated_at | timestamptz | yes | |

Constraint: MVP seed/setup permits only one active `OWNER` unless product scope changes.

### 2.2 `portfolio`

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| name | text | yes | |
| base_currency | char(3) | yes | default `GBP` assumption |
| status | text | yes | `ACTIVE`, `ARCHIVED` |
| created_at | timestamptz | yes | |
| updated_at | timestamptz | yes | |

Partial unique index: only one `ACTIVE` portfolio in MVP.

### 2.3 `holding_definition`
Configuration describing how a holding is treated for hedge exposure.

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| portfolio_id | uuid | yes | FK portfolio |
| instrument_key | text | yes | canonical symbol/ISIN/conid reference |
| display_name | text | yes | |
| source | text | yes | `MANUAL`, `IBKR` |
| currency | char(3) | yes | |
| asset_class | text | yes | `EQUITY`, `FUND`, `ETF`, `CASH`, `OTHER` |
| hedge_eligible | boolean | yes | |
| hedge_benchmark | text | no | initially `SPX`; required if eligible |
| hedge_beta | numeric(12,6) | no | required if eligible |
| archived_at | timestamptz | no | soft-delete |
| created_at | timestamptz | yes | |
| updated_at | timestamptz | yes | |

Unique active key: `(portfolio_id, instrument_key)` where `archived_at is null`.

### 2.4 `portfolio_valuation_snapshot`
Represents the logical portfolio at a point in time, regardless of whether values came from manual input or a broker sync.

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| portfolio_id | uuid | yes | FK portfolio |
| captured_at | timestamptz | yes | |
| source | text | yes | `MANUAL`, `IBKR`, `RESEARCH_PROXY` |
| base_currency | char(3) | yes | |
| total_value | numeric | yes | |
| cash_value | numeric | no | base-currency value if known |
| source_ref | text | no | e.g. broker snapshot ID/import reference |
| created_at | timestamptz | yes | |

Index: `(portfolio_id, captured_at desc)`.

### 2.5 `portfolio_position_snapshot`

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| portfolio_valuation_snapshot_id | uuid | yes | FK |
| holding_definition_id | uuid | no | null only for newly discovered/unmapped position |
| instrument_key | text | yes | |
| quantity | numeric | no | optional for value-only manual entries |
| local_market_price | numeric | no | |
| local_market_value | numeric | yes | position currency |
| currency | char(3) | yes | |
| fx_to_base | numeric | yes | explicit conversion used |
| base_market_value | numeric | yes | |
| benchmark_equivalent_exposure | numeric | no | null if not hedge eligible/mapped |

Unique `(portfolio_valuation_snapshot_id, instrument_key)`.

A broker sync may populate both a `broker_snapshot` (broker evidence) and a derived `portfolio_valuation_snapshot` (application valuation/exposure view). Manual research/live configurations can create a portfolio valuation snapshot without a broker snapshot.

### 2.6 `broker_account`

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| broker | text | yes | `IBKR` |
| environment | text | yes | `PAPER`; `LIVE` future |
| account_alias | text | yes | user-friendly unique alias |
| external_account_ref_encrypted | bytea/text | yes | encrypted or secret-backed, never plain display |
| enabled | boolean | yes | |
| created_at | timestamptz | yes | |
| updated_at | timestamptz | yes | |

Unique `(broker, environment, account_alias)`.

### 2.7 `broker_snapshot`
Immutable snapshot created during reconciliation.

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| broker_account_id | uuid | yes | FK |
| captured_at | timestamptz | yes | |
| base_currency | char(3) | yes | |
| net_liquidation_value | numeric | no | broker-provided |
| available_funds | numeric | no | |
| cash_json | jsonb | yes | currency balances |
| raw_summary_redacted | jsonb | no | no secrets |
| source_status | text | yes | `COMPLETE`, `PARTIAL`, `FAILED` |
| created_at | timestamptz | yes | |

Index: `(broker_account_id, captured_at desc)`.

### 2.8 `broker_position_snapshot`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| broker_snapshot_id | uuid | yes |
| instrument_key | text | yes |
| symbol | text | yes |
| sec_type | text | yes |
| currency | char(3) | yes |
| quantity | numeric | yes |
| market_price | numeric | no |
| market_value | numeric | no |
| average_cost | numeric | no |
| contract_json_redacted | jsonb | no |

Index `(broker_snapshot_id, instrument_key)`.

## 3. Historical dataset entities

### 3.1 `research_dataset`

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| name | text | yes | unique user-facing name |
| source_vendor | text | yes | `CBOE`, `ORATS`, `CUSTOM`, etc. |
| schema_version | text | yes | canonical schema |
| timezone | text | yes | e.g. `America/New_York` |
| default_snapshot_time | time | no | e.g. 15:45 |
| start_date | date | yes | |
| end_date | date | yes | |
| row_count | bigint | yes | |
| manifest_sha256 | char(64) | yes | unique immutable identity |
| storage_uri | text | yes | local path/object URI, not public URL |
| status | text | yes | `INGESTING`, `VALIDATING`, `READY`, `BLOCKED`, `ARCHIVED` |
| qualification_status | text | yes | `NOT_REQUIRED`, `PENDING`, `PASSED`, `FAILED` |
| qualification_report_uri | text | no | provider-specific report artifact |
| qualification_version | text | no | qualification rules/profile version |
| created_at | timestamptz | yes | |

Unique `manifest_sha256`.

### 3.2 `dataset_file`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| dataset_id | uuid | yes |
| relative_path | text | yes |
| sha256 | char(64) | yes |
| byte_size | bigint | yes |
| row_count | bigint | no |
| source_role | text | yes | `RAW_ARCHIVE`, `CANONICAL_OPTIONS`, `EXPIRY_SETTLEMENT`, or other explicit artifact role |

Unique `(dataset_id, relative_path)`.

For a bulk daily archive, each retained source ZIP is a `RAW_ARCHIVE` file.
Filtered canonical Parquet and expiry-settlement artifacts are separate file
records linked to the same dataset and to the source hashes recorded in the
qualification report.

### 3.3 `dataset_validation_result`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| dataset_id | uuid | yes |
| validator_version | text | yes |
| status | text | yes | `PASS`, `WARN`, `FAIL` |
| summary_json | jsonb | yes |
| report_artifact_uri | text | no |
| created_at | timestamptz | yes |

### 3.4 `dataset_qualification_result`

Provider-specific qualification is append-oriented and is distinct from the
generic validation report. A dataset may have multiple qualification attempts
under different qualification-profile versions, but only a `PASSED` result may
authorize real-data campaign use.

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| dataset_id | uuid | yes |
| qualification_version | text | yes |
| status | text | yes | `PASS`, `WARN`, `FAIL` |
| summary_json | jsonb | yes |
| report_artifact_uri | text | no |
| created_at | timestamptz | yes |

### 3.5 Canonical option Parquet schema

Required columns:

```text
snapshot_ts_utc          timestamp[us, UTC]
trade_date               date
source                   string
underlying_symbol        string
root_symbol              string
expiration_date          date
strike                    decimal/float
option_type               enum(PUT,CALL)
bid                       float
ask                       float
bid_size                  nullable int
ask_size                  nullable int
volume                    nullable int
open_interest             nullable int
underlying_price          float
implied_volatility        nullable float
delta                     nullable float
gamma                     nullable float
theta                     nullable float
vega                      nullable float
source_contract_id        nullable string
```

For the real SPX qualification slice (`TASK-022` through `TASK-024`), the canonical schema also
requires the following contract semantics. These must be mapped from verified
source metadata rather than assumed from a ticker string:

```text
expiration_type           enum(STANDARD,WEEKLY,OTHER)
contract_multiplier       int
settlement_type           enum(CASH)
exercise_style            enum(EUROPEAN)
settlement_style          enum(AM,PM,UNKNOWN)
currency                  string
dte_calendar              int16          # derived from expiration - trade date
```

`root_symbol` must preserve distinct roots such as `SPX` and `SPXW`. A paired
vendor row must produce separate call and put rows. Vendor Greeks may only be
copied to a canonical side after their side and sign conventions are verified.
The real-dataset qualification rules are defined in
`docs/DATASET_QUALIFICATION.md`.

Canonical uniqueness within a dataset:
`(snapshot_ts_utc, root_symbol, expiration_date, strike, option_type)`.

Derived analytics are stored in separate derived Parquet artifacts keyed by dataset + transform version; do not rewrite canonical source columns.

### 3.6 Option expiry settlement artifact

Expiry settlement values are stored separately from ordinary quotes:

```text
root_symbol               string
expiration_date           date
settlement_ts_utc         timestamp[us, UTC]
settlement_style          enum(AM,PM)
settlement_value          float
settlement_type           enum(CASH)
source                    string
```

An evaluator may not substitute the last quote or an underlying close when a
required official settlement value is absent. It must exclude the affected
expiry trade or fail closed under the campaign policy.

### 3.7 Canonical underlying/portfolio series Parquet

```text
timestamp_utc             timestamp[us, UTC]
trade_date                date
symbol                    string
currency                  string
open                      nullable float
high                      nullable float
low                       nullable float
close                     float
adjusted_close            nullable float
total_return_index        nullable float
source                    string
```

The backtest configuration declares whether `close`, adjusted close, or total-return series is authoritative for core-portfolio returns.

## 4. Research entities

### 4.1 `research_campaign`

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| name | text | yes | |
| dataset_id | uuid | yes | FK |
| portfolio_proxy_json | jsonb | yes | immutable after start |
| split_config_json | jsonb | yes | immutable |
| scoring_profile_json | jsonb | yes | immutable |
| execution_cost_profile_json | jsonb | yes | immutable |
| robustness_profile_json | jsonb | yes | immutable |
| feature_allowlist_json | jsonb | yes | immutable |
| strategy_bounds_json | jsonb | yes | immutable |
| agent_config_redacted_json | jsonb | yes | no secret |
| evaluator_version | text | yes | code/image digest |
| campaign_manifest_sha256 | char(64) | yes | unique identity |
| status | text | yes | `DRAFT`, `RUNNING`, `PAUSED`, `STOPPED`, `COMPLETED`, `FAILED` |
| max_iterations | int | no | |
| created_by | uuid | yes | owner |
| created_at | timestamptz | yes | |
| started_at | timestamptz | no | |
| ended_at | timestamptz | no | |

After `RUNNING`, immutable config columns may not be updated; changing them clones a campaign.

### 4.2 `experiment_run`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| campaign_id | uuid | yes |
| sequence_no | int | yes |
| parent_experiment_id | uuid | no |
| strategy_sha256 | char(64) | yes |
| strategy_artifact_uri | text | yes |
| agent_rationale | text | no |
| status | text | yes | `QUEUED`, `RUNNING`, `PASSED`, `REJECTED`, `ERROR`, `TIMEOUT` |
| robust_score | numeric | no |
| metrics_json | jsonb | no |
| fold_metrics_json | jsonb | no |
| complexity_json | jsonb | no |
| error_code | text | no |
| error_detail_redacted | text | no |
| selected_as_parent | boolean | yes | default false |
| started_at | timestamptz | no |
| ended_at | timestamptz | no |
| created_at | timestamptz | yes |

Unique `(campaign_id, sequence_no)`.
Index `(campaign_id, robust_score desc)` where status=`PASSED`.

### 4.3 `robustness_run`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| experiment_id | uuid | yes |
| profile_version | text | yes |
| status | text | yes |
| results_json | jsonb | yes |
| artifact_uri | text | no |
| passed_gate | boolean | yes |
| created_at | timestamptz | yes |

### 4.4 `strategy_release`

| Field | Type | Required | Notes |
|---|---|---:|---|
| id | uuid | yes | PK |
| name | text | yes | unique version label |
| source_experiment_id | uuid | yes | FK |
| strategy_sha256 | char(64) | yes | |
| strategy_artifact_uri | text | yes | immutable |
| evaluator_version | text | yes | |
| evidence_summary_json | jsonb | yes | |
| robustness_run_id | uuid | no | |
| holdout_status | text | yes | `UNTOUCHED`, `RUNNING`, `CONSUMED`, `NOT_CONFIGURED` |
| holdout_result_json | jsonb | no | never returned to research agent |
| permitted_modes | text[] | yes | MVP max `SHADOW`,`PAPER` |
| status | text | yes | `FROZEN`, `RETIRED` |
| created_by | uuid | yes | |
| created_at | timestamptz | yes | |
| retired_at | timestamptz | no | |

A release is immutable; any strategy/source change creates a new release.

## 5. Daily operations entities

### 5.1 `daily_run`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| run_key | text | yes | unique idempotency key |
| scheduled_for | timestamptz | yes |
| started_at | timestamptz | no |
| ended_at | timestamptz | no |
| mode | text | yes |
| strategy_release_id | uuid | yes |
| broker_account_id | uuid | no | absent in research-only |
| pretrade_broker_snapshot_id | uuid | no |
| posttrade_broker_snapshot_id | uuid | no |
| status | text | yes | see below |
| decision_code | text | no |
| decision_summary_json | jsonb | no |
| error_code | text | no |
| created_at | timestamptz | yes |

Statuses: `QUEUED`, `RUNNING`, `NO_ACTION`, `SHADOW_COMPLETE`, `EXECUTING`, `COMPLETE`, `BLOCKED`, `FAILED`, `MANUAL_REVIEW_REQUIRED`.

Unique `run_key`.

Recommended `run_key`:
`<broker_account_or_portfolio>:<decision_local_date>:<decision_time>:<strategy_release_id>:<mode>`.

### 5.2 `target_hedge_plan`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| daily_run_id | uuid | yes |
| schema_version | text | yes |
| strategy_sha256 | char(64) | yes |
| context_sha256 | char(64) | yes |
| plan_json | jsonb | yes |
| created_at | timestamptz | yes |

One authoritative plan per daily-run revision.

### 5.3 `risk_decision`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| daily_run_id | uuid | yes |
| risk_policy_version | text | yes |
| passed | boolean | yes |
| checks_json | jsonb | yes |
| created_at | timestamptz | yes |

`checks_json` contains every check, observed value, threshold, result, and reason code.

### 5.4 `order_intent`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| daily_run_id | uuid | yes |
| idempotency_key | char(64) | yes | unique |
| broker_account_id | uuid | yes |
| instrument_key | text | yes |
| symbol | text | yes |
| expiration_date | date | yes |
| strike | numeric | yes |
| option_type | text | yes | must `PUT` in MVP |
| side | text | yes | `BUY`, `SELL_TO_CLOSE` |
| quantity | int | yes |
| reference_bid | numeric | yes |
| reference_ask | numeric | yes |
| reference_ts | timestamptz | yes |
| max_limit_price | numeric | no |
| currency | char(3) | yes |
| status | text | yes |
| risk_decision_id | uuid | yes |
| created_at | timestamptz | yes |
| updated_at | timestamptz | yes |

Constraint: quantity > 0; option_type=`PUT`; `SELL_TO_CLOSE` requires owned position mapping.

### 5.5 `broker_order`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| order_intent_id | uuid | yes |
| broker_order_ref | text | yes |
| broker_order_id | text | no |
| attempt_no | int | yes |
| order_type | text | yes | `LMT` only MVP |
| limit_price | numeric | yes |
| quantity | int | yes |
| status | text | yes |
| submitted_at | timestamptz | no |
| last_status_at | timestamptz | no |
| raw_status_redacted | jsonb | no |

Unique `(order_intent_id, attempt_no)`; index broker refs.

### 5.6 `broker_fill`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| broker_order_id | uuid | yes |
| broker_execution_ref | text | yes | unique |
| fill_ts | timestamptz | yes |
| quantity | int | yes |
| price | numeric | yes |
| commission | numeric | no |
| currency | char(3) | yes |

No soft delete.

## 6. Safety/audit entities

### 6.1 `risk_configuration`
Versioned settings, never updated in place once used.

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| version | int | yes |
| config_json | jsonb | yes |
| config_sha256 | char(64) | yes |
| active_from | timestamptz | yes |
| active_until | timestamptz | no |
| changed_by | uuid | yes |
| change_reason | text | no |
| created_at | timestamptz | yes |

Exactly one active row.

### 6.2 `kill_switch_state`
Keep current state plus audit events.

| Field | Type | Required |
|---|---|---:|
| singleton_key | text | yes | PK = `GLOBAL` |
| engaged | boolean | yes |
| changed_by | uuid | yes |
| changed_at | timestamptz | yes |
| reason | text | no |

### 6.3 `audit_event`

| Field | Type | Required |
|---|---|---:|
| id | uuid | yes |
| occurred_at | timestamptz | yes |
| actor_type | text | yes | `OWNER`, `SYSTEM`, `AGENT`, `BROKER` |
| actor_ref | text | no |
| event_type | text | yes |
| severity | text | yes |
| correlation_id | text | no |
| entity_type | text | no |
| entity_id | uuid | no |
| summary | text | yes |
| details_redacted_json | jsonb | no |

Index `(occurred_at desc)`, `(entity_type, entity_id)`, `(event_type, occurred_at desc)`.

### 6.4 `job` / `job_attempt`
Durable background work queue.

`job`: id, type, payload_json, unique_key nullable, status, priority, run_after, lease_owner, lease_expires_at, attempts, max_attempts, created_at, updated_at.

Unique partial index on `unique_key` for active/completed idempotent jobs as appropriate.

`job_attempt`: job_id, attempt_no, started_at, ended_at, status, error_code, error_detail_redacted.

## 7. Relationships

```text
portfolio 1 ── * holding_definition
portfolio 1 ── * portfolio_valuation_snapshot 1 ── * portfolio_position_snapshot
broker_account 1 ── * broker_snapshot 1 ── * broker_position_snapshot
research_dataset 1 ── * research_campaign 1 ── * experiment_run
research_dataset 1 ── * dataset_qualification_result
experiment_run 1 ── * robustness_run
experiment_run 1 ── * strategy_release
strategy_release 1 ── * daily_run
broker_account 1 ── * daily_run
daily_run 1 ── 1 target_hedge_plan
daily_run 1 ── * risk_decision
daily_run 1 ── * order_intent 1 ── * broker_order 1 ── * broker_fill
```

## 8. Important invariants

### INV-001 — Research provenance
An `experiment_run` may not exist without an immutable campaign manifest and exact strategy hash.

### INV-002 — No holdout feedback leakage
`holdout_result_json` is accessible only through release/owner holdout endpoints, never research-agent prompt construction.

### INV-003 — Release immutability
A `strategy_release` is content-addressed/frozen. Change means new release ID.

### INV-004 — Broker truth before execution
Every paper/live `order_intent` references a `daily_run` with a complete pre-trade broker snapshot.

### INV-005 — Risk decision before order
Every `order_intent` references a passing `risk_decision` whose policy version and inputs are persisted.

### INV-006 — Long puts only
MVP order intents are only `BUY PUT` or `SELL_TO_CLOSE PUT`. A sell quantity cannot exceed verified owned TailHedge-manageable long quantity after accounting for open sell orders.

### INV-007 — No duplicate order intent
`order_intent.idempotency_key` is globally unique.

### INV-008 — Audit append-only
Audit events are never edited/deleted through application features.

### INV-009 — Dataset immutability
Research dataset content referenced by a campaign is immutable. Corrections create a new manifest/dataset revision.

### INV-010 — Money/currency explicit
No arithmetic combines values in different currencies without an explicit FX rate/source/timestamp.

### INV-011 — Real-data qualification before campaign use
A campaign using an external dataset must reference a dataset with a passing
provider-specific qualification result for the selected qualification profile.
Generic ingestion validation alone is insufficient.

## 9. Soft deletion strategy

Soft/archive only:
- portfolio/holding definitions;
- datasets after they are no longer active;
- retired strategy releases;
- broker-account configurations.

Never soft/hard delete as normal product behaviour:
- experiment runs;
- robustness/holdout results;
- daily runs;
- risk decisions;
- order intents/orders/fills;
- audit events.

Data deletion required for privacy/retention should be an explicit maintenance operation preserving the minimum audit references allowed/required by policy; see `SECURITY_AND_PRIVACY.md`.
