---
name: skill-creator
description: Create or update skills. Use when designing, structuring, or packaging skills with scripts, references, and assets.
---

# Skill Creator

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained packages that extend the agent's capabilities by providing specialized knowledge, workflows, and tools. They transform the agent from a general-purpose agent into a specialized one equipped with procedural knowledge.

### What Skills Provide

1. Specialized workflows — multi-step procedures for specific domains
2. Tool integrations — instructions for working with specific file formats or APIs
3. Domain expertise — company-specific knowledge, schemas, business logic
4. Bundled resources — scripts, references, and assets for complex tasks

## Core Principles

### Concise is Key

The context window is a shared resource. Only add context the agent doesn't already have. Challenge each piece of information: "Does the agent really need this?" and "Does this justify its token cost?"

### Anatomy of a Skill

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name + description)
│   └── Markdown instructions
└── Bundled Resources (optional)
    ├── scripts/       — executable code
    ├── references/    — documentation for context
    └── assets/        — files used in output
```

### Frontmatter

Write YAML frontmatter with `name` and `description`:
- `name`: The skill name (lowercase, digits, hyphens, max 64 chars)
- `description`: Primary triggering mechanism. Include what the skill does and when to use it.

### Progressive Disclosure

Skills use a three-level loading system:
1. **Metadata** (name + description) — always in context
2. **SKILL.md body** — loaded when skill triggers
3. **Bundled resources** — loaded as needed by the agent

Keep SKILL.md body under 500 lines. Split content into separate reference files when approaching this limit.

## Skill Creation Process

1. Understand the skill with concrete examples
2. Plan reusable resources (scripts, references, assets)
3. Create the skill directory and SKILL.md
4. Implement resources and write instructions
5. Test by using the skill on real tasks
6. Iterate based on real usage

### Naming Conventions

- Use lowercase letters, digits, and hyphens only
- Keep under 64 characters
- Prefer short, verb-led phrases describing the action
- Name the skill folder exactly after the skill name

### Writing Guidelines

- Use imperative/infinitive form in instructions
- Include "when to use" information in the frontmatter description, not in the body
- Keep instructions focused on what another agent instance needs to execute effectively
