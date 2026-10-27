"""WP5 golden tests: the evals/arabic_golden.jsonl contract.

`evals/run_eval.py` is the runnable report (prints accuracy); these tests pin the
gated parts (normalize / script / signals >= 95% per review G2.4) and execute the
stub-judge comparison so `pytest -k golden` covers the whole file. The corpus in
examples/sample/ is the full WP5 synthetic set (300 top-level + replies); the
three-file parity test compares the parses against each other, not fixed counts.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

from persocial.config import REPO_ROOT, settings

os.environ.setdefault("PERSOCIAL_PACKS", "generic,gulf_ar")


def _load_run_eval():
    path = REPO_ROOT / "evals" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("wp5_run_eval", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wp5_run_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def golden_result():
    settings.cache_clear()
    os.environ["PERSOCIAL_PACKS"] = "generic,gulf_ar"
    settings.cache_clear()
    try:
        mod = _load_run_eval()
        cases = [json.loads(line) for line in
                 (REPO_ROOT / "evals" / "arabic_golden.jsonl").read_text(
                     encoding="utf-8").splitlines() if line.strip()]
        assert len(cases) == 80, f"golden set must stay ~80 cases, got {len(cases)}"
        return mod.evaluate(cases, mod.build_lexicon())
    finally:
        settings.cache_clear()


def _accuracy(result, part: str) -> float:
    hit, total = result["tallies"][part]
    assert total > 0
    return hit / total


def test_golden_normalize(golden_result):
    assert _accuracy(golden_result, "normalize") >= 0.95, golden_result["failures"][:5]


def test_golden_script(golden_result):
    assert _accuracy(golden_result, "script") >= 0.95, golden_result["failures"][:5]


def test_golden_signals(golden_result):
    assert _accuracy(golden_result, "signals") >= 0.95, golden_result["failures"][:5]


def test_golden_judge_reported(golden_result):
    _hit, total = golden_result["tallies"]["judge"]
    assert total == 80
    assert not golden_result["judge_mismatches"], golden_result["judge_mismatches"][:5]
