# Contributing

Contributions of docs, tests, or code are welcome.

## Workflow

1. Fork the repo
2. Clone your fork (`git clone <your_fork_url>`)
3. Create a branch (`git checkout -b my_branch`)
4. Install dependencies: `uv sync`
5. Make your changes
6. Run the [verification pipeline](#verification-pipeline) and fix any issues
7. Commit using [Conventional Commits](#commit-style)
8. Push your branch (`git push origin my_branch`)
9. Open a [Pull Request](https://github.com/Solganis/docopt2/pulls)

Read more about how pulls work on GitHub's [About pull requests](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests) page.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) as the package manager

## Verification pipeline

Run all checks before submitting a PR. Every step must pass.

```bash
# lint
uv run ruff check src tests

# format
uv run ruff format --check src tests

# type check
uv run ty check src/docopt2

# tests with coverage (gated at 100%, line and branch)
uv run pytest
```

CI requires 100% code coverage (line and branch); a PR that drops below it fails. It also runs
`mypy --strict` and `pyright` on the typed surface, across Python 3.10 - 3.15.

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, etc.

## Tests

Write tests for every new feature or bug fix. The suite runs a differential check against the
original docopt as an oracle, so behavior stays a compatible superset.
