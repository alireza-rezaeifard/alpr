"""Root conftest.py — configures Hypothesis profiles for CI and local development."""
from hypothesis import settings, HealthCheck
from datetime import timedelta

from tests import isolation as _isolation

# Third-party / vendored benchmark checkouts under bench/ contain scripts whose
# filenames match pytest's default python_files patterns ("*_test.py", e.g.
# scripts/smoke_test.py). Importing them at collection time executes module
# level code that calls sys.exit(), which aborts collection with an
# INTERNALERROR -> "mainloop: caught unexpected SystemExit!".
# They are not part of the ALPR test suite, so they are never collected.
collect_ignore_glob = ["bench/*", "bench/**", "benchmarks/audit/*", ".freebuff/*"]

# Directories pytest should consider for collection.
collect_ignore = []


def pytest_configure(config):
    """Make the collected root explicit and install the DB safety boundary."""
    if not getattr(config.option, "testpaths", None):
        config.option.testpaths = ["tests"]
    _isolation.install_guard(config)


def pytest_unconfigure(config):
    """Restore the SQLite/DB factories after the test session."""
    _isolation.restore_guard(config)


# CI profile: fast, strict deadlines, reduced examples
settings.register_profile(
    "ci",
    max_examples=50,
    deadline=timedelta(seconds=30),
    suppress_health_check=[HealthCheck.too_slow],
)

# Default (local dev): more thorough
settings.register_profile(
    "default",
    max_examples=100,
    deadline=timedelta(seconds=60),
)

settings.load_profile("default")
