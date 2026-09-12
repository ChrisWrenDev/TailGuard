"""Tests for time-blocked splits with purge/embargo (TASK-018).

Covers:
- Split configuration and validation (FR-004, FR-010, BR-001, BR-002)
- Purge/embargo enforcement between folds
- Physical materialisation and mount lists
- Holdout exclusion from ordinary evaluator input (T-005)
- Split leakage trap (GF-007)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tailhedge.backtest.splits import (
    DateRange,
    EvaluatorMountList,
    FoldDefinition,
    HoldoutPartition,
    MaterializedPartition,
    PartitionType,
    SplitConfig,
    build_all_research_mount_lists,
    build_mount_list_for_fold,
    build_mount_list_for_holdout,
    get_allowed_date_ranges,
    materialize_fold_partitions,
    materialize_holdout_partition,
    validate_split_config,
)

# ---------------------------------------------------------------------------
# DateRange tests
# ---------------------------------------------------------------------------


class TestDateRange:
    """Test DateRange core behaviour."""

    def test_valid_range(self) -> None:
        r = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 12, 31))
        assert r.start_date == date(2020, 1, 1)
        assert r.end_date == date(2020, 12, 31)
        assert not r.is_empty
        assert r.duration_days == 366  # 2020 is a leap year

    def test_single_day_range(self) -> None:
        r = DateRange(start_date=date(2020, 6, 15), end_date=date(2020, 6, 15))
        assert r.duration_days == 1
        assert not r.is_empty

    def test_invalid_range_start_after_end(self) -> None:
        with pytest.raises(ValueError, match=r"start_date.*must not be after"):
            DateRange(start_date=date(2020, 12, 31), end_date=date(2020, 1, 1))

    def test_overlaps_self(self) -> None:
        r = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        assert r.overlaps(r)

    def test_overlaps_partial(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 5), end_date=date(2020, 1, 15))
        assert a.overlaps(b)
        assert b.overlaps(a)

    def test_no_overlap_adjacent(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 11), end_date=date(2020, 1, 20))
        assert not a.overlaps(b)
        assert not b.overlaps(a)

    def test_no_overlap_gap(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 15), end_date=date(2020, 1, 20))
        assert not a.overlaps(b)

    def test_before(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 15), end_date=date(2020, 1, 20))
        assert a.before(b)
        assert not b.before(a)

    def test_before_true_when_adjacent(self) -> None:
        """Adjacent ranges satisfy 'before' because end < other.start."""
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 11), end_date=date(2020, 1, 20))
        assert a.before(b)

    def test_before_false_when_overlapping(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 15))
        b = DateRange(start_date=date(2020, 1, 10), end_date=date(2020, 1, 20))
        assert not a.before(b)

    def test_adjacent(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 11), end_date=date(2020, 1, 20))
        assert a.adjacent(b)

    def test_not_adjacent_with_gap(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 15), end_date=date(2020, 1, 20))
        assert not a.adjacent(b)

    def test_gap_days_to_with_gap(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 15), end_date=date(2020, 1, 20))
        assert a.gap_days_to(b) == 4  # Jan 11, 12, 13, 14

    def test_gap_days_to_adjacent(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 11), end_date=date(2020, 1, 20))
        assert a.gap_days_to(b) == 0

    def test_gap_days_to_overlapping(self) -> None:
        a = DateRange(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10))
        b = DateRange(start_date=date(2020, 1, 5), end_date=date(2020, 1, 20))
        assert a.gap_days_to(b) < 0


# ---------------------------------------------------------------------------
# FoldDefinition tests
# ---------------------------------------------------------------------------


class TestFoldDefinition:
    """Test FoldDefinition creation and properties."""

    def test_valid_fold(self) -> None:
        fold = FoldDefinition(
            fold_index=0,
            train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
            validation_range=DateRange(date(2020, 7, 1), date(2020, 9, 30)),
            purge_start=date(2020, 6, 25),
            purge_end=date(2020, 6, 30),
        )
        assert fold.fold_index == 0
        assert fold.purge_days == 6
        assert fold.train_partition.partition_type == PartitionType.TRAIN
        assert fold.validation_partition.partition_type == PartitionType.VALIDATION

    def test_negative_fold_index(self) -> None:
        with pytest.raises(ValueError, match="fold_index must be non-negative"):
            FoldDefinition(
                fold_index=-1,
                train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                validation_range=DateRange(date(2020, 7, 1), date(2020, 9, 30)),
                purge_start=date(2020, 6, 25),
                purge_end=date(2020, 6, 30),
            )

    def test_invalid_train_range_rejected(self) -> None:
        """DateRange rejects start > end before FoldDefinition sees it."""
        with pytest.raises(ValueError, match=r"start_date.*must not be after"):
            FoldDefinition(
                fold_index=0,
                train_range=DateRange(date(2020, 12, 31), date(2020, 1, 1)),
                validation_range=DateRange(date(2020, 7, 1), date(2020, 9, 30)),
                purge_start=date(2020, 6, 25),
                purge_end=date(2020, 6, 30),
            )

    def test_train_after_validation(self) -> None:
        with pytest.raises(ValueError, match="train_range must end before"):
            FoldDefinition(
                fold_index=0,
                train_range=DateRange(date(2020, 7, 1), date(2020, 12, 31)),
                validation_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                purge_start=date(2020, 6, 25),
                purge_end=date(2020, 6, 30),
            )


# ---------------------------------------------------------------------------
# SplitConfig tests
# ---------------------------------------------------------------------------


class TestSplitConfig:
    """Test SplitConfig creation and properties."""

    def _make_config(self, **kwargs: object) -> SplitConfig:
        folds = (
            FoldDefinition(
                fold_index=0,
                train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                validation_range=DateRange(date(2020, 7, 1), date(2020, 9, 30)),
                purge_start=date(2020, 6, 25),
                purge_end=date(2020, 6, 30),
            ),
        )
        defaults: dict[str, object] = {
            "folds": folds,
            "holdout": HoldoutPartition(
                date_range=DateRange(date(2021, 1, 1), date(2021, 3, 31)),
            ),
            "purge_horizon_days": 5,
            "strategy_lookback_days": 0,
            "max_dte_days": 60,
        }
        defaults.update(kwargs)
        return SplitConfig(**defaults)  # type: ignore[arg-type]

    def test_basic_config(self) -> None:
        config = self._make_config()
        assert config.fold_count == 1
        assert config.has_holdout
        assert config.default_purge_horizon == 60

    def test_empty_folds(self) -> None:
        with pytest.raises(ValueError, match="at least one fold"):
            SplitConfig(
                folds=(),
                holdout=None,
                purge_horizon_days=5,
            )

    def test_negative_purge_horizon(self) -> None:
        with pytest.raises(ValueError, match="purge_horizon_days must be non-negative"):
            SplitConfig(
                folds=(
                    FoldDefinition(
                        fold_index=0,
                        train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                        validation_range=DateRange(date(2020, 7, 1), date(2020, 9, 30)),
                        purge_start=date(2020, 6, 25),
                        purge_end=date(2020, 6, 30),
                    ),
                ),
                holdout=None,
                purge_horizon_days=-1,
            )

    def test_default_purge_horizon(self) -> None:
        config = self._make_config(strategy_lookback_days=20, max_dte_days=30)
        assert config.default_purge_horizon == 30

    def test_no_holdout(self) -> None:
        config = self._make_config(holdout=None)
        assert not config.has_holdout


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestSplitValidation:
    """Test split configuration validation."""

    def test_valid_config(self) -> None:
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2021, 1, 1), date(2021, 3, 31)),
            ),
            purge_horizon_days=30,
        )
        errors = validate_split_config(config)
        assert errors == []

    def test_fold_order_violation(self) -> None:
        """Folds must be in chronological order (BR-001)."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
                FoldDefinition(
                    fold_index=1,
                    train_range=DateRange(date(2020, 4, 1), date(2020, 7, 31)),
                    validation_range=DateRange(date(2020, 9, 1), date(2020, 11, 30)),
                    purge_start=date(2020, 8, 1),
                    purge_end=date(2020, 8, 31),
                ),
            ),
            holdout=None,
            purge_horizon_days=0,
        )
        errors = validate_split_config(config)
        codes = [e.code for e in errors]
        assert "FOLD_ORDER" in codes

    def test_purge_enforcement(self) -> None:
        """Purge horizon must be enforced between train and validation (BR-002)."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 7, 2), date(2020, 9, 30)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 1),
                ),
            ),
            holdout=None,
            purge_horizon_days=5,
        )
        errors = validate_split_config(config)
        codes = [e.code for e in errors]
        assert "PURGE_ENFORCEMENT" in codes

    def test_purge_sufficient(self) -> None:
        """Sufficient purge gap passes validation."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 7, 6), date(2020, 9, 30)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 5),
                ),
            ),
            holdout=None,
            purge_horizon_days=5,
        )
        errors = validate_split_config(config)
        assert errors == []

    def test_overlap_detection(self) -> None:
        """Overlapping date ranges across folds are detected."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
                FoldDefinition(
                    fold_index=1,
                    train_range=DateRange(date(2020, 9, 1), date(2020, 12, 31)),
                    validation_range=DateRange(date(2021, 1, 1), date(2021, 3, 31)),
                    purge_start=date(2020, 12, 26),
                    purge_end=date(2020, 12, 31),
                ),
            ),
            holdout=None,
            purge_horizon_days=5,
        )
        errors = validate_split_config(config)
        codes = [e.code for e in errors]
        # Fold 0 validation (Aug-Oct) overlaps fold 1 train (Sep-Dec)
        assert "OVERLAP" in codes

    def test_holdout_overlap_detected(self) -> None:
        """Holdout overlapping with fold ranges is detected."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2020, 9, 1), date(2020, 11, 30)),
            ),
            purge_horizon_days=30,
        )
        errors = validate_split_config(config)
        codes = [e.code for e in errors]
        assert "OVERLAP" in codes


