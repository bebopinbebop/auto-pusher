FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_PROGRESSOR_DATA_DIR=/work/data \
    GIT_PROGRESSOR_DATABASE_URL=sqlite:////work/data/git-progressor.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir '.[openai]' \
    && mkdir -p /work/data \
    && chown -R 10001:10001 /work

USER 10001:10001
WORKDIR /work
ENTRYPOINT ["git-progressor"]
CMD ["--help"]
