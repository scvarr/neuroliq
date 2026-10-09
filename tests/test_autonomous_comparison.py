from neuroliq.autonomous.comparison import compare


def test_minimal_counterexamples():
    results = compare()["results"]
    assert not results["adjacency"]["roles"]
    assert not results["route"]["same_name"]
    assert not results["route"]["scope"]
    assert all(results["composition"].values())
