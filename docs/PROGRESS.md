# 进度记录（PROGRESS）

记录已交付事项及其未完全做到的部分。规划蓝图见 `docs/plans/`（索引 [docs/plans/README.md](docs/plans/README.md)），目标形态见 [README.md](README.md)；本文件只记状态，不替代规划与 ADR。

最后更新：2026-09-02

## 已完成

- 2026-09-02 **docs/plans 全量修复（按审查报告逐项落地，拍板 1–7）**：依据交叉审查报告（P0×3 / P1×6 / P2×9 / D×4 + 七条拍板，报告已随清理删除，结论沉淀于本条与 ADR-023 v0.6 变更记录），由 4 个并行子代理修复 19 份文档，本人汇总验收通过（关键词覆盖 11/11、全部文件 0 乱码、旧术语无残留、跨文档口径一致）：
  - **[docs/drama-interaction-v2-ADR.md](drama-interaction-v2-ADR.md) 原地升 v0.6**（不新建 ADR-024，用户偏好）：ADR-023 两处决策修订——渲染位置提前到 Candidate Pool 之后（终检改验真实毫秒）、删除全局 DURATION_FLOOR/CEIL 改 keyline 专属上下限代码常量（2500/4500，其余四类直接 type_base 无 clamp）；补时间检查调用时机（Pool 后、冲突组前，先淘汰再竞争）与 spacing 派生校验（`min_interaction_spacing_ms >= max(全部 type_base, KEYLINE_DURATION_CEIL)`，装载期 fail fast）；Current Architecture Snapshot 同步；
  - **[README.md](../README.md)**：架构图渲染环节挪位、结构树注释（constraints.py 补 resolve_anchor、nodes.py 补 render_node）、配置表补渲染参数组；
  - **resolve_anchor 归属 `scheduling/constraints.py`**（不新建模块，constraints.md 扩展为唯一定义处，render_node import）；
  - **拍板 3（零毫秒）**：schemas 两份 + rules.md（分组 A 改「生成侧零毫秒」禁令，可程序修复=置空）+ repair.md（白名单补置空）+ emotion-button.md；
  - **拍板 4（时间校验前移）**：rules.md 分组 B 新增规则 + constraints.md 处理顺序（时间合理性最前）+ nodes.md 丢弃表述更正；
  - **拍板 5（inspect_window 不预告）**：base.md / service.md 防呆注记 + service.md 调用上限升级；
  - **拍板 6（渲染提前）**：nodes.md / builder.md 边结构 `pool_node → render_node → constraints_node →（空则跳过）semantic_node → final_check_node → END`、节点改名、semantic.md 输入带真实毫秒、state.md 拆三层（rendered_candidates / selected_candidates / final_interactions）；
  - **拍板 7（无全局护栏）**：config.md 渲染参数组（7 项）、interaction.md 时长表述、constraints.md 派生校验；
  - **其余一致性**：P1-1/P1-3（type 1–5 写定，出处 `v1/pipline/common/schemas.py:248-252`）、P2-3（终检三项）、P2-5（末窗口径收敛为已定）、P2-6（空证据下游短路）、P2-9（cli 定稿项移位）、plans/README.md（拍板记录 + 待定项更新）；
  - 全文 V1 引用路径更正为 `v1/pipline/...`（配合当日 v1/ 收拢）。
- 2026-09-02 **独立复审（fresh eyes）后 P1/P2 修复落位**：由不带本会话上下文的子代理复审 plans 逻辑，产出 0 P0 / 4 P1 / 6 P2，全部逐项修复并验收通过（乱码 0 + 17 项落点命中）：
  - P1-1/P1-2 → `graph/state.md` 新增 `constraints_report` 字段（淘汰/合并/标记候选 + 确定性原因）、`selected_candidates` 注释澄清为「constraints 先写确定性存活集，semantic 触发时覆盖」；`graph/nodes.md` constraints_node/semantic_node 写入方明确。
  - P1-3 → `ADR`/`config.md`/`interaction.md` 三处补「type_base 运行期单一标量，开发期未冻结默认取区间下限 2500/3500/2500」（保渲染确定性）。
  - P1-4 → `ADR` + `nodes.md` 补「render 打乱 options 时同步将 answer_id 重映射为打乱后新索引」。
  - P2 → PRD §18.1 补 render/constraint 两行；schema.md 示例 duration_ms 5000→2800、reveal 生成侧 null 注；constraints.md「读锚区间长度」措辞；README.md 补 KEYLINE_DURATION_FLOOR/CEIL 常量行；rules.md 补职责切分口径。
