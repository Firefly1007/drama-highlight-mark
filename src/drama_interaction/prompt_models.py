"""模型结构化输出工具使用的 Pydantic 模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OCRResponse(BaseModel):
    """OCR 提取结果。"""

    model_config = ConfigDict(extra="forbid")

    onscreen_texts: list[str] = Field(
        ..., description="当前切片画面中可见的全部屏幕文字；无文字时为空数组"
    )


class VLMResponse(BaseModel):
    """视觉观察提取结果。"""

    model_config = ConfigDict(extra="forbid")

    visual_observations: list[str] = Field(
        ..., description="当前切片中可直接观察到的视觉事实；无内容时为空数组"
    )
    uncertainty: list[str] = Field(
        ..., description="无法从采样帧可靠判定的观察；无不确定点时为空数组"
    )


class AudioObserverResponse(BaseModel):
    """背景音频观察提取结果。"""

    model_config = ConfigDict(extra="forbid")

    audio_observations: list[str] = Field(
        ..., description="当前背景音切片中可听见的客观声音事实；无内容时为空数组"
    )
    uncertainty: list[str] = Field(
        ..., description="无法从背景音可靠判定的观察；无不确定点时为空数组"
    )


class VideoObserverResponse(BaseModel):
    """原始视频按需观察结果。"""

    model_config = ConfigDict(extra="forbid")

    visual_observations: list[str] = Field(...)
    onscreen_texts: list[str] = Field(...)
    audio_observations: list[str] = Field(...)
    uncertainty: list[str] = Field(...)


__all__ = ["AudioObserverResponse", "OCRResponse", "VLMResponse", "VideoObserverResponse"]
