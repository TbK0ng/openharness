# OpenHarness

教程《用 LangChain 从零构建 Agent》的完整复刻：一个可运行的编码 Agent 框架，
Agent Loop、三级权限护栏、MCP、技能、记忆、钩子、多 Agent 协作全部落地。

## 快速开始

```bash
uv sync                      # 安装依赖（httpx / langchain-core / langchain-openai / prompt-toolkit）
uv run pytest tests          # 290 个测试（285 passed + 5 需 LM Studio 的用例跳过）
uv run python -m openharness.cli "列出当前目录的文件" --no-banner
```

默认使用 DeepSeek（需 `DEEPSEEK_API_KEY`）；也可切到本机 LM Studio（`--provider lmstudio`）。

## 模型供应商

两套预设，都走 OpenAI 兼容协议，用 `provider` 切换：

| provider | base_url | 默认模型 | 密钥来源 |
|---|---|---|---|
| `deepseek`（默认） | `https://api.deepseek.com` | `deepseek-flash` | `DEEPSEEK_API_KEY` 环境变量，或 `.oh/settings.json` 的 `api_key` |
| `lmstudio` | `http://127.0.0.1:1234/v1` | 自动发现已加载模型 | 无需（本地端点不校验） |

```bash
# 默认即 DeepSeek，只需提供密钥
export DEEPSEEK_API_KEY=sk-...            # Windows: setx DEEPSEEK_API_KEY sk-...
uv run python -m openharness.cli "列出当前目录"

# 切回本地 LM Studio
uv run python -m openharness.cli "列出当前目录" --provider lmstudio

# 换模型
uv run python -m openharness.cli "列出当前目录" --model deepseek-v4-pro
```

优先级：显式配置（`--provider` / `--model` / settings.json）> provider 预设 > 内置默认值。
空字符串视为「未设置」，因此 `"model": ""` 不会覆盖预设。

## CLI

```
openharness [prompt...] [--cwd DIR] [--config PATH] [--provider lmstudio|deepseek]
            [--model NAME] [--mode default|plan|full-auto] [--max-turns N] [--no-banner]
```

- 交互命令：`/help` `/tools` `/memory` `/mode` `/tasks` `/agents` `/mcp` `/skills` `/cron` `/init` `/clear` `/exit`，以及会话/权限命令 `/new` `/fork` `/side` `/sessions` `/switch` `/rewind` `/permission`（见 `src/openharness/engine/query_engine.py::_register_builtin_commands`）。`/help <命令>` 看单条用法。
- 交互体验（`src/openharness/ui/repl.py`）：输入 `/` 立即弹出命令菜单并显示说明，继续输入按前缀过滤；`Tab` 补全命令与参数（如 `/mode fu<Tab>` → `/mode full-auto`）；`↑`/`↓` 翻历史（存于 `.oh/history`，跨会话保留）；`Ctrl+C` 取消当前输入，`Ctrl+D` 退出；**双击 `Esc` 回退最后一轮**并把原输入放回编辑框（`/rewind` 等价；只回退消息历史，不撤销已产生的文件改动）；底部状态栏显示权限模式 / 模型 / 工具数 / 工作目录 / 当前会话。
- 多轮会话：同一个会话内保留完整消息历史（含最终 assistant 回复），`/new` 开新会话、`/fork` 复制当前历史到分支、`/side` 基于快照开临时会话（`/side off` 丢弃并返回）。main/fork 每轮结束自动保存到 `.oh/sessions/<id>.json`，重启后 `/sessions` 仍可见，`/switch <id|前缀|名称>` 载入继续；side 不落盘。
- 长期记忆：Agent 通过 `MemorySave` / `MemorySearch` / `MemoryDelete` 工具维护 `.oh/memory/*.md` 与 `.oh/MEMORY.md`，索引每轮注入 system prompt；`/memory` 查看当前索引。
- 定时任务：`/cron add <分 时 日 月 周> <command|agent> <内容>` 创建，`/cron list` 查看，`/cron run <id>` 立即触发，`/cron delete <id>` 删除。调度线程随 CLI 启动，输出写入 `.oh/data/cron.log`；**只在 CLI 进程运行期间触发**（`CronCreate` 工具创建任务时也会启动调度器）。
- `/mode` 不带参数：终端下弹出编号选择菜单；非交互环境列出全部模式。`/mode plan`、`/mode full-auto` 直接切换。
- 权限：`/permission allow <工具>` 或审批时输入 `a`，该工具在本会话内不再询问；`/permission save` 把模式与 allow/deny 列表写入 `.oh/settings.json`，下次启动继续生效。plan 模式仍会阻止所有写操作（白名单不能绕过）。
- 管道、CI 或 `OPENHARNESS_PLAIN_INPUT=1` 时自动退回 `input()`（此时双击 Esc 不可用，用 `/rewind`）。
- 权限询问走真实 stdin（`ask_user`），非交互环境默认拒绝。
- 一次性 prompt 的收尾：**真实终端**跑完继续交互（可接着聊）；**管道/CI** 跑完即退出，脚本不会挂住。
- 非交互环境没有审批入口，写操作会被拒绝并打印「非交互环境无法审批」+ 补救办法；
  自动化请改用 `--mode full-auto` 或 `/permission allow <工具>`。

