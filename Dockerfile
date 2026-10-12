FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build==1.2.2
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY --from=build /dist /dist

FROM base AS test
WORKDIR /app
RUN pip install "$(ls /dist/*.whl)[test]"
COPY pyproject.toml ./
COPY tests ./tests
CMD ["pytest", "-v"]

FROM base AS runtime
RUN pip install /dist/*.whl && useradd --create-home --uid 1000 app
USER app
EXPOSE 8080
CMD ["inventory-api"]
