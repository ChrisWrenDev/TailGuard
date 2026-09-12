# TailHedge — System Behaviours

This document defines cross-component workflows. Each workflow names trigger, preconditions, sequence, data changes, external calls, failure behaviour, idempotency, and final state.

## SB-001 — Historical dataset import and validation

**Trigger:** Owner submits a dataset import.

**Preconditions**
- Authenticated owner.
- Files are under configured ingest root or accepted upload location.
- Source/vendor mapping is known or explicitly configured.

**Sequence**
1. API creates `research_dataset` in `INGESTING` and a durable import job.
2. Worker hashes raw files and records `dataset_file` rows.
3. Importer maps source columns into canonical option/underlying schemas.
4. Normalised Parquet is written to a new immutable dataset directory.
5. Worker creates manifest with schema version, rows, date range, hashes, timezone, snapshot metadata.
6. Validator runs mandatory invariant checks.
7. Validation report is persisted.
8. Dataset becomes `READY` (possibly warnings) or `BLOCKED`.

**Data changes**
`research_dataset`, `dataset_file`, `dataset_validation_result`, Parquet files, manifest artifact, audit events.

**External calls**
None required if files are local. Vendor API download is an optional adapter, not part of this core workflow.

**Failure behaviour**
- Partial normalised output remains quarantined and is never marked `READY`.
- Retry may resume/restart from immutable raw files.
- Hash mismatch after initial registration is fatal.

**Idempotency**
Same source files + mapping + schema version produce same manifest hash. Duplicate manifest registration returns existing dataset or explicit duplicate response; it does not create silently divergent data.

**Final state**
`READY` or `BLOCKED`, with complete health report.

---

## SB-002 — Start and run an Autoresearch campaign

**Trigger:** Owner starts a `DRAFT` campaign.

**Preconditions**
- Dataset is `READY`.
- Campaign splits do not overlap.
- Final holdout is configured or explicitly absent.
- Scoring/cost/robustness profiles are valid.
- Agent provider is configured.

**Sequence**
1. Freeze campaign config and compute campaign manifest hash.
2. Store evaluator image/code digest.
3. Transition campaign to `RUNNING` and queue campaign job.
4. For each iteration:
   1. Load current parent candidate and permitted prior feedback.
   2. Construct agent request excluding final-holdout data/metrics and secrets.
   3. Agent provider returns candidate source + optional rationale.
   4. Validate response size/schema and compute strategy hash.
   5. Verify immutable campaign/evaluator hashes.
   6. Run candidate in isolated evaluator container against train/validation folds.
   7. Persist experiment status/metrics/errors.
   8. Apply fixed gates and scalar ranking profile.
   9. Select/reject candidate according to campaign search policy.
   10. Persist checkpoint before next iteration.
5. Stop on user request, iteration/resource limit, unrecoverable error, or campaign completion.

**Data changes**
`research_campaign`, `experiment_run`, strategy artifact files, audit events, job checkpoints.

**External calls**
Agent provider only. Evaluator has no network.

**Failure behaviour**
- Invalid/timeout candidate is a recorded failed experiment.
- Agent provider transient errors may retry within job policy.
- Evaluator/container integrity failure stops campaign, not just the experiment.
- Database persistence failure stops before a new experiment is started.

**Idempotency**
Experiment sequence number is unique per campaign. A resumed worker must continue from the last persisted sequence and must not recreate a completed sequence.

**Final state**
Campaign remains `RUNNING`, or becomes `PAUSED`, `STOPPED`, `COMPLETED`, or `FAILED`; all attempts remain visible.

---

## SB-003 — Candidate robustness/red-team evaluation

**Trigger:** Owner or campaign workflow nominates an experiment for canonical robustness testing.

**Preconditions**
- Experiment evaluation completed successfully.
- Canonical robustness profile exists and is versioned.

**Sequence**
1. Queue robustness job.
2. Re-run exact candidate under each fixed perturbation/test family.
3. Record per-test metrics; never collapse failures before persistence.
4. Compute gate outcome from fixed thresholds.
5. Persist artifact/report.

**Mandatory test families**
- worse transaction fills/spreads;
- premium/cost inflation;
- one-decision-period delay;
- nearby parameter perturbation;
- leave-one-regime/crisis-out;
- removal of dominant payoff events;
- basis/beta perturbation;
- FX perturbation when portfolio base currency differs;
- synthetic crash/recovery paths.

