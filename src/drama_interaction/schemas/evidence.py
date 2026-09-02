"""证据数据契约层模块。

定义共享证据（Shared Evidence）的核心数据结构：
EvidenceWindow（3秒固定窗口）与 TranscriptSegment（精确台词片段），
并将视觉观察、音频观察与屏上文字统一按 3 秒窗口简化为字符串列表，提供序列级窗口纪律校验。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drama_interaction.config import WINDOW_SIZE_MS


class TranscriptSegment(BaseModel):
    """台词语音片段数据模型。

    承载 ASR 识别出的单句台词文本及其实际时间戳。

    Attributes:
        id: 台词唯一标识符。
        start_ms: 片段开始时间（毫秒），必须非负且小于等于 end_ms。
        end_ms: 片段结束时间（毫秒），必须大于等于 start_ms。
        text: 台词文本内容，不能为空。
        speaker_label: 说话人匿名标签（如 speaker_1、speaker_2），可为空。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="台词唯一标识符")
    start_ms: int = Field(..., ge=0, description="片段开始时间（毫秒）")
    end_ms: int = Field(..., ge=0, description="片段结束时间（毫秒）")
    text: str = Field(..., min_length=1, description="台词文本内容")
    speaker_label: str | None = Field(default=None, description="说话人匿名标签")

    @field_validator("id")
    @classmethod
    def validate_id_not_blank(cls, v: str) -> str:
        """校验台词标识符不能全为空白字符。

        Args:
            v: 输入的台词标识符。

        Returns:
            校验通过的标识符。

        Raises:
            ValueError: 当标识符全为空白字符时抛出。
        """
        # 台词 ID 必须具有实际字符
        if not v.strip():
            raise ValueError("台词标识符不能全为空白字符")
        return v

    @field_validator("speaker_label")
    @classmethod
    def validate_speaker_label_not_blank(cls, v: str | None) -> str | None:
        """校验说话人标签若提供则不能全为空白字符。

        Args:
            v: 输入的说话人标签。

        Returns:
            校验通过的说话人标签。

        Raises:
            ValueError: 当标签全为空白字符时抛出。
        """
        # 说话人标签非空时必须有实质字符
        if v is not None and not v.strip():
            raise ValueError("说话人标签不能全为空白字符")
        return v

    @field_validator("text")
    @classmethod
    def validate_text_not_blank(cls, v: str) -> str:
        """校验台词文本不能全为空白字符。

        Args:
            v: 输入的台词文本。

        Returns:
            校验通过的台词文本。

        Raises:
            ValueError: 当文本为空白字符时抛出。
        """
        # 台词文本不能全为空白
        if not v.strip():
            raise ValueError("台词文本不能全为空白字符")
        return v

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranscriptSegment":
        """校验台词片段的时间戳区间合法性。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当 start_ms 大于 end_ms 时抛出。
        """
        # 确保开始时间不晚于结束时间
        if self.start_ms > self.end_ms:
            raise ValueError(
                f"台词片段开始时间 ({self.start_ms}ms) 不能大于结束时间 ({self.end_ms}ms)"
            )
        return self


class EvidenceWindow(BaseModel):
    """单个固定 3 秒证据窗口数据模型。

    短剧证据组织、检索与验证的基础单元。
    视觉观察、音频观察与屏上文字均依附并继承该 3 秒窗口时间范围，直接使用字符串列表承载（ADR-006）。

    Attributes:
        window_id: 窗口序号（0-based 自增整数）。
        start_ms: 窗口开始时间（毫秒），必须与 window_id * 3000 对齐。
        end_ms: 窗口结束时间（毫秒），必须大于 start_ms 且不超过 start_ms + 3000。
        transcript_segments: 窗口内包含（相交）的精确台词片段列表。
        onscreen_texts: 窗口内出现的屏上文字（OCR）描述列表。
        visual_observations: 窗口内客观视觉动作/画面观察描述列表。
        audio_observations: 窗口内客观音频/配乐/音效观察描述列表。
        uncertainty: 窗口内不确定性描述列表。
    """

    model_config = ConfigDict(extra="forbid")

    window_id: int = Field(..., ge=0, description="窗口序号（从0开始）")
    start_ms: int = Field(..., ge=0, description="窗口开始时间（毫秒）")
    end_ms: int = Field(..., ge=0, description="窗口结束时间（毫秒）")
    transcript_segments: list[TranscriptSegment] = Field(
        default_factory=list, description="精确台词片段列表"
    )
    onscreen_texts: list[str] = Field(
        default_factory=list, description="屏上文字列表（依附当前3秒窗口）"
    )
    visual_observations: list[str] = Field(
        default_factory=list, description="客观视觉观察描述列表（纯文本）"
    )
    audio_observations: list[str] = Field(
        default_factory=list, description="客观音频观察描述列表（纯文本）"
    )
    uncertainty: list[str] = Field(default_factory=list, description="不确定性信息列表")

    @field_validator(
        "onscreen_texts", "visual_observations", "audio_observations", "uncertainty"
    )
    @classmethod
    def validate_string_list_not_blank(cls, v: list[str]) -> list[str]:
        """校验字符串列表中的每一项均不能全为空白字符。

        Args:
            v: 输入的字符串列表。

        Returns:
            校验通过的字符串列表。

        Raises:
            ValueError: 当存在全为空白字符的描述条目时抛出。
        """
        for item in v:
            # 条目内容必须具有实质性信息
            if not item.strip():
                raise ValueError("列表条目不能全为空白字符")
        return v

    @model_validator(mode="after")
    def validate_window_discipline(self) -> "EvidenceWindow":
        """校验单个窗口的时间边界与序号对齐纪律。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当时间对齐或时长超出 3 秒限制时抛出。
        """
        # 窗口开始时间必须严格对齐序号边界：window_id * 3000
        expected_start = self.window_id * WINDOW_SIZE_MS
        if self.start_ms != expected_start:
            raise ValueError(
                f"窗口 {self.window_id} 开始时间 ({self.start_ms}ms) "
                f"与预期边界 ({expected_start}ms) 不匹配"
            )

        # 结束时间必须严格大于开始时间
        if self.end_ms <= self.start_ms:
            raise ValueError(
                f"窗口 {self.window_id} 结束时间 ({self.end_ms}ms) "
                f"必须大于开始时间 ({self.start_ms}ms)"
            )

        # 单个窗口时长不得超过 3000 毫秒
        window_duration = self.end_ms - self.start_ms
        if window_duration > WINDOW_SIZE_MS:
            raise ValueError(
                f"窗口 {self.window_id} 时长 ({window_duration}ms) "
                f"超过最大窗口长度 ({WINDOW_SIZE_MS}ms)"
            )

        return self