## 配置目录：`.oh/`

所有运行时状态集中在项目根目录的 `.oh/`，不再散落在项目根：

```
.oh/
├── settings.json      # 配置（等价于旧的 ./settings.json）
├── history            # 交互输入历史（↑/↓ 翻阅，跨会话保留）
├── memory/            # 记忆条目（Markdown + frontmatter）
├── MEMORY.md          # 记忆索引
├── sessions/          # 已保存会话（每轮自动落盘，/sessions /switch 读取）
├── .tasks/            # 任务看板（带 blockedBy 依赖 DAG，CreateTask 等工具）
├── data/cron.json     # 定时任务
├── data/cron.log      # 定时任务触发/命令输出
├── worktrees/         # EnterWorktree 创建的隔离工作区
├── tasks/             # 后台任务历史（TaskCreate 起的命令/子 Agent，跨会话可查）
├── plugins/           # 插件（*.py）
├── skills/            # 插件注册的技能
└── mcp.json           # MCP 服务器（Claude Code 的 {"mcpServers": {...}} 格式）
```

- 交互模式里执行 `/init` 生成默认的 `.oh/settings.json`；也可以手写 JSON。
- MCP 服务器写在 `.oh/mcp.json`，格式为 `{"mcpServers": {...}}`；settings.json 的 `mcp_servers` 仍可用，同名项以 settings 为准。
- 每个 server 可以加 `"timeout": 120` 放宽握手超时（默认 30 秒；大体积本机 server 冷启动常常不够）。
- `command` 写相对路径时按**项目根**解析，例如 `tools/codebase-memory-mcp/codebase-memory-mcp.exe`（`tools/` 为本机副本，不入库）。
- 配置里的相对路径（`skills_dirs` / `memory_dir` / `plugins_dir`）一律以 `.oh/` 为根；绝对路径原样使用。
- 目录名可用环境变量 `OH_DIR` 覆盖（例如测试隔离）。
- 兼容性：`./settings.json` 仍会被读取（`.oh/settings.json` 优先），便于从旧版本迁移。

## 仓库布局

```
.
├── src/openharness/      # 框架源码（src 布局，`pythonpath = ["src"]`）
├── tests/                # 单元/集成测试，按 src 子系统镜像分目录
├── docs/                 # 验证记录等文档
├── pyproject.toml        # 打包与依赖
├── uv.lock               # 锁定依赖
├── README.md
└── .gitignore
```

```bash
uv run python -m openharness "列出当前目录的文件"   # 等价于 openharness / -m openharness.cli
```

`.oh/` 是运行时状态目录，按需创建，不入库。

## 结构

```
src/openharness/
├── __main__.py          # python -m openharness
├── cli.py               # argparse 入口、单次请求 / 交互循环
├── api/                 # registry.py 供应商预设 + client.py LangChain 装配与流式调用
├── config/              # paths.py（.oh/ 约定）+ settings.py（默认配置 / 合并 / 持久化）
├── engine/              # query.py Agent Loop + query_engine.py Engine 装配 + recovery.py
├── prompts/             # system prompt 组装（记忆索引 + 技能清单 + 准则）
├── services/            # session_storage.py 会话落盘、compact.py autoCompact、cron.py 调度
├── ui/                  # repl.py prompt_toolkit 输入、output.py 终端输出/编码降级
├── tools/               # base.py（BaseTool/ToolRegistry）+ 每个工具一个 *_tool.py
├── permissions/ hooks/ commands/ mcp/
├── memory/ skills/ plugins/
├── tasks/               # manager.py 后台任务、board.py 任务看板 DAG、types.py
└── swarm/               # team.py 子 Agent、autonomous.py 自主 Teammate
```

