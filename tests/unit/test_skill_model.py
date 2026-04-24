from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.file_io import delete_skill_file, list_skill_files, read_skill_file, write_skill_file
from src.models.skill import SkillFile, SkillFrontmatter, SkillMetadata, SkillReference


class TestSkillMetadata:
    def test_defaults(self) -> None:
        m = SkillMetadata()
        assert m.update_times == 0
        assert m.confidence_score == 0.0
        assert m.categories == []
        assert isinstance(m.create_at, datetime)
        assert isinstance(m.last_update_at, datetime)

    def test_custom_values(self) -> None:
        now = datetime.now(timezone.utc)
        m = SkillMetadata(
            create_at=now,
            last_update_at=now,
            update_times=5,
            confidence_score=0.85,
            categories=["data_analysis"],
        )
        assert m.update_times == 5
        assert m.confidence_score == 0.85
        assert m.categories == ["data_analysis"]

    def test_confidence_score_bounds(self) -> None:
        SkillMetadata(confidence_score=0.0)
        SkillMetadata(confidence_score=1.0)
        with pytest.raises(ValidationError):
            SkillMetadata(confidence_score=-0.1)
        with pytest.raises(ValidationError):
            SkillMetadata(confidence_score=1.1)

    def test_update_times_negative(self) -> None:
        with pytest.raises(ValidationError):
            SkillMetadata(update_times=-1)


class TestSkillFrontmatter:
    def test_minimal(self) -> None:
        fm = SkillFrontmatter(name="test")
        assert fm.name == "test"
        assert fm.description == ""
        assert fm.version == "1.0.0"
        assert fm.os == []
        assert fm.dependencies == {}

    def test_full(self) -> None:
        fm = SkillFrontmatter(
            name="test",
            description="A test skill",
            author="agent1",
            version="2.0.0",
            os=["linux", "windows"],
            dependencies={"python": ["pandas>=1.5.0"]},
            metadata=SkillMetadata(confidence_score=0.9),
        )
        assert fm.author == "agent1"
        assert fm.os == ["linux", "windows"]
        assert fm.metadata.confidence_score == 0.9


class TestSkillReference:
    def test_creation(self) -> None:
        ref = SkillReference(ref_type="skills", name="sub_skill")
        assert ref.ref_type == "skills"
        assert ref.name == "sub_skill"