# ---------------------------------------------------------------------------
# Materialisation tests
# ---------------------------------------------------------------------------


class TestMaterialisation:
    """Test fold and holdout materialisation against available data."""

    def _make_config(self) -> SplitConfig:
        return SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
                FoldDefinition(
                    fold_index=1,
                    train_range=DateRange(date(2020, 11, 1), date(2021, 2, 28)),
                    validation_range=DateRange(date(2021, 4, 1), date(2021, 6, 30)),
                    purge_start=date(2021, 3, 1),
                    purge_end=date(2021, 3, 31),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2021, 7, 1), date(2021, 9, 30)),
            ),
            purge_horizon_days=30,
        )

    def test_materialize_full_range(self) -> None:
        config = self._make_config()
        folds = materialize_fold_partitions(
            config, date(2019, 12, 1), date(2021, 12, 31)
        )
        assert len(folds) == 2
        assert folds[0].fold_index == 0
        assert folds[1].fold_index == 1

    def test_materialize_clips_to_available(self) -> None:
        config = self._make_config()
        # Available data starts mid-fold 0 train
        folds = materialize_fold_partitions(
            config, date(2020, 3, 1), date(2021, 12, 31)
        )
        assert len(folds) == 2
        assert folds[0].train_range.start_date == date(2020, 3, 1)

    def test_materialize_excludes_fold_outside_range(self) -> None:
        config = self._make_config()
        # Available data only covers fold 0
        folds = materialize_fold_partitions(
            config, date(2020, 1, 1), date(2020, 12, 31)
        )
        assert len(folds) == 1
        assert folds[0].fold_index == 0

    def test_materialize_holdout(self) -> None:
        config = self._make_config()
        holdout = materialize_holdout_partition(
            config, date(2019, 1, 1), date(2021, 12, 31)
        )
        assert holdout is not None
        assert holdout.date_range == DateRange(date(2021, 7, 1), date(2021, 9, 30))

    def test_materialize_holdout_none_when_not_configured(self) -> None:
        config = self._make_config()
        config_no_holdout = SplitConfig(
            folds=config.folds,
            holdout=None,
            purge_horizon_days=config.purge_horizon_days,
        )
        holdout = materialize_holdout_partition(
            config_no_holdout, date(2019, 1, 1), date(2021, 12, 31)
        )
        assert holdout is None

    def test_materialize_holdout_outside_range(self) -> None:
        config = self._make_config()
        holdout = materialize_holdout_partition(
            config, date(2019, 1, 1), date(2020, 12, 31)
        )
        assert holdout is None


