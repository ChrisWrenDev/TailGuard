# TailHedge - Real Dataset Qualification

## Purpose

This document defines the gate between the generic ingestion/evaluator slice and
trustworthy research using an external options dataset. A dataset is not ready
for a research campaign merely because it parses or produces Parquet. It must
also have sufficient provenance, contract identity, timestamp semantics,
settlement data, coverage, and reproducible backtest behaviour.

The first qualification target is the ORATS Near End-of-day archive. ORATS has
confirmed that its historical Strikes files include SPX and SPXW within the
complete US equity-options universe. The archive is the intended canonical
research source, subject to the checks in this document and the applicable
licence review.

The ORATS Data API remains an optional acquisition pilot, not a runtime
dependency for research reproducibility. The archive and API both require
explicit verification of expiry settlement handling and the SPX-specific
quirks documented by ORATS.

## Confirmed archive characteristics

The vendor has confirmed:

- the historical package is `SMV_Strikes` data only;
- summaries, cores, monies, earnings, and other indicators are not included;
- the snapshot is approximately 14 minutes before the close, around 15:46 ET;
- the archive includes SPX and SPXW coverage;
- the snapshot does not include the closing/last price.

The historical archive is delivered from the ORATS-hosted S3 bucket
`s3://orats-smv-strikes-hist` in `us-east-1`. Objects are grouped by year and
contain one zipped CSV per trading day, for example:

```text
ORATS_SMV_Strikes_20150717.zip
```

The archive is approximately 200 GB compressed and approximately 700 GB after
extraction, according to the vendor. Access is provided through personal
read-only credentials for a 14-day window. Download usage is monitored and
excessive repeated retrieval can disable the keys.

The acquisition process must therefore be resumable and one-time oriented:

1. Preflight available disk space, target date range, expected object count, and the 14-day access window.
2. Load S3 credentials only through the local AWS credential mechanism or an approved secret store. Never place them in the repository, manifest, logs, or strategy context.
3. List and persist the expected object keys before downloading.
4. Use a resumable sync into a dataset-owned local raw directory; rerunning the sync must not redownload completed objects unnecessarily.
5. Hash each downloaded ZIP and record its S3 key, year, embedded date, byte size, and acquisition status.
6. Extract and process one daily file at a time, retaining the original ZIP as the raw evidence layer.
7. Filter rows to `SPX` and `SPXW` before expanding paired call/put columns and writing canonical Parquet.
8. Quarantine files whose embedded date, row dates, or content do not agree; never merge them silently.
9. Remove only explicitly disposable temporary extraction files after hashes and canonical outputs are verified.

The filtered dataset is derived evidence, not a replacement for the raw
archive. Its manifest must link every canonical partition back to the source
ZIP hashes. A full archive download should be performed once; later imports or
rebuilds must use the retained local raw files rather than reacquiring S3
objects.

The Strikes-only package is sufficient for the core MVP option-chain research
when the strategy uses only permitted quote, contract, and derived fields. API-
only indicators must not become hidden evaluator inputs. The qualification
report must include the vendor's documented SPX handling quirks, including the
vendor webinar at `https://www.youtube.com/watch?v=py_SOkXqYR8`, and any
resulting mapping rules before the dataset can pass.

## Supplied sample status

The local sample is:

```text
data/ORATS_SMV_Strikes_20240103.csv
```

The file is ignored by Git under the licensed-data rule and must remain local.
The inspected format contains paired call/put columns such as `cOpra`, `pOpra`,
`cBidPx`, `pBidPx`, `cOi`, and `pOi`. It also contains `ticker`, `stkPx`,
`expirDate`, `strike`, and `trade_date`.

The original sample is a parser-format fixture, not SPX qualification evidence.
Its inspected rows use `ticker=A`, contain a 2024-01-03 trade date, do not
provide an explicit quote timestamp, and have blank `spot_px` values in the
sample rows.

The newly supplied file, `data/SMVquotesSPX20150717snippet.csv`, is an SPX
snippet with 924 data rows and a single `trade_date` of 2015-07-17. It provides
multiple near-term expiries and is suitable for exercising SPX ticker mapping,
paired-side extraction, numeric parsing, and validation reporting. It is not a
full historical dataset and does not by itself provide root identity,
multiplier, exercise style, settlement style, or an explicit quote timestamp.
It also contains both `stkPx` and `spot_px`. ORATS defines `stkPx` for indexes
as the solved implied futures price for each expiration and `spot_px` as the
cash price. Therefore the importer must map `spot_px` to the canonical SPX
cash underlying price and retain `stkPx` only as an expiry-specific forward
reference. See the ORATS Near End-of-day field definitions:
`https://orats.com/near-eod-data`.

