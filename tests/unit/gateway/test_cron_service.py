from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest import mock

from apps.gateway import cron_service
from apps.gateway.cron_service import (
    cron_execution_should_deliver,
    _try_deliver_cron_result,
)
from packages.cron import CronJob, CronJobExecution


def _job(*, action_kind: str = "prompt") -> CronJob:
    now = datetime.now(timezone.utc)
    return CronJob(
        job_id=f"cron:{action_kind}",
        name=f"{action_kind} job",
        schedule_text="0 1 * * *",
        schedule_kind="cron",
        action_kind=action_kind,
        payload={"trigger": "dream"} if action_kind == "learning" else {"prompt": "hello"},
        profile_id=None,
        elephant_id=None,
        status="scheduled",
        created_at=now,
        updated_at=now,
    )


class CronServiceDeliveryTest(unittest.TestCase):
    def test_learning_cron_enqueue_ack_is_not_delivered_to_im(self) -> None:
        calls: list[tuple[CronJob, CronJobExecution]] = []
        job = _job(action_kind="learning")
        execution = CronJobExecution(
            job=job,
            outcome="success",
            summary="learning job queued: learning-job:123 (dream)",
            recorded_at=datetime.now(timezone.utc),
        )

        _try_deliver_cron_result(
            lambda delivered_job, delivered_execution: calls.append((delivered_job, delivered_execution)),
            execution,
        )

        self.assertEqual(calls, [])
        self.assertFalse(cron_execution_should_deliver(execution))

    def test_prompt_cron_result_still_delivers(self) -> None:
        calls: list[tuple[CronJob, CronJobExecution]] = []
        job = _job(action_kind="prompt")
        execution = CronJobExecution(
            job=job,
            outcome="success",
            summary="hello from cron",
            recorded_at=datetime.now(timezone.utc),
        )

        _try_deliver_cron_result(
            lambda delivered_job, delivered_execution: calls.append((delivered_job, delivered_execution)),
            execution,
        )

        self.assertEqual(calls, [(job, execution)])
        self.assertTrue(cron_execution_should_deliver(execution))

    def test_silent_prompt_cron_result_is_not_delivered(self) -> None:
        calls: list[tuple[CronJob, CronJobExecution]] = []
        job = _job(action_kind="prompt")
        execution = CronJobExecution(
            job=job,
            outcome="success",
            summary="[SILENT]",
            recorded_at=datetime.now(timezone.utc),
        )

        _try_deliver_cron_result(
            lambda delivered_job, delivered_execution: calls.append((delivered_job, delivered_execution)),
            execution,
        )

        self.assertEqual(calls, [])
        self.assertFalse(cron_execution_should_deliver(execution))

    def test_built_gateway_callback_filters_learning_jobs_before_adapter(self) -> None:
        calls: list[tuple[CronJob, CronJobExecution]] = []

        def callback(job: CronJob, execution: CronJobExecution) -> None:
            calls.append((job, execution))

        with (
            mock.patch.object(cron_service, "_try_feishu_cron_callback", return_value=callback),
            mock.patch.object(cron_service, "_try_discord_cron_callback", return_value=None),
            mock.patch.object(cron_service, "_try_weixin_cron_callback", return_value=None),
        ):
            built = cron_service.build_gateway_cron_delivery_callback(
                state_dir="/tmp/elephant",
                cli_state_dir="/tmp/elephant",
                environ={},
            )

        assert built is not None
        learning = CronJobExecution(
            job=_job(action_kind="learning"),
            outcome="success",
            summary="learning job queued: learning-job:123 (dream)",
            recorded_at=datetime.now(timezone.utc),
        )
        prompt = CronJobExecution(
            job=_job(action_kind="prompt"),
            outcome="success",
            summary="hello from cron",
            recorded_at=datetime.now(timezone.utc),
        )

        built(learning.job, learning)
        built(prompt.job, prompt)

        self.assertEqual(calls, [(prompt.job, prompt)])


if __name__ == "__main__":
    unittest.main()
