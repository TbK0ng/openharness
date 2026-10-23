# 用户视角验收记录

以「用户真的敲命令 / 真的说话」的方式驱动 `openharness`，逐项验证 19 个斜杠命令、
39 个工具、8 个子系统是否能被触发且行为正确。发现的缺陷就地修复并补了回归测试。

## 复跑方式

```bash
uv run pytest tests                    # 单元/集成（原 331 条 + 新增回归）
uv run pytest tests/e2e                # 用户视角、确定性部分
OH_E2E_LIVE=1 uv run pytest tests/e2e  # 再加上真实 DeepSeek 驱动工具的用例
```

- e2e 用子进程启动真实 CLI（`python -m openharness.cli`），每个用例独立临时工作目录，
  状态落在 `<tmp>/.oh/`，不污染仓库根的 `.oh/`。
- TTY 行为用 pywinpty 开真实 ConPTY，按键（Tab / ↑ / Esc Esc / Ctrl+C / Ctrl+D）都是真发。
- live 用例需要 `DEEPSEEK_API_KEY`，模型侧抖动（只回文本不调工具）会让个别用例重试一次。

## 结果

| 套件 | 结果 |
|---|---|
| `uv run pytest tests` | 336 passed, 5 skipped |
| `uv run pytest tests/e2e` | 54 passed, 18 skipped（live 默认跳过） |
| `OH_E2E_LIVE=1 uv run pytest tests/e2e` | **72 passed** |

- 19 条斜杠命令：全部在真实 REPL 里逐条敲过，断言真实输出。
- 39 个工具：`test_tools_live.py::test_every_registered_tool_was_exercised` 断言
  「注册表里的 39 个工具」与「e2e 里真实触发过的工具」差集为空。
- 8 个子系统：权限、会话、记忆、cron（含调度线程自己到点触发）、MCP（本机真实 server）、
  技能 / 插件 / 钩子、多 Agent、任务看板 / 后台任务 / worktree / compact。
- 真实终端：Tab 补全、↑ 历史、Esc Esc 回退、Ctrl+C / Ctrl+D、审批 y / N / a 都真发按键。
- 错误恢复：本地假端点制造 5xx / 输出截断 / 上下文溢出，验重试、备用模型切换、
  max_tokens 升级、反应式压缩，以及「401 不重试」。

## 覆盖矩阵

| 面 | 用户怎么触发 | 用例 |
|---|---|---|
| CLI 参数 | `--cwd/--config/--mode/--model/--max-turns/--no-banner/--provider` | `test_cli_flags.py` |
| 一次性 prompt | `openharness "…"` | `test_cli_surface.py` |
| 交互 REPL | Tab 补全、↑ 历史、Esc Esc 回退、Ctrl+C/D、`/` 菜单数据、状态栏数据 | `test_repl_tty.py` |
| 19 条斜杠命令 | `/help` `/mode` `/new` `/fork` `/side` `/sessions` `/switch` `/rewind` `/permission` `/memory` `/skills` `/tasks` `/cron` `/tools` `/mcp` `/agents` `/init` `/clear` `/exit` | `test_commands.py` |
| 39 个工具 | 自然语言 → 模型自己选工具 | `test_tools_live.py`（含「39 个工具一个不漏」的断言） |
| 权限护栏 | 三级模式 + deny_paths / deny_commands + 审批 y/a/N | `tests/test_permissions/test_checker.py`、`test_repl_tty.py` |
| 会话/记忆持久化 | 关掉进程再打开 | `test_subsystems.py` |
| 技能/插件/钩子 | `.oh/skills/*.md`、`.oh/plugins/*.py`、`settings.json` 的 hooks | `test_subsystems.py` |
| MCP | `.oh/mcp.json` 里的 stdio server（用例内起仓库自带的 stub） | `test_subsystems.py`、`test_tools_live.py` |
| cron | `/cron add …` 后等调度线程自己到点 | `test_cron_scheduler.py`（真实等待） |
| 多 Agent | `Agent` + `SendMessage` | `test_agents.py` |
| 错误恢复 s11 | 端点 5xx / 输出截断 / 上下文溢出 | `test_recovery_e2e.py`（本地假端点） |

## 发现并修复的问题

