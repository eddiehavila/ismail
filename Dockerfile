# ismail MCP server over stdio: docker run -i --rm ismail
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY ismail ./ismail
RUN pip install --no-cache-dir .
WORKDIR /work
ENTRYPOINT ["ismail", "mcp"]
