# 根配置文件内容计划

本计划覆盖 pyproject.toml、.env.example 和 langgraph.json。产品和架构依据分别见 [PRD](../drama-interaction-v2-PRD.md) 与 [ADR](../drama-interaction-v2-ADR.md)。

## 职责与边界

- pyproject.toml 负责 V2 包元数据、依赖、命令入口和开发工具配置。
- .env.example 负责可复制的模型与 PostgreSQL checkpoint 连接变量模板，不包含真实密钥。
- langgraph.json 负责开发调试工具找到已编译的工作流图。
- 三个文件不承载互动 JSON 契约或运行状态；可调的 Specialist/调度器提示词模板集中放在 `src/drama_interaction/config.py`。

## 输入、输出与接口

- pyproject.toml 以 src layout 暴露 drama_interaction 包，并把 python -m drama_interaction 指向 CLI 入口。
- .env.example 至少列出 LLM_MODEL_ID、LLM_API_KEY、LLM_BASE_URL、CHECKPOINT_DATABASE_URL，并说明 .env 只在本地使用；LangSmith 标准变量仅用于可选追踪。
- langgraph.json 指向 graph/builder 导出的图入口，使用项目虚拟环境和同一份配置加载规则。

## 依赖与消费者

- config、cli、graph/builder 和 llm 使用这里约定的包、环境变量或图入口。
- README 的安装与运行说明必须与这些文件保持一致。

## 目标实现要求

- V2 依赖由 pyproject.toml 与 uv.lock 管理，与 V1 的依赖文件隔离。
- 运行依赖覆盖 Pydantic、LangGraph、官方 PostgreSQL checkpointer、LangChain ChatOpenAI 和环境变量加载；测试与静态检查工具在开发依赖中声明。
- pytest 按 unit_tests 与 integration_tests 分层；需要真实模型端点的测试默认不作为离线单测运行。
- langgraph.json 只服务开发调试，正式运行仍由 CLI 发起。

## 失败与边界情形

- 缺少模型或 PostgreSQL checkpoint 连接变量时，配置装载必须在启动阶段给出明确错误。
- .env.example 不得出现真实密钥、私有路径或运行产物。
- 图入口无法加载时，应由开发工具直接失败，不以另一份图配置兜底。
- 版本和工具字段由项目根配置统一维护；运行状态见 [PROGRESS](../PROGRESS.md)。

## 验证

- 干净环境可按 pyproject.toml 安装，并可执行 python -m drama_interaction --help。
- .env.example 的变量名与 config 读取的变量完全一致。
- 图完成后，langgraph 开发工具能载入 builder 导出的图。
