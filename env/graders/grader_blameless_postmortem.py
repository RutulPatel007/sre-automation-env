from __future__ import annotations

from typing import Any

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def grade_blameless_postmortem(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    sections = state.get("sections_written", [])
    postmortem = state.get("postmortem_submitted") or {}

    required_sections = ["summary", "timeline", "root_cause", "impact", "action_items"]
    completed = [s for s in required_sections if s in sections]
    section_score = 0.12 * len(completed)

    content_score = 0.0
    for section_name, section_data in postmortem.items():
        content = section_data.get("content", "")
        word_count = section_data.get("word_count", 0)
        if word_count >= 15:
            content_score += 0.04
        elif word_count >= 8:
            content_score += 0.02
    content_score = min(0.2, content_score)

    incident = state["incident"]
    root_cause_section = postmortem.get("root_cause", {})
    root_content = root_cause_section.get("content", "").lower()
    root_keywords = incident["root_cause"].lower().split()
    root_keyword_matches = sum(1 for kw in root_keywords if kw in root_content)
    root_keyword_score = (
        0.1 if root_keyword_matches >= 3 else 0.05 if root_keyword_matches >= 1 else 0.0
    )

    action_items_section = postmortem.get("action_items", {})
    action_content = action_items_section.get("content", "").lower()
    action_items_mentioned = sum(
        1
        for item in incident["action_items"]
        if item["action"].lower().split()[0] in action_content
    )
    action_items_score = 0.08 * min(
        1.0, action_items_mentioned / max(1, len(incident["action_items"]))
    )

    queried_data = len(state.get("queried_data", []))
    evidence_bonus = 0.1 if queried_data >= 3 else 0.05 if queried_data >= 2 else 0.0

    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = (
        section_score
        + content_score
        + root_keyword_score
        + action_items_score
        + evidence_bonus
        - invalid_penalty
    )
    total = _clamp(total)

    breakdown = {
        "sections_completed": completed,
        "section_score": round(section_score, 4),
        "content_score": round(content_score, 4),
        "root_cause_keyword_matches": root_keyword_matches,
        "root_cause_keyword_score": round(root_keyword_score, 4),
        "action_items_coverage": round(
            action_items_mentioned / max(1, len(incident["action_items"])), 4
        ),
        "action_items_score": round(action_items_score, 4),
        "evidence_queries": queried_data,
        "evidence_bonus": round(evidence_bonus, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "Rewards completing all required sections with substantive content, "
            "matching root cause keywords, covering action items, and querying incident data."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
