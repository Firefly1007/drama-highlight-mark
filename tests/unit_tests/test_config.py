"""全局配置与参数常量单元测试。

验证 config.py 中所有数字类参数、默认值及业务约束常量的完整性与合理性。
"""

import drama_interaction.config as cfg


def test_render_duration_constants():
    """测试渲染时长基准与生理时间常量。"""
    assert cfg.DEFAULT_EMOTION_BUTTON_DURATION_MS == 2500
    assert cfg.DEFAULT_REPEAT_KEYLINE_DURATION_MS == 2500
    assert cfg.DEFAULT_INSTANT_VOTE_DURATION_MS == 3500
    assert cfg.DEFAULT_DEFERRED_VOTE_DURATION_MS == 3500
    assert cfg.DEFAULT_SIDE_COMMENT_DURATION_MS == 2500

    assert cfg.KEYLINE_TAIL_MS == 700
    assert cfg.KEYLINE_DURATION_FLOOR == 2500
    assert cfg.KEYLINE_DURATION_CEIL == 4500
    assert cfg.KEYLINE_DURATION_FLOOR <= cfg.KEYLINE_DURATION_CEIL

    assert cfg.DEFAULT_REVEAL_DISPLAY_MS == 3000
    assert cfg.DEFAULT_REVEAL_GAP_MIN_MS == 5000


def test_interaction_shape_constraints():
    """测试互动形态与选项数量约束。"""
    assert cfg.EMOTION_BUTTON_MIN_ID == 0
    assert cfg.EMOTION_BUTTON_MAX_ID == 5
    assert cfg.INSTANT_VOTE_OPTIONS_COUNT == 2
    assert cfg.DEFERRED_VOTE_MIN_OPTIONS == 2
    assert cfg.DEFERRED_VOTE_MAX_OPTIONS == 4


def test_llm_and_path_defaults():
    """测试 LLM 与路径默认配置。"""
    assert cfg.DEFAULT_LLM_TEMPERATURE == 0.0
    assert cfg.DEFAULT_LLM_TIMEOUT_SECONDS == 60.0
    assert cfg.DEFAULT_LLM_MAX_RETRIES == 3
    assert cfg.DEFAULT_LLM_RETRY_DELAY_SECONDS == 1.0

    assert cfg.DEFAULT_DATA_ROOT == "data"
    assert cfg.DEFAULT_V1_SEGMENTS_DIR == "data/text"
    assert cfg.DEFAULT_EVIDENCE_DIR == "data/evidence"
    assert cfg.DEFAULT_INTERACTION_V2_DIR == "data/interaction_v2"
    assert cfg.DEFAULT_RUNS_DIR == "data/interaction_v2/runs"
    assert cfg.DEFAULT_CHECKPOINT_DB_PATH == "data/interaction_v2/runs/checkpoints.db"
