# tests/test_profiles.py
import pytest

from ai_doc_creator.core.graph import (
    build_diagram_section,
    build_doc_prompt,
    build_index_prompt,
)
from ai_doc_creator.core.profiles import PROFILES, get_profile


def test_all_profiles_keep_summary_first():
    # The index generator extracts '### Summary' from every per-file doc.
    for profile in PROFILES.values():
        assert profile.file_sections.startswith("### Summary")


def test_get_profile_defaults_and_case():
    assert get_profile(None).name == "readme"
    assert get_profile("API").name == "api"
    assert get_profile(" architecture ").name == "architecture"


def test_get_profile_unknown_raises_with_valid_list():
    with pytest.raises(ValueError, match="readme"):
        get_profile("banana")


def test_doc_prompt_reflects_profile():
    api = build_doc_prompt("f.py", "code", profile="api")
    assert "API Reference" in api
    tutorial = build_doc_prompt("f.py", "code", profile="tutorial")
    assert "Walkthrough" in tutorial


def test_doc_prompt_diagram_hint_only_when_enabled_and_supported():
    with_diagram = build_doc_prompt("f.py", "code", profile="architecture", diagrams=True)
    assert "Mermaid" in with_diagram
    without = build_doc_prompt("f.py", "code", profile="architecture", diagrams=False)
    assert "Mermaid" not in without
    api = build_doc_prompt("f.py", "code", profile="api", diagrams=True)
    assert "Mermaid" not in api  # api profile opts out of per-file diagrams


def test_index_prompt_reflects_profile_and_warns_off_diagrams():
    prompt = build_index_prompt("a.py", "- a", profile="architecture")
    assert "architecture document" in prompt.lower()
    assert "appended automatically" in prompt


def test_build_diagram_section_empty_for_trivial_repo(tmp_path):
    assert build_diagram_section(["one.py"], str(tmp_path)) == ""


def test_build_diagram_section_contains_structure(tmp_path):
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("import b\n", encoding="utf-8")
    section = build_diagram_section(["a.py", "b.py", "c.py"], str(tmp_path))
    assert "## Architecture Diagrams" in section
    assert "### Project Structure" in section
    assert "### Module Dependencies" in section
    assert section.count("```mermaid") == 2