The importer must not infer that `stkPx` is the canonical SPX index level or
that the shared Greek columns are put Greeks without vendor-semantic
confirmation. A separate representative multi-date SPX acquisition is still
required before a real SPX backtest is considered qualified.

## Qualification sequence

1. Hash and register the supplied sample without modifying it.
2. Build an explicit ORATS column mapping and record the semantic assumptions.
3. Run the mapping against the sample and report unmapped/source-only fields.
4. Map the supplied SPX snippet and confirm the archive file layout and metadata.
5. Include quiet periods, 2008, 2020, 2022, expiration dates, and dates containing SPXW where available.
6. Review ORATS SPX handling documentation and confirm root, Greeks, snapshot, settlement, and internal-use semantics.
7. Download the archive within the vendor's access window and record file hashes, expected files, missing dates, and extraction results.
8. Filter the raw archive to SPX/SPXW and import it into a new immutable dataset revision.
9. Run all fatal validation checks and produce the qualification report.
10. Run static baselines and a static strategy through the same controlled evaluator.
11. Repeat the qualification/backtest from the same hashes and compare output hashes.

If the API is used instead of or alongside the archive, request count,
pagination, retries, endpoint limits, SPX/SPXW coverage, response completeness,
and post-subscription retention must be included in the request ledger.

## Canonical option quote schema

The canonical dataset is vendor-neutral. Raw ORATS files and responses remain
the evidence layer; only explicitly mapped fields enter canonical Parquet.

`spx_option_quotes.parquet` contains one row per option side per snapshot:

| Field | Type | Required rule |
|---|---|---|
| `snapshot_ts_utc` | `timestamp[us, UTC]` | Actual source timestamp; inferred timestamps must be marked in the manifest |
| `trade_date` | `date` | Exchange-local New York trading date |
| `source` | `string` | `ORATS` for this qualification |
| `underlying_symbol` | `string` | Must be `SPX` for the SPX dataset |
| `root_symbol` | enum | Preserve `SPX` and `SPXW`; never merge them silently |
| `source_contract_id` | `string` | Side-specific vendor identity |
| `expiration_date` | `date` | Must be after the observation date |
| `expiration_type` | enum | `STANDARD`, `WEEKLY`, or an explicitly mapped value |
| `strike` | `decimal(12,4)` | Positive and finite |
| `option_type` | enum | `PUT` or `CALL` |
| `contract_multiplier` | `int` | Verified from source metadata; expected 100 for SPX index options |
| `settlement_type` | enum | Must be `CASH` |
| `exercise_style` | enum | Must be `EUROPEAN` |
| `settlement_style` | enum | `AM`, `PM`, or `UNKNOWN`; unknown blocks expiry use |
| `currency` | `string` | `USD` |
| `bid` | `float64` nullable | Non-negative |
| `ask` | `float64` nullable | Non-negative and not below bid |
| `bid_size` | `uint32` nullable | Non-negative |
| `ask_size` | `uint32` nullable | Non-negative |
| `volume` | `uint64` nullable | Non-negative |
| `open_interest` | `uint64` nullable | Non-negative |
| `underlying_price` | `float64` | Positive and finite at the snapshot |
| `implied_volatility` | `float64` nullable | Non-negative, with units recorded |
| `delta` | `float64` nullable | Side-specific and vendor convention verified |
| `gamma` | `float64` nullable | Non-negative when supplied |
| `theta` | `float64` nullable | Sign convention recorded |
| `vega` | `float64` nullable | Non-negative when supplied |
| `dte_calendar` | `int16` | Recomputed from dates, never trusted from vendor |

The uniqueness key is:

```text
(snapshot_ts_utc, root_symbol, expiration_date, strike, option_type)
```

The paired ORATS row must become two canonical rows. Call and put prices,
sizes, volume, open interest, IV, and contract IDs must not be cross-wired.
Shared or call-side vendor Greeks must not be copied to the put row without
documented semantics and a test proving the mapping.

## Expiry settlement artifact

Expiry settlement must be represented separately from ordinary quote rows:

`option_expiry_settlements.parquet`:

| Field | Type |
|---|---|
| `root_symbol` | `string` |
| `expiration_date` | `date` |
| `settlement_ts_utc` | `timestamp[us, UTC]` |
| `settlement_style` | enum |
| `settlement_value` | `float64` |
| `settlement_type` | enum |
| `source` | `string` |

