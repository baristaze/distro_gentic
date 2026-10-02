from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from host_support import Stack, stack


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    async with stack(tmp_path) as running:
        yield running
