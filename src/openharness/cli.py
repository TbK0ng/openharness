"""CLI 入口 — 教程第 12 章第 1 步。

用户在终端输入请求 → CLI 包装成用户消息 → 交给 Engine 的 Agent Loop。

用法：
    python -m openharness.cli                 # 交互式会话
    python -m openharness.cli "读一下 a.py"    # 单次请求；终端下跑完继续交互，管道下退出
    python -m openharness.cli --mode plan      # 指定权限模式启动
    python -m openharness.cli --cwd ./myproj   # 指定工作目录

会话内：
    直接输入        → 发给 Agent（多轮历史保留在同一会话）
    /help /mode ... → 斜杠命令
    /new /fork /side /sessions /switch → 会话管理
    /rewind 或双击 Esc → 回退上一轮
    /permission …   → 白名单 / 拒绝 / 持久化
    exit | /exit    → 退出
"""
from __future__ import annotations

import argparse
import difflib
import sys

from .engine.query import run_query_sync
from .engine.query_engine import Engine
from .ui.output import BANNER, emit, is_tty, print_assistant
from .ui.repl import LineReader, RewindRequest, wants_repl


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="openharness",
        description="OpenHarness — 教程第 12 章全流程的 LangChain 实现",
    )
    p.add_argument("prompt", nargs="*", help="首个用户请求（留空进入交互式）")
    p.add_argument("--cwd", default=None, help="工作目录（默认当前目录）")
    p.add_argument("--config", default=None, help="配置文件路径（默认 .oh/settings.json）")
    p.add_argument("--provider", default=None, choices=["lmstudio", "deepseek"],
                   help="LLM 供应商（默认取 settings.json，缺省 deepseek）")
    p.add_argument("--model", default=None, help="覆盖模型名（如 deepseek-flash）")
    p.add_argument("--mode", default=None, choices=["default", "plan", "full-auto"],
                   help="权限模式（第 6 章三级护栏）")
    p.add_argument("--max-turns", type=int, default=None,
                   help="Agent Loop 最大回合数")
    p.add_argument("--no-banner", action="store_true", help="不打印启动横幅")
    return p


def _make_engine(args) -> Engine:
    engine = Engine(cwd=args.cwd, config_path=args.config)
    if getattr(args, "provider", None):
        engine.config["provider"] = args.provider
    if getattr(args, "model", None):
        engine.config["model"] = args.model
    if args.mode:
        engine.permissions.set_mode(args.mode)
    return engine


def _interactive_ask(prompt: str) -> str:
    """权限审批回调（第 12 章：CLI 必须把 ask_user 接到真实输入）。

    返回值：y = 允许一次，a = 本会话始终允许该工具，其他 = 拒绝。
    """
    try:
        # 待审批的内容已经由 execute_tool_with_hooks 打印过，这里只要输入行
        return input("选择 [y/a/N]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _deny_ask(prompt: str) -> str:
    """非交互环境（管道 / CI）的审批回调。

    待审批的操作已经由 `execute_tool_with_hooks` 通过 on_event 打印过一次，
    这里只补一句「为什么被拒」和补救办法。
    """
    emit("（非交互环境无法审批，已按拒绝处理；可加 --mode full-auto "
         "或用 /permission allow <工具>）")
    return ""


def run_once(engine: Engine, prompt: str, max_turns: int | None,
             ask_user=None) -> str:
    """跑一轮完整的 Agent Loop（第 12 章第 3–8 步）。

    复用当前会话的 Context（多轮历史、todo、恢复状态），只在每轮刷新
    system prompt / 工具表 / 已关闭的 LLM 客户端。
    """
    ctx = engine.begin_turn()
    if max_turns:
        ctx.max_turns = max_turns
    ctx.ask_user = ask_user or _deny_ask
    ctx.messages.append({"role": "user", "content": prompt})
    ctx.on_event = emit
    try:
        return run_query_sync(ctx)
    finally:
        # 即使被 Ctrl+C 中断也保存 user 消息与已产生的工具结果。
        engine.save_current_session()


def _handle_command(engine: Engine, line: str) -> bool:
    """执行斜杠命令；返回 True 表示已处理。"""
    if line.strip().strip("/") == "":
        line = "/help"
    name = line.lstrip("/").split()[0]
    cmd = engine.commands.get(name)
    if cmd is None:
        close = difflib.get_close_matches(name, [c.name for c in engine.commands.list()],
                                          n=1)
        hint = f"，你是想输入 /{close[0]} 吗？" if close else ""
        print(f"未知命令: {line}（输入 /help 查看可用命令）{hint}")
        return True
    args = line.split(" ", 1)[1] if " " in line else ""
    try:
        print(cmd.fn(args))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — 命令出错不应杀掉会话
        print(f"命令执行出错: {e}")
    return True


def interactive(engine: Engine, max_turns: int | None) -> int:
    reader = LineReader(engine)
    print("\n输入你的请求，或 /help 查看命令。输入 / 即出补全菜单。")
    print("双击 Esc 回退上一轮；/new 新会话 · /fork 分叉 · /side 临时会话。")
    prefill = ""
    try:
        while True:
            try:
                line = reader.read(prefill).strip()
            except RewindRequest:
                prefill, note = engine.rewind_last_turn()
                prefill = prefill or ""
                print("\n" + note)
                continue
            except (EOFError, KeyboardInterrupt):
                print("\n再见 👋")
                return 0
            prefill = ""
            if not line:
                continue
            if line.lower() in ("exit", "quit", "q"):
                print("再见 👋")
                return 0
            if line.startswith("/"):
                try:
                    _handle_command(engine, line)
                except SystemExit:
                    print("\n再见 👋")
                    return 0
                continue
            try:
                print_assistant(run_once(
                    engine, line, max_turns,
                    ask_user=_interactive_ask if is_tty() else _deny_ask))
            except KeyboardInterrupt:
                print("\n(已中断当前请求)")
            except SystemExit:
                return 0
            except Exception as e:  # noqa: BLE001 — 单轮失败不应终止会话
                print(f"\n⚠️  请求失败: {type(e).__name__}: {e}")
    finally:
        engine.save_current_session()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = _make_engine(args)
    except Exception as e:  # noqa: BLE001
        print(f"Engine 初始化失败: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    try:
        return _run(engine, args)
    finally:
        engine.close()


def _run(engine: Engine, args) -> int:
    engine.start_background()   # cron 后台调度（仅在本进程运行期间触发）

    if not args.no_banner:
        print(BANNER)
        print(f"工作目录: {engine.cwd}")
        print(f"配置目录: {engine.oh_dir}")
        print(f"权限模式: {engine.permissions.mode}")
        print(f"已注册工具: {len(engine.registry.list_tools())}")
        print(f"已保存会话: {len(engine.persisted_sessions())} · "
              f"定时任务: {len(engine.cron.list())}")

    if args.prompt:
        text = " ".join(args.prompt)
        # 只有真实终端才值得跑完继续交互；管道/CI 下跑完必须退出，否则挂住
        repl = wants_repl()
        try:
            print_assistant(run_once(engine, text, args.max_turns,
                                      ask_user=_interactive_ask if is_tty() else None))
        except KeyboardInterrupt:
            print("\n(已中断)")
            return 130
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  请求失败: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if not repl:
            return 0

    return interactive(engine, args.max_turns)


if __name__ == "__main__":
    raise SystemExit(main())
