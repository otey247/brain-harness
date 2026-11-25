from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from okf import Bundle, Status, TrustTier, rank_conflicting, trust_info, validate
from okf.bundle import parse_concept, split_frontmatter
from okf.conflicts import follow_superseded
from okf.links import extract_links, resolve_target
from okf.validate import is_conformant
from okf.writer import append_log, render_index
from okf.yaml12 import Yaml12Error, load_mapping

EXAMPLE = Path(__file__).resolve().parents[3] / "bundles" / "example"
NOW = datetime(2026, 11, 25, tzinfo=UTC)


@pytest.fixture()
def bundle() -> Bundle:
    return Bundle.load(EXAMPLE)


# ---- YAML 1.2 core ------------------------------------------------------


def test_yaml12_keeps_yes_no_on_off_as_strings() -> None:
    data = load_mapping("a: yes\nb: off\nc: true\nd: 010\ne: 0x1F\nf: 2026-11-01\n")
    assert data == {"a": "yes", "b": "off", "c": True, "d": 10, "e": 31, "f": "2026-11-01"}


def test_yaml12_rejects_duplicates_and_tags() -> None:
    with pytest.raises(Yaml12Error):
        load_mapping("a: 1\na: 2\n")
    with pytest.raises(Yaml12Error):
        load_mapping("a: !custom x\n")
    with pytest.raises(Yaml12Error):
        load_mapping("- just\n- a list\n")


# ---- parsing --------------------------------------------------------------


def test_file_without_type_is_not_a_concept() -> None:
    assert parse_concept("README.md", "# hi\n") is None
    assert parse_concept("a.md", "---\ntitle: x\n---\nbody") is None


def test_frontmatter_must_start_the_file() -> None:
    fm = split_frontmatter("\n---\ntype: x\n---\n")
    assert not fm.has_frontmatter


def test_bundle_scan(bundle: Bundle) -> None:
    assert "README.md" in bundle.other_markdown
    assert "index.md" in bundle.reserved and "log.md" in bundle.reserved
    assert len(bundle.concepts) == 5
    assert bundle.okf_version == "0.3"
    assert bundle.description and "Sample bundle" in bundle.description


def test_scalar_tags_are_not_split(bundle: Bundle) -> None:
    person = bundle.get("people/alex-chen.md")
    assert person is not None and person.tags == ["person"]


def test_unknown_and_extension_keys_preserved(bundle: Bundle) -> None:
    topic = bundle.get("topics/agentic-search.md")
    assert topic is not None and topic.meta["x-example-confidence"] == "medium"


# ---- trust ---------------------------------------------------------------


def test_trust_tiers(bundle: Bundle) -> None:
    assert (
        trust_info(bundle.concepts["decisions/2026-11-retrieval-grep-first.md"], NOW).tier is TrustTier.HUMAN_REVIEWED
    )
    assert trust_info(bundle.concepts["topics/agentic-search.md"], NOW).tier is TrustTier.MACHINE_CONFIRMED
    assert trust_info(bundle.concepts["people/alex-chen.md"], NOW).tier is TrustTier.UNVERIFIED


def test_verification_before_generation_does_not_count() -> None:
    text = (
        "---\ntype: note\ngenerated: {by: tool/1, at: '2026-11-10T00:00:00Z'}\n"
        "verified:\n  - {by: 'human:jo', at: '2026-11-01T00:00:00Z'}\n---\nbody\n"
    )
    concept = parse_concept("n.md", text)
    assert concept is not None
    assert trust_info(concept, NOW).tier is TrustTier.UNVERIFIED


def test_staleness(bundle: Bundle) -> None:
    assert trust_info(bundle.concepts["topics/agentic-search.md"], NOW).stale
    assert not trust_info(bundle.concepts["projects/okf-harness.md"], NOW).stale
    bad = parse_concept("b.md", "---\ntype: x\nstale_after: next week\n---\n")
    assert bad is not None and trust_info(bad, NOW).stale  # unparseable is never fresh


def test_unknown_status_is_not_current() -> None:
    c = parse_concept("c.md", "---\ntype: x\nstatus: archived\n---\n")
    assert c is not None and c.status is Status.UNKNOWN