- 2026-09-02 **全量文档表述瘦身（23 份）**：文档经多轮修订后堆积成单行 500+ 字、括号套括号、加粗泛滥、"拍板 N"过程痕迹混入正文。先按四项指标（超长行 / 括号嵌套 / 加粗 / 拍板痕迹）量化定位重灾区，再由 4 个子代理按文件零重叠并行改写，共用统一瘦身规则：
  - 规则：删过程痕迹；一行一义（>100 字拆主句 + 缩进子列表）；括号不过二；加粗只给硬约束；去重；**只改表述形式、不改技术内容**；章节骨架不变。
  - 防删内容：改写前快照到 `/tmp/docbak`，验收用 token 集合对比（大写常量 / 模块路径 / 下划线标识符 / 数字 / 行内代码）+ 反引号奇偶检查。
  - **效果**：最长单行 569→150（-74%）、超长行 63→0、括号嵌套 61→12（-80%）、加粗 76→36（-53%）、拍板痕迹 30→0、乱码 0、反引号配对全 OK、技术 token 零实质丢失。总字数 +1%（拆列表的正常开销）。
  - 修复的 4 处改写疏漏：`constraints.md` 补回 `deferred_vote` 限定（否则会对四类无 `reveal_time` 的候选执行校验而触发空值错误）；`config.md` 补回 LLM 连接组与路径组；`interaction.md` 补回 instant_vote 两选项约束与 reveal 非负整数；`ADR` 补回 `schema.md` 引用。
- 2026-09-02 **全量术语中文化（24 份，约 1588 处 `中文(english)` 标注）**：按用户要求把正文英文术语改为 `中文(english)`（半角括号、每次出现都标），README.md 优先。先建统一译名表驱动 7 个子代理按文件零重叠执行：
  - **格式与保护**：代码标识符（反引号内）/ 代码块 / 路径 / 表格代码值 / 框架库专名（LangGraph/OpenAI/pydantic/JSON）不标；引用编号 ADR-0xx / PRD §x 不拆标。
  - **验收**（对照标注前快照）：乱码 0、反引号 token 零丢失、无嵌套标注、核心术语无一词多译。
  - **修正的代理越界**：E 组曾删光 constraints/semantic 行内代码反引号（已从备份基线返工恢复）；"ADR-015"→"架构决策记录(ADR)-015"这类编号拆标共修复 219 处（全局正则还原）；英文括号后残留空格清理 662 行。
- 2026-09-02 **V2 文件结构骨架**：按 README.md「项目结构（目标形态）」建立：
  - [src/drama_interaction/](src/drama_interaction/)：24 个模块占位（仅 docstring），实现以 `docs/plans/src/drama_interaction/*.md` 为蓝本，模块清单同 README.md 目标结构；
  - [tests/](tests/)：`unit_tests/` / `integration_tests/` / `fixtures/` 三层；
  - [benchmark/golden/](benchmark/golden/)：`evidence/` 与 `cases/` 两个空目录；
  - [data/evidence/](data/evidence/) 与 [data/interaction_v2/](data/interaction_v2/)；
  - 空目录均以 `.gitkeep` 占位。
- 2026-09-02 **删除 uv 脚手架残留包** [src/drama_highlight_mark/](src/)（仅 Hello World 占位，无任何引用；V1 真实代码在 `pipline/`，不受影响）。
- 2026-09-02 **工程壳三件套按 [docs/plans/project-config.md](docs/plans/project-config.md) 重写**：
  - [pyproject.toml](pyproject.toml)：项目名 `drama-interaction`（对应包 `drama_interaction`）、`requires-python >= 3.10`（README.md 口径；本地 `.python-version` 仍为 3.12）、运行时依赖 langgraph / pydantic / openai / python-dotenv（宽约束）、开发依赖组 pytest / ruff、pytest 分层（默认只跑 `tests/unit_tests`，integration 显式触发）、ruff src 布局感知。
  - [.env.example](.env.example)：`LLM_MODEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL` 注释化模板，与 README.md「安装」节对齐；另加可选 LangSmith 监控四变量（`LANGSMITH_TRACING / ENDPOINT / API_KEY / PROJECT`，用户 2026-09-02 提供模板）。
  - [langgraph.json](langgraph.json)：图入口指向 `src/drama_interaction/graph/builder.py`。
