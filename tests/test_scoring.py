import numpy as np

from poker44.score.scoring import reward


def test_reward_perfect_predictions():
    y_true = np.asarray([0, 1, 0, 1], dtype=int)
    y_pred = np.asarray([0.1, 0.9, 0.2, 0.8], dtype=float)

    rew, metrics = reward(y_pred, y_true)

    assert metrics["fp_score"] == 1.0
    assert metrics["f1_score"] == 1.0
    assert metrics["ap_score"] == 1.0
    assert rew == 1.0


def test_reward_empty_predictions():
    y_true = np.asarray([], dtype=int)
    y_pred = np.asarray([], dtype=float)

    rew, metrics = reward(y_pred, y_true)

    assert metrics["ap_score"] == 0.0
    assert rew >= 0.0

