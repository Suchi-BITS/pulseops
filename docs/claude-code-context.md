# PulseOps — Claude Code Context Strategy

## Source of Truth

Claude Code should use repository files as persistent project context.

- `CLAUDE.md` — persistent behavior and engineering rules.
- `project-plan.md` — overall roadmap.
- `docs/` — detailed architecture and domain knowledge.
- `docs/phases/` — current implementation contract.
- `ontology/pulseops.ttl` — semantic source artifact.

## Interaction Pattern

Prefer short task prompts:

```text
Read docs/phases/<current-phase>.md and implement it.
```

The phase document should reference stable architecture documents instead of duplicating them.

## Context Discipline

- Do not paste large architecture documents into chat.
- Do not ask Claude to repeat documentation.
- Use fresh conversations for major phases when useful.
- Keep implementation requests scoped to one phase.
- Store durable decisions in files rather than relying on chat history.
