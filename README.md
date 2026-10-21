# OpenHarness

教程《用 LangChain 从零构建 Agent》的完整复刻：一个可运行的编码 Agent 框架，
Agent Loop、三级权限护栏、MCP、技能、记忆、钩子、多 Agent 协作全部落地。

## 快速开始

```bash
uv sync                      # 安装依赖（httpx / langchain-core / langchain-openai）
uv run pytest tests          # 273 个测试（268 passed + 5 需 LM Studio 的用例跳过）
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

- 交互命令：`/help` `/tools` `/memory` `/mode` `/tasks` `/agents` `/mcp` `/skills` `/cron` `/init` `/clear` `/exit`（见 `engine/query_engine.py::_register_builtin_commands`）。
- 权限询问走真实 stdin（`ask_user`），非交互环境默认拒绝。

## 配置目录：`.oh/`

所有运行时状态集中在项目根目录的 `.oh/`，不再散落在项目根：

```
.oh/
├── settings.json      # 配置（等价于旧的 ./settings.json）
├── memory/            # 记忆条目（Markdown + frontmatter）
├── MEMORY.md          # 记忆索引
├── .tasks/            # 任务看板（带 blockedBy 依赖 DAG，CreateTask 等工具）
├── data/cron.json     # 定时任务
├── worktrees/         # EnterWorktree 创建的隔离工作区
├── tasks/             # 后台任务历史（TaskCreate 起的命令/子 Agent，跨会话可查）
├── plugins/           # 插件（*.py）
├── skills/            # 插件注册的技能
└── mcp.json           # MCP 服务器（Claude Code 的 {"mcpServers": {...}} 格式）
```

- 复制 `settings.example.json` 为 `.oh/settings.json`，或在交互模式里执行 `/init` 自动生成。
- MCP 服务器写在 `.oh/mcp.json`（参考 `mcp.example.json`）；settings.json 的 `mcp_servers` 仍可用，同名项以 settings 为准。
- `command` 写相对路径时按**项目根**解析，例如 `tools/codebase-memory-mcp/codebase-memory-mcp.exe`。
- 配置里的相对路径（`skills_dirs` / `memory_dir` / `plugins_dir`）一律以 `.oh/` 为根；绝对路径原样使用。
- 目录名可用环境变量 `OH_DIR` 覆盖（例如测试隔离）。
- 兼容性：`./settings.json` 仍会被读取（`.oh/settings.json` 优先），便于从旧版本迁移。

## 结构

| 模块 | 职责 |
|---|---|
| `engine/llm.py` | 供应商预设（DeepSeek / LM Studio）、LangChain ChatOpenAI 装配、消息转换 |
| `engine/query.py` | Agent Loop：LLM → 工具调用 → 观察 → 再推理，回合上限控制 |
| `engine/compact.py` | autoCompact（s08）：LLM 摘要 / 熔断器 / 紧急压缩 |
| `engine/recovery.py` | 错误恢复（s11）：重试 / 指数退避 / Path 1 输出截断升级 / Path 3 备用模型切换 |
| `tools/` | bash / 文件读写编辑 / glob / grep / web / notebook / 元工具（plan、ask_user、tool_search、worktree、todo、compact）/ 任务看板 / 多 Agent |
| `permissions/` | 三级护栏：default / plan / full-auto，deny 列表按工具·路径·命令 |
| `mcp/` | MCP server 客户端（stdio），外部工具接入 |
| `skills/` `memory/` `hooks/` | 技能加载、长期记忆、事件钩子 |
| `agents/` `tasks/` `cron/` | 子 Agent 派发、自主 Agent（s17：身份重注入 / shutdown_request / consume_lead_inbox）、任务看板（s12）、定时任务 |
| `plugins/` `commands/` | 插件注册、内置斜杠命令 |

## 验证记录

- `uv run pytest tests`：268 passed, 5 skipped（跳过的 5 个用例需要本机 LM Studio 可达）
- 真实 LLM 冒烟：`uv run python -m openharness.cli "用 bash 工具列出当前目录的文件" --no-banner --max-turns 4`
  —— 模型自主调用 Glob/Read，权限询问正常弹出，回合上限生效。
- Agent Loop 离线冒烟：用假 LLM 注入 ToolCall，验证「调用工具 → 结果回填 → 下一回合 → 返回文本」全链路。
- 测试结束自动清理 `_tmp_tests/`、`tmp*/`、`oh_test_*/`、`oh_hooks_*/`（见 `conftest.py`）。
