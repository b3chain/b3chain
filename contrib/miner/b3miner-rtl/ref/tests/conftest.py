"""pytest config: prepend `ref/` to sys.path so `import b3pow_ref` works."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: full 2048-iteration reduced-memory floor measurement",
    )
