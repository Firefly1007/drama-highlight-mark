"""托管人声分离客户端。"""

from __future__ import annotations

import time
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client

from drama_interaction.config import (
    AUDIO_SEPARATOR_DIALOGUE_URL_EXPIRES_SECONDS,
    AUDIO_SEPARATOR_POLL_INTERVAL_SECONDS,
    AUDIO_SEPARATOR_SDK_RETRIES,
    AUDIO_SEPARATOR_WAIT_TIMEOUT_SECONDS,
)


class AudioSeparatorError(RuntimeError):
    """人声分离调用或任务处理失败。"""


def _job_detail(response: dict) -> dict:
    details = response.get("JobsDetail")
    if isinstance(details, list):
        details = details[0] if details else None
    if not isinstance(details, dict):
        raise AudioSeparatorError(f"人声分离响应缺少 JobsDetail: {response}")
    return details


class AudioSeparatorClient:
    """使用托管 CI 服务提交并获取 VoiceSeparate 任务。"""

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        bucket: str,
        region: str,
    ) -> None:
        config = CosConfig(
            Region=region,
            SecretId=access_key_id,
            SecretKey=access_key_secret,
        )
        self.client = CosS3Client(config, retry=AUDIO_SEPARATOR_SDK_RETRIES)
        self.bucket = bucket
        self.region = region

    def separate(
        self,
        flac_path: str | Path,
        background_path: str | Path,
        dialogue_path: str | Path,
        *,
        drama_name: str,
        episode_name: str,
    ) -> None:
        """上传整集混音并落盘两个分离音轨。"""
        prefix = f"v2/{drama_name}/{episode_name}"
        input_key = f"{prefix}/mix.flac"
        background_key = f"{prefix}/background.mp3"
        dialogue_key = f"{prefix}/dialogue.mp3"

        self.client.put_object_from_local_file(
            Bucket=self.bucket,
            LocalFilePath=str(flac_path),
            Key=input_key,
        )
        response = self.client.ci_create_media_jobs(
            Bucket=self.bucket,
            Jobs={
                "Tag": "VoiceSeparate",
                "Input": {"Object": input_key},
                "Operation": {
                    "VoiceSeparate": {
                        "AudioMode": "AudioAndBackground",
                        "AudioConfig": {"Codec": "mp3"},
                    },
                    "Output": {
                        "Region": self.region,
                        "Bucket": self.bucket,
                        "Object": background_key,
                        "AuObject": dialogue_key,
                    },
                },
            },
            ContentType="application/xml",
        )
        job_id = _job_detail(response).get("JobId")
        if not job_id:
            raise AudioSeparatorError(f"人声分离创建任务响应缺少 JobId: {response}")

        self._wait(str(job_id))

        for key, output_path, label in (
            (background_key, background_path, "background"),
            (dialogue_key, dialogue_path, "dialogue"),
        ):
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = self.client.get_object(Bucket=self.bucket, Key=key)
            result["Body"].get_stream_to_file(str(destination))
            if not destination.is_file() or destination.stat().st_size == 0:
                raise AudioSeparatorError(f"人声分离 {label} 输出为空")

    def dialogue_url(self, *, drama_name: str, episode_name: str) -> str:
        """为已落盘的 dialogue 输出重新生成短时 URL，供 ASR 恢复使用。"""
        dialogue_key = f"v2/{drama_name}/{episode_name}/dialogue.mp3"
        signed_dialogue_url = self.client.get_presigned_download_url(
            Bucket=self.bucket,
            Key=dialogue_key,
            Expired=AUDIO_SEPARATOR_DIALOGUE_URL_EXPIRES_SECONDS,
        )
        if not signed_dialogue_url:
            raise AudioSeparatorError("人声分离 dialogue 输出缺少下载 URL")
        return str(signed_dialogue_url)

    def _wait(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = AUDIO_SEPARATOR_POLL_INTERVAL_SECONDS,
        timeout_seconds: float = AUDIO_SEPARATOR_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            if time.monotonic() >= deadline:
                raise AudioSeparatorError(
                    f"人声分离任务超时 ({timeout_seconds}s): {job_id}"
                )

            detail = _job_detail(
                self.client.ci_get_media_jobs(Bucket=self.bucket, JobIDs=job_id)
            )
            state = detail.get("State")
            if state == "Success":
                return
            if state in {"Failed", "Cancel"}:
                raise AudioSeparatorError(f"人声分离任务失败: {detail}")
            if state not in {"Submitted", "Running"}:
                raise AudioSeparatorError(f"人声分离任务状态异常: {detail}")
            time.sleep(poll_interval_seconds)


__all__ = [
    "AudioSeparatorClient",
    "AudioSeparatorError",
]
