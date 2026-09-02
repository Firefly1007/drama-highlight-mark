"""数据契约层离线单元测试模块。

全面测试 evidence、interaction、candidate 各模块的数据模型、
字段约束、业务纪律校验器、错误处理路径与双向序列化往返一致性。
"""

import inspect
import json
import pytest
from pydantic import ValidationError

import drama_interaction.schemas as schemas_pkg
from drama_interaction.schemas import (
    WINDOW_SIZE_MS,
    VALID_SPECIALIST_TYPES,
    Abstention,
    Candidate,
    DeferredVotePayload,
    EmotionButtonPayload,
    EvidenceWindow,
    FinalInteraction,
    InstantVotePayload,
    InteractionPayload,
    InteractionType,
    CommentMood,
    MOOD_INT_TO_STR,
    MOOD_STR_TO_INT,
    RepeatKeylinePayload,
    RevealAnchor,
    SideCommentPayload,
    SpecialistResult,
    TranscriptSegment,
    TriggerAnchor,
    TYPE_INT_TO_STR,
    TYPE_STR_TO_INT,
    VALID_COMMENT_MOODS,
    validate_evidence_sequence,
)

# =====================================================================
# 1. 证据数据契约测试 (Evidence Schemas)
# =====================================================================


class TestEvidenceSchema:
    """证据层数据模型测试集。"""

    def test_transcript_segment_valid(self):
        """测试台词片段合法构造与字段提取。"""
        ts1 = TranscriptSegment(
            id="t1",
            start_ms=100,
            end_ms=1500,
            text="因为我在哪，纪家就在哪",
            speaker_label="speaker_1",
        )
        assert ts1.id == "t1"
        assert ts1.start_ms == 100
        assert ts1.end_ms == 1500
        assert ts1.text == "因为我在哪，纪家就在哪"
        assert ts1.speaker_label == "speaker_1"

        # 允许 speaker_label 为 None（ADR-005）
        ts2 = TranscriptSegment(
            id="t2",
            start_ms=0,
            end_ms=0,
            text="瞬时台词",
            speaker_label=None,
        )
        assert ts2.speaker_label is None

    def test_transcript_segment_invalid(self):
        """测试台词片段非法输入（时间、文本、标识符、说话人与多余字段）。"""
        # start_ms 为负数
        with pytest.raises(ValidationError):
            TranscriptSegment(id="t1", start_ms=-1, end_ms=100, text="测试")

        # start_ms > end_ms
        with pytest.raises(ValidationError, match="不能大于结束时间"):
            TranscriptSegment(id="t1", start_ms=2000, end_ms=1000, text="测试")

        # 空白文本与空字符串
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            TranscriptSegment(id="t1", start_ms=0, end_ms=100, text="   ")
        with pytest.raises(ValidationError):
            TranscriptSegment(id="t1", start_ms=0, end_ms=100, text="")

        # 空白 id 与空 id
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            TranscriptSegment(id="   ", start_ms=0, end_ms=100, text="测试")
        with pytest.raises(ValidationError):
            TranscriptSegment(id="", start_ms=0, end_ms=100, text="测试")

        # 空白 speaker_label
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            TranscriptSegment(
                id="t1", start_ms=0, end_ms=100, text="测试", speaker_label="   "
            )

        # 禁止多余字段与置信度字段（ADR-002）
        with pytest.raises(ValidationError):
            TranscriptSegment(
                id="t1", start_ms=0, end_ms=100, text="测试", extra_field="bad"
            )
        with pytest.raises(ValidationError):
            TranscriptSegment(
                id="t1", start_ms=0, end_ms=100, text="测试", confidence=0.9
            )

    def test_evidence_window_string_lists(self):
        """测试视觉观察、音频观察、屏上文字简化为字符串列表及其非空校验（ADR-006）。"""
        w = EvidenceWindow(
            window_id=0,
            start_ms=0,
            end_ms=3000,
            onscreen_texts=["三年后...", "纪家豪宅"],
            visual_observations=["女主愤怒地扇了男主一巴掌", "男主后退一步"],
            audio_observations=["突发剧烈破碎声", "激昂背景音乐"],
            uncertainty=["光线较暗"],
        )
        assert len(w.onscreen_texts) == 2
        assert len(w.visual_observations) == 2
        assert len(w.audio_observations) == 2
        assert len(w.uncertainty) == 1

        # 包含空白字符串报错
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            EvidenceWindow(window_id=0, start_ms=0, end_ms=3000, onscreen_texts=["   "])
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            EvidenceWindow(
                window_id=0, start_ms=0, end_ms=3000, visual_observations=[""]
            )
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            EvidenceWindow(
                window_id=0, start_ms=0, end_ms=3000, audio_observations=[" "]
            )
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            EvidenceWindow(window_id=0, start_ms=0, end_ms=3000, uncertainty=["   "])

    def test_evidence_window_single_discipline(self):
        """测试单个证据窗口边界与纪律校验。"""
        # 标准 3 秒窗口
        w0 = EvidenceWindow(
            window_id=0,
            start_ms=0,
            end_ms=3000,
            transcript_segments=[
                TranscriptSegment(id="t1", start_ms=100, end_ms=1200, text="你好")
            ],
            visual_observations=["男子微笑"],
            audio_observations=["轻柔钢琴曲"],
            uncertainty=["光线较暗"],
        )
        assert w0.window_id == 0
        assert len(w0.transcript_segments) == 1

        # 末窗短于 3 秒合法
        w_last = EvidenceWindow(window_id=2, start_ms=6000, end_ms=7500)
        assert w_last.end_ms - w_last.start_ms == 1500

        # 窗口开始时间未与 window_id * 3000 对齐
        with pytest.raises(ValidationError, match="与预期边界 .* 不匹配"):
            EvidenceWindow(window_id=1, start_ms=2500, end_ms=5500)

        # 窗口结束时间早于等于开始时间
        with pytest.raises(ValidationError, match="必须大于开始时间"):
            EvidenceWindow(window_id=0, start_ms=0, end_ms=0)

        # 窗口时长超过 3000ms
        with pytest.raises(ValidationError, match="超过最大窗口长度"):
            EvidenceWindow(window_id=0, start_ms=0, end_ms=3500)

        # 窗口负数 window_id
        with pytest.raises(ValidationError):
            EvidenceWindow(window_id=-1, start_ms=0, end_ms=3000)

        # 严禁多余字段（如剧集元数据，PRD §6.2）
        with pytest.raises(ValidationError):
            EvidenceWindow(
                window_id=0,
                start_ms=0,
                end_ms=3000,
                episode_title="第一集",  # type: ignore
            )

    def test_validate_evidence_sequence_valid(self):
        """测试证据窗口序列合法性校验。"""
        # 空序列合法
        validate_evidence_sequence([])

        # 单个完整窗口合法
        validate_evidence_sequence(
            [EvidenceWindow(window_id=0, start_ms=0, end_ms=3000)]
        )

        # 单个短窗口（短剧集收尾）合法
        validate_evidence_sequence(
            [EvidenceWindow(window_id=0, start_ms=0, end_ms=1800)]
        )

        # 多个窗口，末窗短于 3000ms 合法，台词跨窗正常复制（ADR-004）
        shared_ts = TranscriptSegment(
            id="t_cross",
            start_ms=2500,
            end_ms=3500,
            text="跨窗台词",
            speaker_label="spk1",
        )
        windows = [
            EvidenceWindow(
                window_id=0,
                start_ms=0,
                end_ms=3000,
                transcript_segments=[shared_ts],
            ),
            EvidenceWindow(
                window_id=1,
                start_ms=3000,
                end_ms=6000,
                transcript_segments=[shared_ts],
            ),
            EvidenceWindow(
                window_id=2,
                start_ms=6000,
                end_ms=7200,  # 允许短于 3000
            ),
        ]
        validate_evidence_sequence(windows)

    def test_validate_evidence_sequence_invalid_cases(self):
        """测试证据窗口序列不合规情况（跳号、非末窗短时长、重叠/间隙、跨窗与窗内重复）。"""
        # 1. window_id 不连续（跳号）
        w0 = EvidenceWindow(window_id=0, start_ms=0, end_ms=3000)
        w2 = EvidenceWindow(window_id=2, start_ms=6000, end_ms=9000)
        with pytest.raises(ValueError, match="窗口序号不连续"):
            validate_evidence_sequence([w0, w2])

        # 2. window_id 未从 0 开始
        w1 = EvidenceWindow(window_id=1, start_ms=3000, end_ms=6000)
        with pytest.raises(ValueError, match="窗口序号不连续"):
            validate_evidence_sequence([w1])

        # 3. 非末尾窗口时长不足 3000ms
        w0_short = EvidenceWindow(window_id=0, start_ms=0, end_ms=2000)
        w1_valid = EvidenceWindow(window_id=1, start_ms=3000, end_ms=6000)
        with pytest.raises(ValueError, match="必须严格等于 3000ms"):
            validate_evidence_sequence([w0_short, w1_valid])

        # 4. 跨窗口台词复制不一致（相同 id 但文本/时间不同）
        ts_a = TranscriptSegment(id="t_dup", start_ms=2000, end_ms=3500, text="版本A")
        ts_b = TranscriptSegment(id="t_dup", start_ms=2000, end_ms=3500, text="版本B")
        w0_with_a = EvidenceWindow(
            window_id=0, start_ms=0, end_ms=3000, transcript_segments=[ts_a]
        )
        w1_with_b = EvidenceWindow(
            window_id=1, start_ms=3000, end_ms=6000, transcript_segments=[ts_b]
        )
        with pytest.raises(ValueError, match="跨窗口台词片段复制数据不一致"):
            validate_evidence_sequence([w0_with_a, w1_with_b])

        # 5. 单个窗口内部存在重复台词 ID
        ts_same = TranscriptSegment(
            id="t_single_dup", start_ms=500, end_ms=1000, text="同句台词"
        )
        w0_intra_dup = EvidenceWindow(
            window_id=0,
            start_ms=0,
            end_ms=3000,
            transcript_segments=[ts_same, ts_same],
        )
        with pytest.raises(ValueError, match="存在重复的台词片段 id"):
            validate_evidence_sequence([w0_intra_dup])

    def test_evidence_serialization_round_trip(self):
        """测试证据窗口序列化与反序列化 round-trip。"""
        windows = [
            EvidenceWindow(
                window_id=0,
                start_ms=0,
                end_ms=3000,
                transcript_segments=[
                    TranscriptSegment(
                        id="t1",
                        start_ms=500,
                        end_ms=2500,
                        text="台词1",
                        speaker_label="s1",
                    )
                ],
                onscreen_texts=["标题"],
                visual_observations=["动作A"],
                audio_observations=["音效B"],
                uncertainty=["无"],
            )
        ]
        dumped_data = [w.model_dump() for w in windows]
        json_str = json.dumps(dumped_data, ensure_ascii=False)

        loaded_data = json.loads(json_str)
        reconstructed_windows = [
            EvidenceWindow.model_validate(item) for item in loaded_data
        ]
        assert reconstructed_windows == windows


