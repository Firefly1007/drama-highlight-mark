import functools
import json
import random
import unicodedata
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import BaseModel, ValidationError
from tqdm import tqdm

from pipline.common.paths import DATA_DIR
from pipline.common.schemas import (
    DEFERRED_VOTE_TOP_LEVEL_TYPE,
    DramaInfo,
    EMOTION_BUTTON_TOP_LEVEL_TYPE,
    EMOTION_BUTTON_TYPE_TO_ID,
    DeferredVoteInteractionItem,
    DeferredVoteModelDocument,
    DeferredVotePayload,
    DeferredVotePreparedInteractionItem,
    EmotionButtonInteractionItem,
    EmotionButtonModelDocument,
    EmotionButtonPayload,
    EmotionButtonPreparedInteractionItem,
    FinalHighlightItem,
    HighlightsDocument,
    HighlightsList,
    INSTANT_VOTE_TOP_LEVEL_TYPE,
    InstantVoteInteractionItem,
    InstantVoteModelDocument,
    InstantVotePayload,
    InstantVotePreparedInteractionItem,
    InteractionsDocument,
    PreparedInteractionVariant,
    REPEAT_KEYLINE_TOP_LEVEL_TYPE,
    RepeatKeylineInteractionItem,
    RepeatKeylineModelDocument,
    RepeatKeylinePayload,
    RepeatKeylinePreparedInteractionItem,
    SIDE_COMMENT_TOP_LEVEL_TYPE,
    SegmentsDocument,
    SegmentsList,
    SideCommentInteractionItem,
    SideCommentModelDocument,
    SideCommentPayload,
    SideCommentPreparedInteractionItem,
)

DRAMA_INFO_PATH = DATA_DIR / "video" / "drama_info.json"
MAX_INTERACTION_DURATION_MS = 5000
SIDE_COMMENT_MAX_DURATION_MS = 3000


def timestamp_to_milliseconds(timestamp: str) -> int:
    """将 HH:MM:SS.mmm 格式时间转换为相对视频开始的毫秒整数。"""
    hh, mm, ss_mmm = timestamp.split(":")
    ss, mmm = ss_mmm.split(".")
    return (
        int(hh) * 60 * 60 * 1000
        + int(mm) * 60 * 1000
        + int(ss) * 1000
        + int(mmm)
    )


def get_highpoint_duration_ms(highpoint: FinalHighlightItem) -> int:
    """计算互动持续时长：trigger segment 结束后加 700ms，并限制最大 5000ms。"""
    segment_map = {segment.id: segment for segment in highpoint.evidence_segments}
    trigger_segment = segment_map.get(highpoint.trigger_segment_id)
    if trigger_segment is None:
        raise ValueError(
            "interactions.json 校验失败: "
            f"highpoint_id={highpoint.id} 的 trigger_segment_id={highpoint.trigger_segment_id} "
            "不在 evidence_segments 中"
        )

    show_at_ms = timestamp_to_milliseconds(trigger_segment.start)
    end_ms = timestamp_to_milliseconds(trigger_segment.end) + 700
    duration_ms = end_ms - show_at_ms
    if duration_ms <= 0:
        raise ValueError(
            "interactions.json 校验失败: "
            f"highpoint_id={highpoint.id} 的 trigger segment 结束时间必须晚于开始时间"
        )
    return min(duration_ms, MAX_INTERACTION_DURATION_MS)


def load_drama_info() -> dict[str, DramaInfo]:
    with open(DRAMA_INFO_PATH, "r", encoding="utf-8") as f:
        drama_list_raw = json.loads(f.read())
    drama_map: dict[str, DramaInfo] = {}
    for item in drama_list_raw:
        drama = DramaInfo.model_validate(item)
        drama_map[drama.name] = drama
    return drama_map


def get_drama_name_from_path(path: str | Path) -> str:
    return Path(path).parent.name


