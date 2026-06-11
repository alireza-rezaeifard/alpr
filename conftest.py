"""Root conftest.py — configures Hypothesis profiles for CI and local development."""
from hypothesis import settings, HealthCheck
from datetime import timedelta

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