# =====================================================================
# 2. 互动契约测试 (Interaction Schemas)
# =====================================================================


class TestInteractionSchema:
    """互动载荷与最终输出数据模型测试集。"""

    def test_type_mappings_and_dicts(self):
        """测试类型枚举与映射字典的权威一致性。"""
        # 互动类型映射
        assert InteractionType.EMOTION_BUTTON.value == 1
        assert InteractionType.REPEAT_KEYLINE.value == 2
        assert InteractionType.INSTANT_VOTE.value == 3
        assert InteractionType.DEFERRED_VOTE.value == 4
        assert InteractionType.SIDE_COMMENT.value == 5

        assert TYPE_STR_TO_INT["emotion_button"] == 1
        assert TYPE_STR_TO_INT["repeat_keyline"] == 2
        assert TYPE_STR_TO_INT["instant_vote"] == 3
        assert TYPE_STR_TO_INT["deferred_vote"] == 4
        assert TYPE_STR_TO_INT["side_comment"] == 5

        for k, v in TYPE_STR_TO_INT.items():
            assert TYPE_INT_TO_STR[v] == k

        # 情绪标签映射字典
        assert MOOD_STR_TO_INT["roast"] == 1
        assert MOOD_STR_TO_INT["shock"] == 2
        assert MOOD_STR_TO_INT["laugh"] == 3
        assert MOOD_STR_TO_INT["praise"] == 4
        assert MOOD_STR_TO_INT["sympathy"] == 5
        assert MOOD_STR_TO_INT["doubt"] == 6

        for mk, mv in MOOD_STR_TO_INT.items():
            assert MOOD_INT_TO_STR[mv] == mk
            assert mk in VALID_COMMENT_MOODS

    def test_emotion_button_payload_full_matrix(self):
        """测试情绪按钮全部 button_id (0-5) 的字段条件约束矩阵。"""
        # 0: 爽 (cool) -> text 可选, danmaku 可选
        p0_full = EmotionButtonPayload(button_id=0, text="爽快", danmaku=["大快人心"])
        assert p0_full.button_id == 0
        p0_none = EmotionButtonPayload(button_id=0, text=None, danmaku=None)
        assert p0_none.text is None and p0_none.danmaku is None

        # 1: 笑 (laugh) -> text 禁止, danmaku 可选
        p1 = EmotionButtonPayload(button_id=1, danmaku=["哈哈哈哈"])
        assert p1.danmaku == ["哈哈哈哈"]
        with pytest.raises(ValidationError, match="不允许配置 text"):
            EmotionButtonPayload(button_id=1, text="笑死了")

        # 2: 丢番茄 (tomato) -> text 可选, danmaku 可选
        p2 = EmotionButtonPayload(button_id=2, text="恶有恶报", danmaku=["砸他"])
        assert p2.text == "恶有恶报"

        # 3: 护住TA (protect) -> text 禁止, danmaku 禁止
        p3 = EmotionButtonPayload(button_id=3)
        assert p3.text is None and p3.danmaku is None
        with pytest.raises(ValidationError, match="不允许配置 text"):
            EmotionButtonPayload(button_id=3, text="快跑")
        with pytest.raises(ValidationError, match="不允许配置 danmaku"):
            EmotionButtonPayload(button_id=3, danmaku=["挡刀"])
        with pytest.raises(ValidationError, match="不能为空列表"):
            EmotionButtonPayload(button_id=3, danmaku=[])

        # 4: 心疼TA (pity) -> text 禁止, danmaku 禁止
        p4 = EmotionButtonPayload(button_id=4)
        assert p4.button_id == 4
        with pytest.raises(ValidationError, match="不允许配置 text"):
            EmotionButtonPayload(button_id=4, text="太惨了")
        with pytest.raises(ValidationError, match="不允许配置 danmaku"):
            EmotionButtonPayload(button_id=4, danmaku=["哭了"])
        with pytest.raises(ValidationError, match="不能为空列表"):
            EmotionButtonPayload(button_id=4, danmaku=[])

        # 5: 磕到了 (ship) -> text 禁止, danmaku 可选
        p5 = EmotionButtonPayload(button_id=5, danmaku=["在一起"])
        assert p5.danmaku == ["在一起"]
        with pytest.raises(ValidationError, match="不允许配置 text"):
            EmotionButtonPayload(button_id=5, text="甜甜甜")

        # 空弹幕列表与空白弹幕项校验
        with pytest.raises(ValidationError, match="不能为空列表"):
            EmotionButtonPayload(button_id=0, danmaku=[])
        with pytest.raises(ValidationError, match="弹幕条目不能全为空白字符"):
            EmotionButtonPayload(button_id=0, danmaku=["   "])

        # button_id 越界 (<0 或 >5)
        with pytest.raises(ValidationError):
            EmotionButtonPayload(button_id=-1)
        with pytest.raises(ValidationError):
            EmotionButtonPayload(button_id=6)

        # 禁止多余字段与评分
        with pytest.raises(ValidationError):
            EmotionButtonPayload(button_id=0, confidence=0.99)  # type: ignore

    def test_repeat_keyline_payload(self):
        """测试跟读金句载荷。"""
        p = RepeatKeylinePayload(text="正义也许会迟到，但绝不会缺席！")
        assert p.text == "正义也许会迟到，但绝不会缺席！"

        with pytest.raises(ValidationError, match="不能全为空白字符"):
            RepeatKeylinePayload(text="   ")
        with pytest.raises(ValidationError):
            RepeatKeylinePayload(text="")
        with pytest.raises(ValidationError):
            RepeatKeylinePayload(text="台词", score=100)  # type: ignore

    def test_instant_vote_payload(self):
        """测试即时投票载荷（严格 2 个不重复选项）。"""
        # 恰好 2 个选项合法
        p = InstantVotePayload(question="你站谁？", options=["站男主", "站女主"])
        assert len(p.options) == 2

        # 选项数量不是 2
        with pytest.raises(ValidationError, match="选项数量必须严格等于 2"):
            InstantVotePayload(question="你站谁？", options=["站男主"])
        with pytest.raises(ValidationError, match="选项数量必须严格等于 2"):
            InstantVotePayload(
                question="你站谁？", options=["站男主", "站女主", "弃权"]
            )

        # 选项为空白
        with pytest.raises(ValidationError, match="选项不能全为空白字符"):
            InstantVotePayload(question="你站谁？", options=["站男主", "  "])

        # 选项重复
        with pytest.raises(ValidationError, match="选项不能重复"):
            InstantVotePayload(question="你站谁？", options=["站男主", "站男主"])
        with pytest.raises(ValidationError, match="选项不能重复"):
            InstantVotePayload(question="你站谁？", options=["站男主", " 站男主 "])

        # 题干空白
        with pytest.raises(ValidationError, match="题干不能全为空白字符"):
            InstantVotePayload(question="   ", options=["A", "B"])

    def test_deferred_vote_payload(self):
        """测试延时投票载荷（2-4 个不重复选项，answer_id 默认 0 且校验范围）。"""
        # 默认 answer_id = 0
        p_default = DeferredVotePayload(
            question="凶手是谁？",
            options=["管家", "保姆"],
        )
        assert p_default.answer_id == 0
        assert p_default.reveal_time is None

        # 4 个选项，指定合法 answer_id
        p4 = DeferredVotePayload(
            question="凶手是谁？",
            options=["A", "B", "C", "D"],
            answer_id=3,
            reveal_time=12000,
            reveal_delay=5000,
        )
        assert p4.answer_id == 3
        assert p4.reveal_time == 12000

        # 选项超出 [2, 4] 范围
        with pytest.raises(ValidationError, match="选项数量必须在 2 到 4 之间"):
            DeferredVotePayload(question="问题", options=["唯一选项"])
        with pytest.raises(ValidationError, match="选项数量必须在 2 到 4 之间"):
            DeferredVotePayload(
                question="问题",
                options=["1", "2", "3", "4", "5"],
            )

        # 重复选项
        with pytest.raises(ValidationError, match="不能包含重复项"):
            DeferredVotePayload(question="问题", options=["A", "A"])
        with pytest.raises(ValidationError, match="不能包含重复项"):
            DeferredVotePayload(question="问题", options=["A", "B", " A "])

        # answer_id 越界
        with pytest.raises(ValidationError, match="超出 options 索引范围"):
            DeferredVotePayload(question="问题", options=["A", "B"], answer_id=2)
        with pytest.raises(ValidationError):
            DeferredVotePayload(question="问题", options=["A", "B"], answer_id=-1)

    def test_side_comment_payload_and_mood_options(self):
        """测试边看边聊载荷与 6 种确定性 mood 选项。"""
        p1 = SideCommentPayload(text="这也太敢说了吧！")
        assert p1.mood is None

        # 测试全部 6 种标准情绪字符串
        valid_moods = ["roast", "shock", "laugh", "praise", "sympathy", "doubt"]
        for mood_name in valid_moods:
            p = SideCommentPayload(text="评论文案", mood=mood_name)
            assert p.mood == mood_name

        # 大小写不敏感校验（如 ROAST 自动转为 roast）
        p_upper = SideCommentPayload(text="大写测试", mood="ROAST")
        assert p_upper.mood == "roast"

        # 非法 mood 选项报错
        with pytest.raises(ValidationError, match="未知的 mood"):
            SideCommentPayload(text="吐槽", mood="invalid_mood")

        with pytest.raises(ValidationError):
            SideCommentPayload(text="")
        with pytest.raises(ValidationError, match="评论文本不能全为空白字符"):
            SideCommentPayload(text="   ")

    def test_final_interaction_valid_and_mismatch(self):
        """测试最终互动模型及 type（支持数字或字符串名）与 payload 一致性校验。"""
        # 合法构造（数字类型）
        fi = FinalInteraction(
            id=1,
            type=1,
            show_at=1000,
            duration_ms=2800,
            payload=EmotionButtonPayload(button_id=0, text="爽"),
        )
        assert fi.id == 1
        assert fi.type == 1
        assert isinstance(fi.payload, EmotionButtonPayload)

        # 字典形式构造自动装配 payload，支持字符串类型名转数字
        fi_dict = FinalInteraction.model_validate(
            {
                "id": 2,
                "type": "instant_vote",  # 字符串自动转 3
                "show_at": 5000,
                "duration_ms": 3500,
                "payload": {"question": "站哪边？", "options": ["左", "右"]},
            }
        )
        assert fi_dict.type == 3
        assert isinstance(fi_dict.payload, InstantVotePayload)

        # type 与 payload 类型不匹配
        with pytest.raises(ValidationError, match="不匹配"):
            FinalInteraction(
                id=3,
                type=1,  # 情绪按钮
                show_at=0,
                duration_ms=2500,
                payload=RepeatKeylinePayload(text="金句"),  # 跟读金句
            )

        # 非法 id / 毫秒
        with pytest.raises(ValidationError):
            FinalInteraction(
                id=0,  # 必须 >= 1
                type=1,
                show_at=0,
                duration_ms=2500,
                payload=EmotionButtonPayload(button_id=0),
            )
        with pytest.raises(ValidationError):
            FinalInteraction(
                id=1,
                type=1,
                show_at=-100,  # 必须 >= 0
                duration_ms=2500,
                payload=EmotionButtonPayload(button_id=0),
            )
        with pytest.raises(ValidationError):
            FinalInteraction(
                id=1,
                type=1,
                show_at=0,
                duration_ms=0,  # 必须 > 0
                payload=EmotionButtonPayload(button_id=0),
            )

    def test_final_interaction_serialization_round_trip(self):
        """测试最终互动模型五类载荷的双向序列化 round-trip。"""
        interactions = [
            FinalInteraction(
                id=1,
                type=1,
                show_at=0,
                duration_ms=2500,
                payload=EmotionButtonPayload(button_id=0, text="爽"),
            ),
            FinalInteraction(
                id=2,
                type=2,
                show_at=3000,
                duration_ms=3700,
                payload=RepeatKeylinePayload(text="金句台词"),
            ),
            FinalInteraction(
                id=3,
                type=3,
                show_at=6000,
                duration_ms=3500,
                payload=InstantVotePayload(question="选谁？", options=["A", "B"]),
            ),
            FinalInteraction(
                id=4,
                type=4,
                show_at=9000,
                duration_ms=3500,
                payload=DeferredVotePayload(
                    question="真相？",
                    options=["真", "假"],
                    answer_id=0,
                    reveal_time=15000,
                    reveal_delay=5000,
                ),
            ),
            FinalInteraction(
                id=5,
                type=5,
                show_at=12000,
                duration_ms=2500,
                payload=SideCommentPayload(text="神评", mood="laugh"),
            ),
        ]

        for item in interactions:
            dumped = item.model_dump()
            json_str = json.dumps(dumped, ensure_ascii=False)
            reconstructed = FinalInteraction.model_validate(json.loads(json_str))
            assert reconstructed == item


