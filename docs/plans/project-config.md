# 根配置文件（pyproject.toml / .env.example / langgraph.json）内容规划

- 状态：已部分实现
- 上游依据：README.md 结构树、ADR-022

## 总原则

- 三个文件共同承载「工程壳」：依赖与工具链（pyproject）、环境变量模板（.env.example）、LangGraph 工具入口（langgraph.json）。
- V2 依赖独立于 V1 的 requirements.txt（V1 保留在仓库用于对照，两者依赖互不污染）；V2 用 pyproject + uv 管理。
- 本文档只描述各文件将包含的内容，不含文件本体。

## pyproject.toml

- 项目元信息：包名 drama_interaction、Python 3.10+ 下限、src layout 包发现配置（包体在 src/drama_interaction）。
- 运行时依赖（逐项用途）：
  - langgraph：工作流框架（状态图(StateGraph) / 检查点(checkpoint) / 中断(interrupt)，ADR-022）；
  - pydantic：三层 模式(schema)与 config 的契约实现；
  - OpenAI 开发工具包(SDK)：llm.py 唯一网络出口的底层（具体包名待定项）；
  - 配置装载库：python-dotenv。
- 版本策略：运行时依赖宽约束，uv 锁文件锁精确版本。
- 开发依赖：pytest（分层运行）、ruff（lint + format）、uv 相关声明。
- 工具配置：pytest 的 unit_tests / integration_tests 分层路径与标记（integration 需要真实 大语言模型(LLM)端点，默认跳过）；ruff 基础规则与 src 布局感知。
- console entry：`python -m drama_interaction` 指向 cli.py。

## .env.example

- 三个变量的注释化模板：`LLM_MODEL_ID`（模型 标识(ID)，注释说明需兼容 OpenAI 接口(API)的文本模型）、`LLM_API_KEY`、`LLM_BASE_URL`（第三方端点须以 /v1 结尾之类约定，与 V1 README 的说明对齐）。
- 提交安全说明注释：.env 不入库，本文件只作模板。

## langgraph.json

- 声明图入口：指向 drama_interaction 包内 graph/builder.py 编译产出的图（供 langgraph dev / LangGraph Studio 可视化调试用，README.md 结构树定位）。
- 声明依赖环境（项目环境/venv）与配置加载方式；具体 模式(schema)随 LangGraph 1.x 版本核对（待定项）。
- 该文件只服务开发调试，不参与生产 运行(run)（生产走 命令行(cli)）。

## 待定项

- OpenAI 开发工具包(SDK)的具体包（openai 官方包为默认倾向）。
- 配置装载库选型（pydantic-settings vs 手工 dotenv）。
- langgraph.json 的字段格式以实现时 LangGraph 1.x 文档为准。
- pytest integration 层是否第一版就建立（可先只建 unit，integration 随 生成专家(Specialist)实现引入）。

## 验证方式

- pyproject 写好后：uv 安装成功、`python -m drama_interaction --help` 可运行、ruff/pytest 可执行。
- .env.example：配合 README「安装」节的人工步骤核对三变量名一致。
- langgraph.json：`langgraph dev` 能加载图并可视化（需 builder 完成后验证）。
