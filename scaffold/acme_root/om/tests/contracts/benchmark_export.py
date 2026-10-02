"""What the benchmark job keeps beyond its runner. Its stack goes with the
runner, so each case hands what it recorded to the export: every
benchmark, with each trial's verdict, the hidden suite's runs, and the
cost, and the model matrix's rows it fed. The job's end writes them to one
file, which the workflow uploads with the run, and each qualification
cites the run that holds it."""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from acme.om.benchmarks.types.benchmark import Benchmark
from acme.om.matrix.types.record import BenchmarkResult

FOLDER = "BENCHMARK_EXPORT"
"""The folder the export is written to, which the workflow uploads."""

RUN_URL = "BENCHMARK_RUN_URL"
"""The address each qualification cites: the job's run, which holds the
export. Unset, as on a person's machine, the export file's own address."""


@dataclass
class Export:
    """The file the job writes, the address its qualifications cite, and
    what the cases kept."""

    path: Path
    run: str
    benchmarks: list[Benchmark] = field(default_factory=list)
    results: list[BenchmarkResult] = field(default_factory=list)

    @classmethod
    def at(cls, fallback: Path) -> Export:
        """The export the environment names, or one in `fallback`."""
        folder = os.environ.get(FOLDER)
        path = ((Path(folder) if folder else fallback) / "benchmarks.json").resolve()
        return cls(path=path, run=os.environ.get(RUN_URL) or path.as_uri())

    def keep(self, benchmark: Benchmark, results: Sequence[BenchmarkResult]) -> None:
        self.benchmarks.append(benchmark)
        self.results.extend(results)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "run": self.run,
            "benchmarks": [found.model_dump(mode="json") for found in self.benchmarks],
            "matrix_results": [found.model_dump(mode="json") for found in self.results],
        }
        self.path.write_text(json.dumps(document, indent=2))
