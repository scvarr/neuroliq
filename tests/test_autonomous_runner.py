from pathlib import Path
import json
import subprocess
import sys
import pytest
from neuroliq.autonomous.learning import Policy, corpus
from neuroliq.autonomous.memory import Memory, evidence
from neuroliq.autonomous.navigation import Navigator, Query
from neuroliq.autonomous.representation import Invalid, cid
from neuroliq.autonomous.runner import demo, peak_rss


def test_independent_gold_and_persistent_vertical_slice(tmp_path):
    report = demo(tmp_path)
    assert all(group["passed"] == group["total"] for group in report["groups"].values())
    assert report["expressions"][0]["ru"] == "Мария дала книгу Игорю."
    assert report["python_probe"]["supported"] is False
    assert peak_rss() < 512 * 1024 * 1024
    assert report["export"]["roundtrip_failures"] == 0
    command = subprocess.run([sys.executable, "-m", "neuroliq.autonomous", "query", "--memory", str(tmp_path / "memory.json"),
                              "--request", str(tmp_path / "query.json"), "--output", str(tmp_path / "answer.json")], capture_output=True, timeout=10)
    assert command.returncode == 0, command.stderr.decode("utf-8", errors="replace")
    answer = json.loads((tmp_path / "answer.json").read_text(encoding="utf-8"))
    assert len(answer["results"]) == 3


def test_no_training_on_test_and_no_stale_index():
    memory, tasks = corpus("test", 0)
    navigator = Navigator(memory)
    with pytest.raises(Invalid, match="train"):
        Policy().fit(navigator, [task["query"] for task in tasks])
    memory.context("new")
    with pytest.raises(Invalid, match="Память изменилась"):
        navigator.search(tasks[0]["query"])
