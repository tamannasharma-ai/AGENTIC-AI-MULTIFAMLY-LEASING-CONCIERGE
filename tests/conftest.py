import pytest


@pytest.fixture(autouse=True)
def disable_external_analytics(monkeypatch):
    """UI tests must never write analytics into the configured demo database."""
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("ANALYTICS_MODE", "test")
    monkeypatch.setenv("DEMO_CONTROLS", "false")
