"""Data models for the skills system."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*$")


class SkillSource(str, Enum):
    """Where a skill was loaded from (highest to lowest priority)."""

    WORKSPACE = "workspace"
    PROJECT = "project"
    GLOBAL = "global"
    BUILTIN = "builtin"


class SkillMetadata(BaseModel):
    """Parsed frontmatter metadata from a SKILL.md file."""

    name: str = ""
    description: str = ""


class SkillInfo(BaseModel):
    """A discovered skill with its location and source tier."""

    name: str
    path: str = ""
    source: SkillSource
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v:
            raise ValueError("name is required")
        if len(v) > MAX_NAME_LENGTH:
            raise ValueError(f"name exceeds {MAX_NAME_LENGTH} characters")
        if not NAME_PATTERN.match(v):
            raise ValueError("name must be alphanumeric with hyphens")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v:
            raise ValueError("description is required")
        if len(v) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"description exceeds {MAX_DESCRIPTION_LENGTH} characters")
        return v


class SearchResult(BaseModel):
    """A single result from a skill registry search."""

    score: float = 0.0
    slug: str = ""
    display_name: str = ""
    summary: str = ""
    version: str = ""
    registry_name: str = ""


class SkillMeta(BaseModel):
    """Metadata about a skill from a registry."""

    slug: str = ""
    display_name: str = ""
    summary: str = ""
    latest_version: str = ""
    is_malware_blocked: bool = False
    is_suspicious: bool = False
    registry_name: str = ""


class InstallResult(BaseModel):
    """Returned by DownloadAndInstall for moderation and user messaging."""

    version: str = ""
    is_malware_blocked: bool = False
    is_suspicious: bool = False
    summary: str = ""
