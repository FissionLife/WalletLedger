# WalletLedger in a container. Works on Cloud Run, Fly.io, Render, Railway, or your own server.
#
#   docker build -t walletledger .
#   docker run -p 8080:8080 --env-file .env walletledger
#
# On hosts that scale to zero, use webhook mode (USE_WEBHOOK=true) and Postgres (DB_MODE=postgres):
# the container's disk is not kept between runs. See docs/DEPLOYMENT.md.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 MPLBACKEND=Agg

# Dependencies first, so rebuilds after a code change are fast
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Never run as root
RUN useradd --create-home app && chown -R app /app
USER app

# Most hosts pass the port in $PORT (Cloud Run, Render); 8080 otherwise
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uv run --no-sync uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
