FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --create-home spectrum && mkdir -p /app/.work && chown -R spectrum:spectrum /app
USER spectrum
ENV PYTHONUNBUFFERED=1
CMD ["spectrum", "run"]
