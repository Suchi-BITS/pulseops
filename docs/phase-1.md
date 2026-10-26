Phase 0 is complete. Proceed with Phase 1.

Read only the relevant project documentation needed for Phase 1:

- plan.md
- CLAUDE.md
- docs/business-context.md
- docs/data-model.md
- docs/architecture.md
- docs/security.md

Implement the Phase 1 operational foundation.

Scope:

1. Add SQLite persistence.
2. Implement domain models for:
   - Service
   - Incident
   - Log
   - Metric
   - Deployment
   - Repository
   - RepositoryMapping
3. Implement repository/data-access layer.
4. Implement service/business layer.
5. Implement API schemas separately from persistence models.
6. Implement initial incident APIs:
   - POST /incidents
   - GET /incidents
   - GET /incidents/{incident_id}
7. Add deterministic synthetic seed data.
8. Add tests for models, repositories, services, and incident APIs.
9. Keep the implementation deterministic and AI-free.

Constraints:

- Do not add Claude or Anthropic dependencies.
- Do not add Claude Agent SDK.
- Do not add MCP.
- Do not add n8n.
- Do not implement the Incident Agent.
- Do not implement GitHub API integration.
- Do not implement autonomous actions.
- Do not implement production infrastructure.
- Follow the existing architecture and security documents.
- Keep source evidence separate from future AI-generated analysis.
- Use repository/service abstractions so SQLite can later be replaced by PostgreSQL.
- Do not modify the existing Phase 0 behavior unnecessarily.

Before implementation, briefly state the planned changes.

Then implement Phase 1.

Run the test suite when implementation is complete.

Return:
1. What was implemented
2. Files created/changed
3. Test result
4. Any important design decisions
5. Any unresolved issues

Do not repeat the project documentation.