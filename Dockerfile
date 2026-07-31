FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM build AS test
RUN pip install --no-cache-dir '.[dev]'
COPY tests ./tests
CMD ["pytest"]

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY --from=build /install /usr/local
COPY --chown=appuser:appuser jobs /app/jobs
COPY --chown=appuser:appuser prompts /app/prompts
RUN mkdir /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 8787
CMD ["python", "-m", "prompt_dispatcher", "serve"]
