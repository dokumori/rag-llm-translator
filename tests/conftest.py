"""
Root conftest.py
----------------
Applies the `integration` mark automatically to any test discovered under the
`integration/` directory and skips those tests when running locally (i.e. when
the ChromaDB Docker container is not reachable).

To force-run integration tests locally (containers must be up):
    pytest --run-integration
"""

import os
import pytest


# ---------------------------------------------------------------------------
# Mark registration — must happen before collection so pytest never warns
# about an "Unknown mark".  pytest_configure runs regardless of rootdir,
# so this works both locally (rootdir = tests/) and inside Docker
# (rootdir = /app/).
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require the Docker stack "
        "(deselect with '-m \"not integration\"')",
    )


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests that require the Docker stack (ChromaDB, rag-proxy).",
    )


# ---------------------------------------------------------------------------
# Auto-mark integration tests
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    """
    Any test whose file lives under a path containing '/integration/' is
    automatically tagged with @pytest.mark.integration.

    If --run-integration was NOT passed (the default), those tests are
    skipped with a clear message.
    """
    run_integration = config.getoption("--run-integration")
    skip_marker = pytest.mark.skip(
        reason="Integration test — requires Docker stack. Pass --run-integration to enable."
    )

    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            if not run_integration:
                item.add_marker(skip_marker)
