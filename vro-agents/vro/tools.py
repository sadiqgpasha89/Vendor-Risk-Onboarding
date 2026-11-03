"""Tool registry with least-privilege allow-lists (plan §4.5, §6.7; GR-001, GR-008, GR-009, GR-011, GR-013).

This is the in-process equivalent of the MCP servers in the plan: same tool contracts, same authorisation point (a policy
proxy). tenant/vendor/case ids are BOUND SERVER-SIDE from the run context; any such argument supplied by an agent is ignored.
There is deliberately no tool that approves, rejects, clears a sanctions match, or sends a message (GR-001/GR-011).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .util import iso, new_id, now, sha256_text

FORBIDDEN_TOOL_FRAGMENTS = ("approve", "reject", "clear", "send", "dispose", "decide", "email", "post_message")
MAX_TOOL_CALLS = 12
MAX_CONSECUTIVE_FAILURES = 3


class ToolError(Exception):
    pass


class ToolDenied(ToolError):
    pass


class LoopBoundExceeded(ToolError):
    pass


@dataclass
class Tool:
    name: str
    fn: Callable[..., Any]
    writes: bool = False
    description: str = ""


@dataclass
class ToolContext:
    tenant_id: str
    case_id: str
    vendor_id: str
    agent: str
    run_id: str
    allowed: frozenset
    registry: "ToolRegistry"
    tainted: bool = False            # contaminated by flagged content => write tools disabled (§8.3 control 4)
    calls: int = 0
    consecutive_failures: int = 0

    def call(self, name: str, **args) -> Any:
        return self.registry.call(self, name, **args)


class ToolRegistry:
    def __init__(self, store=None):
        self.store = store
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        low = tool.name.lower()
        if any(f in low for f in FORBIDDEN_TOOL_FRAGMENTS):
            raise ValueError(f"tool name '{tool.name}' is forbidden by GR-001/GR-011")
        self.tools[tool.name] = tool

    def call(self, ctx: ToolContext, name: str, **args) -> Any:
        if name not in ctx.allowed or name not in self.tools:
            raise ToolDenied(f"agent {ctx.agent} may not call '{name}'")
        tool = self.tools[name]
        if tool.writes and ctx.tainted:
            raise ToolDenied("write tools are disabled for runs that processed flagged content")
        if ctx.calls >= MAX_TOOL_CALLS:
            raise LoopBoundExceeded(f"max {MAX_TOOL_CALLS} tool calls reached (GR-013)")
        if ctx.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            raise LoopBoundExceeded("3 consecutive tool failures (GR-013)")
        for forbidden in ("tenant_id", "vendor_id", "case_id"):
            args.pop(forbidden, None)           # GR-009: ids come from the run context only
        ctx.calls += 1
        t0 = time.time()
        status, result = "ok", None
        try:
            result = tool.fn(ctx, **args)
            ctx.consecutive_failures = 0
            return result
        except Exception as e:
            ctx.consecutive_failures += 1
            status = "error:" + type(e).__name__
            raise
        finally:
            if self.store is not None:
                redacted = {k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:80]) for k, v in args.items()}
                self.store.insert("tool_calls", {
                    "call_id": new_id("tc_"), "run_id": ctx.run_id, "tool": name, "args_redacted": redacted,
                    "result_hash": sha256_text(json.dumps(result, default=str)[:20000]) if result is not None else None,
                    "status": status, "latency_ms": int((time.time() - t0) * 1000), "started_at": iso(now())})
