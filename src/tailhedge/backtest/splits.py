"""Time-blocked splits with purge/embargo for research evaluation.

Implements FR-004, FR-010, BR-001, BR-002: chronological train/validation/
final-holdout partitioning with configurable purge horizons to prevent
look-ahead leakage and ensure holdout isolation.

Split policy:
- BR-001: Train/test partitions preserve chronology; random row-level
  splitting is prohibited.
- BR-002: Fold boundaries purge enough history to prevent positions/
  lookback windows from crossing from training into evaluation.  Default
  purge horizon is ``max(strategy lookback, maximum allowed DTE/holding
  horizon)`` unless the evaluator proves a shorter non-leaking horizon.
- FR-010: Final holdout is physically excluded from ordinary evaluator
  input; holdout paths are not mounted into strategy runtime during
  research.
- FR-004: No strategy call receives future rows or final-holdout labels.

Materialisation:
The split service produces physical allowed-range mount lists for each
evaluator run.  Only data within the permitted date ranges is mounted;
final holdout paths are never provided to the research-agent runtime
(TECHNICAL_ARCHITECTURE §7.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class PartitionType(StrEnum):
    """Partition type enumeration."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


@dataclass(frozen=True)
class DateRange:
    """An inclusive date range [start_date, end_date].

    Both endpoints are inclusive.  An empty range (where start > end)
    represents a partition with no data.
    """

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            msg = (
                f"start_date ({self.start_date}) must not be after "
                f"end_date ({self.end_date})"
            )
            raise ValueError(msg)

    @property
    def is_empty(self) -> bool:
        """Return True if the range contains no days."""
        return self.start_date > self.end_date

    @property
    def duration_days(self) -> int:
        """Return the number of calendar days in the range (inclusive)."""
        if self.is_empty:
            return 0
        return (self.end_date - self.start_date).days + 1

    def overlaps(self, other: DateRange) -> bool:
        """Return True if this range overlaps with *other*."""
        return self.start_date <= other.end_date and other.start_date <= self.end_date

    def before(self, other: DateRange) -> bool:
        """Return True if this range ends strictly before *other* starts."""
        return self.end_date < other.start_date

    def adjacent(self, other: DateRange) -> bool:
        """Return True if this range ends exactly one day before *other* starts."""
        return self.end_date + timedelta(days=1) == other.start_date

    def gap_days_to(self, other: DateRange) -> int:
        """Return the number of gap days between this range's end and other's start.

        A positive value means a gap exists; zero means adjacent or
        overlapping; negative means overlapping.
        """
        return (other.start_date - self.end_date).days - 1


@dataclass(frozen=True)
class FoldPartition:
    """A single partition (train or validation) within a fold."""

    partition_type: PartitionType
    date_range: DateRange

    def __post_init__(self) -> None:
        if self.partition_type == PartitionType.HOLDOUT:
            msg = "Use FoldPartition for TRAIN/VALIDATION; use HoldoutPartition for HOLDOUT"
            raise ValueError(msg)


@dataclass(frozen=True)
class FoldDefinition:
    """A single fold in the time-blocked split.

    Contains a training range, a validation range, and the purge gap
    between them.  The purge gap ensures that positions/lookback windows
    opened during training do not leak into validation evaluation.

    ``purge_start`` and ``purge_end`` define the excluded date range
    between training and validation.  If the purge gap is zero days,
    the training end and validation start are adjacent.
    """

    fold_index: int
    train_range: DateRange
    validation_range: DateRange
    purge_start: date
    purge_end: date

    def __post_init__(self) -> None:
        if self.fold_index < 0:
            msg = f"fold_index must be non-negative, got {self.fold_index}"
            raise ValueError(msg)
        if self.train_range.is_empty:
            msg = f"Fold {self.fold_index}: train_range must not be empty"
            raise ValueError(msg)
        if self.validation_range.is_empty:
            msg = f"Fold {self.fold_index}: validation_range must not be empty"
            raise ValueError(msg)
        if not self.train_range.before(self.validation_range):
            msg = (
                f"Fold {self.fold_index}: train_range must end before "
                f"validation_range starts"
            )
            raise ValueError(msg)

    @property
    def purge_days(self) -> int:
        """Return the number of calendar days in the purge gap (inclusive)."""
        if self.purge_start > self.purge_end:
            return 0
        return (self.purge_end - self.purge_start).days + 1

    @property
    def train_partition(self) -> FoldPartition:
        """Return the training partition."""
        return FoldPartition(
            partition_type=PartitionType.TRAIN,
            date_range=self.train_range,
        )

    @property
    def validation_partition(self) -> FoldPartition:
        """Return the validation partition."""
        return FoldPartition(
            partition_type=PartitionType.VALIDATION,
            date_range=self.validation_range,
        )


