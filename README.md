# modpath-cpp

`modpath-cpp` reads `compile_commands.json` and produces a practical C++20 modules migration plan.

## What the MVP analyzes

- Translation units and include usage frequency
- Likely macro-heavy headers (`#define` count)
- Best-effort include cycle detection among project headers
- Migration phases:
  - **P1** header units
  - **P2** named modules
  - **P3** `import std` readiness checks

## Quick start

```bash
# from repo root
./modpath-cpp

# explicit metadata path
./modpath-cpp path/to/compile_commands.json

# machine-readable output for CI
./modpath-cpp path/to/compile_commands.json --json
```

If you install with pip, the same command is available as:

```bash
modpath-cpp path/to/compile_commands.json
```

## Example output (text)

```text
Top migration candidates
1. include/core/math.hpp (includes=3, risk=26/100 low)
   recommendation: P1 header unit candidate

Phased plan
P1) Header units
- Convert include/core/math.hpp to a header unit pilot ...
P2) Named modules
- Prototype named module 'core.math' from include/core/math.hpp
P3) import std readiness
- [warn] C++20 compiler mode coverage: 1 TU(s) are below C++20 or missing -std flag
```

## JSON output shape

```json
{
  "summary": {
    "translation_units": 12,
    "scanned_headers": 47,
    "cycle_header_count": 3
  },
  "candidates": [
    {
      "header": "include/foo/bar.hpp",
      "risk_score": 28,
      "recommendation": "P1 header unit candidate"
    }
  ],
  "phases": {
    "p1_header_units": {"actions": []},
    "p2_named_modules": {"actions": []},
    "p3_import_std_readiness": {"checks": []}
  }
}
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

## CI and PyPI publishing

This repo includes two GitHub Actions workflows:

- **CI** (`.github/workflows/ci.yml`):
  - runs linting (ruff)
  - runs tests on PR/push (Python 3.9/3.11/3.13)
  - runs package coverage on Python 3.11 (threshold: **70%**, adjustable via `COVERAGE_FAIL_UNDER`)
  - uploads `coverage.xml` + text report artifacts
  - builds/checks `dist/*` and smoke-tests the built wheel/CLI
- **Publish** (`.github/workflows/publish-pypi.yml`): publishes to PyPI on `v*` tags (or manual dispatch).

### One-time PyPI setup (recommended: Trusted Publishing)

1. Create the project on PyPI (`modpath-cpp`) if it does not exist yet.
2. In PyPI project settings, add a **Trusted Publisher** for this GitHub repo/workflow.
   - Owner: `gyuro`
   - Repository: `modpath-cpp`
   - Workflow: `publish-pypi.yml`
   - Environment (if prompted): `pypi`

### Release flow

1. Bump `project.version` in `pyproject.toml`.
2. Commit and push to `main`.
3. Create and push a tag matching the version:

```bash
git tag v0.1.1
git push origin v0.1.1
```

The publish workflow validates that tag version == `pyproject.toml` version before uploading.
