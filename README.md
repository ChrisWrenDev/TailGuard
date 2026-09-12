# TailHedge

TailHedge is a planned single-user research and execution system for studying and operating a systematic long-put tail-risk hedge around a long-term equity portfolio.

**Repository status:** specification only. Application code does not exist yet.

## Current scope

The MVP will:

- import daily historical option-chain data into a vendor-neutral local research store;
- backtest the **combined core portfolio + hedge + cash + reinvestment**;
- compare simple mechanical hedge baselines;
- run an Autoresearch-style agent loop in which only candidate strategy logic may change;
- preserve every research attempt and isolate a final holdout;
- run robustness/red-team tests before a strategy can be frozen;
- apply a frozen release once per trading day to current broker/market state;
- support IBKR read-only shadow operation and IBKR **paper** long-put execution;
- enforce a deterministic risk gate, limit orders, idempotent reconciliation, and a kill switch.

It will **not** place real-money orders in the MVP.

## Architecture at a glance

```text
Historical option data ──> Parquet/DuckDB ──> immutable backtester/evaluator
                                              ^
                                              |
                                      Autoresearch agent
                                      may change strategy only
                                              |
                                              v
                                       frozen strategy release
                                              |
Current portfolio/quotes <── IBKR <── broker adapter
          |                                   |
          +────────> strategy runtime ──> target hedge plan
                                      ──> deterministic risk gate
                                      ──> shadow / paper limit orders
```

Core trust rule: **the research/AI layer never has broker authority.** It can only produce a target hedge plan. Trusted deterministic code reconciles the account, checks risk limits, and creates broker orders.

## Intended repository structure

```text
/
├── README.md
├── pyproject.toml                # future
├── compose.yaml                  # future
├── docs/
│   ├── PROJECT_OVERVIEW.md
│   ├── PRD.md
│   ├── UX_SPEC.md
│   ├── TECHNICAL_ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── API_SPEC.md
│   ├── SYSTEM_BEHAVIOURS.md
│   ├── SECURITY_AND_PRIVACY.md
│   ├── TEST_STRATEGY.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── AGENT_INSTRUCTIONS.md
│   ├── TASKS.md
│   ├── DECISIONS.md
│   └── OPEN_QUESTIONS.md
├── src/tailhedge/                # future
├── strategy_sdk/                 # future
├── evaluator_image/              # future
├── tests/                        # future
└── data/                         # future, gitignored/licensed local data
```

See `docs/TECHNICAL_ARCHITECTURE.md` for the full proposed structure.

## Local development approach (planned)

The specification selects:

- Python 3.12+
- FastAPI + Jinja2/HTMX
- PostgreSQL + SQLAlchemy/Alembic
- Parquet + DuckDB for historical research data
- a dedicated worker/scheduler process
- isolated OCI containers for agent-generated strategy evaluation
- IBKR TWS API behind a broker adapter
- pytest/Hypothesis/Playwright testing

The first runnable version must use synthetic/golden data and `FakeBroker`; no paid dataset or broker account should be required to verify core correctness.

## Important documentation

Start here:

1. `docs/PROJECT_OVERVIEW.md` — what/why/scope/principles.
2. `docs/PRD.md` — stable functional requirements and acceptance criteria.
3. `docs/TECHNICAL_ARCHITECTURE.md` — chosen architecture/stack/trust boundaries.
4. `docs/IMPLEMENTATION_PLAN.md` — ordered phases.
5. `docs/TASKS.md` — autonomous-agent-sized backlog.
6. `docs/TEST_STRATEGY.md` — what must be proven.
7. `docs/AGENT_INSTRUCTIONS.md` — mandatory coding-agent behaviour.
8. `docs/DECISIONS.md` and `docs/OPEN_QUESTIONS.md` — settled decisions and unresolved choices.

## Implementation status

```text
Specifications       COMPLETE
Repository bootstrap NOT STARTED
Research engine      NOT STARTED
Autoresearch loop    NOT STARTED
IBKR shadow          NOT STARTED
IBKR paper trading   NOT STARTED
Live trading         OUT OF MVP SCOPE
```

Do not infer code or integrations exist because they are described in the documents.

## How an AI agent should begin

1. Read all documentation before writing code.
2. Start with `TASK-001` in `docs/TASKS.md`.
3. Follow `docs/AGENT_INSTRUCTIONS.md` exactly.
4. Keep the application runnable after each task.
5. Use synthetic/golden fixtures before external integrations.
6. Never loosen broker/risk/holdout isolation to make a test pass.
7. Record any new architectural/product decision rather than hiding it in implementation.

## Key MVP safety boundaries

- paper account only for broker writes;
- long puts only;
- no market orders;
- no sell-to-open;
- no AI-to-broker direct path;
- no blind retry after ambiguous order submission;
- final holdout not exposed to Autoresearch;
- kill switch fails closed;
- unknown safety state means no trade.
