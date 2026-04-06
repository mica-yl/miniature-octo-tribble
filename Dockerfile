# Use Python 3.12 slim as the base (highly compatible with LangChain & PyMuPDF)
FROM python:3.12-slim-bookworm

# 1. Copy the blazing-fast uv binary directly from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 2. Optimize uv for Docker environments
# Compile bytecode during install for faster app startup times
ENV UV_COMPILE_BYTECODE=1
# Prevent hardlink errors across Docker mount boundaries
ENV UV_LINK_MODE=copy

# 3. Copy ONLY dependency files first
# This is the "magic" step: Docker will cache this layer so rebuilds are 
# instant unless you actually change your pyproject.toml or uv.lock
COPY pyproject.toml uv.lock ./

# 4. Install dependencies via cache mount
# --frozen: strictly respects your uv.lock file
# --no-dev: skips installing dev tools you don't need in production
# --no-install-project: tells uv not to look for the app code yet
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 5. Now, copy your actual application code into the container
COPY . /app

# 6. Install the project itself (links your app into the environment)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 7. Put the uv-managed virtual environment on the system PATH
ENV PATH="/app/.venv/bin:$PATH"

# 8. Start the application 
# (Since you ran `python app.py` locally earlier, we will use that here)
CMD ["python", "app.py"]