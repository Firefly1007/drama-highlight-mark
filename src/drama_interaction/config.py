"""全局配置与参数常量模块。

集中存放项目中所有可根据业务需要进行调整的全局变量与参数，尤其是数字类阈值与默认值。
各功能模块均从此模块导入配置，避免在代码中硬编码 Magic Number。
"""

# =====================================================================
# 1. 证据与时间窗口参数 (Evidence & Window)
# =====================================================================

# 单个共享证据窗口的固定时长（毫秒，ADR-002 / ADR-019）
WINDOW_SIZE_MS: int = 3000


# =====================================================================
# 2. 渲染时长与展示参数（毫秒，ADR-023）
# =====================================================================

# 情绪按钮（emotion_button）基准展示时长（毫秒，单击动作无需阅读）
DEFAULT_EMOTION_BUTTON_DURATION_MS: int = 2500

# 跟读金句（repeat_keyline）基准展示时长（毫秒，内容自适应）
DEFAULT_REPEAT_KEYLINE_DURATION_MS: int = 2500

# 即时投票（instant_vote）基准展示时长（毫秒，读题+选项点击）
DEFAULT_INSTANT_VOTE_DURATION_MS: int = 3500

# 延时投票（deferred_vote）基准展示时长（毫秒，读题+选项点击）
DEFAULT_DEFERRED_VOTE_DURATION_MS: int = 3500

# 边看边聊（side_comment）基准展示时长（毫秒，纯阅读无需操作）
DEFAULT_SIDE_COMMENT_DURATION_MS: int = 2500

# 跟读金句台词尾部缓冲时间（毫秒，沿用 V1 生理时间常量）
KEYLINE_TAIL_MS: int = 700

# 跟读金句展示时长硬下限（毫秒，生理限制代码常量，不参与调参）
KEYLINE_DURATION_FLOOR: int = 2500

# 跟读金句展示时长硬上限（毫秒，生理限制代码常量，不参与调参）
KEYLINE_DURATION_CEIL: int = 4500

# 延时投票揭晓弹窗展示时长（毫秒）
DEFAULT_REVEAL_DISPLAY_MS: int = 3000

# 延时投票揭晓时刻与提问触发结束点之间的最小安全间隔（毫秒，ADR-023）
DEFAULT_REVEAL_GAP_MIN_MS: int = 5000


# =====================================================================
# 3. 互动形态与选项数量约束 (Interaction Shape Constraints)
# =====================================================================

# 情绪按钮合法编号最小值
EMOTION_BUTTON_MIN_ID: int = 0

# 情绪按钮合法编号最大值
EMOTION_BUTTON_MAX_ID: int = 5

# 即时投票严格要求的选项数量
INSTANT_VOTE_OPTIONS_COUNT: int = 2

# 延时投票支持的最小选项数量
DEFERRED_VOTE_MIN_OPTIONS: int = 2

# 延时投票支持的最大选项数量
DEFERRED_VOTE_MAX_OPTIONS: int = 4

# 延时投票生成侧固定输出的正确答案索引（0 号位）
DEFAULT_DEFERRED_VOTE_ANSWER_ID: int = 0


# =====================================================================
# 4. 调度预算与冷却约束默认值 (Scheduling & Budget Defaults, ADR-019)
# =====================================================================

# 单集最终互动总数预算上限（未配置时为 None，由 Benchmark 调参确定）
DEFAULT_INTERACTION_BUDGET: int | None = None

# 任意两个互动之间的最小展示间隔（毫秒，未配置时为 None）
DEFAULT_MIN_INTERACTION_SPACING_MS: int | None = None

# 同类型互动的冷却时间映射字典（毫秒）
DEFAULT_TYPE_COOLDOWN_MS: dict[str, int] = {}


# =====================================================================
# 5. 大语言模型 (LLM) 调用参数 (LLM Parameters)
# =====================================================================

# 默认采样温度（0.0 保证输出确定性）
DEFAULT_LLM_TEMPERATURE: float = 0.0

# 默认请求超时时间（秒）
DEFAULT_LLM_TIMEOUT_SECONDS: float = 60.0

# 默认最大失败重试次数
DEFAULT_LLM_MAX_RETRIES: int = 3

# 默认失败重试等待延迟（秒）
DEFAULT_LLM_RETRY_DELAY_SECONDS: float = 1.0


# =====================================================================
# 6. 默认路径约定 (Paths)
# =====================================================================

# 数据根目录
DEFAULT_DATA_ROOT: str = "data"

# V1 片段输入目录
DEFAULT_V1_SEGMENTS_DIR: str = "data/text"

# V2 证据落盘目录
DEFAULT_EVIDENCE_DIR: str = "data/evidence"

# V2 最终产物输出目录
DEFAULT_INTERACTION_V2_DIR: str = "data/interaction_v2"

# 运行时状态与运行记录保存目录
DEFAULT_RUNS_DIR: str = "data/interaction_v2/runs"

# 检查点 SQLite 数据库文件路径
DEFAULT_CHECKPOINT_DB_PATH: str = "data/interaction_v2/runs/checkpoints.db"
