"""全局配置装载与只读性测试。"""

from pathlib import Path

import pytest

from drama_interaction.config import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_MIN_REPORTED_GAP_MS,
    SettingsError,
    load_settings,
)


def _required() -> dict[str, str]:
    return {
        "LLM_MODEL_ID": "model-from-override",
        "LLM_API_KEY": "secret",
        "LLM_BASE_URL": "https://llm.example/v1",
        "CHECKPOINT_DATABASE_URL": "postgresql://user:pass@localhost/db",
    }


def test_load_settings_uses_defaults_and_keeps_optional_limits_unconfigured():
    settings = load_settings(_required(), env_file=None)

    assert settings.llm_model_id == "model-from-override"
    assert settings.llm_timeout_seconds == 3600.0
    assert settings.llm_max_tokens == DEFAULT_LLM_MAX_TOKENS == 131_072
    assert settings.min_reported_gap_ms == DEFAULT_MIN_REPORTED_GAP_MS == 2500
    assert settings.interaction_budget is None
    assert settings.min_interaction_spacing_ms is None
    assert settings.type_cooldown_ms == {}
    assert settings.runs_dir == Path("data/interaction_v2/runs")
    assert settings.langsmith_tracing is False


def test_explicit_overrides_win_over_environment_and_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MODEL_ID=dotenv-model\n"
        "LLM_API_KEY=dotenv-key\n"
        "LLM_BASE_URL=https://dotenv.example/v1\n"
        "CHECKPOINT_DATABASE_URL=postgresql://dotenv/db\n"
        "INTERACTION_BUDGET=2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODEL_ID", "environment-model")
    monkeypatch.setenv("INTERACTION_BUDGET", "4")

    settings = load_settings(
        {"LLM_MODEL_ID": "explicit-model", "INTERACTION_BUDGET": 7},
        env_file=env_file,
    )

    assert settings.llm_model_id == "explicit-model"
    assert settings.interaction_budget == 7
    assert settings.llm_api_key == "dotenv-key"


def test_missing_required_values_are_reported_together():
    with pytest.raises(SettingsError) as error:
        load_settings(env_file=None)

    message = str(error.value)
    for name in (
        "LLM_MODEL_ID",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "CHECKPOINT_DATABASE_URL",
    ):
        assert name in message
    assert error.value.missing == (
        "LLM_MODEL_ID",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "CHECKPOINT_DATABASE_URL",
    )


def test_settings_is_frozen_including_cooldown_mapping():
    settings = load_settings(
        {
            **_required(),
            "TYPE_COOLDOWN_MS": {"instant_vote": 1000},
        },
        env_file=None,
    )

    with pytest.raises((TypeError, ValueError)):
        settings.llm_model_id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        settings.type_cooldown_ms["instant_vote"] = 2000


def test_type_cooldown_accepts_json_object_only():
    settings = load_settings(
        {**_required(), "TYPE_COOLDOWN_MS": '{"instant_vote": 1000}'},
        env_file=None,
    )
    assert settings.type_cooldown_ms == {"instant_vote": 1000}

    for value in ("instant_vote=1000", "instant_vote:1000", ""):
        with pytest.raises(SettingsError, match="TYPE_COOLDOWN_MS"):
            load_settings({**_required(), "TYPE_COOLDOWN_MS": value}, env_file=None)


@pytest.mark.parametrize(
    "override",
    [
        {"LLM_MAX_RETRIES": -1},
        {"LLM_MAX_RETRIES": "not-an-integer"},
        {"MIN_REPORTED_GAP_MS": 0},
        {"MIN_INTERACTION_SPACING_MS": 100},
        {"CHECKPOINT_DATABASE_URL": "sqlite:///tmp/checkpoints.db"},
    ],
)
def test_invalid_values_fail_during_load(override):
    with pytest.raises(SettingsError):
        load_settings({**_required(), **override}, env_file=None)


def test_langsmith_configuration_is_optional():
    settings = load_settings(
        {
            **_required(),
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_ENDPOINT": "https://smith.example",
            "LANGSMITH_PROJECT": "demo",
        },
        env_file=None,
    )

    assert settings.langsmith_tracing is True
    assert settings.langsmith_endpoint == "https://smith.example"
    assert settings.langsmith_project == "demo"