class TestSkillFileFromMarkdown:
    def test_parse_basic(self) -> None:
        text = """---
name: test_skill
description: A test
---
## 任务目标
Do something
"""
        sf = SkillFile.from_markdown(text)
        assert sf.frontmatter.name == "test_skill"
        assert sf.frontmatter.description == "A test"
        assert "任务目标" in sf.content

    def test_parse_full_frontmatter(self) -> None:
        text = """---
name: full_skill
description: Full test
author: agent1
version: "2.0.0"
os:
- linux
- windows
dependencies:
  python:
  - pandas>=1.5.0
metadata:
  create_at: "2024-01-01T00:00:00+00:00"
  last_update_at: "2024-01-01T00:00:00+00:00"
  update_times: 3
  confidence_score: 0.8
  categories:
  - data_analysis
---
Content here
"""
        sf = SkillFile.from_markdown(text)
        assert sf.frontmatter.name == "full_skill"
        assert sf.frontmatter.author == "agent1"
        assert sf.frontmatter.os == ["linux", "windows"]
        assert sf.frontmatter.metadata.confidence_score == 0.8

    def test_missing_opening_delimiter(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            SkillFile.from_markdown("no frontmatter here")

    def test_missing_closing_delimiter(self) -> None:
        with pytest.raises(ValueError, match="closing"):
            SkillFile.from_markdown("---\nname: test\n")


class TestSkillFileToMarkdown:
    def test_round_trip(self) -> None:
        original = """---
name: round_trip
description: Round trip test
author: bot
---
## Step 1
[[skills: sub_skill]]
[[tools: my_tool]]
"""
        sf = SkillFile.from_markdown(original)
        exported = sf.to_markdown()
        sf2 = SkillFile.from_markdown(exported)
        assert sf2.frontmatter.name == "round_trip"
        assert sf2.frontmatter.description == "Round trip test"
        assert sf2.frontmatter.author == "bot"
        assert "[[skills: sub_skill]]" in sf2.content

    def test_output_starts_with_delimiter(self) -> None:
        sf = SkillFile(frontmatter=SkillFrontmatter(name="test"), content="body")
        md = sf.to_markdown()
        assert md.startswith("---\n")


class TestExtractReferences:
    def test_skill_references(self) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="test"),
            content="[[skills: sub1]] and [[skills: sub2]]",
        )
        refs = sf.extract_references()
        assert len(refs) == 2
        assert refs[0] == SkillReference(ref_type="skills", name="sub1")
        assert refs[1] == SkillReference(ref_type="skills", name="sub2")

    def test_tool_references(self) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="test"),
            content="Use [[tools: analyzer]] for this",
        )
        refs = sf.extract_references()
        assert len(refs) == 1
        assert refs[0].ref_type == "tools"
        assert refs[0].name == "analyzer"

    def test_reference_references(self) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="test"),
            content="See [[references: guide.md]]",
        )
        refs = sf.extract_references()
        assert len(refs) == 1
        assert refs[0].ref_type == "references"
        assert refs[0].name == "guide.md"

    def test_mixed_references(self) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="test"),
            content="[[skills: sub]] [[tools: t1]] [[references: r.md]]",
        )
        refs = sf.extract_references()
        assert len(refs) == 3
        types = [r.ref_type for r in refs]
        assert types == ["skills", "tools", "references"]

    def test_no_references(self) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="test"),
            content="Just plain text here",
        )
        assert sf.extract_references() == []

    def test_reference_with_spaces(self) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="test"),
            content="[[skills:   sub_skill]]",
        )
        refs = sf.extract_references()
        assert len(refs) == 1
        assert refs[0].name == "sub_skill"


class TestFileIO:
    def test_write_and_read(self, tmp_path: Path) -> None:
        sf = SkillFile(
            frontmatter=SkillFrontmatter(name="io_test", description="IO test"),
            content="## Body\nHello",
        )
        path = tmp_path / "io_test.md"
        write_skill_file(path, sf)
        assert path.exists()
        loaded = read_skill_file(path)
        assert loaded.frontmatter.name == "io_test"
        assert "Hello" in loaded.content

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        sf = SkillFile(frontmatter=SkillFrontmatter(name="nested"), content="x")
        path = tmp_path / "sub" / "dir" / "nested.md"
        write_skill_file(path, sf)
        assert path.exists()

    def test_delete_skill_file(self, tmp_path: Path) -> None:
        sf = SkillFile(frontmatter=SkillFrontmatter(name="del"), content="x")
        path = tmp_path / "del.md"
        write_skill_file(path, sf)
        delete_skill_file(path)
        assert not path.exists()

    def test_delete_nonexistent_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "nope.md"
        with pytest.raises(FileNotFoundError):
            delete_skill_file(path)

    def test_list_skill_files(self, tmp_path: Path) -> None:
        sf = SkillFile(frontmatter=SkillFrontmatter(name="a"), content="a")
        write_skill_file(tmp_path / "a.md", sf)
        write_skill_file(tmp_path / "b.md", SkillFile(frontmatter=SkillFrontmatter(name="b"), content="b"))
        (tmp_path / "c.txt").write_text("not a skill")
        files = list_skill_files(tmp_path)
        assert len(files) == 2
        assert all(f.suffix == ".md" for f in files)

    def test_list_skill_files_empty_dir(self, tmp_path: Path) -> None:
        assert list_skill_files(tmp_path) == []

    def test_list_skill_files_nonexistent_dir(self, tmp_path: Path) -> None:
        assert list_skill_files(tmp_path / "nope") == []
