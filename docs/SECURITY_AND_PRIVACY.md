# TailHedge — Security and Privacy

## 1. Risk posture

TailHedge handles brokerage state and may eventually submit financial orders. Security must therefore be stricter than a normal personal dashboard. The MVP cannot place real-money orders, but the architecture must not create an easy path for research/AI code to gain broker authority later.

Primary principle: **the strategy/AI proposes desired hedge state; deterministic trusted code decides whether and how anything reaches the broker.**

## 2. Authentication model

- Single local owner account in MVP.
- Password stored only as Argon2id hash.
- Session-based browser authentication.
- Session cookies `HttpOnly`, `SameSite=Strict`; `Secure` when TLS is enabled.
- Session expiration configurable; sensitive actions (kill-switch disengage, loosening risk limits, future live approval) should require recent authentication.
- No social login/OIDC in MVP.
- Broker authentication is separate; TailHedge must not treat an authenticated IBKR session as application authentication.

## 3. Authorization model

Application role: `OWNER` only.

Capability separation matters more than role count:

| Component | Permitted | Explicitly forbidden |
|---|---|---|
| Web owner session | Configure/run/review within enabled product modes | Bypass server risk gate |
| Research agent | Propose candidate strategy source | Broker calls, secrets, holdout access, evaluator modification |
| Evaluator sandbox | Read allowed data slice; run strategy/backtest | Network, broker, host source writes, secret access |
| Worker | Execute application jobs | Loosen risk config without owner command |
| Broker adapter/executor | Read broker; place validated paper orders | Accept arbitrary AI/user raw order payload through public API |
| Scheduler | Create due jobs | Direct broker action |

## 4. Data ownership boundaries

All research datasets, broker snapshots, strategy artifacts, and operational records are owned by the single application owner.

Paid historical data may have vendor licensing restrictions. The application:
- stores datasets privately;
- does not provide sharing/public-download features;
- does not bundle vendor data in source distributions/backups intended for others;
- records vendor/source metadata for provenance.

## 5. Sensitive data

High sensitivity:
- broker account identifiers;
- broker session/configuration details;
- financial positions, balances, net liquidation values;
- application password hashes;
- API keys for AI/notification providers;
- future live account references.

Medium sensitivity:
- historical research results/strategy logic;
- portfolio mappings;
- audit trail.

Not secret but integrity-critical:
- risk settings;
- strategy-release hashes;
- dataset manifests;
- evaluator versions;
- order idempotency keys.

## 6. Secrets handling

- Never commit secrets.
- `.env.example` contains names/placeholders only.
- Production secrets supplied via environment, Docker secrets, systemd credentials, or OS secret store.
- Database stores encrypted broker external-account reference only if persistence is necessary; prefer broker alias/config secret where practical.
- Strategy contexts, experiment prompts, research artifacts, error messages, and logs must never contain secrets.
- LLM/agent prompts must not receive broker account values beyond generic portfolio research inputs needed for research; historical research should normally use proxy values, not private account identifiers.

## 7. Input validation

### File imports
- Restrict staged paths to configured ingest root; reject traversal/symlink escape.
- Enforce file-size/config limits.
- Parse with explicit schemas; do not execute macros or embedded content.
- Treat CSV/Parquet strings as data, not commands.
- Hash all source files.
- Historical-source credentials are supplied through the local secret mechanism only; never store them in dataset manifests, job payloads, logs, or strategy contexts.
- Bulk archive acquisition must use a resumable, bounded workflow to avoid uncontrolled repeated vendor downloads.

### HTTP/API
- Pydantic validation for all request bodies.
- Enumerations for modes, sides, option types, statuses.
- Numeric bounds on risk settings and strategy campaign bounds.
- Reject NaN/infinite numeric values.

### Broker data
Broker/API responses are external/untrusted input. Validate contract identity, multiplier, currency, expiry, side, quote ordering/freshness, and account/environment before using them.

### Agent output
Treat as hostile/untrusted:
- maximum source size;
- expected response schema;
- hash exact source;
- no direct filesystem write by agent provider if avoidable;
- execute only in evaluator sandbox;
- validate `TargetHedgePlan` after execution.

## 7.1 Agent-provider isolation

The proposal agent may need network access to an LLM/API, unlike the strategy evaluator. Run that provider with a sanitised environment and least privilege:
- expose only the provider-specific credential it needs;
- do not expose broker credentials, database passwords, application session secrets, or raw environment dumps;
- use a dedicated temporary working directory containing only the research request and response;
- prefer a separate OS user/container/service boundary for `LocalCommandAgentProvider`;
- never pass final-holdout data/metrics in the request.

The provider returns candidate source text; it does not write directly into the repository or evaluator.

## 8. Strategy-code sandbox

Minimum OCI runtime controls:
- `--network=none`;
- read-only root filesystem;
- non-root user;
- drop all capabilities;
- no privileged mode;
- no host PID/IPC namespace;
- no Docker/Podman socket;
- no host home directory;
- read-only mounts only for evaluator and allowed data slice;
- tmpfs/writable result directory with size limit;
- CPU quota;
- memory limit;
- PID/process limit;
- hard wall-clock timeout;
- default seccomp/AppArmor/SELinux protections where available.

The live broker process must not share a process or writable filesystem namespace with strategy evaluation.

## 9. Broker safety controls

