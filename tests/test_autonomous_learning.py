from neuroliq.autonomous.learning import Policy, corpus, experiment
from neuroliq.autonomous.navigation import Navigator
from neuroliq.autonomous.representation import dumps


def test_learning_changes_cost_not_content_and_exposes_shift():
    result = experiment()
    assert result["before"]["estimates"] == {}
    assert result["after"]["estimates"]["role:0:value"] < result["after"]["estimates"]["predicate"]
    assert result["learning"]["probe_visits"] > 0
    for measurement in result["measurements"]:
        assert all(measurement[mode]["exact_set_accuracy"] == 1 for mode in ("fixed", "learned", "full_scan"))
    assert result["measurements"][-1]["visit_reduction"] > 0.2
    assert result["distribution_shift"]["learned"]["mean_visits"] > result["distribution_shift"]["fixed"]["mean_visits"]
    assert result["split_check"]["target_compound_overlap"] == 0


def test_training_does_not_modify_memory_and_default_is_fixed():
    memory, tasks = corpus("train", 1)
    navigator = Navigator(memory)
    snapshot = dumps(memory.snapshot())
    policy = Policy()
    query = tasks[0]["query"]
    assert navigator.search(query, policy=policy)["cost"]["entry"] == navigator.search(query)["cost"]["entry"]
    policy.fit(navigator, [task["query"] for task in tasks])
    assert dumps(memory.snapshot()) == snapshot