# =====================================================================
# 3. 专家与候选契约测试 (Candidate Schemas)
# =====================================================================


class TestCandidateSchema:
    """专家输出与候选数据模型测试集。"""

    def test_trigger_and_reveal_anchors(self):
        """测试锚点数据模型。"""
        ta = TriggerAnchor(window_id=3, transcript_segment_id="t12")
        assert ta.window_id == 3
        assert ta.transcript_segment_id == "t12"

        # 仅窗口锚点（纯视觉/音频）
        ra = RevealAnchor(window_id=8)
        assert ra.transcript_segment_id is None

        # 负数 window_id
        with pytest.raises(ValidationError):
            TriggerAnchor(window_id=-1)
        with pytest.raises(ValidationError):
            RevealAnchor(window_id=-2)

        # 空白 transcript_segment_id
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            TriggerAnchor(window_id=0, transcript_segment_id="   ")
        with pytest.raises(ValidationError, match="不能全为空白字符"):
            RevealAnchor(window_id=0, transcript_segment_id="   ")

        # 禁止多余字段
        with pytest.raises(ValidationError):
            TriggerAnchor(window_id=0, extra="invalid")

    def test_candidate_valid_all_types(self):
        """测试五类合法候选对象构造（模型输出字符串类型名）。"""
        # 1. 情绪按钮
        c1 = Candidate(
            specialist_type="emotion_button",
            evidence_window_ids=[0, 1],
            trigger_anchor=TriggerAnchor(window_id=1, transcript_segment_id="t1"),
            payload=EmotionButtonPayload(button_id=0, text="爽"),
        )
        assert c1.candidate_id is None
        assert c1.reveal_anchor is None

        # 2. 跟读金句
        c2 = Candidate(
            specialist_type="repeat_keyline",
            evidence_window_ids=[2],
            trigger_anchor=TriggerAnchor(window_id=2, transcript_segment_id="t5"),
            payload=RepeatKeylinePayload(text="我在哪，纪家就在哪"),
        )
        assert c2.specialist_type == "repeat_keyline"

        # 3. 即时投票
        c3 = Candidate(
            specialist_type="instant_vote",
            evidence_window_ids=[3],
            trigger_anchor=TriggerAnchor(window_id=3),
            payload=InstantVotePayload(question="站谁？", options=["A", "B"]),
        )
        assert isinstance(c3.payload, InstantVotePayload)

        # 4. 延时投票（必须带 reveal_anchor，生成侧固定 answer_id=0）
        c4 = Candidate(
            specialist_type="deferred_vote",
            evidence_window_ids=[4, 5, 8],
            trigger_anchor=TriggerAnchor(window_id=4),
            reveal_anchor=RevealAnchor(window_id=8, transcript_segment_id="t20"),
            payload=DeferredVotePayload(
                question="他说的是真话吗？",
                options=["真话", "假话"],
                answer_id=0,
            ),
        )
        assert c4.reveal_anchor is not None
        assert c4.reveal_anchor.window_id == 8
        assert c4.payload.answer_id == 0

        # 5. 边看边聊
        c5 = Candidate(
            specialist_type="side_comment",
            evidence_window_ids=[6],
            trigger_anchor=TriggerAnchor(window_id=6),
            payload=SideCommentPayload(text="太劲爆了！", mood="shock"),
        )
        assert isinstance(c5.payload, SideCommentPayload)

    def test_candidate_deferred_vote_silent_millisecond_discard(self):
        """测试零毫秒禁令：生成侧附带的 reveal 毫秒字段静默丢弃为 None 而非报错（ADR-023）。"""
        # 1. 字典形式输入附带毫秒值 -> 自动静默清洗为 None
        c_dict = Candidate.model_validate(
            {
                "specialist_type": "deferred_vote",
                "evidence_window_ids": [1, 5],
                "trigger_anchor": {"window_id": 1},
                "reveal_anchor": {"window_id": 5},
                "payload": {
                    "question": "真相是？",
                    "options": ["A", "B"],
                    "answer_id": 0,
                    "reveal_time": 15000,  # 附带毫秒
                    "reveal_delay": 5000,  # 附带毫秒
                },
            }
        )
        assert isinstance(c_dict.payload, DeferredVotePayload)
        assert c_dict.payload.reveal_time is None
        assert c_dict.payload.reveal_delay is None

        # 2. 模型对象输入附带毫秒值 -> 自动静默清洗为 None
        raw_payload = DeferredVotePayload(
            question="真相是？",
            options=["A", "B"],
            answer_id=0,
            reveal_time=20000,
            reveal_delay=3000,
        )
        c_obj = Candidate(
            specialist_type="deferred_vote",
            evidence_window_ids=[1, 5],
            trigger_anchor=TriggerAnchor(window_id=1),
            reveal_anchor=RevealAnchor(window_id=5),
            payload=raw_payload,
        )
        assert c_obj.payload.reveal_time is None
        assert c_obj.payload.reveal_delay is None

    def test_candidate_deferred_vote_invariants(self):
        """测试延时投票候选的结构约束（缺失 reveal_anchor、揭晓早于触发报错）。"""
        # 缺失 reveal_anchor 报错
        with pytest.raises(ValidationError, match="必须配置 reveal_anchor"):
            Candidate(
                specialist_type="deferred_vote",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=DeferredVotePayload(
                    question="真相是？", options=["A", "B"], answer_id=0
                ),
            )

        # 揭晓窗口早于触发窗口报错
        with pytest.raises(ValidationError, match="不能早于触发窗口"):
            Candidate(
                specialist_type="deferred_vote",
                evidence_window_ids=[1, 5],
                trigger_anchor=TriggerAnchor(window_id=5),
                reveal_anchor=RevealAnchor(window_id=2),  # 早于 5
                payload=DeferredVotePayload(
                    question="真相是？", options=["A", "B"], answer_id=0
                ),
            )

    def test_candidate_non_deferred_vote_with_reveal_anchor_rejected(self):
        """测试全部非延时投票类型均严禁配置 reveal_anchor。"""
        non_deferred_types = [
            ("emotion_button", EmotionButtonPayload(button_id=0)),
            ("repeat_keyline", RepeatKeylinePayload(text="金句")),
            ("instant_vote", InstantVotePayload(question="题干", options=["A", "B"])),
            ("side_comment", SideCommentPayload(text="评论")),
        ]
        for stype, payload in non_deferred_types:
            with pytest.raises(
                ValidationError, match="仅 deferred_vote 允许配置 reveal_anchor"
            ):
                Candidate(
                    specialist_type=stype,
                    evidence_window_ids=[1],
                    trigger_anchor=TriggerAnchor(window_id=1),
                    reveal_anchor=RevealAnchor(window_id=2),  # 非法携带
                    payload=payload,
                )

    def test_candidate_invalid_invariants(self):
        """测试候选非法输入（空白 candidate_id、未知类型、重复窗口 ID、载荷不匹配）。"""
        # 空白 candidate_id
        with pytest.raises(ValidationError, match="candidate_id 不能全为空白字符"):
            Candidate(
                candidate_id="   ",
                specialist_type="emotion_button",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
            )

        # 未知专家类型
        with pytest.raises(ValidationError, match="未知的 specialist_type"):
            Candidate(
                specialist_type="unknown_type",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
            )

        # 空证据窗口列表 / 负数窗口 ID / 重复窗口 ID
        with pytest.raises(ValidationError):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
            )
        with pytest.raises(ValidationError, match="包含非法负数窗口编号"):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[-1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
            )
        with pytest.raises(ValidationError, match="包含重复的窗口编号"):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[1, 1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
            )

        # 载荷类型不匹配
        with pytest.raises(ValidationError, match="不匹配"):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=RepeatKeylinePayload(text="跟读金句"),
            )

    def test_candidate_zero_confidence_fields(self):
        """测试 Candidate 全结构严禁置信度、评分与概率字段（ADR-012）。"""
        with pytest.raises(ValidationError):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
                confidence=0.95,  # type: ignore
            )
        with pytest.raises(ValidationError):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
                score=88,  # type: ignore
            )
        with pytest.raises(ValidationError):
            Candidate(
                specialist_type="emotion_button",
                evidence_window_ids=[1],
                trigger_anchor=TriggerAnchor(window_id=1),
                payload=EmotionButtonPayload(button_id=0),
                probability=0.8,  # type: ignore
            )

    def test_candidate_serialization_round_trip(self):
        """测试 Candidate 对象的 JSON 序列化与反序列化往返。"""
        c = Candidate(
            candidate_id="cand_123",
            specialist_type="instant_vote",
            evidence_window_ids=[2, 3],
            trigger_anchor=TriggerAnchor(window_id=3, transcript_segment_id="t9"),
            payload=InstantVotePayload(question="选谁？", options=["A", "B"]),
        )
        dumped = c.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        reconstructed = Candidate.model_validate(json.loads(json_str))
        assert reconstructed == c

    def test_abstention_model(self):
        """测试专家弃权模型及字段校验。"""
        abs_valid = Abstention(
            specialist_type="repeat_keyline",
            reason="本集无足够辨识度与情绪张力的金句台词",
        )
        assert abs_valid.specialist_type == "repeat_keyline"
        assert len(abs_valid.reason) > 0

        # 空白原因报错
        with pytest.raises(ValidationError, match="弃权原因不能全为空白字符"):
            Abstention(specialist_type="repeat_keyline", reason="   ")

        # 非法专家类型报错
        with pytest.raises(ValidationError, match="未知的 specialist_type"):
            Abstention(specialist_type="invalid", reason="无")

    def test_specialist_result_valid_and_consistency(self):
        """测试专家汇总结果对象及分支类型一致性约束。"""
        cand1 = Candidate(
            specialist_type="emotion_button",
            evidence_window_ids=[1],
            trigger_anchor=TriggerAnchor(window_id=1),
            payload=EmotionButtonPayload(button_id=0),
        )
        abs1 = Abstention(
            specialist_type="emotion_button",
            reason="后半段无合适情绪点",
        )
        res = SpecialistResult(
            specialist_type="emotion_button",
            candidates=[cand1],
            abstentions=[abs1],
        )
        assert len(res.candidates) == 1
        assert len(res.abstentions) == 1

        # 混入其他专家类型的 Candidate 报错
        cand_wrong = Candidate(
            specialist_type="repeat_keyline",
            evidence_window_ids=[2],
            trigger_anchor=TriggerAnchor(window_id=2),
            payload=RepeatKeylinePayload(text="台词"),
        )
        with pytest.raises(
            ValidationError, match="包含类型为 'repeat_keyline' 的 Candidate"
        ):
            SpecialistResult(
                specialist_type="emotion_button",
                candidates=[cand_wrong],
            )

        # 混入其他专家类型的 Abstention 报错
        abs_wrong = Abstention(
            specialist_type="instant_vote",
            reason="无冲突",
        )
        with pytest.raises(
            ValidationError, match="包含类型为 'instant_vote' 的 Abstention"
        ):
            SpecialistResult(
                specialist_type="emotion_button",
                abstentions=[abs_wrong],
            )

    def test_candidate_lifecycle_and_native_json_roundtrip(self):
        """测试 Candidate 生命周期（从生成侧 None 到入池分配 candidate_id）及 Pydantic 原生 JSON 往返。"""
        # 1. 模拟 Specialist / LLM 初始生成候选（candidate_id 为 None，零毫秒，固定 answer_id=0）
        cand_raw = Candidate(
            specialist_type="deferred_vote",
            evidence_window_ids=[0, 1],
            trigger_anchor=TriggerAnchor(window_id=0, transcript_segment_id="t1"),
            reveal_anchor=RevealAnchor(window_id=1),
            payload=DeferredVotePayload(
                question="猜对了吗？", options=["对", "错"], answer_id=0
            ),
        )
        assert cand_raw.candidate_id is None

        # 2. 模拟入池（Pool）时程序后赋值 candidate_id
        cand_pooled = cand_raw.model_copy(update={"candidate_id": "cand_v2_001"})
        assert cand_pooled.candidate_id == "cand_v2_001"
        assert cand_pooled.specialist_type == "deferred_vote"

        # 3. 测试 Pydantic 原生 model_dump_json 与 model_validate_json
        cand_json = cand_pooled.model_dump_json()
        cand_restored = Candidate.model_validate_json(cand_json)
        assert cand_restored == cand_pooled
        assert isinstance(cand_restored.payload, DeferredVotePayload)


