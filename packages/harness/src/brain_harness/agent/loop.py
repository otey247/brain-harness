"""The agent loop: the harness owns it, the model only picks tools.

One planner agent with read-only tools plus ``delegate``, which runs a searcher
subagent (same read tools, no delegate, depth 1) for an independent
sub-question. Every run:

- enforces budgets with Pydantic AI ``UsageLimits`` plus :class:`RunGuard`;
- collapses old tool output and compacts history before each model request;
- must end in a typed :class:`Answer`, which is then citation-checked in code;
- writes one run record (and OTel spans when tracing is on).

Pydantic AI is imported lazily so the OKF and tools layers load without it.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from okf import Bundle

from brain_harness.agent.citations import CitationReport, verify_answer
from brain_harness.agent.compaction import make_history_processor
from brain_harness.agent.guards import RunGuard
from brain_harness.agent.output import Answer, SearchReport
from brain_harness.agent.prompts import SEARCHER, planner_prompt
from brain_harness.config import BundleConfig, Settings
from brain_harness.index.sqlite_index import SqliteIndex
from brain_harness.models.registry import resolve
from brain_harness.observability.runlog import RunLog, RunRecord
from brain_harness.tools.knowledge import KnowledgeTools, ToolError

READ_TOOLS = ("list", "glob", "grep", "read", "frontmatter_query", "links", "search")


@dataclass
class Deps:
    tools: KnowledgeTools
    guard: RunGuard
    semaphore: asyncio.Semaphore
    depth: int = 0
    reports: list[SearchReport] = field(default_factory=list)


@dataclass
class AskResult:
    answer: Answer
    citations: CitationReport
    record: RunRecord


def _guarded(name: str, method: Callable[..., str]) -> Callable[..., Any]:
    """Wrap a KnowledgeTools method as a Pydantic AI tool with the run guard applied.

    The wrapper keeps the method's signature and docstring, which become the
    tool's JSON schema and description.
    """
    sig = inspect.signature(method)
    params = [p for p in sig.parameters.values() if p.name != "self"]

    async def tool(ctx: Any, **kwargs: Any) -> str:
        deps: Deps = ctx.deps
        if nudge := deps.guard.check(name, kwargs):
            return nudge
        try:
            return getattr(deps.tools, name)(**kwargs)
        except ToolError as exc:
            return f"error: {exc}"

    from pydantic_ai import RunContext

    ctx_param = inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=RunContext[Deps])
    tool.__signature__ = sig.replace(parameters=[ctx_param, *params], return_annotation=str)  # type: ignore[attr-defined]
    tool.__name__ = name
    tool.__doc__ = method.__doc__
    tool.__annotations__ = {"ctx": RunContext[Deps], **{p.name: p.annotation for p in params}, "return": str}
    return tool


def _register_read_tools(agent: Any, search_enabled: bool) -> None:
    for name in READ_TOOLS:
        if name == "search" and not search_enabled:
            continue
        agent.tool(_guarded(name, getattr(KnowledgeTools, name)), name=name)


class Harness:
    """Entry point shared by the CLI, the HTTP API, the MCP server and the evals."""

    def __init__(
        self,
        settings: Settings,
        bundle_name: str | None = None,
        now: datetime | None = None,
        index_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.bundle_name = bundle_name or settings.default_bundle
        self.bundle_cfg: BundleConfig = settings.bundle(bundle_name)
        self.bundle = Bundle.load(self.bundle_cfg.path)
        self.index = SqliteIndex(index_path) if index_path else None
        self.now = now
        self.run_log = RunLog(settings.run_log_dir)
        self._planner: Any = None
        self._searcher: Any = None

    # ---- tools (also used directly by the MCP server) ----------------------------
    def tools(self) -> KnowledgeTools:
        return KnowledgeTools(
            self.bundle,
            caps=self.settings.caps,
            scratch_dir=self.settings.scratch_dir,
            now=self.now,
            index=self.index,
        )

    def reload(self) -> None:
        self.bundle = Bundle.load(self.bundle_cfg.path)

    # ---- agents ------------------------------------------------------------------
    def _capabilities(self) -> list[Any]:
        from pydantic_ai.capabilities import ProcessHistory

        b = self.settings.budgets
        processor = make_history_processor(b.context_window_tokens, b.collapse_after_turns, b.compact_at_fraction)
        return [ProcessHistory(processor)]

    def searcher(self) -> Any:
        if self._searcher is None:
            from pydantic_ai import Agent

            agent = Agent(
                resolve(self.settings, "searcher", self.bundle_cfg),
                deps_type=Deps,
                output_type=SearchReport,
                instructions=SEARCHER,
                capabilities=self._capabilities(),
                retries=self.settings.budgets.model_retries,
                name="searcher",
            )
            _register_read_tools(agent, self.index is not None)
            self._searcher = agent
        return self._searcher

    def planner(self) -> Any:
        if self._planner is None:
            from pydantic_ai import Agent, RunContext

            budgets = self.settings.budgets
            agent = Agent(
                resolve(self.settings, "planner", self.bundle_cfg),
                deps_type=Deps,
                output_type=Answer,
                instructions=planner_prompt(budgets.max_parallel_searchers, self.bundle.description),
                capabilities=self._capabilities(),
                retries=budgets.model_retries,
                name="planner",
            )
            _register_read_tools(agent, self.index is not None)
            searcher = self.searcher()

            async def delegate(ctx: RunContext[Deps], sub_question: str) -> str:
                """Hand one independent sub-question to a read-only searcher. Returns its cited findings."""
                deps = ctx.deps
                if deps.depth >= 1:
                    return "error: searchers cannot delegate"
                if nudge := deps.guard.check("delegate", {"sub_question": sub_question}):
                    return nudge
                child = Deps(tools=deps.tools, guard=deps.guard, semaphore=deps.semaphore, depth=deps.depth + 1)
                async with deps.semaphore:
                    result = await searcher.run(sub_question, deps=child, usage=ctx.usage)
                report: SearchReport = result.output
                deps.reports.append(report)
                return report.model_dump_json(indent=1)

            # Annotations are strings under `from __future__ import annotations`; RunContext is
            # imported locally, so give the schema builder the real objects.
            delegate.__annotations__ = {"ctx": RunContext[Deps], "sub_question": str, "return": str}
            agent.tool(delegate)

            self._planner = agent
        return self._planner

    # ---- ask ---------------------------------------------------------------------
    async def ask(self, question: str) -> AskResult:
        from pydantic_ai.usage import UsageLimits

        b = self.settings.budgets
        tools = self.tools()
        guard = RunGuard(b.repeat_call_limit, b.max_tool_calls, b.max_cost_usd)
        deps = Deps(tools=tools, guard=guard, semaphore=asyncio.Semaphore(b.max_parallel_searchers))
        roles = self.settings.roles
        models = {k: v["model"] for k, v in roles.model_dump().items() if v} if roles else {}
        record = RunRecord(question=question, bundle=self.bundle_name, models=models)
        limits = UsageLimits(
            request_limit=b.max_requests,
            tool_calls_limit=b.max_tool_calls,
            total_tokens_limit=b.max_total_tokens,
        )
        try:
            result = await self.planner().run(question, deps=deps, usage_limits=limits)
            checked, report = verify_answer(self.bundle, result.output, self.now)
            usage = result.usage
            record.usage = {
                "requests": usage.requests,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "tool_calls": usage.tool_calls,
            }
            record.answer = checked.model_dump()
            record.citation_validity = report.validity
            return AskResult(answer=checked, citations=report, record=record)
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record.opened = sorted(tools.ledger.opened())
            record.grep_hits = sorted(tools.ledger.grep_hits)
            record.tool_calls = dict(guard.calls)
            record.finish()
            self.run_log.write(record)

    def ask_sync(self, question: str) -> AskResult:
        return asyncio.run(self.ask(question))