| # | 现象 | 根因 | 修复 | 回归 |
|---|---|---|---|---|
| 1 | 同一进程里问第二句话就报 `ValidationError: tool_calls Input should be a valid list`，**多轮会话完全不可用** | `to_langchain_messages` 对没有工具调用的 assistant 消息显式传 `tool_calls=None`，langchain-core 1.x 的 pydantic 校验拒绝 | 没有工具调用时不带该字段 | `tests/test_api/test_client.py::test_assistant_message_without_tool_calls_maps_cleanly`、`test_cli_surface.py` 多轮用例 |
| 2 | `Agent` 工具调用后永久卡死（实测 >90s 无返回，只能 Ctrl+C） | 子 Agent 复用父会话的 `ChatOpenAI`/httpx 客户端，却在新线程的新事件循环里 `asyncio.run`；跨事件循环调用把主循环 join 死 | 子 Agent 自建客户端，并在自己的循环里关闭 | `test_agents.py::test_agent_spawns_and_returns_without_deadlock` |
| 3 | `SendMessage` 永远失败：模型拿不到子 Agent 的 id | `Agent` 工具只回子 Agent 的文本 | 输出追加 `[agent_id: …]`，并在工具描述里指明用法 | `test_agents.py::test_send_message_continues_existing_subagent` |
| 4 | 管道 / CI 里 `openharness "…"` 跑完后落进交互循环，脚本挂住 | `main()` 无条件 `return interactive(...)` | 只有真实终端才在一次性 prompt 后继续交互，管道下直接退出 | `test_cli_surface.py::test_one_shot_prompt_answers_then_exits` |
| 5 | 非交互环境写操作被静默拒绝，用户只看到「权限不足」；且审批文案打印两遍 | `ask_user` 默认空实现，且事件与回调各打印一次 | 非交互回调打印「为什么被拒 + 补救办法」；审批文案只由事件打印一次 | `tests/test_permissions/test_checker.py`（拒绝路径）、`test_repl_tty.py`（审批只出现一次） |
| 6 | `/exit` 直接消失，不打印 `再见`（而 `exit` 关键字会） | `SystemExit` 穿透 REPL 循环 | 捕获后统一道别退出 | `test_commands.py::test_clear_and_exit` |
| 7 | 状态栏显示 `deepseek` 而不是真正在用的 `deepseek-flash` | `_status_text` 直读 `config["model"]`，而模型名是 provider 预设解析出来的 | 用 `resolve_provider` 解析后再显示 | `test_repl_tty.py::test_status_bar_reports_mode_model_tools_and_session` |
| 8 | `deny_paths` 写了 `secret/*` 仍能写进 `secret/x`（模型换成绝对路径就绕过了） | 规则只按字面字符串 fnmatch，相对规则匹配不到绝对写法 | 先把候选路径解析并转成工作区相对形式，再对同一条规则多形式匹配 | `tests/test_permissions/test_checker.py::test_path_rule_matches_absolute_form_of_relative_rule`、`tests/test_permissions/test_checker.py::test_deny_path_blocks_one_target_only` |
| 9 | 切到备用模型时用户毫无提示 | `_switch_fallback` 用 `on_text`（正文流），而 CLI 只接了 `on_event` | 改走 `on_event` | `test_recovery_e2e.py::test_three_5xx_switches_to_fallback_model` |
| 10 | 「输出截断 → 放大上限重试」从未真正生效 | `llm.bind(max_tokens=…).bind_tools(…)` 会丢掉 max_tokens（RunnableBinding 重建时前面的 kwargs 不保留） | 先 `bind_tools`，再 `bind(model/max_tokens)` | `test_recovery_e2e.py::test_truncated_output_escalates_max_tokens` |
| 11 | 连续 5xx 永远不触发备用模型；重试次数按 N×M 放大 | SDK 的 `max_retries` 和 `src/openharness/engine/recovery.py` 共用同一个配置键，SDK 先静默重试把 5xx 吞掉了 | SDK 不再自己重试（`max_retries=0`），重试只由 recovery 负责 | `test_recovery_e2e.py::test_three_5xx_switches_to_fallback_model` |
| 12 | 本机大体积 MCP server 冷启动时直接 `FAILED — timed out on initialize`，用户无从调整 | 握手超时写死 30 秒 | 每个 server 支持 `"timeout": 秒`，默认仍是 30 | `test_subsystems.py::test_mcp_server_connects_and_exposes_tools`、`tests/test_mcp/test_client.py` |
| 13 | CLI 退出后 MCP server 子进程留在后台，下次启动撞单实例锁直接握手失败 | `main()` 没有收尾，Windows 下父进程退出不带走子进程 | 新增 `Engine.close()`（停 cron + `mcp.close_all()`），`main()` 用 `finally` 保证执行 | `tests/test_mcp/test_client.py::test_engine_close_terminates_mcp_children` |

## 观察项（未改）

- **ToolSearch 空转**：39 个工具全部 `lazy=False`，全部随每轮 prompt 下发；
  `ToolSearch` 搜不到任何「延迟工具」，`get_tool_schemas(include_lazy=…)` 也是恒等开关。
  这是教程第 5 章延迟加载机制在当前工具集上的遗留；要不要真的把一部分工具延迟化是
  产品决策（影响模型可见工具集与 token 消耗），未擅自动。
- `--provider lmstudio` 在本机无端点时的报错来自 OpenAI 客户端透传，可读性一般。
- 本机那个 287MB 的 `codebase-memory-mcp` 与宿主进程共用单实例，放进自动用例会互相打架，
  所以 e2e 用仓库自带的 stdio stub；真 server 已手工 `/mcp` 验过（列出 17 个工具、
  注册 17 个原生工具）。

## 已知限制

- ConPTY 的字节流里没有 prompt_toolkit 的浮动区域（`/` 菜单、底部状态栏）。
  这两块用数据源断言（`match_commands` / `_status_text`）+ 人工观感验证，
  见 `tests/e2e/test_repl_tty.py` 顶部说明。
- `autoCompact` 的自动触发需要长上下文，本轮只验证 `Compact` 工具本身可被调用
  以及 Path 2 的反应式压缩（`test_recovery_e2e.py`）。