@dataclass(frozen=True)
class HoldoutPartition:
    """The final holdout partition.

    The holdout is excluded from ordinary evaluator input during
    research (FR-010).  It may be consumed exactly once per strategy
    release to produce final evidence.
    """

    date_range: DateRange

    @property
    def partition(self) -> FoldPartition:
        """Return the equivalent FoldPartition (for mount-list uniformity)."""
        return FoldPartition(
            partition_type=PartitionType.HOLDOUT,
            date_range=self.date_range,
        )


@dataclass(frozen=True)
class SplitConfig:
    """Configuration for a time-blocked split policy.

    Defines the complete partition scheme for a campaign:
    - Ordered list of folds (train/validation with purge gaps).
    - Optional final holdout partition.
    - Purge horizon in calendar days applied between train and validation
      within each fold.

    The purge horizon defaults to ``max(strategy_lookback_days,
    max_dte_days)`` unless a shorter non-leaking horizon has been
    validated by the evaluator (BR-002).
    """

    folds: tuple[FoldDefinition, ...]
    holdout: HoldoutPartition | None
    purge_horizon_days: int
    strategy_lookback_days: int = 0
    max_dte_days: int = 60

    def __post_init__(self) -> None:
        if not self.folds:
            msg = "SplitConfig must have at least one fold"
            raise ValueError(msg)
        if self.purge_horizon_days < 0:
            msg = f"purge_horizon_days must be non-negative, got {self.purge_horizon_days}"
            raise ValueError(msg)
        if self.strategy_lookback_days < 0:
            msg = (
                f"strategy_lookback_days must be non-negative, "
                f"got {self.strategy_lookback_days}"
            )
            raise ValueError(msg)
        if self.max_dte_days < 0:
            msg = f"max_dte_days must be non-negative, got {self.max_dte_days}"
            raise ValueError(msg)

    @property
    def fold_count(self) -> int:
        """Return the number of folds."""
        return len(self.folds)

    @property
    def has_holdout(self) -> bool:
        """Return True if a final holdout partition is configured."""
        return self.holdout is not None

    @property
    def default_purge_horizon(self) -> int:
        """Compute the default purge horizon from lookback and DTE config.

        ``max(strategy_lookback_days, max_dte_days)`` per BR-002.
        """
        return max(self.strategy_lookback_days, self.max_dte_days)


@dataclass(frozen=True)
class MaterializedPartition:
    """A physical date-range partition for an evaluator mount list.

    Produced by materialising a ``SplitConfig`` against actual available
    data dates.  Each partition represents a contiguous date range that
    may be mounted as read-only input to an evaluator run.
    """

    partition_type: PartitionType
    fold_index: int
    date_range: DateRange
    label: str  # e.g. "fold_0_train", "fold_0_validation", "holdout"

    @property
    def is_holdout(self) -> bool:
        """Return True if this is a holdout partition."""
        return self.partition_type == PartitionType.HOLDOUT


@dataclass(frozen=True)
class EvaluatorMountList:
    """The allowed mount list for a single evaluator run.

    For ordinary research runs, the mount list includes only the train
    and validation partitions for a single fold.  The holdout partition
    is never included (FR-010).

    For holdout evaluation, the mount list includes only the holdout
    partition.
    """

    partitions: tuple[MaterializedPartition, ...]
    is_holdout_run: bool

    def date_ranges(self) -> list[DateRange]:
        """Return the date ranges of all partitions in order."""
        return [p.date_range for p in self.partitions]

    def total_date_range(self) -> DateRange | None:
        """Return the union of all partition date ranges, or None if empty."""
        if not self.partitions:
            return None
        ranges = self.date_ranges()
        start = min(r.start_date for r in ranges)
        end = max(r.end_date for r in ranges)
        return DateRange(start_date=start, end_date=end)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitValidationError:
    """A single validation error for a split configuration."""

    code: str
    message: str


