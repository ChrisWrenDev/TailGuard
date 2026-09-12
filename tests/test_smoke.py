"""Smoke tests verifying the package bootstraps correctly."""

import importlib


def test_package_imports() -> None:
    """tailhedge package is importable and exposes a version."""
    import tailhedge

    assert hasattr(tailhedge, "__version__")
    assert isinstance(tailhedge.__version__, str)


def test_version_is_semver() -> None:
    """Version string follows basic semver."""
    import tailhedge

    parts = tailhedge.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_subpackages_importable() -> None:
    """Key subpackages can be imported without side effects."""
    modules = [
        "tailhedge.domain",
        "tailhedge.data",
        "tailhedge.backtest",
        "tailhedge.research",
        "tailhedge.broker",
        "tailhedge.operations",
        "tailhedge.persistence",
        "tailhedge.jobs",
        "tailhedge.web",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None
