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
# Node.js 20.x LTSをインストール（Debian公式リポジトリから）
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Quarto CLIのインストール（quarto_mcp用）
# マルチアーキテクチャ対応（amd64/arm64）
# TARGETARCHを使用してアーキテクチャに応じたパッケージをダウンロード
ARG TARGETARCH
ENV QUARTO_VERSION=1.4.555
RUN apt-get update && apt-get install -y gdebi-core && \
    case ${TARGETARCH} in \
        amd64) QUARTO_ARCH=amd64 ;; \
        arm64) QUARTO_ARCH=arm64 ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
    esac && \
    curl -LO https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${QUARTO_ARCH}.deb && \
    gdebi -n quarto-${QUARTO_VERSION}-linux-${QUARTO_ARCH}.deb && \
    rm quarto-${QUARTO_VERSION}-linux-${QUARTO_ARCH}.deb && \
    rm -rf /var/lib/apt/lists/*

# uvのインストール（Python製MCPサーバー用、uvx経由）
RUN pip install --no-cache-dir uv

# よく使うMCPサーバーを事前にキャッシュ（初回起動時の遅延を削減）
# uvのツールディレクトリを明示的に設定
ENV UV_TOOL_DIR=/root/.local/share/uv/tools
ENV UV_TOOL_BIN_DIR=/root/.local/bin
RUN uv tool install office-powerpoint-mcp-server && \
    ln -sf /root/.local/bin/ppt_mcp_server /usr/local/bin/ppt_mcp_server || true

# Quarto MCPサーバーをキャッシュ
RUN uvx --from git+https://github.com/notfolder/quarto_mcp quarto-mcp --help || true

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