# =====================================================================
# 4. 契约包完整性与工程约束测试 (Package Integrity)
# =====================================================================


class TestPackageIntegrity:
    """契约层包导出、依赖纯净度与注释规范测试集。"""

    def test_schema_exports(self):
        """验证 __init__.py 完整导出全部模型与工具。"""
        expected_symbols = [
            "WINDOW_SIZE_MS",
            "TranscriptSegment",
            "EvidenceWindow",
            "validate_evidence_sequence",
            "InteractionType",
            "CommentMood",
            "TYPE_STR_TO_INT",
            "TYPE_INT_TO_STR",
            "MOOD_STR_TO_INT",
            "MOOD_INT_TO_STR",
            "VALID_COMMENT_MOODS",
            "EmotionButtonPayload",
            "RepeatKeylinePayload",
            "InstantVotePayload",
            "DeferredVotePayload",
            "SideCommentPayload",
            "InteractionPayload",
            "FinalInteraction",
            "VALID_SPECIALIST_TYPES",
            "TriggerAnchor",
            "RevealAnchor",
            "Candidate",
            "Abstention",
            "SpecialistResult",
        ]
        for sym in expected_symbols:
            assert hasattr(schemas_pkg, sym), f"schemas 包未导出预期符号: {sym}"
            assert sym in schemas_pkg.__all__, f"__all__ 未包含符号: {sym}"

    def test_no_io_or_llm_dependencies(self):
        """测试契约层零 IO、零 LLM、纯粹 Pydantic 依赖。"""
        forbidden_modules = [
            "openai",
            "langchain",
            "langgraph",
            "requests",
            "httpx",
            "urllib",
            "sqlite3",
            "pathlib",
        ]
        import drama_interaction.schemas.evidence as ev_mod
        import drama_interaction.schemas.interaction as in_mod
        import drama_interaction.schemas.candidate as ca_mod

        for mod in (ev_mod, in_mod, ca_mod):
            mod_code = inspect.getsource(mod)
            for forbidden in forbidden_modules:
                assert (
                    f"import {forbidden}" not in mod_code
                ), f"契约模块 {mod.__name__} 违规导入外部 IO/LLM 依赖: {forbidden}"

    def test_docstrings_in_chinese(self):
        """测试全部导出类的 docstring 均存在且包含中文描述。"""
        import drama_interaction.schemas as pkg

        def contains_chinese(text: str) -> bool:
            return any("\u4e00" <= char <= "\u9fff" for char in text)

        for name in pkg.__all__:
            obj = getattr(pkg, name)
            if inspect.isclass(obj):
                doc = inspect.getdoc(obj)
                assert doc is not None, f"类 {name} 缺少 docstring"
                assert contains_chinese(doc), f"类 {name} docstring 缺少中文解释: {doc}"

    def test_extra_fields_forbidden_on_all_models(self):
        """测试所有模型均启用 extra='forbid'。"""
        import drama_interaction.schemas as pkg

        for name in pkg.__all__:
            obj = getattr(pkg, name)
            if inspect.isclass(obj) and issubclass(
                obj,
                schemas_pkg.BaseModel if hasattr(schemas_pkg, "BaseModel") else object,
            ):
                if hasattr(obj, "model_config"):
                    assert (
                        obj.model_config.get("extra") == "forbid"
                    ), f"模型 {name} 未配置 extra='forbid'"
