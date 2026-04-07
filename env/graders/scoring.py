from __future__ import annotations

MIN_TASK_SCORE = 0.0001
MAX_TASK_SCORE = 0.9999


def clamp_task_score(value: float) -> float:
    """Clamp scores to a strict open interval (0, 1) with stable precision."""
    return max(MIN_TASK_SCORE, min(MAX_TASK_SCORE, round(float(value), 4)))