def validate_evidence_sequence(windows: list[EvidenceWindow]) -> None:
    """校验全集证据窗口序列的连续性、无重叠与跨窗复制一致性纪律。

    业务规则：
    1. 窗口列表可以为空；若非空，window_id 必须从 0 开始连续自增。
    2. 除末尾最后一个窗口外，其余所有窗口时长必须严格等于 3000ms。
    3. 末尾窗口时长允许短于 3000ms（如剧集收尾），但必须大于 0ms。
    4. 相邻窗口之间必须首尾相接，无时间间隙且无时间重叠。
    5. 单个窗口内部台词片段 id 不得重复。
    6. 跨窗口复制的台词片段（相同 id）其字段（start_ms, end_ms, text, speaker_label）必须完全一致。

    Args:
        windows: 待校验的证据窗口列表。

    Raises:
        ValueError: 当窗口序号不连续、时间重叠/间隙、时长不合规或跨窗台词数据不一致时抛出。
    """
    if not windows:
        # 空序列合法
        return

    # 用于校验跨窗复制一致性的台词缓存字典：id -> TranscriptSegment
    seen_transcripts: dict[str, TranscriptSegment] = {}

    total_windows = len(windows)
    for idx, win in enumerate(windows):
        # 1. 窗口序号必须从 0 开始连续自增
        if win.window_id != idx:
            raise ValueError(
                f"窗口序号不连续：索引 {idx} 处窗口的 window_id 为 {win.window_id}"
            )

        # 2. 窗口开始时间检查（确保与序号严格对齐）
        expected_start = idx * WINDOW_SIZE_MS
        if win.start_ms != expected_start:
            raise ValueError(
                f"窗口 {win.window_id} 开始时间 ({win.start_ms}ms) "
                f"与序号预期 ({expected_start}ms) 不一致"
            )

        # 3. 时长检查：非末尾窗口必须严格等于 3000ms，末尾窗口必须在 (0, 3000ms] 内
        duration = win.end_ms - win.start_ms
        is_last_window = idx == total_windows - 1
        if not is_last_window:
            if duration != WINDOW_SIZE_MS:
                raise ValueError(
                    f"非末尾窗口 {win.window_id} 时长 ({duration}ms) 必须严格等于 {WINDOW_SIZE_MS}ms"
                )
        else:
            if not (0 < duration <= WINDOW_SIZE_MS):
                raise ValueError(
                    f"末尾窗口 {win.window_id} 时长 ({duration}ms) 必须在 (0, {WINDOW_SIZE_MS}ms] 范围内"
                )

        # 4. 相邻窗口连续性检查
        if idx > 0:
            prev_win = windows[idx - 1]
            if prev_win.end_ms != win.start_ms:
                raise ValueError(
                    f"窗口 {prev_win.window_id} 结束时间 ({prev_win.end_ms}ms) "
                    f"与窗口 {win.window_id} 开始时间 ({win.start_ms}ms) 不连续"
                )

        # 5. 单窗口内台词 ID 唯一性检查
        window_ts_ids: set[str] = set()
        for ts in win.transcript_segments:
            if ts.id in window_ts_ids:
                raise ValueError(
                    f"窗口 {win.window_id} 内存在重复的台词片段 id: '{ts.id}'"
                )
            window_ts_ids.add(ts.id)

        # 6. 跨窗口台词复制完整性校验（ADR-004）
        for ts in win.transcript_segments:
            if ts.id in seen_transcripts:
                prev_ts = seen_transcripts[ts.id]
                # 相同 id 的台词在所有相交窗口中必须保留完全相同的属性
                if (
                    ts.start_ms != prev_ts.start_ms
                    or ts.end_ms != prev_ts.end_ms
                    or ts.text != prev_ts.text
                    or ts.speaker_label != prev_ts.speaker_label
                ):
                    raise ValueError(
                        f"跨窗口台词片段复制数据不一致：id='{ts.id}' "
                        f"在窗口 {win.window_id} 与先前窗口记录不匹配 "
                        f"(当前: start={ts.start_ms}, end={ts.end_ms}, text='{ts.text}', speaker='{ts.speaker_label}'; "
                        f"先前: start={prev_ts.start_ms}, end={prev_ts.end_ms}, text='{prev_ts.text}', speaker='{prev_ts.speaker_label}')"
                    )
            else:
                # 记录首次出现的台词片段
                seen_transcripts[ts.id] = ts
