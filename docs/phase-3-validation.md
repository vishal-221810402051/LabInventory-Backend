# Phase 3 Validation

Use the normal safe validation path first. It never performs a billable OpenAI request.

```powershell
docker compose config
docker compose up -d --build db backend
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker compose exec -T backend python -m compileall app tests tools
docker compose exec -T backend pytest -q
docker compose exec -T backend ruff check .
docker compose exec -T backend mypy app tools
.\scripts\validate-phase0.ps1
.\scripts\validate-phase1.ps1
.\scripts\validate-phase2.ps1
.\scripts\validate-phase3.ps1
git diff --check
git status
```

Expected Alembic head:

```text
202607250002 (head)
```

Migration reversibility:

```powershell
docker compose exec -T backend alembic downgrade 202607250001
docker compose exec -T backend alembic upgrade head
```

The default Phase 3 validation script forces safe disabled/unconfigured AI modes and checks:

- Compose config
- DB/backend startup
- Alembic upgrade and one head
- compileall
- Pytest
- Ruff
- Mypy
- Phase 0 endpoints
- `/api/v1/ai/status`
- disabled behavior: `AI_INTERPRETATION_DISABLED`
- unconfigured behavior: `AI_PROVIDER_NOT_CONFIGURED`
- OpenAPI availability
- whitespace in Git diff

It deletes no Docker volumes and makes no live OpenAI request.

Live OpenAI validation is separate:

```powershell
.\scripts\validate-phase3-live.ps1 -ConfirmLiveAi
```

The live script requires `AI_INTERPRETATION_ENABLED=true` and `OPENAI_API_KEY`, warns before use, and makes one billable provider request.
