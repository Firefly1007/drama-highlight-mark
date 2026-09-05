"""剧集级上下文加载与数据模型。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from drama_interaction.config import DEFAULT_DRAMA_INFO_PATH


class DramaContext(BaseModel):
    """一部剧集共享的简介与角色表。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    characters: list[str] = Field(default_factory=list)


def load_drama_context(
    input_path: str | Path,
    info_path: str | Path = DEFAULT_DRAMA_INFO_PATH,
) -> DramaContext:
    """按输入文件父目录名称加载剧集上下文。"""

    drama_name = Path(input_path).parent.name
    with Path(info_path).open(encoding="utf-8") as file:
        records = json.load(file)
    if not isinstance(records, list):
        raise ValueError("drama_info.json 顶层必须是数组")
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict) and item.get("name") == drama_name
        ),
        None,
    )
    if record is None:
        raise ValueError(f"drama_info.json 中不存在剧集: {drama_name}")
    return DramaContext.model_validate(record)


__all__ = ["DEFAULT_DRAMA_INFO_PATH", "DramaContext", "load_drama_context"]
