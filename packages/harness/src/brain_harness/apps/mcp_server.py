"""MCP server: the harness as a tool any MCP client can use.

Exposes ``ask`` (the full loop, cited answer) and the read primitives, so a
client that runs its own loop can still get capped, trust-labelled results.
``propose_change`` is registered only when the bundle has ``writes_enabled``.

Run: ``brain mcp`` (stdio) or ``brain mcp --transport streamable-http``.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from brain_harness.agent.loop import Harness
from brain_harness.tools.knowledge import ToolError

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def _run(fn: Any, **kwargs: Any) -> str:
    try:
        return fn(**kwargs)
    except ToolError as exc:
        return f"error: {exc}"


def build_server(harness: Harness) -> MCPServer:
    bundle = harness.bundle
    server = MCPServer(
        name="brain-harness",
        instructions=(
            "Search and read one Open Knowledge Format bundle. Use `ask` for a cited answer, "
            "or the primitives (grep, read, list, links, frontmatter_query) to search yourself. "
            "Every result carries trust labels; prefer stable, human-reviewed, non-stale concepts. "
            f"Bundle: {bundle.description or harness.bundle_name}"
        ),
        version="0.1.0",
    )

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def ask(question: str) -> dict[str, Any]:
        """Answer a question from the bundle. Returns the answer, verified citations, concepts used and gaps."""
        result = await harness.ask(question)
        return result.answer.model_dump()

    @server.tool(annotations=READ_ONLY)
    def grep(
        pattern: str,
        path: str = "",
        mode: Literal["files", "content", "count"] = "content",
        ignore_case: bool = True,
        context: int = 0,
        offset: int = 0,
    ) -> str:
        """Regex search over the bundle's Markdown. Results carry file line numbers and trust labels."""
        return _run(
            harness.tools().grep,
            pattern=pattern,
            path=path,
            mode=mode,
            ignore_case=ignore_case,
            context=context,
            offset=offset,
        )

    @server.tool(annotations=READ_ONLY)
    def read(path: str, offset: int = 1, limit: int | None = None, frontmatter_only: bool = False) -> str:
        """Read a concept (or a scratch: spill file) with file line numbers."""
        return _run(harness.tools().read, path=path, offset=offset, limit=limit, frontmatter_only=frontmatter_only)

    @server.tool(name="list", annotations=READ_ONLY)
    def list_dir(directory: str = "") -> str:
        """List one directory: its index, concepts with trust labels, and subdirectories."""
        return _run(harness.tools().list, directory=directory)

    @server.tool(annotations=READ_ONLY)
    def links(path: str, direction: Literal["out", "in", "both"] = "both", depth: int = 1) -> str:
        """Outbound links and backlinks of a concept, up to depth 2."""
        return _run(harness.tools().links, path=path, direction=direction, depth=depth)

    @server.tool(annotations=READ_ONLY)
    def frontmatter_query(
        type: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        tier: str | None = None,
        stale: bool | None = None,
        updated_since: str | None = None,
        text: str | None = None,
    ) -> str:
        """Filter concepts by type, tag, status, trust tier, staleness or generated date."""
        return _run(
            harness.tools().frontmatter_query,
            type=type,
            tag=tag,
            status=status,
            tier=tier,
            stale=stale,
            updated_since=updated_since,
            text=text,
        )

    if harness.index is not None:

        @server.tool(annotations=READ_ONLY)
        def search(query: str, k: int = 10) -> str:
            """Ranked pages from the local index (BM25 or hybrid)."""
            return _run(harness.tools().search, query=query, k=k)

    if harness.bundle_cfg.writes_enabled:
        from brain_harness.ingest.propose import ProposalError, propose_change

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        def propose(path: str, content: str, reason: str) -> str:
            """Propose a new or changed concept. It is committed to a new review branch, never the main branch."""
            try:
                p = propose_change(harness.bundle.root, path, content, reason, harness.settings.producer_id)
            except ProposalError as exc:
                return f"error: {exc}"
            return f"proposed {p.path} on branch {p.branch} ({p.commit[:12]}); a human reviews and merges it"

    @server.resource("okf://index", name="index", mime_type="text/markdown")
    def root_index() -> str:
        """The bundle's root index.md."""
        path = harness.bundle.root / "index.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    return server


def main(transport: str = "stdio", bundle: str | None = None) -> None:
    from brain_harness.config import load_settings
    from brain_harness.observability.tracing import setup_tracing

    setup_tracing()
    harness = Harness(load_settings(), bundle_name=bundle)
    build_server(harness).run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