### Required invariants
1. MVP broker environment must be verified `PAPER` before order submission.
2. Allowed order actions: buy long put or sell-to-close verified owned long put.
3. No sell-to-open.
4. No market orders.
5. No order if quote stale/invalid/wide beyond configured threshold.
6. No premium buy if cash/budget checks fail.
7. No order after kill switch engaged.
8. No retry after ambiguous submission without reconciliation.
9. No generic arbitrary-order endpoint.
10. Strategy/agent never receives a broker-client object/capability.

### Account/environment mismatch
Any mismatch between configured account alias/environment and broker-returned account state is a hard block. Do not “fall back” to another account.

## 10. CSRF, XSS, and web security

- CSRF tokens on state-changing browser requests.
- Autoescape templates.
- Content Security Policy suitable for selected chart/HTMX assets; prefer self-hosted assets.
- No rendering agent rationale/strategy source as trusted HTML.
- Security headers: frame denial, MIME sniffing prevention, referrer policy.
- If remote access is enabled, require TLS and private VPN/reverse-proxy controls.

## 11. Abuse protection and rate limiting

Because MVP is private/single-user, public abuse is not the primary concern. Still:
- login endpoint rate-limited and temporarily back off repeated failures;
- state-changing campaign/start/order-adjacent endpoints reject rapid duplicate requests via idempotency/state rules;
- broker adapter obeys IBKR pacing limits and uses controlled concurrency;
- agent provider has campaign-level request/cost/iteration limits.

No broad public API exposure.

## 12. Logging restrictions

Never log:
- passwords;
- session cookies;
- secret/API tokens;
- full broker account numbers;
- raw authentication responses containing sensitive data;
- full environment-variable dumps.

Mask external account refs and sensitive IDs. Structured logs should use internal UUIDs and aliases.

Order details, prices, quantities, and portfolio values are operationally useful and may be logged/persisted locally; treat log files as sensitive financial data and protect with filesystem permissions.

## 13. Audit requirements

Append-only audit events for:
- login security events as appropriate;
- risk configuration changes;
- execution mode changes;
- kill-switch engage/disengage;
- strategy-release creation/retirement;
- final-holdout consumption;
- broker reconciliation mismatch;
- order intent creation/submission/modification/cancellation/fill/rejection;
- overrides of failed robustness gates;
- data manifest/validation state changes.

Audit entries contain who/what/when and redacted before/after values for settings.

## 14. Data retention and deletion

Default local retention:
- research experiments: indefinite unless owner performs explicit archive/export cleanup;
- order/fill/daily-run/audit: indefinite for product lifetime by default;
- broker raw redacted payloads: configurable retention, recommended 90 days if detailed payload not needed after normalisation;
- logs: rotate, recommended 30–90 days;
- licensed raw market data: according to vendor licence and owner policy.

Deletion tools are future maintenance operations. They must not silently destroy provenance required by retained strategy releases or order records.

## 15. Privacy considerations

The application should not transmit private portfolio/broker data to an AI provider unless explicitly required and configured. Default Autoresearch prompts should use research dataset context/metrics and strategy source, not account identifiers or current private holdings.

No third-party analytics/advertising telemetry.

## 16. Threat model

### TH-001 — Agent attempts to modify evaluator or access holdout
**Defences:** only candidate source accepted; content hash checks; holdout not mounted; evaluator immutable; no network.

### TH-002 — Agent-generated code escapes and steals secrets
**Defences:** isolated unprivileged container, no secret mounts/network, resource limits, separate broker process.

### TH-003 — Duplicate order after process/network failure
**Defences:** deterministic intent ID; persistent client refs; broker reconciliation before retry; manual-review state on ambiguity.

### TH-004 — Accidental live-account order
**Defences:** MVP code rejects live mode; paper environment verification; account alias/environment checks; future live requires explicit compile/config/product gate.

### TH-005 — Strategy produces short/naked option action
**Defences:** declarative target schema; target-to-order translator and risk gate allow only long puts/sell-to-close owned quantity.

### TH-006 — Stale or corrupt quote causes bad limit
**Defences:** freshness, bid/ask, spread, timestamp, contract checks; immediate pre-submit refresh; fail closed.

### TH-007 — Wrong portfolio hedge because holding mapping is missing/wrong
**Defences:** mapping completeness warnings, explicit beta/benchmark configuration, versioned mapping, dashboard exposure breakdown, over-coverage limit.

### TH-008 — Research result is data-mined/overfit and treated as truth
**Defences:** complete experiment ledger, immutable scoring, blocked validation, perturbation, withheld regimes, secret holdout, baseline comparisons, complexity reporting. This is an epistemic safety threat as well as a modelling risk.

### TH-009 — Web UI exposed to internet
**Defences:** bind privately by default; authenticated owner; TLS/private VPN if remotely accessed; no public deployment instructions as default.

### TH-010 — Risk settings weakened accidentally
**Defences:** versioned settings, absolute bounds, old/new confirmation, audit event, re-evaluate unsent intents under latest config.

## 17. Incident behaviour

When safety-critical uncertainty exists:
- engage or treat system as if kill switch is engaged;
- stop new broker submissions;
- preserve evidence/logs;
- reconcile broker truth;
- do not automatically liquidate existing positions;
- require owner review before resuming if external order state was ambiguous.

## 18. Live-release security gate (future)

Before enabling any real-money mode, require a new security review covering:
- IBKR live authentication/session behaviour at that time;
- least-privilege account/API capabilities available;
- host hardening/backups;
- penetration/dependency scanning;
- paper/shadow operational history;
- order/recovery fault injection;
- explicit maximum monetary-loss limits;
- notification channel reliability;
- legal/tax/account-wrapper implications outside this software’s scope.
