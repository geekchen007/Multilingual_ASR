# Repository Guidelines

## Project Structure & Module Organization

This is a Python/Flask multilingual ASR evaluation platform. `app.py` contains the application factory, SQLite access, routes, background evaluation jobs, and account CLI. `providers.py` implements demo and HTTP transcription adapters. Browser templates live in `templates/`; JavaScript and CSS live in `static/`. Integration tests are in `tests/test_app.py`. Consult `SPEC.md`, `IMPLEMENTATION_PLAN.md`, and `docs/` for requirements; `VERIFICATION.md` records verification details.

## Build, Test, and Development Commands

Use Python 3.12+ and install FFmpeg on `PATH`. No separate build step is required. From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python app.py create-user --username developer --role research
.venv\Scripts\python app.py serve
.venv\Scripts\python -m pytest tests -q --basetemp=.test-tmp
```

These commands create an environment, install runtime and test dependencies, create an account interactively, start the server at `http://127.0.0.1:5080`, and run tests. Check FFmpeg availability with `ffmpeg -version`.

## Coding Style & Naming Conventions

Use four-space indentation and PEP 8 conventions. Use `snake_case` for Python functions and variables, `UPPER_CASE` for constants, and `test_` prefixes for tests. Prefer lines under 88 characters, grouped imports, context managers, and narrow exception handling. Add type hints and docstrings for new public interfaces. Match surrounding code and avoid unrelated formatting changes. No formatter or linter configuration is currently provided.

## Testing Guidelines

Use pytest with Flask's test client, temporary data directories, and mocked provider calls. Add focused regression tests for changed behavior, especially authorization, CSRF, blind-result visibility, audio cropping, provider failures, and regression exports. No numeric coverage threshold is configured. Real provider calls and physical microphone recording require separate manual verification.

## Commit & Pull Request Guidelines

Follow the Huawei Cloud LiteOS / Angular Conventional Commits format:

```text
<type>(<scope>): <subject>

<body>

<footer>
```

Allowed types are `feat`, `fix`, `docs`, `style`, `refactor`, `test`, and `chore`. Keep the subject imperative, lowercase, under 50 characters, and without a trailing period. Use the body to explain why the change is needed and what behavior changes. Reserve the footer for `BREAKING CHANGE` or issue references. Keep each commit focused on one reviewable purpose. Pull requests should explain behavior changes, link relevant issues or specification sections, report validation results, and include screenshots for UI changes.

## Security & Configuration

Keep API keys in server environment variables; use `providers.example.json` as the configuration template. Never commit credentials, recordings, or runtime `data/`. Back up the entire data directory, including SQLite and `session.key`. Use `ASR_DATA_DIR` and `ASR_PROVIDERS` for custom paths. Preserve single-process deployment and account isolation.
