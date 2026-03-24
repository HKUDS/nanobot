"""Root pytest configuration — custom CLI options."""


def pytest_addoption(parser):
    parser.addoption("--e2e", action="store_true", default=False, help="Run E2E tests with real LLM")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--e2e"):
        import pytest
        skip_e2e = pytest.mark.skip(reason="Need --e2e flag to run E2E tests")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)
