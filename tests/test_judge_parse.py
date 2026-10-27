from persocial.judge.client import salvage

# Verbatim qwen3.5-4b output that failed json.loads (reasons dropped, "}" closing entries).
RAW_4B = ('{"1": ["keep", "spam_fun", 0, 1.0], "2": ["keep", "grief", 0, 1.0], '
          '"3": ["review", "appeal", 2, 0.95], "6": ["keep", "grievance", 1, 0.9}, '
          '"7": ["hide", "sectarian", 3, 1.0], "9": ["review", "political_criticism", 2, 0.9}, '
          '"10": ["review", "political_criticism", 2, 0.9}]')


def test_salvage_recovers_malformed_small_model_output():
    ids = {str(i): f"c{i}" for i in range(1, 11)}
    out = salvage(RAW_4B, ids)
    assert set(out) == {"c1", "c2", "c3", "c6", "c7", "c9", "c10"}
    assert out["c6"] == {"verdict": "keep", "category": "grievance", "severity": 1,
                         "confidence": 0.9, "reason": ""}
    assert out["c7"]["verdict"] == "hide" and out["c7"]["severity"] == 3


def test_salvage_full_entries_and_unknown_ids():
    raw = '{"1": ["hide", "insult", 3, 0.8, "slur"], "99": ["keep", "none", 0, 1.0, "x"]}'
    assert salvage(raw, {"1": "a"}) == {"a": {"verdict": "hide", "category": "insult",
                                              "severity": 3, "confidence": 0.8, "reason": "slur"}}
