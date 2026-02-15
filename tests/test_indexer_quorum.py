from poker44.p2p.indexer.quorum import majority_quorum


def test_majority_quorum_examples():
    assert majority_quorum(0) == 0
    assert majority_quorum(1) == 0  # no "other validators" exist
    assert majority_quorum(2) == 1
    assert majority_quorum(3) == 2
    assert majority_quorum(6) == 3
    assert majority_quorum(7) == 4
