import shutil

import pytest

import improve
import metrics
from harness import config
from harness.agent import run_agent
from harness.providers import MockProvider

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (config.VERIFIER_DIR / "dist" / "src" / "verify.js").exists(),
    reason="needs Node and a built verifier",
)


def test_metrics_aggregate_and_prometheus(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    for seed in range(3):
        run_agent("sliding tile puzzle", MockProvider(seed=seed))
    m = metrics.collect(tmp_path)
    assert len(m["ends"]) == 3
    prom = metrics.to_prometheus(m)
    assert 'gamesmith_runs_total{outcome="passed"} 3' in prom
    assert "gamesmith_latency_ms" in prom


def test_failure_report_and_distill(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    results = [run_agent("water jugs", MockProvider(seed=s)) for s in range(6)]
    report = improve.failure_report(results)
    assert report  # mock makes mistakes on some seeds
    rules = MockProvider().distill(report, playbook="")
    assert rules.startswith("- (")
    assert MockProvider().distill(report, playbook=rules) != rules  # never re-proposes existing rules


def test_acceptance_prefers_pass_rate_then_first_try_then_steps():
    base = {"pass_rate": 0.8, "first_try_pass_rate": 0.5, "avg_steps": 5}
    assert improve.score({**base, "pass_rate": 0.9}) > improve.score(base)
    assert improve.score({**base, "first_try_pass_rate": 0.6}) > improve.score(base)
    assert improve.score({**base, "avg_steps": 4}) > improve.score(base)
    assert not improve.score(base) > improve.score(base)
