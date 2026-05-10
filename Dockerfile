FROM python:3.11-slim

# System deps + Node.js 22 (for Claude Code CLI)
RUN apt-get update && apt-get install -y curl git && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Claude Code CLI (claude_agent_sdk が内部で呼び出す)
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Python 依存関係を先にインストール（キャッシュ効率化）
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] python-multipart \
    jinja2 pydantic rich anyio \
    pymupdf pillow pillow-heif python-dotenv \
    "claude-agent-sdk>=0.1.0"

# ソースコードをコピー
COPY . .

# 実行時に必要なディレクトリ
RUN mkdir -p output uploads

ENV PYTHONPATH=/app/src
ENV PORT=8080

# claude CLI が ~/.claude/ に書き込むため HOME を明示
ENV HOME=/root

CMD ["sh", "-c", "uvicorn research.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
