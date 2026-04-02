# Workflow Visualizer task runner
# https://github.com/casey/just

# Default: list available recipes
default:
    just --list

# Launch JupyterLab rooted at the project directory
lab:
    uv run jupyter lab --notebook-dir=.

# Run the test suite
test *args:
    uv run pytest {{args}}

# Install all dependencies (including dev)
install:
    uv sync --extra dev

# Run linting
lint:
    uv run ruff check src/ tests/
    uv run black --check src/ tests/
