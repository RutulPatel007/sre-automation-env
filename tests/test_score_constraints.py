from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import inference
from env.models import SREAction
from env.sre_env import SREEnv


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class ScoreConstraintTests(unittest.TestCase):
    def test_format_task_score_keeps_boundaries_open(self):
        self.assertEqual(inference._format_task_score(0.0), "0.0001")
        self.assertEqual(inference._format_task_score(1.0), "0.9999")
        self.assertEqual(inference._format_task_score(None), "0.0001")

    def test_run_episode_emits_open_interval_score_even_if_upstream_rounds_to_edge(self):
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"action_type":"resolve","target":"noop","parameters":{},"reasoning":"finish"}'
                    )
                )
            ]
        )

        reset_payload = {
            "session_id": "session-1",
            "task_id": "alert_triage",
            "step": 0,
            "context": {},
            "available_actions": ["resolve"],
            "alert_queue": [],
            "service_map": {},
            "metrics": {},
            "logs": [],
            "done": False,
            "message": "ready",
        }

        step_payload = {
            "observation": {**reset_payload, "step": 1, "done": True},
            "reward": {"value": 1.0, "breakdown": {}, "done": True, "info": {}},
            "done": True,
            "info": {"cumulative_score": 1.0},
        }

        with patch("inference.httpx.post") as mock_post, patch.object(
            inference.client.chat.completions, "create", return_value=completion
        ):
            mock_post.side_effect = [
                _FakeResponse(reset_payload),
                _FakeResponse(step_payload),
            ]
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                score = inference.run_episode("alert_triage")

        self.assertEqual(score, 0.9999)
        self.assertIn("score=0.9999", stdout.getvalue())
        self.assertNotIn("score=1.0000", stdout.getvalue())

    def test_env_rewards_and_cumulative_scores_stay_inside_open_interval(self):
        for task_id in inference.TASKS:
            with self.subTest(task_id=task_id):
                env = SREEnv(task_id)
                observation = env.reset()
                done = False
                steps_taken = 0

                while not done and steps_taken < inference.MAX_STEPS[task_id]:
                    action_payload = inference.TASK_FALLBACK[task_id](
                        observation.model_dump()
                    )
                    action = SREAction(**action_payload)
                    observation, reward, done, info = env.step(action)

                    self.assertGreater(reward.value, 0.0)
                    self.assertLess(reward.value, 1.0)
                    self.assertGreater(info["cumulative_score"], 0.0)
                    self.assertLess(info["cumulative_score"], 1.0)

                    steps_taken += 1

                self.assertGreater(steps_taken, 0)


if __name__ == "__main__":
    unittest.main()