def test_conflict_order_prefers_current_reviewed_fresh(bundle: Bundle) -> None:
    ranked = rank_conflicting(
        [
            bundle.concepts["decisions/2026-06-retrieval-vectors-first.md"],
            bundle.concepts["decisions/2026-11-retrieval-grep-first.md"],
        ],
        NOW,
    )
    assert ranked[0].concept.path == "decisions/2026-11-retrieval-grep-first.md"
    assert "deprecated" in ranked[1].reason


def test_follow_superseded(bundle: Bundle) -> None:
    chain = follow_superseded(bundle, "decisions/2026-06-retrieval-vectors-first.md")
    assert chain == ["decisions/2026-06-retrieval-vectors-first.md", "decisions/2026-11-retrieval-grep-first.md"]


# ---- links ----------------------------------------------------------------


def test_link_resolution_rules() -> None:
    assert resolve_target("https://x.org/a", "a/b.md") == (None, True, None)
    assert resolve_target("/people/p.md", "a/b.md")[0] == "people/p.md"
    assert resolve_target("../people/p.md#bio", "a/b.md") == ("people/p.md", False, "bio")
    assert resolve_target("../../outside.md", "a/b.md")[0] is None


def test_v02_root_fallback() -> None:
    exists = {"people/p.md"}.__contains__
    assert resolve_target("people/p.md", "projects/x.md", exists)[0] == "people/p.md"


def test_wikilinks_and_code_are_not_links() -> None:
    body = "See [[Other]] and `[x](y.md)`\n```\n[a](b.md)\n```\n[real](c.md)\n"
    links = extract_links(body, "n.md")
    assert [lk.target for lk in links] == ["c.md"]
    assert links[0].line == 5


def test_graph_edges_and_backlinks(bundle: Bundle) -> None:
    edges = bundle.edges_from("projects/okf-harness.md")
    assert set(edges) == {"decisions/2026-11-retrieval-grep-first.md", "people/alex-chen.md"}
    back = bundle.backlinks()
    assert "decisions/2026-06-retrieval-vectors-first.md" in back["decisions/2026-11-retrieval-grep-first.md"]


# ---- validation -------------------------------------------------------------


def test_example_bundle_is_clean(bundle: Bundle) -> None:
    issues = validate(bundle)
    assert is_conformant(issues)
    assert issues == []


def test_validator_flags_problems(tmp_path: Path) -> None:
    root = tmp_path / "b"
    shutil.copytree(EXAMPLE, root)
    (root / "bad.md").write_text("---\ntype: x\nstatus: deprecated\n---\n[gone](missing.md) [^nope]\n")
    (root / "broken.md").write_text("---\ntype: [unclosed\n---\n")
    (root / "topics" / "index.md").write_text("---\ntitle: no\n---\n")
    codes = {i.code for i in validate(Bundle.load(root))}
    assert {"W120", "W130", "W150", "E101", "E110"} <= codes


# ---- writer ---------------------------------------------------------------


def test_render_index_keeps_root_frontmatter(bundle: Bundle) -> None:
    text = render_index(bundle)
    assert text.startswith('---\nokf_version: "0.3"')
    sub = render_index(bundle, "decisions")
    assert "* [Retrieval: grep first](2026-11-retrieval-grep-first.md) - " in sub


def test_append_log_newest_first(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    log.write_text("# Log\n\n## 2026-11-20\n\n- older\n")
    append_log(log, "newer", day=datetime(2026, 11, 25).date())
    append_log(log, "same day", day=datetime(2026, 11, 25).date())
    text = log.read_text()
    assert text.index("## 2026-11-25") < text.index("## 2026-11-20")
    assert text.index("- same day") < text.index("- newer")


def test_set_frontmatter_round_trip() -> None:
    pytest.importorskip("ruamel.yaml")
    from okf.writer import set_frontmatter, stamp_generated

    text = "---\n# keep me\ntype: note\ntitle: 'Quoted'\nx-mine: {a: 1}\n---\nBody stays.\n"
    out = set_frontmatter(text, {"status": "draft"})
    assert "# keep me" in out and "'Quoted'" in out and "x-mine" in out and out.endswith("Body stays.\n")
    with pytest.raises(PermissionError):
        set_frontmatter(text, {"verified": [{"by": "me", "at": "now"}]})
    assert "generated:" in stamp_generated(text, "brain-harness/0.1.0+test")