**Failure behaviour**
Individual test errors are reported distinctly from economic failures. If infrastructure failure prevents required tests, canonical gate is `INCOMPLETE`, never `PASS`.

**Idempotency**
Same experiment hash + robustness profile version + evaluator version produces one canonical result identity.

**Final state**
`robustness_run` complete with `passed_gate` and full result set.

---

## SB-004 — Freeze strategy release and consume final holdout

**Trigger:** Owner freezes a candidate; optionally later initiates holdout.

**Preconditions**
- Candidate completed.
- Canonical robustness suite completed, or owner provides explicit recorded override.

**Freeze sequence**
1. Copy/reference exact strategy artifact by content hash.
2. Persist evidence summary and permitted modes.
3. Create immutable `strategy_release` with `holdout_status=UNTOUCHED` if configured.
4. Audit event records release creation and any override.

**Holdout sequence**
1. Owner confirms holdout consumption.
2. System verifies it has not been consumed for this release/evidence context.
3. Run frozen strategy in evaluator against holdout only.
4. Persist holdout result directly on owner-visible release evidence.
5. Set `holdout_status=CONSUMED`.
6. Do not add result to research-agent feedback.

**Failure behaviour**
Infrastructure failure before results are observable may be retried using same frozen artifact. If partial metrics are shown to a human, treat holdout as consumed conservatively.

**Final state**
Frozen release with immutable provenance and accurate holdout state.

---

## SB-005 — Scheduled daily shadow run

**Trigger:** Scheduler creates daily job at default 15:45 `America/New_York` on a candidate trading day.

**Preconditions**
- Active frozen release permitted for `SHADOW`.
- Kill switch state may be either; in shadow it is reported but no order can be sent.
- Broker account configured if using actual portfolio state.

**Sequence**
1. Compute deterministic `run_key`; insert only if absent.
2. Verify broker environment/account alias.
3. Query broker connectivity and obtain current positions, cash, open orders, recent executions.
4. Reconcile known TailHedge orders/positions.
5. Persist pre-trade broker snapshot.
6. Calculate portfolio benchmark-equivalent exposure from mappings.
7. Resolve current allowed option chain/contract details and current quotes.
8. Build `StrategyContext` from permitted current data.
9. Execute frozen strategy in isolated runtime and schema-validate `TargetHedgePlan`.
10. Translate target plan into position deltas/order intents.
11. Run deterministic risk gate even though mode is shadow; store would-pass/would-fail evidence.
12. Do not send orders.
13. Persist final decision and mark `SHADOW_COMPLETE` or blocked/failure state.

**External calls**
IBKR account/contract/market-data reads only.

**Failure behaviour**
Any uncertain broker/quote/strategy state produces no action and a reason code. Shadow run still records diagnostic evidence when possible.

**Idempotency**
Unique run key prevents duplicate scheduled run. Manual re-evaluation creates an explicit revision/new manual run rather than mutating the completed run.

**Final state**
Explainable `NO_ACTION`, proposed intents, or blocked/failed shadow decision.

---

## SB-006 — Scheduled daily paper run

**Trigger:** Same scheduler/manual path with mode `PAPER`.

**Preconditions**
- Strategy release permits `PAPER`.
- Broker account environment is verified `PAPER`.
- Kill switch disengaged.
- Reconciliation complete.
- Current quotes pass freshness/liquidity checks.

**Sequence**
Steps 1–11 from SB-005, then:
12. If no position delta is needed, finish `NO_ACTION`.
13. Re-query/revalidate contract and quote immediately before submission.
14. Re-run applicable risk checks with fresh price/cash/spend.
15. Create immutable `order_intent` with unique idempotency key.
16. Executor calculates initial limit from execution policy.
17. Submit via IBKR adapter using persistent client/order reference.
18. Persist acknowledgement/status.
19. Monitor fills/status for bounded interval.
20. If allowed, re-quote and modify limit within cap.
21. Cancel remaining unfilled quantity after policy timeout.
22. Reconcile positions/open orders/executions from broker.
23. Persist post-trade broker snapshot and final run status.

**Failure behaviour**
- Disconnect before submission: no order; run blocked/failed.
- Disconnect after possible submission: mark `RECONCILIATION_REQUIRED`; on reconnect query broker before any retry.
- Rejected order: persist rejection; no alternate market order.
- Partial fill: remaining target is recomputed from actual fill; no blind repeat.
- Unknown contract/order state: `MANUAL_REVIEW_REQUIRED`.

