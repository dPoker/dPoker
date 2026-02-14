"""
Reward and scoring utilities for poker44 poker bot detection.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import torch
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score


def reward(y_pred: np.ndarray, y_true: np.ndarray) -> tuple[float, dict]:
    """
    Compute a reward based on F1, average precision and false-positive control.
    """
    y_pred = np.asarray(y_pred)
    y_true = np.asarray(y_true)

    # Empty windows can happen early on (or on missing miner responses). Treat as no-signal.
    if y_pred.size == 0 or y_true.size == 0:
        res = {"fp_score": 0.0, "f1_score": 0.0, "ap_score": 0.0}
        return 0.0, res

    # Defensive: mismatched lengths means we can't compute meaningful metrics.
    if y_pred.shape[0] != y_true.shape[0]:
        res = {"fp_score": 0.0, "f1_score": 0.0, "ap_score": 0.0}
        return 0.0, res

    preds = np.round(y_pred).astype(int)
    cm = confusion_matrix(y_true, preds, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    f1 = f1_score(y_true, preds) if (tp + fp) > 0 else 0.0
    ap_score = average_precision_score(y_true, y_pred) if y_pred.size else 0.0

    res = {
        "fp_score": 1 - fp / max(len(y_pred), 1),
        "f1_score": f1,
        "ap_score": ap_score,
    }
    rew = sum(res.values()) / len(res)
    return rew, res
