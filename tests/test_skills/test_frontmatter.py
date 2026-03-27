"""Tests for frontmatter parsing."""

import pytest

from pyclaw.skills.frontmatter import (
    extract_frontmatter,
    parse_metadata,
    strip_frontmatter,
)


class TestExtractFrontmatter:
    def test_basic_yaml(self):
        content = "---\nname: test\ndescription: hello\n---\n# Body"
        assert extract_frontmatter(content) == "name: test\ndescription: hello"

    def test_no_frontmatter(self):
        content = "# Just a heading\nSome text"
        assert extract_frontmatter(content) == ""

    def test_windows_line_endings(self):
        content = "---\r\nname: test\r\n---\r\n# Body"
        assert "name: test" in extract_frontmatter(content)

    def test_classic_mac_line_endings(self):
        content = "---\rname: test\r---\r# Body"
        assert "name: test" in extract_frontmatter(content)

    def test_empty_frontmatter(self):
        content = "---\n\n---\n# Body"
        # The regex requires at least a newline between --- delimiters
        fm = extract_frontmatter(content)
        assert fm == ""  # empty line between delimiters

    def test_multiline_frontmatter(self):
        content = "---\nname: test\ndescription: a long description\ntags: foo\n---\n"
        fm = extract_frontmatter(content)
        assert "name: test" in fm
        assert "description: a long description" in fm


class TestStripFrontmatter:
    def test_basic(self):
        content = "---\nname: test\n---\n# Body\nText"
        assert strip_frontmatter(content) == "# Body\nText"

    def test_no_frontmatter(self):
        content = "# Just text"
        assert strip_frontmatter(content) == "# Just text"

    def test_trailing_newlines_stripped(self):
        content = "---\nname: test\n---\n\n\n# Body"
        result = strip_frontmatter(content)
        assert result == "# Body"

    def test_windows_line_endings(self):
        content = "---\r\nname: test\r\n---\r\n# Body"
        result = strip_frontmatter(content)
        assert "# Body" in result


class TestParseMetadata:
    def test_yaml_frontmatter(self):
        content = "---\nname: my-skill\ndescription: Does things\n---\n# Body"
        meta = parse_metadata(content)
        assert meta.name == "my-skill"
        assert meta.description == "Does things"

    def test_json_frontmatter(self):
        content = '---\n{"name": "json-skill", "description": "JSON format"}\n---\n# Body'
        meta = parse_metadata(content)
        assert meta.name == "json-skill"
        assert meta.description == "JSON format"

    def test_no_frontmatter_uses_fallback(self):
        content = "# Just a body"
        meta = parse_metadata(content, fallback_name="fallback-name")
        assert meta.name == "fallback-name"
        assert meta.description == ""

    def test_quoted_values(self):
        content = '---\nname: "quoted-name"\ndescription: \'quoted desc\'\n---\n'
        meta = parse_metadata(content)
        assert meta.name == "quoted-name"
        assert meta.description == "quoted desc"

    def test_missing_name_uses_fallback(self):
        content = "---\ndescription: something\n---\n"
        meta = parse_metadata(content, fallback_name="dir-name")
        assert meta.name == "dir-name"
        assert meta.description == "something"

    def test_comments_in_yaml(self):
        content = "---\n# a comment\nname: test\ndescription: desc\n---\n"
        meta = parse_metadata(content)
        assert meta.name == "test"
