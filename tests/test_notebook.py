import json

from scripts.build_colab_notebook import OUT, notebook


def test_committed_notebook_matches_core():
    """core.py is the single source of the scoring code; regenerate with
    `persocial notebook` after editing it."""
    assert OUT.exists(), "run `persocial notebook`"
    assert json.loads(OUT.read_text(encoding="utf-8")) == json.loads(json.dumps(notebook()))
