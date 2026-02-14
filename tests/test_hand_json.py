from __future__ import annotations

import copy

from poker44.core.hand_json import V0_JSON_HAND, from_standard_json


def test_from_standard_json_parses_hand_and_label():
    hand = from_standard_json(V0_JSON_HAND)

    assert hand.metadata.game_type == "Hold'em"
    assert len(hand.participants) == 6
    assert len(hand.actions) > 0
    assert hand.label is False  # V0_JSON_HAND has label="human"

    payload = hand.to_payload()
    assert payload["label"] == "human"


def test_from_standard_json_parses_bot_label():
    bot_payload = copy.deepcopy(V0_JSON_HAND)
    bot_payload["label"] = "bot"
    hand = from_standard_json(bot_payload)
    assert hand.label is True

