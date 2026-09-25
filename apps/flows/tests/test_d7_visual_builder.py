"""D7 acceptance: the shipped Visual Builder examples express the real product path."""

from __future__ import annotations

import json

from apps.flows.portability.library import library_path
from apps.flows.schema.nodes import ACTION_VERBS, node_spec


def _template(name: str) -> dict:
    return json.loads((library_path() / name).read_text(encoding="utf-8"))


def _flow(document: dict) -> dict:
    return document["flows"][0]


def test_follow_to_unlock_is_the_native_three_state_follow_gate_flow() -> None:
    flow = _flow(_template("instagram-comment-follow-to-unlock.json"))
    trigger = flow["triggers"][0]
    graph = flow["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["source"], edge["sourceHandle"], edge["target"]) for edge in graph["edges"]}

    assert trigger["type"] == "comment"
    assert trigger["platform"] == "instagram"
    assert trigger["config"]["public_reply"]["mode"] == "random"
    assert trigger["config"]["like_comment"] is False

    assert nodes["opening"]["type"] == "send_message"
    assert nodes["follow_check"] == {
        "id": "follow_check",
        "type": "instagram_follow_gate",
        "config": {"unknown_policy": "ask_again"},
        "position": {"x": 300, "y": 0},
    }
    assert nodes["deliver"]["type"] == "send_message"
    assert nodes["tag_follower"]["type"] == "action"

    assert ("follow_check", "follow:following", "deliver") in edges
    assert ("follow_check", "follow:not_following", "follow_prompt") in edges
    assert ("follow_check", "follow:unknown", "unknown") in edges
    assert ("follow_prompt", "qr:check_again", "follow_check") in edges
    assert ("unknown", "qr:check_again", "follow_check") in edges


def test_handoff_template_uses_the_first_class_terminal_handoff_node() -> None:
    flow = _flow(_template("hand-over-to-a-person.json"))
    graph = flow["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["source"], edge["sourceHandle"], edge["target"]) for edge in graph["edges"]}

    assert nodes["handoff"]["type"] == "human_handoff"
    assert ("flag", "default", "handoff") in edges
    assert not any(source == "handoff" for source, _handle, _target in edges)

    spec = node_spec("human_handoff")
    assert spec is not None
    assert spec.terminal is True
    assert spec.handles == ()


def test_visual_builder_exposes_every_d7_required_capability() -> None:
    """D7's roadmap list is a release contract, not just a template wishlist."""
    required_nodes = {
        "send_message",
        "instagram_follow_gate",
        "condition",
        "action",
        "smart_delay",
        "human_handoff",
    }
    for node_type in required_nodes:
        assert node_spec(node_type) is not None, node_type

    # Tag add/remove and custom-field action are first-class builder actions.
    assert {"add_tag", "remove_tag", "set_field", "clear_field"} <= set(ACTION_VERBS)

    # Branch/end semantics must be drawable without hidden conventions.
    follow = node_spec("instagram_follow_gate")
    assert follow is not None
    assert follow.handles == (
        "follow:following",
        "follow:not_following",
        "follow:unknown",
    )

    delay = node_spec("smart_delay")
    assert delay is not None
    assert delay.handles == ("default",)

    handoff = node_spec("human_handoff")
    assert handoff is not None
    assert handoff.terminal is True
    assert handoff.handles == ()


def test_follow_to_unlock_template_covers_the_opinionated_d7_product_path() -> None:
    flow = _flow(_template("instagram-comment-follow-to-unlock.json"))
    graph = flow["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["source"], edge["sourceHandle"], edge["target"]) for edge in graph["edges"]}

    # Comment -> Public Reply is represented by the comment trigger itself.
    trigger = flow["triggers"][0]
    assert trigger["type"] == "comment"
    assert trigger["platform"] == "instagram"
    assert trigger["config"]["public_reply"]["mode"] != "none"

    # Opening DM -> Follow Check -> Content / Follow Prompt.
    assert nodes["opening"]["type"] == "send_message"
    assert ("opening", "qr:check", "follow_check") in edges
    assert nodes["follow_check"]["type"] == "instagram_follow_gate"
    assert ("follow_check", "follow:following", "deliver") in edges
    assert ("follow_check", "follow:not_following", "follow_prompt") in edges
    assert nodes["deliver"]["type"] == "send_message"
    assert nodes["follow_prompt"]["type"] == "send_message"