class EpisodeStatus(str, Enum):
    """表示单个剧集处理任务的生命周期状态。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


def parse_segments_document(raw_text: str) -> SegmentsDocument:
    """校验并解析 segments 文档 JSON。"""
    try:
        return SegmentsDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"segments.json 校验失败: {exc}") from exc


def parse_segments_list(raw_text: str) -> list:
    """校验并解析以数组为根节点的 segments JSON。"""
    try:
        return SegmentsList.model_validate_json(raw_text).root
    except ValidationError as exc:
        raise ValueError(f"segments.json 校验失败: {exc}") from exc


def parse_highlights_document(
    raw_text: str, segments: list | None = None
) -> list[FinalHighlightItem]:
    """校验并解析模型输出的 highlights 文档。"""
    try:
        doc = HighlightsDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"highlights.json 校验失败: {exc}") from exc

    if segments is None:
        raise ValueError("highlights.json 校验失败: 缺少原始 segments，无法补全最终结果")

    return doc.validate_against_segments(segments)


def parse_highlights_list(raw_text: str) -> list:
    """校验并解析以数组为根节点的最终 highlights JSON。"""
    try:
        return HighlightsList.model_validate_json(raw_text).root
    except ValidationError as exc:
        raise ValueError(f"highlights.json 校验失败: {exc}") from exc


def parse_interactions_document(raw_text: str) -> InteractionsDocument:
    """校验并解析 interactions 文档 JSON。"""
    try:
        return InteractionsDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"interactions.json 校验失败: {exc}") from exc


def parse_emotion_button_candidates_document(
    raw_text: str, highpoints: list[FinalHighlightItem]
) -> list[EmotionButtonPreparedInteractionItem]:
    """校验 emotion_button 模型输出，并转换为最终 interaction 中间结果。"""
    try:
        doc = EmotionButtonModelDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"interactions.json 校验失败: {exc}") from exc

    highpoint_map = {highpoint.id: highpoint for highpoint in highpoints}
    prepared_items: list[EmotionButtonPreparedInteractionItem] = []

    for index, item in enumerate(doc.interactions, start=1):
        highpoint = highpoint_map.get(item.highpoint_id)
        if highpoint is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 highpoint_id={item.highpoint_id} "
                "在输入 highpoints 中不存在"
            )

        segment_map = {segment.id: segment for segment in highpoint.evidence_segments}
        segment = segment_map.get(highpoint.trigger_segment_id)
        if segment is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"highpoint_id={highpoint.id} 的 trigger_segment_id={highpoint.trigger_segment_id} "
                "不在 evidence_segments 中"
            )

        prepared_items.append(
            EmotionButtonPreparedInteractionItem(
                type=EMOTION_BUTTON_TOP_LEVEL_TYPE,
                show_at=timestamp_to_milliseconds(segment.start),
                duration_ms=get_highpoint_duration_ms(highpoint),
                payload=EmotionButtonPayload(
                    button_id=EMOTION_BUTTON_TYPE_TO_ID[item.payload.button_type],
                    text=item.payload.text,
                    danmaku=item.payload.danmaku,
                ),
            )
        )

    return prepared_items


def strip_punctuation_for_match(text: str) -> str:
    """移除文本中的 Unicode 标点，保留原始字词顺序用于匹配。"""
    return "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("P")
    )


def validate_repeat_keyline_text_against_highpoint(
    text: str, highpoint: FinalHighlightItem
) -> None:
    """校验复述文本确实存在于当前 highpoint 的原始证据文本中。"""
    candidate = strip_punctuation_for_match(text)
    evidence_text = "".join(segment.text for segment in highpoint.evidence_segments)
    normalized_evidence_text = strip_punctuation_for_match(evidence_text)

    if candidate not in normalized_evidence_text:
        raise ValueError(
            "interactions.json 校验失败: "
            f"highpoint_id={highpoint.id} 的 payload.text 在对应 evidence_segments 中不存在"
        )


def parse_repeat_keyline_candidates_document(
    raw_text: str, highpoints: list[FinalHighlightItem]
) -> list[RepeatKeylinePreparedInteractionItem]:
    """校验 repeat_keyline 模型输出，并转换为最终 interaction 中间结果。"""
    try:
        doc = RepeatKeylineModelDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"interactions.json 校验失败: {exc}") from exc

    highpoint_map = {highpoint.id: highpoint for highpoint in highpoints}
    prepared_items: list[RepeatKeylinePreparedInteractionItem] = []

    for index, item in enumerate(doc.interactions, start=1):
        highpoint = highpoint_map.get(item.highpoint_id)
        if highpoint is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 highpoint_id={item.highpoint_id} "
                "在输入 highpoints 中不存在"
            )

        segment_map = {segment.id: segment for segment in highpoint.evidence_segments}
        segment = segment_map.get(highpoint.trigger_segment_id)
        if segment is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"highpoint_id={highpoint.id} 的 trigger_segment_id={highpoint.trigger_segment_id} "
                "不在 evidence_segments 中"
            )

        validate_repeat_keyline_text_against_highpoint(item.payload.text, highpoint)

        prepared_items.append(
            RepeatKeylinePreparedInteractionItem(
                type=REPEAT_KEYLINE_TOP_LEVEL_TYPE,
                show_at=timestamp_to_milliseconds(segment.start),
                duration_ms=get_highpoint_duration_ms(highpoint),
                payload=RepeatKeylinePayload(
                    text=item.payload.text,
                ),
            )
        )

    return prepared_items


def parse_instant_vote_candidates_document(
    raw_text: str, highpoints: list[FinalHighlightItem]
) -> list[InstantVotePreparedInteractionItem]:
    """校验 instant_vote 模型输出，并转换为最终 interaction 中间结果。"""
    try:
        doc = InstantVoteModelDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"interactions.json 校验失败: {exc}") from exc

    highpoint_map = {highpoint.id: highpoint for highpoint in highpoints}
    prepared_items: list[InstantVotePreparedInteractionItem] = []

    for index, item in enumerate(doc.interactions, start=1):
        highpoint = highpoint_map.get(item.highpoint_id)
        if highpoint is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 highpoint_id={item.highpoint_id} "
                "在输入 highpoints 中不存在"
            )

        segment_map = {segment.id: segment for segment in highpoint.evidence_segments}
        segment = segment_map.get(highpoint.trigger_segment_id)
        if segment is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"highpoint_id={highpoint.id} 的 trigger_segment_id={highpoint.trigger_segment_id} "
                "不在 evidence_segments 中"
            )

        prepared_items.append(
            InstantVotePreparedInteractionItem(
                type=INSTANT_VOTE_TOP_LEVEL_TYPE,
                show_at=timestamp_to_milliseconds(segment.start),
                duration_ms=get_highpoint_duration_ms(highpoint),
                payload=InstantVotePayload(
                    question=item.payload.question,
                    options=item.payload.options,
                ),
            )
        )

    return prepared_items


def shuffle_deferred_vote_options(options: list[str]) -> tuple[list[str], int]:
    """随机打乱 deferred_vote 选项，并返回正确答案的新下标。"""
    shuffled_options = options.copy()
    correct_option = shuffled_options[0]
    random.shuffle(shuffled_options)
    return shuffled_options, shuffled_options.index(correct_option)


def parse_deferred_vote_candidates_document(
    raw_text: str, highpoints: list[FinalHighlightItem]
) -> list[DeferredVotePreparedInteractionItem]:
    """校验 deferred_vote 模型输出，并转换为最终 interaction 中间结果。"""
    try:
        doc = DeferredVoteModelDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"interactions.json 校验失败: {exc}") from exc

    highpoint_map = {highpoint.id: highpoint for highpoint in highpoints}
    prepared_items: list[DeferredVotePreparedInteractionItem] = []

    for index, item in enumerate(doc.interactions, start=1):
        highpoint = highpoint_map.get(item.highpoint_id)
        if highpoint is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 highpoint_id={item.highpoint_id} "
                "在输入 highpoints 中不存在"
            )

        segment_map = {segment.id: segment for segment in highpoint.evidence_segments}
        segment = segment_map.get(highpoint.trigger_segment_id)
        if segment is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"highpoint_id={highpoint.id} 的 trigger_segment_id={highpoint.trigger_segment_id} "
                "不在 evidence_segments 中"
            )

        reveal_highpoint = highpoint_map.get(item.payload.reveal_id)
        if reveal_highpoint is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 reveal_id={item.payload.reveal_id} "
                "在输入 highpoints 中不存在"
            )
        if item.payload.reveal_id <= item.highpoint_id:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 reveal_id={item.payload.reveal_id} "
                f"必须晚于 highpoint_id={item.highpoint_id}"
            )

        reveal_segment_map = {
            candidate.id: candidate for candidate in reveal_highpoint.evidence_segments
        }
        reveal_segment = reveal_segment_map.get(reveal_highpoint.trigger_segment_id)
        if reveal_segment is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"reveal highpoint_id={reveal_highpoint.id} 的 trigger_segment_id={reveal_highpoint.trigger_segment_id} "
                "不在 evidence_segments 中"
            )

        shuffled_options, answer_id = shuffle_deferred_vote_options(
            item.payload.options
        )

        prepared_items.append(
            DeferredVotePreparedInteractionItem(
                type=DEFERRED_VOTE_TOP_LEVEL_TYPE,
                show_at=timestamp_to_milliseconds(segment.start),
                duration_ms=get_highpoint_duration_ms(highpoint),
                payload=DeferredVotePayload(
                    question=item.payload.question,
                    options=shuffled_options,
                    reveal_time=timestamp_to_milliseconds(reveal_segment.start),
                    reveal_delay=get_highpoint_duration_ms(reveal_highpoint),
                    answer_id=answer_id,
                ),
            )
        )

    return prepared_items


def parse_side_comment_candidates_document(
    raw_text: str, highpoints: list[FinalHighlightItem]
) -> list[SideCommentPreparedInteractionItem]:
    """校验 side_comment 模型输出，并转换为最终 interaction 中间结果。"""
    try:
        doc = SideCommentModelDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"interactions.json 校验失败: {exc}") from exc

    highpoint_map = {highpoint.id: highpoint for highpoint in highpoints}
    prepared_items: list[SideCommentPreparedInteractionItem] = []

    for index, item in enumerate(doc.interactions, start=1):
        highpoint = highpoint_map.get(item.highpoint_id)
        if highpoint is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"第 {index} 条 interaction 的 highpoint_id={item.highpoint_id} "
                "在输入 highpoints 中不存在"
            )

        segment_map = {segment.id: segment for segment in highpoint.evidence_segments}
        segment = segment_map.get(highpoint.trigger_segment_id)
        if segment is None:
            raise ValueError(
                "interactions.json 校验失败: "
                f"highpoint_id={highpoint.id} 的 trigger_segment_id={highpoint.trigger_segment_id} "
                "不在 evidence_segments 中"
            )

        prepared_items.append(
            SideCommentPreparedInteractionItem(
                type=SIDE_COMMENT_TOP_LEVEL_TYPE,
                show_at=timestamp_to_milliseconds(segment.start),
                duration_ms=min(
                    get_highpoint_duration_ms(highpoint),
                    SIDE_COMMENT_MAX_DURATION_MS,
                ),
                payload=SideCommentPayload(text=item.payload.text),
            )
        )

    return prepared_items


def build_interactions_document(
    prepared_items: Sequence[PreparedInteractionVariant],
) -> InteractionsDocument:
    """按时间排序并补全 id 后，构造最终 interaction 根文档。"""
    sorted_items = sorted(prepared_items, key=lambda item: (item.show_at, item.duration_ms))
    return InteractionsDocument(
        root=[
            EmotionButtonInteractionItem(
                id=index,
                type=item.type,
                show_at=item.show_at,
                duration_ms=item.duration_ms,
                payload=item.payload,
            )
            if item.type == EMOTION_BUTTON_TOP_LEVEL_TYPE
            else RepeatKeylineInteractionItem(
                id=index,
                type=item.type,
                show_at=item.show_at,
                duration_ms=item.duration_ms,
                payload=item.payload,
            )
            if item.type == REPEAT_KEYLINE_TOP_LEVEL_TYPE
            else InstantVoteInteractionItem(
                id=index,
                type=item.type,
                show_at=item.show_at,
                duration_ms=item.duration_ms,
                payload=item.payload,
            )
            if item.type == INSTANT_VOTE_TOP_LEVEL_TYPE
            else DeferredVoteInteractionItem(
                id=index,
                type=item.type,
                show_at=item.show_at,
                duration_ms=item.duration_ms,
                payload=item.payload,
            )
            if item.type == DEFERRED_VOTE_TOP_LEVEL_TYPE
            else SideCommentInteractionItem(
                id=index,
                type=item.type,
                show_at=item.show_at,
                duration_ms=item.duration_ms,
                payload=item.payload,
            )
            for index, item in enumerate(sorted_items, start=1)
        ]
    )


def print_episode_status(
    status: EpisodeStatus,
    *,
    source_path: str,
    output_path: str,
    error: str = "",
) -> None:
    """输出单个剧集处理任务的状态信息。"""
    message = f"[{status.value}] {source_path} -> {output_path}"
    if error:
        message = f"{message} | {error}"
    tqdm.write(message)


def write_json_document(output_path: str, data: BaseModel | dict[str, Any] | list[Any]) -> None:
    """将模型对象、字典或列表写入格式化 JSON 文件。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, BaseModel):
        payload = data.model_dump(mode="json")
    elif isinstance(data, list):
        payload = [item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in data]
    else:
        payload = data
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def with_retry(max_attempts: int = 3, *, label: str | None = None) -> Callable:
    """为异步函数添加重试机制，失败后立即重试。"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            retry_label = label or func.__name__
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        tqdm.write(
                            f"[retrying][{retry_label}] 第 {attempt} 次失败，剩余 {max_attempts - attempt} 次: {exc}"
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
