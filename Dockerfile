# MCPO On-Demand Bridge Dockerfile
# Python 3.11ベースイメージを使用
FROM python:3.11-slim

# 作業ディレクトリを設定
WORKDIR /app

# システムパッケージの更新と必要なパッケージのインストール
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node.jsのインストール（office-powerpoint-mcp-server用、npx経由）
# Node.js 20.x LTSをインストール
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# uvのインストール（Python製MCPサーバー用、uvx経由）
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

# Pythonの依存関係ファイルをコピー
COPY requirements.txt .

# Python依存パッケージのインストール
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# 設定ディレクトリを作成
RUN mkdir -p /app/config

# 一時ファイル用ディレクトリを作成
RUN mkdir -p /tmp/mcpo-jobs

# ログディレクトリを作成
RUN mkdir -p /var/log/mcpo

# ポート8080を公開
EXPOSE 8080

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:8080/health || exit 1

# アプリケーション起動コマンド
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
