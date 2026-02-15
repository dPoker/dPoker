from __future__ import annotations


def majority_quorum(total_validators: int) -> int:
    """
    Majority quorum for attesting a subject from the perspective of a fixed validator set.

    We count votes from *other* validators (exclude the subject itself).

    Examples:
    - total=2 -> other=1 -> quorum=1
    - total=6 -> other=5 -> quorum=3
    - total=7 -> other=6 -> quorum=4
    """

    n = max(0, int(total_validators))
    others = max(0, n - 1)
    # floor(others/2)+1
    return (others // 2) + (1 if others > 0 else 0)