- 2026-09-02 **创建 [.env](.env)**：结构同 [.env.example](.env.example)；三个 `LLM_*` 与 `LANGSMITH_*` 已由用户填入实际值（含真实 API Key，不入库）；`LANGSMITH_PROJECT=drama_interaction`。
- 2026-09-02 **V1 资产收拢至 [v1/](v1/)**：判定规则（用户 2026-09-02 拍板）——V2 不使用的全部移入 `v1/`，V2 使用的保持不动。移入的：
  - [v1/pipline/](v1/pipline/)：V1 八个流水线脚本与 `common/`、`steps_05/`（V1 链路仍需可运行：README.md 声明其用于 benchmark 对照，且 `03_audio2text` 产物是 V2 Legacy Adapter 的输入契约）；
  - [v1/test/](v1/test/)：两个手工联调脚本（audio / text）；
  - [v1/requirements.txt](v1/requirements.txt)：V1 独立依赖清单（与 V2 pyproject 互不污染）；
  - [v1/schema.md](v1/schema.md)：V1 最终互动 JSON 字段说明（V2 输出格式与其保持一致，[docs/schema.md](docs/schema.md) 为 V2 当前版本）；
  - [v1/interaction.md](v1/interaction.md)：V1 互动方式总览（P0–P3 表）。
  - [v1/README.md](v1/README.md)：V1 说明文档（其内 `python pipline/...` 示例现过时，见「未完全做到」）。
  - V2 使用的保持原位：[data/](data/) 各目录（V2 输入与产物根）、[docs/](docs/)（V2 设计文档为主，`docs/now_applied_interaction.md` 是 V2 五类互动需求来源）。
  - 兼容性修复：[v1/pipline/common/paths.py:4](v1/pipline/common/paths.py:4) 的 `PROJECT_ROOT` 从 `parents[2]` 改为 `parents[3]`（目录加深一层后仍指向仓库根，保证 `data/` 与 `.env` 定位不变）。
  - `docs/now_applied_interaction.md` 是 `interaction.md` 的更新版（表格列相同、条目更新），仍留在 docs/ 未动；`data/` 下各目录为 V1 产物 / V2 输入共用，保持原位。
  - git 记录为 rename（`pipline/... -> v1/pipline/...` 等），已暂存未提交。
  - 验证：`uv run python v1/pipline/01/03/04/05_*.py --help` 全部通过；`v1/pipline/common/config.get_settings()` 能读到根目录 [.env](.env)（`LLM_MODEL_ID=GLM-5.3-flash`）。

## 未完全做到

1. **langgraph.json 未实测**：`graph/builder.py` 目前是占位，没有可加载的编译图；文件格式按 LangGraph 1.x 文档书写（`dependencies` / `graphs` / `env` 三键），`graphs` 键名 `drama_interaction` 为暂定命名。
2. **pyproject 未声明 `[project.scripts]`**：README.md 只约定 `python -m drama_interaction`，console 命令名未定，未擅自命名。
3. **[.env.example](.env.example) 未包含 V1 专用的 `VIDEO_*` 三变量**（V2 三件套只按规划保留 `LLM_*` 与 `LANGSMITH_*`）。V1 代码（[v1/pipline/common/config.py:63](v1/pipline/common/config.py:63)）在运行 video 相关脚本（01/06/07）时会断言 `VIDEO_MODEL_ID / VIDEO_API_KEY / VIDEO_BASE_URL` 非空，根目录 [.env](.env) 当前没有这三项；本轮未运行 V1 的 video 脚本，未回补。[.env.example](.env.example) 是否加 V1 区块待定。
4. **[v1/README.md](v1/README.md)（V1 说明）未更新**：其「项目结构」与所有 `python pipline/...` 运行示例仍指向旧路径，收拢后实际路径为 `v1/pipline/...`；未顺手改写（属 V1 文档，等提交前统一确认）。
5. 以上新增 / 修改均未提交 git（已暂存部分为 rename，当前分支 v2）。

## 验证记录

- 2026-09-02 `uv lock`（53 包解析通过）与 `uv sync`（安装成功）；`python -c "import langgraph, pydantic, openai, pydantic_settings"` 通过。
- 2026-09-02 `uv run ruff check src/` 通过（stub docstring 超长行已改写为多行）；`uv run pytest -q` 正常运行（`no tests ran`，符合预期：默认排除 integration，且尚无用例）。
- 2026-09-02 选型改用 python-dotenv 后重新 `uv lock` / `uv sync`（pydantic-settings 已移除）；`import dotenv` 通过。