def validate_split_config(config: SplitConfig) -> list[SplitValidationError]:
    """Validate a split configuration for correctness.

    Checks:
    - Folds are in chronological order (BR-001).
    - No date-range overlap within or across folds.
    - Purge horizon is enforced between train and validation within each
      fold.
    - Final holdout does not overlap with any fold.
    - No date ranges are empty.

    Parameters
    ----------
    config : SplitConfig
        The split configuration to validate.

    Returns
    -------
    list[SplitValidationError]
        Empty list if valid; otherwise, one error per violation.
    """
    errors: list[SplitValidationError] = []

    # Check chronological order of folds
    for i in range(1, len(config.folds)):
        prev = config.folds[i - 1]
        curr = config.folds[i]
        if not prev.validation_range.before(curr.train_range):
            errors.append(
                SplitValidationError(
                    code="FOLD_ORDER",
                    message=(
                        f"Folds {i - 1} and {i} are not in chronological order: "
                        f"fold {i - 1} validation ends at "
                        f"{prev.validation_range.end_date}, "
                        f"fold {i} train starts at "
                        f"{curr.train_range.start_date}"
                    ),
                )
            )

    # Check each fold's internal purge
    for fold in config.folds:
        purge_gap = fold.train_range.gap_days_to(fold.validation_range)
        # Purge gap includes the purge range itself (start to end inclusive)
        # The number of excluded days between train end and validation start
        # is (validation_start - train_end - 1).  The purge range adds
        # purge_horizon_days of additional exclusion on top of the base gap.
        excluded_between = purge_gap + 1 if purge_gap >= 0 else 0
        if excluded_between < config.purge_horizon_days:
            errors.append(
                SplitValidationError(
                    code="PURGE_ENFORCEMENT",
                    message=(
                        f"Fold {fold.fold_index}: purge gap of "
                        f"{excluded_between} day(s) is less than required "
                        f"purge horizon of {config.purge_horizon_days} day(s) "
                        f"(train ends {fold.train_range.end_date}, "
                        f"validation starts {fold.validation_range.start_date})"
                    ),
                )
            )

    # Check for overlaps across folds
    all_ranges: list[tuple[int, str, DateRange]] = []
    for fold in config.folds:
        all_ranges.append((fold.fold_index, "train", fold.train_range))
        all_ranges.append((fold.fold_index, "validation", fold.validation_range))
    if config.holdout is not None:
        all_ranges.append((-1, "holdout", config.holdout.date_range))

    for i in range(len(all_ranges)):
        for j in range(i + 1, len(all_ranges)):
            idx_a, type_a, range_a = all_ranges[i]
            idx_b, type_b, range_b = all_ranges[j]
            if range_a.overlaps(range_b):
                errors.append(
                    SplitValidationError(
                        code="OVERLAP",
                        message=(
                            f"Date range overlap between {type_a} of fold {idx_a} "
                            f"({range_a.start_date} to {range_a.end_date}) and "
                            f"{type_b} of fold {idx_b} "
                            f"({range_b.start_date} to {range_b.end_date})"
                        ),
                    )
                )

    # Check holdout does not overlap with folds
    if config.holdout is not None:
        holdout_range = config.holdout.date_range
        for fold in config.folds:
            if holdout_range.overlaps(fold.train_range) or holdout_range.overlaps(
                fold.validation_range
            ):
                # Already caught by cross-fold overlap check above, but
                # add a specific holdout message for clarity.
                pass  # Covered by OVERLAP

    return errors


# ---------------------------------------------------------------------------
# Materialisation
# ---------------------------------------------------------------------------


def materialize_fold_partitions(
    config: SplitConfig,
    available_start: date,
    available_end: date,
) -> list[FoldDefinition]:
    """Materialise fold definitions against available data range.

    Clips fold date ranges to the available data range.  Folds that
    fall entirely outside the available range are excluded.

    Parameters
    ----------
    config : SplitConfig
        The split configuration.
    available_start, available_end : date
        The first and last dates with data available.

    Returns
    -------
    list[FoldDefinition]
        Materialised folds with ranges clipped to available data.
    """
    available = DateRange(start_date=available_start, end_date=available_end)
    materialized: list[FoldDefinition] = []

    for fold in config.folds:
        train_clip = _clip_range(fold.train_range, available)
        val_clip = _clip_range(fold.validation_range, available)

        if train_clip is None or val_clip is None:
            continue  # Fold entirely outside available range

        materialized.append(
            FoldDefinition(
                fold_index=fold.fold_index,
                train_range=train_clip,
                validation_range=val_clip,
                purge_start=fold.purge_start,
                purge_end=fold.purge_end,
            )
        )

    return materialized