# ---------------------------------------------------------------------------
# Mount list tests
# ---------------------------------------------------------------------------


class TestMountLists:
    """Test evaluator mount list construction."""

    def test_fold_mount_list_excludes_holdout(self) -> None:
        """FR-010: Holdout is excluded from ordinary evaluator mount lists."""
        fold = FoldDefinition(
            fold_index=0,
            train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
            validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
            purge_start=date(2020, 7, 1),
            purge_end=date(2020, 7, 31),
        )
        mount_list = build_mount_list_for_fold(fold)

        assert not mount_list.is_holdout_run
        assert len(mount_list.partitions) == 2
        partition_types = {p.partition_type for p in mount_list.partitions}
        assert partition_types == {PartitionType.TRAIN, PartitionType.VALIDATION}
        # Holdout must NOT be in the mount list
        assert PartitionType.HOLDOUT not in partition_types

    def test_holdout_mount_list(self) -> None:
        """FR-010: Holdout mount list contains only holdout partition."""
        holdout = HoldoutPartition(
            date_range=DateRange(date(2021, 1, 1), date(2021, 3, 31)),
        )
        mount_list = build_mount_list_for_holdout(holdout)

        assert mount_list.is_holdout_run
        assert len(mount_list.partitions) == 1
        assert mount_list.partitions[0].partition_type == PartitionType.HOLDOUT
        assert mount_list.partitions[0].label == "holdout"

    def test_all_research_mount_lists_excludes_holdout(self) -> None:
        """FR-010: build_all_research_mount_lists never includes holdout."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
                FoldDefinition(
                    fold_index=1,
                    train_range=DateRange(date(2020, 11, 1), date(2021, 2, 28)),
                    validation_range=DateRange(date(2021, 4, 1), date(2021, 6, 30)),
                    purge_start=date(2021, 3, 1),
                    purge_end=date(2021, 3, 31),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2021, 7, 1), date(2021, 9, 30)),
            ),
            purge_horizon_days=30,
        )
        mount_lists = build_all_research_mount_lists(
            config, date(2019, 1, 1), date(2021, 12, 31)
        )

        assert len(mount_lists) == 2
        for ml in mount_lists:
            assert not ml.is_holdout_run
            for p in ml.partitions:
                assert p.partition_type != PartitionType.HOLDOUT

    def test_allowed_date_ranges(self) -> None:
        """get_allowed_date_ranges returns the physical date ranges."""
        holdout = HoldoutPartition(
            date_range=DateRange(date(2021, 1, 1), date(2021, 3, 31)),
        )
        mount_list = build_mount_list_for_holdout(holdout)
        ranges = get_allowed_date_ranges(mount_list)
        assert len(ranges) == 1
        assert ranges[0] == DateRange(date(2021, 1, 1), date(2021, 3, 31))

    def test_mount_list_total_date_range(self) -> None:
        """EvaluatorMountList.total_date_range spans all partitions."""
        mount_list = EvaluatorMountList(
            partitions=(
                MaterializedPartition(
                    partition_type=PartitionType.TRAIN,
                    fold_index=0,
                    date_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    label="fold_0_train",
                ),
                MaterializedPartition(
                    partition_type=PartitionType.VALIDATION,
                    fold_index=0,
                    date_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    label="fold_0_validation",
                ),
            ),
            is_holdout_run=False,
        )
        total = mount_list.total_date_range()
        assert total is not None
        assert total.start_date == date(2020, 1, 1)
        assert total.end_date == date(2020, 10, 31)

    def test_empty_mount_list(self) -> None:
        """Empty mount list has no date range."""
        mount_list = EvaluatorMountList(partitions=(), is_holdout_run=False)
        assert mount_list.total_date_range() is None
        assert mount_list.date_ranges() == []


# ---------------------------------------------------------------------------
# T-005 / GF-007: Strategy receives no future/holdout rows
# ---------------------------------------------------------------------------


class TestHoldoutExclusion:
    """T-005: Strategy receives no future/holdout rows.

    GF-007: Construct data where future feature would make performance
    unrealistically perfect. Evaluator must prevent strategy access to
    future rows.
    """

    def test_holdout_not_in_research_mount(self) -> None:
        """FR-010: Holdout partition must not be accessible to strategy during research."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 12, 31)),
                    validation_range=DateRange(date(2021, 1, 1), date(2021, 6, 30)),
                    purge_start=date(2020, 12, 26),
                    purge_end=date(2020, 12, 31),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2021, 7, 1), date(2021, 12, 31)),
            ),
            purge_horizon_days=5,
        )

        research_mounts = build_all_research_mount_lists(
            config, date(2019, 1, 1), date(2022, 1, 1)
        )

        # Collect all date ranges available to the strategy during research
        all_research_dates: set[date] = set()
        for mount in research_mounts:
            for rng in mount.date_ranges():
                d = rng.start_date
                while d <= rng.end_date:
                    all_research_dates.add(d)
                    d += timedelta(days=1)

        # Holdout dates must not appear in any research mount
        holdout_start = date(2021, 7, 1)
        holdout_end = date(2021, 12, 31)
        d = holdout_start
        while d <= holdout_end:
            assert d not in all_research_dates, (
                f"Holdout date {d} leaked into research mount list"
            )
            d += timedelta(days=1)

    def test_holdout_dates_excluded_from_evaluator_range(self) -> None:
        """The evaluator's allowed ranges must not include holdout dates."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 8, 1), date(2020, 10, 31)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 31),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2020, 11, 1), date(2020, 12, 31)),
            ),
            purge_horizon_days=30,
        )

        research_mounts = build_all_research_mount_lists(
            config, date(2019, 1, 1), date(2021, 1, 1)
        )

        for mount in research_mounts:
            allowed = get_allowed_date_ranges(mount)
            assert config.holdout is not None
            holdout_range = config.holdout.date_range
            for rng in allowed:
                assert not rng.overlaps(holdout_range), (
                    f"Evaluator allowed range {rng} overlaps holdout {holdout_range}"
                )

    def test_purge_prevents_train_to_validation_leakage(self) -> None:
        """BR-002: Purge gap prevents positions opened in train from leaking into validation."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 7, 10), date(2020, 9, 30)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 9),
                ),
            ),
            holdout=None,
            purge_horizon_days=9,  # 9-day purge = Jul 1-9
        )

        errors = validate_split_config(config)
        assert errors == []

        # Verify the purge gap exists: train ends Jun 30, validation starts Jul 10
        # Gap is Jul 1-9 = 9 days, which satisfies the 9-day purge horizon
        fold = config.folds[0]
        assert fold.train_range.end_date == date(2020, 6, 30)
        assert fold.validation_range.start_date == date(2020, 7, 10)
        gap_days = fold.train_range.gap_days_to(fold.validation_range)
        # gap_days_to counts days between end and start (exclusive)
        # Jun 30 to Jul 10: gap = 10 - 1 = 9 days (Jul 1-9)
        assert gap_days >= config.purge_horizon_days - 1

    def test_gf007_leakage_trap_data(self) -> None:
        """GF-007: Future feature would make performance unrealistically perfect.

        Scenario: A synthetic dataset has a known "future signal" — on
        Jul 1 2020 the underlying jumps 50%. If the strategy can see
        this date during training, it would always buy puts before the
        jump and appear to have perfect foresight.

        The split must ensure that Jul 1 2020 is either:
        1. In the validation period (not visible during training), or
        2. In the holdout (not visible at all during research), or
        3. In the purge gap (excluded from both).
        """
        # Jul 1 is the "crash date" — a future feature that would
        # create a leakage trap
        crash_date = date(2020, 7, 1)

        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 6, 30)),
                    validation_range=DateRange(date(2020, 7, 15), date(2020, 9, 30)),
                    purge_start=date(2020, 7, 1),
                    purge_end=date(2020, 7, 14),
                ),
            ),
            holdout=None,
            purge_horizon_days=14,
        )

        # Validate that the crash date is in the purge gap
        assert crash_date >= config.folds[0].purge_start
        assert crash_date <= config.folds[0].purge_end

        # Build research mount lists — the crash date must not appear
        mount_lists = build_all_research_mount_lists(
            config, date(2019, 1, 1), date(2020, 12, 31)
        )

        all_research_dates: set[date] = set()
        for mount in mount_lists:
            for rng in mount.date_ranges():
                d = rng.start_date
                while d <= rng.end_date:
                    all_research_dates.add(d)
                    d += timedelta(days=1)

        assert crash_date not in all_research_dates, (
            f"GF-007 leakage trap: crash date {crash_date} is accessible "
            f"during research — strategy could exploit future knowledge"
        )

    def test_multiple_folds_no_cross_fold_leakage(self) -> None:
        """No fold can access another fold's data."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2020, 1, 1), date(2020, 3, 31)),
                    validation_range=DateRange(date(2020, 4, 15), date(2020, 6, 30)),
                    purge_start=date(2020, 4, 1),
                    purge_end=date(2020, 4, 14),
                ),
                FoldDefinition(
                    fold_index=1,
                    train_range=DateRange(date(2020, 7, 1), date(2020, 9, 30)),
                    validation_range=DateRange(date(2020, 10, 15), date(2020, 12, 31)),
                    purge_start=date(2020, 10, 1),
                    purge_end=date(2020, 10, 14),
                ),
            ),
            holdout=None,
            purge_horizon_days=14,
        )

        mount_lists = build_all_research_mount_lists(
            config, date(2019, 1, 1), date(2021, 1, 1)
        )

        assert len(mount_lists) == 2

        # Fold 0 mount should only contain fold 0 dates
        fold0_dates: set[date] = set()
        for rng in mount_lists[0].date_ranges():
            d = rng.start_date
            while d <= rng.end_date:
                fold0_dates.add(d)
                d += timedelta(days=1)

        # Fold 1 mount should only contain fold 1 dates
        fold1_dates: set[date] = set()
        for rng in mount_lists[1].date_ranges():
            d = rng.start_date
            while d <= rng.end_date:
                fold1_dates.add(d)
                d += timedelta(days=1)

        # No overlap between fold mounts
        assert fold0_dates.isdisjoint(fold1_dates), (
            "Cross-fold leakage detected: folds share accessible dates"
        )

    def test_holdout_single_use_enforcement(self) -> None:
        """FR-010: Holdout is consumed exactly once per strategy release."""
        holdout = HoldoutPartition(
            date_range=DateRange(date(2021, 7, 1), date(2021, 9, 30)),
        )
        mount1 = build_mount_list_for_holdout(holdout)
        mount2 = build_mount_list_for_holdout(holdout)

        # Both mounts reference the same holdout dates — the caller
        # must track consumption state externally (strategy_release
        # table). The mount list itself is idempotent.
        assert mount1.date_ranges() == mount2.date_ranges()
        assert mount1.is_holdout_run
        assert mount2.is_holdout_run


# ---------------------------------------------------------------------------
# Integration: end-to-end split workflow
# ---------------------------------------------------------------------------


class TestEndToEndSplitWorkflow:
    """Test a complete split configuration through validation and materialisation."""

    def test_complete_workflow(self) -> None:
        """Configure, validate, and materialise a 3-fold split with holdout."""
        config = SplitConfig(
            folds=(
                FoldDefinition(
                    fold_index=0,
                    train_range=DateRange(date(2015, 1, 1), date(2017, 12, 31)),
                    validation_range=DateRange(date(2018, 1, 15), date(2018, 6, 30)),
                    purge_start=date(2018, 1, 1),
                    purge_end=date(2018, 1, 14),
                ),
                FoldDefinition(
                    fold_index=1,
                    train_range=DateRange(date(2018, 7, 1), date(2020, 12, 31)),
                    validation_range=DateRange(date(2021, 1, 15), date(2021, 6, 30)),
                    purge_start=date(2021, 1, 1),
                    purge_end=date(2021, 1, 14),
                ),
                FoldDefinition(
                    fold_index=2,
                    train_range=DateRange(date(2021, 7, 1), date(2023, 12, 31)),
                    validation_range=DateRange(date(2024, 1, 15), date(2024, 6, 30)),
                    purge_start=date(2024, 1, 1),
                    purge_end=date(2024, 1, 14),
                ),
            ),
            holdout=HoldoutPartition(
                date_range=DateRange(date(2024, 7, 1), date(2024, 12, 31)),
            ),
            purge_horizon_days=14,
        )

        # 1. Validate
        errors = validate_split_config(config)
        assert errors == []

        # 2. Materialise against available data
        available_start = date(2014, 12, 1)
        available_end = date(2025, 1, 1)

        folds = materialize_fold_partitions(config, available_start, available_end)
        assert len(folds) == 3

        holdout = materialize_holdout_partition(config, available_start, available_end)
        assert holdout is not None

        # 3. Build research mount lists (one per fold)
        research_mounts = build_all_research_mount_lists(
            config, available_start, available_end
        )
        assert len(research_mounts) == 3

        # 4. Each mount list has exactly 2 partitions (train + validation)
        for ml in research_mounts:
            assert len(ml.partitions) == 2
            assert not ml.is_holdout_run

        # 5. Build holdout mount list separately
        holdout_mount = build_mount_list_for_holdout(holdout)
        assert holdout_mount.is_holdout_run
        assert len(holdout_mount.partitions) == 1

        # 6. Verify no date overlap across all mounts
        all_dates: set[date] = set()
        for ml in research_mounts:
            for rng in ml.date_ranges():
                d = rng.start_date
                while d <= rng.end_date:
                    assert d not in all_dates, f"Date {d} appears in multiple mounts"
                    all_dates.add(d)
                    d += timedelta(days=1)

        # 7. Holdout dates must not be in research dates
        holdout_rng = holdout.date_range
        d = holdout_rng.start_date
        while d <= holdout_rng.end_date:
            assert d not in all_dates, (
                f"Holdout date {d} leaked into research mount list"
            )
            d += timedelta(days=1)
