"""托管人声分离客户端契约测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from drama_interaction.config import (
    AUDIO_SEPARATOR_DIALOGUE_URL_EXPIRES_SECONDS,
    AUDIO_SEPARATOR_SDK_RETRIES,
)
from drama_interaction.evidence.audio_separator import (
    AudioSeparatorClient,
    AudioSeparatorError,
)


def _client() -> tuple[AudioSeparatorClient, MagicMock]:
    fake = MagicMock(name="CosS3Client")
    fake.get_presigned_download_url.return_value = "https://cos.example/dialogue.mp3"
    fake.get_object.return_value = {"Body": MagicMock()}
    with patch(
        "drama_interaction.evidence.audio_separator.CosS3Client", return_value=fake
    ):
        client = AudioSeparatorClient("id", "secret", "bucket-123", "ap-guangzhou")
    return client, fake


def test_client_uses_configured_sdk_retry_budget() -> None:
    with patch("drama_interaction.evidence.audio_separator.CosS3Client") as factory:
        AudioSeparatorClient("id", "secret", "bucket-123", "ap-guangzhou")

    assert factory.call_args.kwargs["retry"] == AUDIO_SEPARATOR_SDK_RETRIES


def test_separate_submits_voice_job_and_downloads_stems(tmp_path: Path):
    client, fake = _client()
    fake.ci_create_media_jobs.return_value = {"JobsDetail": [{"JobId": "job-1"}]}
    fake.ci_get_media_jobs.return_value = {"JobsDetail": [{"State": "Success"}]}
    fake.get_object.return_value["Body"].get_stream_to_file.side_effect = lambda path: (
        Path(path).write_bytes(b"background")
    )
    mix = tmp_path / "mix.flac"
    background = tmp_path / "background.mp3"
    dialogue = tmp_path / "dialogue.mp3"
    mix.write_bytes(b"mix")

    with patch("drama_interaction.evidence.audio_separator.time.sleep"):
        client.separate(
            mix,
            background,
            dialogue,
            drama_name="测试剧",
            episode_name="第1集",
        )

    fake.put_object_from_local_file.assert_called_once_with(
        Bucket="bucket-123", LocalFilePath=str(mix), Key="v2/测试剧/第1集/mix.flac"
    )
    request_kwargs = fake.ci_create_media_jobs.call_args.kwargs
    assert request_kwargs["ContentType"] == "application/xml"
    jobs = request_kwargs["Jobs"]
    assert jobs["Tag"] == "VoiceSeparate"
    assert jobs["Input"] == {"Object": "v2/测试剧/第1集/mix.flac"}
    assert jobs["Operation"]["VoiceSeparate"] == {
        "AudioMode": "AudioAndBackground",
        "AudioConfig": {"Codec": "mp3"},
    }
    assert jobs["Operation"]["Output"] == {
        "Region": "ap-guangzhou",
        "Bucket": "bucket-123",
        "Object": "v2/测试剧/第1集/background.mp3",
        "AuObject": "v2/测试剧/第1集/dialogue.mp3",
    }
    fake.get_presigned_download_url.assert_not_called()
    assert background.read_bytes() == b"background"
    assert dialogue.read_bytes() == b"background"
    assert [call.kwargs["Key"] for call in fake.get_object.call_args_list] == [
        "v2/测试剧/第1集/background.mp3",
        "v2/测试剧/第1集/dialogue.mp3",
    ]


def test_dialogue_url_signs_existing_dialogue_output():
    client, fake = _client()

    assert client.dialogue_url(drama_name="测试剧", episode_name="第1集") == (
        "https://cos.example/dialogue.mp3"
    )
    fake.get_presigned_download_url.assert_called_once_with(
        Bucket="bucket-123",
        Key="v2/测试剧/第1集/dialogue.mp3",
        Expired=AUDIO_SEPARATOR_DIALOGUE_URL_EXPIRES_SECONDS,
    )


@pytest.mark.parametrize("state", ["Failed", "Cancel"])
def test_failed_job_stops_episode(state: str, tmp_path: Path):
    client, fake = _client()
    fake.ci_create_media_jobs.return_value = {"JobsDetail": [{"JobId": "job-1"}]}
    fake.ci_get_media_jobs.return_value = {
        "JobsDetail": [{"State": state, "Message": "bad input"}]
    }

    mix = tmp_path / "mix.flac"
    mix.write_bytes(b"mix")
    with pytest.raises(AudioSeparatorError, match="任务失败"):
        client.separate(
            mix,
            tmp_path / "background.mp3",
            tmp_path / "dialogue.mp3",
            drama_name="d",
            episode_name="e",
        )


def test_missing_job_detail_fails(tmp_path: Path):
    client, fake = _client()
    fake.ci_create_media_jobs.return_value = {"RequestId": "request-1"}
    mix = tmp_path / "mix.flac"
    mix.write_bytes(b"mix")

    with pytest.raises(AudioSeparatorError, match="缺少 JobsDetail"):
        client.separate(
            mix,
            tmp_path / "background.mp3",
            tmp_path / "dialogue.mp3",
            drama_name="d",
            episode_name="e",
        )