def materialize_holdout_partition(
    config: SplitConfig,
    available_start: date,
    available_end: date,
) -> HoldoutPartition | None:
    """Materialise the holdout partition against available data range.

    Returns None if no holdout is configured or if the holdout range
    falls entirely outside the available data.
    """
    if config.holdout is None:
        return None

    clipped = _clip_range(
        config.holdout.date_range, DateRange(available_start, available_end)
    )
    if clipped is None:
        return None

    return HoldoutPartition(date_range=clipped)


def _clip_range(
    target: DateRange,
    available: DateRange,
) -> DateRange | None:
    """Clip a target range to available data, returning None if empty after clipping."""
    clipped_start = max(target.start_date, available.start_date)
    clipped_end = min(target.end_date, available.end_date)
    if clipped_start > clipped_end:
        return None
    return DateRange(start_date=clipped_start, end_date=clipped_end)


def build_mount_list_for_fold(
    fold: FoldDefinition,
) -> EvaluatorMountList:
    """Build the evaluator mount list for a single fold (research run).

    The mount list includes the training and validation partitions for
    the given fold.  The holdout partition is explicitly excluded
    (FR-010).

    Parameters
    ----------
    config : SplitConfig
        The split configuration.
    fold : FoldDefinition
        The fold to materialise.

    Returns
    -------
    EvaluatorMountList
        Mount list with train and validation partitions only.
    """
    partitions = (
        MaterializedPartition(
            partition_type=PartitionType.TRAIN,
            fold_index=fold.fold_index,
            date_range=fold.train_range,
            label=f"fold_{fold.fold_index}_train",
        ),
        MaterializedPartition(
            partition_type=PartitionType.VALIDATION,
            fold_index=fold.fold_index,
            date_range=fold.validation_range,
            label=f"fold_{fold.fold_index}_validation",
        ),
    )
    return EvaluatorMountList(partitions=partitions, is_holdout_run=False)


def build_mount_list_for_holdout(
    holdout: HoldoutPartition,
) -> EvaluatorMountList:
    """Build the evaluator mount list for holdout evaluation.

    The mount list includes only the holdout partition.  This list is
    used exactly once per strategy release for final evidence (FR-010).

    Parameters
    ----------
    holdout : HoldoutPartition
        The holdout partition to mount.

    Returns
    -------
    EvaluatorMountList
        Mount list with only the holdout partition.
    """
    partition = MaterializedPartition(
        partition_type=PartitionType.HOLDOUT,
        fold_index=-1,
        date_range=holdout.date_range,
        label="holdout",
    )
    return EvaluatorMountList(partitions=(partition,), is_holdout_run=True)


def build_all_research_mount_lists(
    config: SplitConfig,
    available_start: date,
    available_end: date,
) -> list[EvaluatorMountList]:
    """Build all mount lists for a complete research campaign.

    Returns one mount list per fold (train + validation) for ordinary
    research evaluation.  The holdout mount list is NOT included in
    this list — it must be requested separately to ensure FR-010
    isolation.

    Parameters
    ----------
    config : SplitConfig
        The split configuration.
    available_start, available_end : date
        Available data date range.

    Returns
    -------
    list[EvaluatorMountList]
        One mount list per fold, ordered by fold index.
    """
    folds = materialize_fold_partitions(config, available_start, available_end)
    return [build_mount_list_for_fold(fold) for fold in folds]


def get_allowed_date_ranges(
    mount_list: EvaluatorMountList,
) -> list[DateRange]:
    """Return the date ranges that an evaluator may access.

    This is the core enforcement of FR-010: the evaluator receives
    only these date ranges.  Any access outside these ranges must be
    blocked by the sandbox mount configuration.

    Parameters
    ----------
    mount_list : EvaluatorMountList
        The mount list for the evaluator run.

    Returns
    -------
    list[DateRange]
        Ordered list of permitted date ranges.
    """
    return mount_list.date_ranges()
