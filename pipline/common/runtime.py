import functools
import json
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from tqdm import tqdm

from pipline.common.schemas import (
    HighlightOutput,
    HighlightsDocument,
    HighlightsList,
    InteractionsDocument,
    SegmentsDocument,
    SegmentsList,
)


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


def parse_highlights_document(raw_text: str, segments: list | None = None) -> list[HighlightOutput]:
    """校验并解析 highlights 文档 JSON，返回含 start/end 的输出列表。"""
    try:
        doc = HighlightsDocument.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"highlights.json 校验失败: {exc}") from exc

    if segments is not None:
        return doc.validate_against_segments(segments)

    return [HighlightOutput(
        id=h.id,
        start="00:00:00.000",
        end="00:00:00.000",
        label=h.label,
        level=h.level,
        summary=h.summary,
        reason=h.reason,
        evidence=h.evidence,
    ) for h in doc.highlights]


def parse_highlights_list(raw_text: str) -> list:
    """校验并解析以数组为根节点的 highlights JSON。"""
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


def with_retry(max_attempts: int = 3) -> Callable:
    """为异步函数添加重试机制，失败后立即重试。"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        tqdm.write(f"[retrying] 第 {attempt} 次失败，剩余 {max_attempts - attempt} 次: {str(exc).splitlines()[0]}")
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
