# Project Guidelines

## DRY — Don't Repeat Yourself

- Never duplicate logic. Reuse existing functions, utilities, and patterns.
- Before writing new code, search the codebase for existing implementations.
- Extract shared logic into well-named, reusable modules.

## File Size Limit

- **Maximum 300 lines per file.** No exceptions.
- When a file exceeds 300 lines, split it into a well-named folder with clearly named sub-files.
- Folder and file names must be descriptive and reflect their purpose (e.g., `providers/claude.py`, not `utils2.py`).

## No Quick Wins — Future-Proof Only

- Never write throwaway or "just make it work" code.
- Every solution must be stable, maintainable, and future-proof.
- Prefer long-term correctness over short-term speed.
- Design for extensibility — new providers, models, or features should slot in cleanly.

## Best Practices

- Follow Python and FastAPI best practices at all times.
- Use type hints, Pydantic models, and async patterns correctly.
- Write clean, readable code with clear intent.
- Keep functions focused — single responsibility.

## Latest Libraries & Versions

- Always use the **latest stable versions** of all libraries.
- **Use context7** MCP tool to look up current documentation before writing code that depends on a library.
- Do not rely on memorized or outdated API signatures — verify with context7.

## Documentation & ReDoc Sync

- When adding, updating, or removing an endpoint, update the **FastAPI route metadata** (summary, description, response_model, tags) so `/docs` and `/redoc` stay accurate.
- When changing request/response shapes, update the corresponding **Pydantic models** in `models.py` — ReDoc auto-generates from these.
- When adding a new provider or integration, update the `API_DESCRIPTION` in `service.py` and the **README.md** usage section.
- After any API-surface change, open `/redoc` locally and verify the docs render correctly before considering the task done.

## Test Coverage

- Every new endpoint or public method **must** have at least one test before the task is complete.
- When modifying an existing endpoint's behavior, update the corresponding tests to match.
- New providers require: a fake CLI branch in `tests/fakes/fake_cli.py`, a config section in `conftest.py`, and a dedicated test in `test_api.py`.
- Run `pytest` and confirm all tests pass before finishing any change.

## README Maintenance

- Keep `README.md` in sync with the live API surface — endpoints, providers, models, and config options.
- When a provider is added or removed, update the provider table and config examples.
- Usage examples in the README must be copy-pasteable and correct.

## Don't Assume — Ask

- If requirements are ambiguous, **ask** before implementing.
- If you're unsure about a design decision, **ask** before committing to it.
- Use **context7** to verify library APIs, patterns, and best practices rather than guessing.
- Never assume a function exists or an API works a certain way — look it up.
