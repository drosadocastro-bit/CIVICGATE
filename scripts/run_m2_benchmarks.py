"""Generate Milestone 2 benchmark artifacts without live credentials."""

from civicgate.evaluation.benchmarks import write_reports

if __name__ == "__main__":
    write_reports()
    print(
        "Wrote artifacts/granite-agent-benchmark.json, artifacts/judge-benchmark.json, artifacts/hybrid-evaluation.json"
    )
