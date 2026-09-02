# src/drama_interaction/config.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-019、PRD §16、README_v2.md「配置」「使用」两节

## 职责与边界

- 全项目唯一的配置入口：运行参数、大语言模型(LLM)连接、路径约定、检查点(checkpoint)开关，全部集中于此。
- 明确不做：不含业务逻辑；不定义 提示词(Prompt)；不定义数据 模式(schema)；不感知 LangGraph 具体实现。
- 配置对象装载后只读（不可变），各模块只读引用，不允许运行中改配置。

## 依赖关系

- 依赖 `.env` 文件与 命令行(CLI)显式参数（优先级：显式参数 > 环境变量/.env > 内置默认值）。
- 被几乎全部模块依赖：
  - llm.py：连接三要素
  - adapter：window_size_ms、落盘路径
  - graph/builder：检查点(checkpoint)位置
  - cli：路径与输出
  - scheduling 两个模块：预算(budget) / 间隔(spacing) / 冷却(cooldown)数值来源

## 主要组成

- 运行参数组：
  - `window_size_ms`：默认 3000，已确定（ADR-019）。
  - `interaction_budget` / `min_interaction_spacing_ms` / `type_cooldown_ms`：无内置默认值，处于「未配置」状态时必须显式可查询，不得静默填充 Magic number；数值待 基准评测(benchmark)后定。
- 渲染参数组（ADR-023，渲染断点定稿；调度取值的唯一来源）：
  - 五类 `type_base` 时长（毫秒，基准评测(benchmark)调参后冻结）：
    - `emotion_button` 2500–3000
    - `repeat_keyline` 2500
    - `instant_vote` 3500–4000
    - `deferred_vote` 3500–4000
    - `side_comment` 2500–3000
  - 区间只是调参搜索空间，**运行期必须为每类单一标量**；开发期未冻结时默认取区间下限（2500 / 3500 / 2500），保证渲染确定性不变量——同一输入不得因区间产生不同 时长(duration)。
  - `keyline_tail_ms`：700（沿用 V1，已定）
  - `reveal_display_ms`：待 基准评测(benchmark)定
  - `reveal_gap_min_ms`：待 基准评测(benchmark)定
  - 三点说明（ADR-023）：
    1. `repeat_keyline` 的专属上下限 `KEYLINE_DURATION_FLOOR=2500` / `KEYLINE_DURATION_CEIL=4500` 为**代码常量**，不入 config。
       - 跟读台词的生理时间范围不是调参对象，与 `keyline_tail_ms=700` 同待遇。
    2. 全局 `DURATION_FLOOR` / `DURATION_CEIL` 已删除，其余四类直接取 type_base、无 截断(clamp)，配置合理性由 基准评测(benchmark)观测。
    3. 装载期派生校验（属 config 装载逻辑而非独立参数）：`min_interaction_spacing_ms >= max(全部 type_base, KEYLINE_DURATION_CEIL)`，违者 快速失败(fail fast)。
       - 右边从 config 数据现算，不引入新常量，调参改时长后校验下界自动跟随。
- 大语言模型(LLM)连接组：`LLM_MODEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL`，从 `.env` 装载，供 llm.py 使用。
- 路径组：
  - V1 片段(segments)输入根：`data/text/`
  - 证据(Evidence)落盘根：`data/evidence/`
  - V2 产物根：`data/interaction_v2/`
  - 执行状态子目录：`data/interaction_v2/runs/`
  - 检查点(checkpoint)文件位置
- 检查点(checkpoint)介质开关：开发期本地文件（SQLite），预留可替换的配置项（介质本身属 Deferred，PRD §22 第 8 项）。
- 集中装载机制：一个统一的装载入口完成合并与校验；必填项缺失时立即报错并列出全部缺失项（快速失败(fail fast)），不逐个模块各自报错。

## 关键设计点

- 数值参数不写死在 提示词(Prompt)中（ADR-019 / PRD §16）：生成专家(Specialist)与 调度器(Scheduler)的 提示词(Prompt)只引用配置注入的值，调参不改 提示词(Prompt)。
- 预算(budget) / 间隔(spacing) / 冷却(cooldown)允许显式「未配置」，是为 基准评测(benchmark)阶段通过配置文件注入实验值服务的（PRD §16：基准评测(benchmark)后调参）。
- 路径集中定义，避免各模块自行拼接相对路径导致产物散落。
- 装载时即完成类型与取值校验（如 window_size_ms 必须为正整数），坏配置在启动时失败而不是运行中途失败。

## 待定项

- 配置装载实现选型：pydantic-settings 还是普通 dataclass + dotenv 手工合并（倾向 pydantic-settings，与 模式(schemas)层技术栈一致；见 project-config.md）。
- 检查点(checkpoint)介质的选项枚举与命名（介质本身待定）。
- 是否需要 `--config` 显式配置文件注入（基准评测(benchmark)覆盖参数用），第一版是否实现待 roadmap 确认。

## 测试要点

- 必填项缺失时报错且错误信息包含全部缺失项清单。
- 优先级合并顺序（显式参数 > .env > 默认值）可离线验证。
- 「未配置」状态的 预算(budget) / 间隔(spacing) / 冷却(cooldown)不会静默变成数值 0 或其他 Magic number。
- 全部默认值只有 window_size_ms=3000 一个数值默认。
- 渲染参数组装载期派生校验：间隔(spacing)小于现算下界（`max(全部 type_base, KEYLINE_DURATION_CEIL)`）时 快速失败(fail fast)并报出具体冲突值（触发例）；间隔(spacing)满足下界时正常放行、不误报（放行例）。
