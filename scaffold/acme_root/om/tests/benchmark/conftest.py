"""The benchmark job's export, one for the whole job: every case keeps what
it recorded in it, and the job's end writes it, whatever the cases
showed, so a run that regressed or failed is kept as well."""

from collections.abc import Iterator

import pytest
from contracts.benchmark_export import Export


@pytest.fixture(scope="session")
def export(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Export]:
    kept = Export.at(tmp_path_factory.mktemp("benchmark-export"))
    yield kept
    kept.write()
    print(
        f"\nbenchmark export: {kept.path}, {len(kept.benchmarks)} benchmark(s), cited as {kept.run}"
    )
