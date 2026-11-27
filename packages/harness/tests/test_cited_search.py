import json
from pathlib import Path

import pytest
from brain_harness.agent.output import Answer
from brain_harness.workflows.cited_search.cli import RESOURCES, main


def test_smoke_ignores_ambient_provider_and_bundle(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BRAIN_MODEL", "openai:unused")
    monkeypatch.setenv("BRAIN_BUNDLE", str(tmp_path / "absent"))
    assert main(["smoke", "--log-dir", str(tmp_path)]) == 0
    answer = Answer.model_validate_json(capsys.readouterr().out)
    (citation,) = answer.citations
    assert answer.answer == citation.quote and answer.gaps == []
    lines = (RESOURCES / "bundle" / citation.path).read_text().splitlines()
    assert lines[citation.start_line - 1] == citation.quote
    assert answer.concepts_used[0].status == "stable"
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text())
    assert record["grep_hits"] == record["opened"] == ["handoff.md"]


def test_live_dispatch_uses_selected_bundle_and_roles(monkeypatch, tmp_path, capsys):
    from brain_harness.agent.loop import Harness

    # Stop at the provider boundary after the real CLI has built the configured harness.
    class Result:
        answer = Answer(answer="No receiving schedule in these notes.", abstained=True)

    def ask(self, question):
        assert question == "When is receiving open?"
        assert self.bundle.root == tmp_path
        assert self.bundle_cfg.allowed_providers == ["openai", "anthropic"]
        assert not self.bundle_cfg.writes_enabled
        assert self.settings.roles.planner.model == "openai:fixture"
        assert self.settings.roles.searcher.model == "claude:fixture"
        return Result()

    monkeypatch.setattr(Harness, "ask_sync", ask)
    monkeypatch.setenv("BRAIN_PLANNER_MODEL", "openai:fixture")
    monkeypatch.setenv("BRAIN_SEARCHER_MODEL", "claude:fixture")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    (tmp_path / "hours.md").write_text("---\ntype: procedure\n---\n")
    assert (
        main(
            [
                "ask",
                "--live",
                "--allow-provider",
                "openai",
                "--allow-provider",
                "anthropic",
                "--bundle",
                str(tmp_path),
                "When is receiving open?",
            ]
        )
        == 0
    )
    assert Answer.model_validate_json(capsys.readouterr().out).abstained


@pytest.mark.parametrize(
    ("searcher", "error"),
    [
        ("openai:unused", "bundle allows"),
        ("claude:unused", "bundle must be an existing directory"),
    ],
)
def test_bad_live_configuration_fails_before_running(searcher, error, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_PLANNER_MODEL", "claude:unused")
    monkeypatch.setenv("BRAIN_SEARCHER_MODEL", searcher)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert main(["ask", "--live", "--allow-provider", "anthropic", "--bundle", str(tmp_path / "missing"), "?"]) == 1
    out = capsys.readouterr()
    assert not out.out and error in out.err


def test_log_dir_cannot_be_in_bundle(capsys):
    assert main(["smoke", "--log-dir", str(RESOURCES / "bundle" / "logs")]) == 1
    assert "outside the bundle" in capsys.readouterr().err


def test_linked_file_refused(tmp_path, monkeypatch, capsys):
    from brain_harness.workflows.cited_search import cli

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    try:
        (bundle / "linked.md").symlink_to(Path(__file__))
    except OSError:
        pytest.skip("symlinks unavailable")
    monkeypatch.setattr(cli, "RESOURCES", tmp_path)
    assert main(["smoke"]) == 1
    assert "symlinks" in capsys.readouterr().err