**Retry/idempotency**
Generic job retry may repeat pre-order read/calculation stages. It may not blindly repeat an order submission. Order submission retries require broker reconciliation by client/order reference first.

**Final state**
`COMPLETE`, `NO_ACTION`, `BLOCKED`, `FAILED`, or `MANUAL_REVIEW_REQUIRED`; final broker state linked.

---

## SB-007 — Target plan to order-intent translation

**Trigger:** Valid `TargetHedgePlan` and current broker/market state.

**Preconditions**
- Plan schema version supported.
- Allowed underlying and long-put-only rules.

**Sequence**
1. Determine desired hedge notional/contract characteristics from plan.
2. Enumerate eligible current contracts within DTE/delta/moneyness/liquidity bounds.
3. Rank deterministically using release/execution-policy rules.
4. Apply discrete contract sizing and over-coverage limit.
5. Compare desired positions with actual positions and TailHedge-owned open orders.
6. Prefer closing/reducing obsolete TailHedge-owned positions before new premium buys when policy calls for roll.
7. Produce broker-neutral intents.

**Failure behaviour**
If no contract satisfies all constraints, return `NO_ELIGIBLE_CONTRACT`; do not relax bounds silently.

**Final state**
Zero or more intents ready for deterministic risk evaluation.

---

## SB-008 — Hedge monetisation/reinvestment in backtest

**Trigger:** Daily strategy decision indicates reduction of profitable hedge and reinvestment.

**Preconditions**
- Daily snapshot provides an executable simulated sell price under cost model.
- Strategy action is permitted by campaign bounds.

**Sequence**
1. Calculate sell-to-close quantity using current owned long quantity only.
2. Apply conservative simulated sale fill and costs.
3. Credit cash.
4. Apply strategy’s reinvestment fraction at the same or next permitted core-portfolio execution convention defined by campaign.
5. Record portfolio units/cash and remaining hedge.
6. Ensure no future intraday high is used.

**Failure behaviour**
Missing executable quote means no simulated trade under base rules; report missed/untradeable action.

**Final state**
Updated combined-portfolio ledger with explicit hedge P&L and reinvestment cash flow.

---

## SB-009 — Kill switch engage/disengage

**Engage trigger:** Owner action or future automated safety mechanism.

**Sequence**
1. Transactionally set global kill switch `engaged=true` and audit event.
2. New order submission checks immediately fail.
3. Queue cancellation attempts for TailHedge-created open orders.
4. Reconcile cancellations.
5. Existing positions remain untouched.

**Disengage trigger:** Owner explicit action.

**Preconditions**
- Authenticated/recently authenticated owner.
- Confirmation received.

**Sequence**
1. Set `engaged=false` with audit reason.
2. Do not automatically run missed trades; next daily/manual run recalculates from broker truth.

**Failure behaviour**
If database state is uncertain, executor must behave as if kill switch is engaged.

---

## SB-010 — Service restart / recovery

**Trigger:** web/worker/scheduler/broker service restarts unexpectedly.

**Sequence**
1. Worker releases/recovers expired job leases.
2. Broker subsystem reconnects/authenticates when possible.
3. For any daily run in `EXECUTING`, fetch broker open orders/recent executions using stored client/order references.
4. Reconstruct actual order/fill state.
5. Mark complete/cancelled or `MANUAL_REVIEW_REQUIRED`.
6. Only after reconciliation may a new daily run or order be created.

**Invariant:** application-local `SUBMITTED` state is not evidence that the broker did or did not receive the order.

---

## SB-011 — IBKR weekly authentication loss

**Trigger:** broker status reports unauthenticated/disconnected around restart/reset or any other time.

**Sequence**
1. Set broker health to unavailable.
2. Reject execution-capable daily runs before order generation.
3. Create deduplicated owner notification.
4. Continue research-only jobs.
5. After user re-authenticates TWS/IB Gateway, reconciliation must run before normal paper operation resumes.

No attempt is made to bypass IBKR’s supported authentication model.

---

## SB-012 — Risk configuration change

**Trigger:** Owner saves edited risk controls.

**Sequence**
1. Validate against application absolute bounds.
2. Show/record old vs new values.
3. Create new immutable `risk_configuration` version.
4. End previous version’s active period and activate new version transactionally.
5. Audit actor/reason.
6. Existing order intents are not silently re-authorized; any not-yet-submitted intent must be re-evaluated under the current config before submission.

**Final state**
Exactly one active risk-config version.