If official settlement values are unavailable, the evaluator must exclude the
affected expiry trade or fail closed. It must not substitute the last quote or
underlying close without an explicit versioned methodology.

## Manifest requirements

The immutable dataset manifest must include:

- dataset and source identifiers;
- vendor/product and licence reference, without credentials;
- importer and canonical schema versions;
- raw file and response SHA-256 hashes;
- acquisition ledger hash and acquisition timestamps;
- S3 bucket, object-key list, access-window dates, and raw archive hashes;
- filtered-symbol rule and source-object-to-canonical-partition mapping;
- source timezone and snapshot-time policy;
- date range, expected trading dates, and actual dates;
- row count, contract count, and counts by root/type;
- mapped, ignored, and unmapped source columns;
- settlement-artifact coverage;
- validation report hash and status;
- canonical Parquet artifact hashes;
- any inferred fields or unresolved semantic assumptions.

## Validation gate

Validation results are `PASS`, `WARN`, or `FAIL`. A dataset is eligible for a
backtest only when all fatal checks pass. Warnings must remain quantified and
visible in the campaign evidence.

### Provenance and integrity

Fatal checks:

- raw files are unchanged and individually hashed;
- every acquisition request, retry, failure, and missing response is recorded;
- importer and schema versions are pinned;
- no source field is silently remapped or discarded;
- duplicate manifest identities resolve deterministically;
- canonical artifacts can be rebuilt from the raw hashes.

### Coverage and timestamps

Fatal checks for the selected interval:

- the expected SPX trading calendar is explicit and versioned;
- every required decision date has exactly one selected snapshot;
- missing dates are outside the interval or explicitly excluded and reported;
- timestamps normalize deterministically to UTC;
- when the archive has no row-level timestamp, the nominal 15:46 ET observation
  time is recorded as inferred rather than presented as an exact quote time;
- local `trade_date` agrees with the New York date of the timestamp;
- underlying price exists on every required decision date;
- snapshot timing is reported from observed source timestamps;
- no post-decision or future value enters the strategy context.

### Contract identity and settlement

Fatal checks:

- only the intended underlying is present;
- `SPX` and `SPXW` remain distinguishable;
- the canonical key is unique;
- expiration, strike, side, multiplier, currency, exercise, and settlement
  metadata are consistent;
- recomputed calendar DTE agrees with the stored derived value;
- expiry settlement exists for every contract that may be held to expiry;
- no expiration precedes the observation date.

### Numeric and quote quality

Fatal row checks:

- no negative or non-finite prices, sizes, volume, or open interest;
- no crossed quotes;
- no ask below bid;
- no invalid option type, strike, expiration, or currency;
- underlying and option prices are positive and finite;
- Greek ranges and sign conventions match the documented vendor mapping.

Warnings requiring quantified reports:

- missing bids or asks;
- zero bids or zero sizes;
- wide spreads;
- missing volume, open interest, IV, or Greeks;
- unusually low contract or expiry counts by date.

Invalid or untradable rows must not be midpoint-filled. The evaluator must
reject the individual quote or record an explicit no-action/missed-action
outcome according to the frozen cost and tradability policy.

### Research coverage

The report must show, by date and root:

- contract and expiry counts;
- DTE and strike/moneyness coverage;
- put/call counts;
- valid and tradable quote rates;
- zero-bid and wide-spread rates;
- underlying-price consistency;
- coverage of the campaign's allowed strategy region.

### Backtest readiness

Before a result is trusted:

- no-hedge and fixed-put baselines use the same accounting and fill engine;
- hand-calculated synthetic fixtures still pass;
- a poisoned future-row test proves no look-ahead;
- final-holdout paths and metrics remain absent from ordinary evaluation;
- invalid/stale quotes produce explicit no-action outcomes;
- missing settlement data blocks or explicitly skips the affected trade;
- no closing/last price is inferred from the Near EOD snapshot;
- cash, positions, premiums, commissions, and settlements reconcile at every step;
- identical inputs produce identical metrics and artifact hashes;
- dataset, evaluator, split, cost, campaign, and strategy hashes are persisted;
- skipped, failed, and untradeable decisions are retained in the evidence.

## Qualification result

The qualification task is complete only when the report, manifest, canonical
artifacts, and deterministic static-backtest evidence are available together.
Passing the gate establishes that the data/evaluator path is usable. It does
not establish that a hedge is economically useful or suitable for paper
execution.
