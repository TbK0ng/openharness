# OpenHarness

教程《用 LangChain 从零构建 Agent》的完整复刻：一个可运行的编码 Agent 框架，
Agent Loop、三级权限护栏、MCP、技能、记忆、钩子、多 Agent 协作全部落地。

## 快速开始

```bash
uv sync                      # 安装依赖（httpx / langchain-core / langchain-openai）
uv run pytest tests          # 133 个测试
uv run python -m openharness.cli "列出当前目录的文件" --no-banner
```

要求本机 LM Studio 在 `http://127.0.0.1:1234/v1` 提供服务（或其他 OpenAI 兼容端点）。

## CLI

```
openharness [prompt...] [--cwd DIR] [--config settings.json]
            [--mode default|plan|full-auto] [--max-turns N] [--no-banner]
```

- 交互命令：`/help` `/tools` `/memory` `/mode` `/tasks` `/agents` `/mcp` `/skills` `/cron` `/clear` `/exit`（见 `engine/query_engine.py::_register_builtin_commands`）。
- 权限询问走真实 stdin（`ask_user`），非交互环境默认拒绝。

## 配置

复制 `settings.example.json` 为 `settings.json`，键与 `engine/query_engine.py::default_config()` 一一对应：
provider / base_url / model / max_turns / permissions / hooks / mcp_servers / skills_dirs / memory_dir。

## 结构

| 模块 | 职责 |
|---|---|
| `engine/llm.py` | LM Studio 模型发现、LangChain ChatOpenAI 装配、消息转换 |
| `engine/query.py` | Agent Loop：LLM → 工具调用 → 观察 → 再推理，回合上限控制 |
| `engine/compact.py` | autoCompact（s08）：LLM 摘要 / 熔断器 / 紧急压缩 |
| `engine/recovery.py` | 错误恢复（s11）：重试 / 指数退避 / prompt_too_long 升级 |
| `tools/` | bash / 文件读写编辑 / glob / grep / web / notebook / 元工具（plan、ask_user、tool_search、worktree、todo、compact）/ 任务看板 / 多 Agent |
| `permissions/` | 三级护栏：default / plan / full-auto，deny 列表按工具·路径·命令 |
| `mcp/` | MCP server 客户端（stdio），外部工具接入 |
| `skills/` `memory/` `hooks/` | 技能加载、长期记忆、事件钩子 |
| `agents/` `tasks/` `cron/` | 子 Agent 派发、自主 Agent（s17）、任务看板（s12）、定时任务 |
| `plugins/` `commands/` | 插件注册、内置斜杠命令 |

## 验证记录

- `uv run pytest tests`：133 passed
- 真实 LLM 冒烟：`uv run python -m openharness.cli "用 bash 工具列出当前目录的文件" --no-banner --max-turns 4`
  —— 模型自主调用 Glob/Read，权限询问正常弹出，回合上限生效。