| 模块 | 职责 |
|---|---|
| `api/registry.py` | 供应商预设（DeepSeek / LM Studio）、配置解析、模型发现 |
| `api/client.py` | LangChain ChatOpenAI 装配、消息转换、`stream_response` / `llm_complete` |
| `engine/query.py` | Agent Loop：LLM → 工具调用 → 观察 → 再推理，回合上限控制 |
| `engine/query_engine.py` | Engine 装配：子系统初始化、工具/命令注册、会话切换、`/` 命令实现 |
| `engine/recovery.py` | 错误恢复（s11）：重试 / 指数退避 / Path 1 输出截断升级 / Path 3 备用模型切换 |
| `services/session_storage.py` | 会话模型与落盘：多轮历史、`/new` `/fork` `/side`、回退与跨进程切换 |
| `services/compact.py` | autoCompact（s08）：LLM 摘要 / 熔断器 / 紧急压缩 |
| `services/cron.py` | 定时任务持久化与调度线程（command / agent） |
| `prompts/system_prompt.py` | 每轮 system prompt：身份/环境 → 记忆索引 → 技能清单 → 准则 |
| `ui/repl.py` `ui/output.py` | 行编辑（补全 / 历史 / Esc Esc）、状态栏、编码安全的终端输出 |
| `tools/` | 39 个内置工具，按类名一文件：`bash_tool.py`、`file_read_tool.py`、`todo_write_tool.py`… |
| `permissions/` | 三级护栏：default / plan / full-auto，deny 列表按工具·路径·命令 |
| `mcp/` | MCP server 客户端（stdio），外部工具接入 |
| `skills/` `memory/` `hooks/` | 技能加载、长期记忆、事件钩子 |
| `swarm/` `tasks/` | 子 Agent 派发、自主 Agent（s17）、后台任务（s13）、任务看板（s12） |
| `plugins/` `commands/` | 插件注册、内置斜杠命令 |

`tests/` 与源码一一对应：`tests/test_api/`、`test_engine/`、`test_services/`、`test_tools/`、
`test_swarm/`、`test_tasks/`、`test_cli/`、`test_ui/` 等；跨子系统的用户视角用例在 `tests/e2e/`。

## 用户视角 e2e（`tests/e2e/`）

以真实子进程 / 真实终端（ConPTY）驱动 CLI，覆盖 19 个斜杠命令、39 个工具、8 个子系统：

```bash
uv run pytest tests/e2e                 # 确定性部分（命令、插件、技能、cron、持久化、参数）
OH_E2E_LIVE=1 uv run pytest tests/e2e   # 加上真实 DeepSeek 驱动工具的用例
```

- 每个用例在自己的临时工作目录里跑，状态落在 `<tmp>/.oh/`，不碰仓库根的 `.oh/`。
- TTY 行为（Tab 补全、↑ 历史、双击 Esc、Ctrl+C/D、审批弹窗）用 pywinpty 开真实 ConPTY。
- 限制：ConPTY 的字节流里没有 prompt_toolkit 的浮动区域（`/` 菜单、底部状态栏），
  这两块用数据源断言（`match_commands` / `_status_text`）加人工观感验证，见
  `tests/e2e/test_repl_tty.py` 顶部说明。

## 验证记录

- `uv run pytest tests`：390 passed, 23 skipped（18 个 e2e live 用例默认跳过，5 个需要本机 LM Studio 可达）
- `uv run pytest tests/e2e`：54 passed, 18 skipped（live 用例默认跳过）
- `OH_E2E_LIVE=1 uv run pytest tests/e2e`：72 passed —— 19 个斜杠命令、39 个工具、
  8 个子系统全部经真实 DeepSeek / 真实终端触发，另有假端点下的错误恢复路径，详见 `docs/VERIFICATION.md`
- 持久化/调度冒烟：跨进程 `/sessions` 载入会话、`MemorySave` 后新进程 `/memory` 可见、`*/1` cron 命令真实触发并写 `cron.log`。
- 真实 LLM 冒烟：`uv run python -m openharness.cli "用 bash 工具列出当前目录的文件" --no-banner --max-turns 4`
  —— 模型自主调用 Glob/Read，权限询问正常弹出，回合上限生效。
- Agent Loop 离线冒烟：用假 LLM 注入 ToolCall，验证「调用工具 → 结果回填 → 下一回合 → 返回文本」全链路。
- 测试结束自动清理 `_tmp_tests/`、`tmp*/`、`oh_test_*/`、`oh_hooks_*/`（见 `tests/conftest.py`）。
