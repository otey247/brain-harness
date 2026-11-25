from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from brain_harness.agent.loop import Harness
from brain_harness.apps.mcp_server import build_server
from conftest import NOW


@pytest.fixture
def server(settings):
    return build_server(Harness(settings, now=NOW))


async def _text(server, name, args):
    result = await server.call_tool(name, args)
    return result.content[0].text


def test_tools_registered(server):
    import asyncio

    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"ask", "grep", "read", "list", "links", "frontmatter_query"} <= names
    assert "search" not in names and "propose" not in names


def test_grep_and_errors_over_mcp(server):
    import asyncio

    out = asyncio.run(_text(server, "grep", {"pattern": "Alex", "mode": "files"}))
    assert "people/alex-chen.md" in out
    err = asyncio.run(_text(server, "read", {"path": "../secret.md"}))
    assert err.startswith("error:")
