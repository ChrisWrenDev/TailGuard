# TailHedge — Instructions for the AI Coding Agent

## 1. Source of truth

1. Read `README.md` and all files in `docs/` before coding.
2. Treat these specifications as the current source of truth.
3. Requirement IDs (`FR-*`), invariants (`INV-*`), behaviours (`SB-*`), tasks (`TASK-*`), and decisions (`ADR-*`) are stable references.
4. If code and documentation later disagree, do not silently choose one. Determine whether a deliberate approved change exists. Otherwise surface the contradiction and prefer the safer behaviour until resolved.

## 2. Implementation behaviour

- Implement incrementally.
- Keep the application runnable after each meaningful change.
- Prefer a vertical slice over building an unused abstraction layer.
- Run relevant tests after every change.
- Do not silently change product behaviour to make implementation easier.
- Do not introduce dependencies without a clear reason recorded in the pull request/change note.
- Follow existing repository patterns once established.
- Update documentation when an implementation decision materially changes an interface, invariant, or operational requirement.
- Record assumptions explicitly; do not hide them inside code.
- Prefer the simplest architecture that satisfies the requirements.
- Avoid premature abstraction.
- Do not implement future-scope features unless required to make an MVP interface testable.
- Protect backwards compatibility after an interface is used by stored data, migrations, or tests.
- Never hard-code secrets.
- Validate external and user-provided input.
- Surface blockers clearly.

## 3. Financial/safety rules you may not relax

Unless the owner explicitly changes the specifications:

1. **MVP cannot submit live-money orders.** `LIVE_APPROVAL` and `LIVE_AUTONOMOUS` must be rejected/disabled.
2. Broker-executable hedge actions are long puts only: `BUY PUT` or `SELL_TO_CLOSE` verified owned long puts.
3. No market orders.
4. No sell-to-open or naked option logic.
5. No intentional borrowing/margin to fund option premiums.
6. Strategy/AI code must never call IBKR or receive broker credentials.
7. A strategy returns a target hedge plan; deterministic trusted code creates orders.
8. Every order intent must pass the risk gate under current broker/quote state.
9. Ambiguous broker submission state must reconcile before any retry.
10. The system fails closed when safety-relevant state is unknown.
11. Kill switch prevents new submissions; it does not automatically liquidate existing positions.
12. Final holdout data/metrics must not be included in research-agent feedback.
13. Every research attempt, including failure, remains in the experiment ledger.
14. Research datasets referenced by a campaign are immutable.
15. A frozen strategy release is immutable.

If a requested implementation change conflicts with these rules, stop that change and identify the conflict rather than weakening the rule implicitly.

## 4. Research correctness rules

- Do not use random row-level train/test splitting.
- Prevent look-ahead at the data-access boundary, not just by convention.
- Purge/embargo fold boundaries according to configured holding/lookback horizon.
- Base backtest and all baselines must use the same accounting/execution-cost engine.
- Do not substitute midpoint fills when the configured model requires spread penalty.
- Do not infer intraday execution from daily data.
- Store exact dataset/evaluator/config/strategy hashes with results.
- Treat agent rationale as untrusted commentary, never as quantitative evidence.

## 5. Strategy sandbox rules

Agent-generated strategy code is untrusted.

- Execute only in the specified isolated runtime.
- No network.
- No secret mounts.
- No broker socket/API.
- No host source-tree write access.
- No Docker socket.
- Enforce CPU/memory/PID/time/output limits.
- Validate output schema.
- A sandbox error becomes a failed experiment or failed daily strategy evaluation; never fall back to executing it in-process.

## 6. Database rules

- Use Alembic migrations for schema changes.
- Financial/research audit entities are append-oriented.
- Do not hard-delete experiments, daily runs, risk decisions, order intents/orders/fills, strategy-release evidence, or audit events through normal application features.
- Enforce important invariants both in application logic and database constraints where reasonable.
- Preserve UTC timestamps in persistence; keep exchange/local timezone semantics explicit at boundaries.
- Never mix currencies without explicit FX input.

## 7. Broker integration rules

Develop against `FakeBroker` first.

When implementing IBKR:
- use an adapter; do not leak IBKR SDK objects into domain models;
- verify configured account/environment on every executable run;
- read positions/open orders/recent executions before calculating executable delta;
- attach persistent client/order references for reconciliation;
- persist broker acknowledgement/status/fills;
- obey API pacing and reconnect behaviour;
- do not use IBKR expired-options history as the historical research dataset;
- test with a paper account only in MVP.

## 8. UI rules

- Browser is never authoritative for financial calculations or risk checks.
- Critical statuses have text, not colour-only meaning.
- `NO_ACTION` is an explicit outcome with reasons.
- Do not hide losing experiments or failed robustness tests.
- Final-holdout consumption and risk-limit loosening require explicit confirmations.
- Escape agent-provided/source text; never render it as trusted HTML.

## 9. Tests required with changes

For each task:
1. Add/modify unit tests for changed domain logic.
2. Add integration tests when persistence, Parquet/DuckDB, jobs, sandbox, or broker adapters are touched.
3. Add/update requirement-mapped tests from `TEST_STRATEGY.md` when relevant.
4. For safety-critical behaviour, include a negative test proving the prohibited action fails.
5. Run the smallest relevant suite during iteration, then the task’s required suite before completion.

Do not mark a task complete because manual testing “looked right.”

## 10. Dependency policy

Before adding a dependency, ask:
- Does standard library/current stack solve this adequately?
- Is the project actively maintained and widely used?
- Does it materially reduce correctness/security risk or implementation complexity?
- Does it add a service/runtime dependency (Redis, Node, etc.) that the architecture intentionally avoids?

Record meaningful dependency decisions in `DECISIONS.md` if they alter architecture.

## 11. What to do when a requirement is missing

### Non-blocking ambiguity
If a sensible safe default exists:
1. choose the narrowest/safest interpretation consistent with existing docs;
2. add the assumption to `OPEN_QUESTIONS.md` or an ADR if permanent;
3. write code so the choice is configurable when that is low-cost and appropriate;
4. continue.

### Blocking ambiguity
Only stop when proceeding would likely:
- create incompatible persisted data;
- expose real money/secrets;
- violate a core research validity constraint;
- choose between materially different external integration contracts that cannot be abstracted.

Surface the exact question, affected requirements/tasks, and recommended default.

## 12. What to do when specifications contradict

Use this priority:
1. explicit safety/security invariant;
2. requirement with acceptance criteria;
3. system behaviour;
4. data/API model;
5. implementation plan/task wording;
6. examples/defaults.

Then:
- choose the interpretation that is safer and more reversible;
- record the conflict and decision in `DECISIONS.md`;
- update affected docs in the same change so inconsistency does not persist;
- never “resolve” a contradiction by weakening broker/risk/holdout isolation silently.

## 13. Task execution template

For each `TASK-*`:

1. Read related `FR-*`, `SB-*`, `INV-*`, ADRs, and tests.
2. State a short implementation plan.
3. Implement only the task plus strictly necessary refactors.
4. Add tests.
5. Run tests/lint/types.
6. Check migrations/config/docs.
7. Summarise changed files, behavioural impact, tests run, and any new assumption/blocker.

## 14. Definition of done for agent work

A task is done only when:
- acceptance criteria pass;
- required tests pass;
- application remains runnable;
- no safety invariant is weakened;
- no secret/test/licensed data is committed accidentally;
- documentation/interfaces are consistent;
- any new assumption is recorded.
