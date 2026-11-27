"""A scripted model for the installed fixture. The search tools and citation checker run normally."""

import re

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from brain_harness.agent.loop import AskResult, Harness

QUESTION = "When does the evening dispatcher sign the handoff sheet?"
EXPECTED = "The evening dispatcher signs the handoff sheet at 18:30 UTC."


def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    reply = next((part for part in messages[-1].parts if isinstance(part, ToolReturnPart)), None)
    if reply is None:
        call = ToolCallPart("grep", {"pattern": "signs the handoff sheet", "mode": "files"})
    elif reply.tool_name == "grep":
        path = str(reply.content).split("  [", 1)[0]
        call = ToolCallPart("read", {"path": path})
    else:
        content = str(reply.content)
        match = re.search(r"^\s*(\d+)\t(The evening dispatcher .+)$", content, re.MULTILINE)
        if reply.tool_name != "read" or match is None:
            raise ValueError("the installed handoff procedure is missing its evidence line")
        line, quote = match.groups()
        path = content.splitlines()[0].removeprefix("# ").split("  [", 1)[0]
        citation = dict(path=path, start_line=int(line), end_line=int(line), quote=quote, claim=quote)
        call = ToolCallPart(info.output_tools[0].name, {"answer": quote, "citations": [citation]})
    return ModelResponse(parts=[call])


def run(harness: Harness) -> AskResult:
    model = FunctionModel(_dispatch)
    with harness.planner().override(model=model):
        result = harness.ask_sync(QUESTION)
    if (
        result.answer.answer != EXPECTED
        or result.answer.abstained
        or not result.citations.valid
        or result.citations.invalid
        or "handoff.md" not in result.record.opened
    ):
        raise ValueError("smoke failed to read and cite the installed handoff procedure")
    return result
