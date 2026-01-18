# MCPO On-Demand MCP Bridge

MCPO On-Demand Bridgeは、OpenWebUI + MCPO環境において、PowerPoint等の「ファイル生成系MCPサーバー」を数百人規模で安全に利用可能にするシステムです。

## 概要

本システムは、MCP/MCPOの同期モデルを維持したまま、以下を実現します：

- **マルチユーザー対応**: 数百ユーザーの同時利用
- **リソース分離**: ユーザー間の完全な成果物分離
- **一時ファイルの確実な削除**: ガーベジコレクションによる自動クリーンアップ
- **スケーラビリティ**: Nginxロードバランサーとdocker-compose replicasによる水平スケール対応
- **監視機能**: Prometheusメトリクスによる運用監視

## 特徴

### Ephemeral（短命）プロセスモデル

- **1リクエスト = 1プロセス**: リクエスト毎にMCPサーバープロセスを起動
- **即座に終了**: 処理完了後は即座にプロセス終了
- **リソース効率**: メモリ常駐を避け、必要時のみリソース消費

### セキュアなファイル管理

- **ジョブ単位の分離**: UUID v4による一意なジョブディレクトリ
- **有効期限付きURL**: ダウンロードURLは自動的に期限切れ
- **自動削除**: ガーベジコレクションによる定期的なファイル削除

### Nginx統合アーキテクチャ

- **効率的なファイル配信**: Nginxによる高速な静的ファイル配信
- **ロードバランシング**: 複数Bridgeインスタンスへの自動負荷分散
- **透過的なプロキシ**: MCP/MCPOリクエストの透過的な転送

### Docker完全対応

- **OpenWebUIと統合**: docker-compose.ymlで同時起動
- **簡単デプロイ**: docker-compose up -dで即座に利用開始
- **簡単スケール**: replicas設定で複数インスタンス起動
- **環境の一貫性**: 開発環境と本番環境で同一構成

## アーキテクチャ

```
User Browser
   |
   | HTTPS
   v
Nginx (Load Balancer & File Server)
   |
   +-- Load Balancing --> MCPO Bridge Instance 1
   |                      MCPO Bridge Instance 2
   |                      MCPO Bridge Instance N
   |
   +-- Static Files ----> Shared Volume (/tmp/mcpo-jobs)


OpenWebUI (Docker Container)
   |
   | MCP / MCPO (JSON-RPC over HTTP)
   v
Nginx Load Balancer
   |
   v
MCPO On-Demand Bridge (Docker Container x N)
   |
   | per-request subprocess
   v
Ephemeral MCP Server Process
   |
   | ファイル生成 (pptx, pdf, etc.)
   v
Temporary File Store (Shared Volume)
   |
   | HTTPS download via Nginx
   v
User Browser
```

## クイックスタート

### 必要環境

- Docker Engine 20.10+
- Docker Compose 2.0+

### 起動手順

1. リポジトリをクローン:
```bash
git clone https://github.com/notfolder/mcpo-bridge.git
cd mcpo-bridge
```

2. MCP設定ファイルを作成:
```bash
cp config/mcp-servers.json.example config/mcp-servers.json
# config/mcp-servers.jsonを編集して使用するMCPサーバーを定義
```

3. Docker Composeで起動:
```bash
docker-compose up -d
```

4. ブラウザでOpenWebUIにアクセス:
```
http://localhost:80
```

### 停止方法

```bash
docker-compose down
```

## ドキュメント

詳細な設計仕様と運用ガイドは以下のドキュメントを参照してください：

- **[詳細設計書](docs/detailed-design.md)**: システム全体の詳細設計仕様（日本語）
- **[Dockerデプロイメント設計](docs/docker-deployment.md)**: Docker化とデプロイに関する詳細仕様（日本語）

### ドキュメント構成

#### 詳細設計書の内容

1. システム概要
2. 要求仕様（機能要件・非機能要件）
3. アーキテクチャ設計（Nginx統合含む）
4. コンポーネント詳細設計
5. 処理フロー設計
6. API仕様設計（MCP/MCPO分離、複数サーバータイプ対応）
7. データ設計
8. セキュリティ設計
9. スケーラビリティ設計（docker-compose replicas）
10. ガーベジコレクション設計
11. エラーハンドリング設計
12. Docker化設計
13. Docker Compose設計
14. MCP設定ファイル仕様
15. Nginx設定設計
16. 運用設計
17. テスト設計

#### Dockerデプロイメント設計の内容

1. Docker化の概要
2. Dockerfile設計
3. Docker Compose設計
4. Nginx統合設計
5. 開発環境と本番環境の差異
6. 運用コマンド
7. セキュリティ考慮事項
8. モニタリングと監視
9. スケーリング戦略

## 設定

### MCP設定ファイル

`config/mcp-servers.json`でMCPサーバーを定義します。Claude等で使用される標準的なJSON形式に準拠しています。

設定ファイルはソースコード配下のconfigディレクトリに配置され、サンプルが`config/mcp-servers.json.example`として用意されています。

設定例の構造:
```
{
  "mcpServers": {
    "server-name": {
      "command": "実行コマンド",
      "args": ["引数1", "引数2", "__WORKDIR__"],
      "env": {
        "環境変数名": "値"
      }
    }
  }
}
```

特殊トークン:
- `__WORKDIR__`: ジョブ作業ディレクトリパスに置換
- `__JOB_ID__`: ジョブUUIDに置換

### 環境変数

docker-compose.ymlで以下の環境変数を設定できます:

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| MCPO_BASE_URL | http://nginx | ダウンロードURL生成用ベースURL |
| MCPO_CONFIG_FILE | /app/config/mcp-servers.json | MCP設定ファイルパス |
| MCPO_JOBS_DIR | /tmp/mcpo-jobs | ジョブディレクトリルート |
| MCPO_FILE_EXPIRY | 3600 | ファイル有効期限（秒） |
| MCPO_MAX_CONCURRENT | 16 | 最大同時実行プロセス数 |
| MCPO_TIMEOUT | 300 | プロセスタイムアウト（秒） |
| MCPO_LOG_LEVEL | INFO | ログレベル |

## API

### MCP/MCPOエンドポイント（複数サーバータイプ対応）

各MCPサーバータイプごとに独立したエンドポイント:

#### MCPOエンドポイント

- **URL**: `http://localhost/mcpo/{server-type}`
- 例：`/mcpo/pptx-generator`、`/mcpo/pdf-generator`
- **メソッド**: POST
- **形式**: JSON-RPC 2.0

#### MCPエンドポイント

- **URL**: `http://localhost/mcp/{server-type}`
- 例：`/mcp/pptx-generator`、`/mcp/pdf-generator`
- **メソッド**: POST
- **形式**: MCP標準プロトコル

### ヘルスチェックエンドポイント

- **URL**: `http://localhost/health`（Nginx経由）
- **メソッド**: GET
- **レスポンス**: JSON形式のステータス情報

### メトリクスエンドポイント

- **URL**: `http://localhost/metrics`
- **メソッド**: GET
- **レスポンス**: Prometheus形式
- **説明**: 全Bridgeインスタンスのメトリクスを集約

### ファイルダウンロードエンドポイント（Nginx経由）

- **URL**: `http://localhost/files/{job-uuid}/{filename}`
- **メソッド**: GET
- **レスポンス**: ファイルバイナリ
- **説明**: Nginxが直接ファイルを配信

## 運用

### ログ確認

全サービスのログ:
```bash
docker-compose logs -f
```

MCPO Bridgeのみ:
```bash
docker-compose logs -f mcpo-bridge
```

Nginxのみ:
```bash
docker-compose logs -f nginx
```

ログボリュームから直接確認:
```bash
docker-compose exec mcpo-bridge ls -la /var/log/mcpo
```

### サービス再起動

```bash
docker-compose restart mcpo-bridge
```

### 設定更新

1. `config/mcp-servers.json`を編集
2. サービス再起動:
```bash
docker-compose restart mcpo-bridge
```

### スケールアウト

docker-compose.ymlのreplicas設定を変更:
```yaml
services:
  mcpo-bridge:
    deploy:
      replicas: 5  # インスタンス数を変更
```

適用:
```bash
docker-compose up -d
```

Nginxが自動的に新しいインスタンスをロードバランシング対象に追加します。

## 監視

### Prometheusメトリクス

メトリクスエンドポイント:
```bash
curl http://localhost/metrics
```

### 主要メトリクス

- `mcpo_requests_total`: 総リクエスト数
- `mcpo_request_duration_seconds`: リクエスト処理時間
- `mcpo_requests_in_progress`: 処理中のリクエスト数
- `mcpo_processes_started_total`: 起動したプロセス総数
- `mcpo_jobs_active`: アクティブなジョブ数
- `mcpo_disk_usage_bytes`: ディスク使用量

### Grafanaダッシュボード

Prometheusと連携してGrafanaダッシュボードで可視化可能。

## トラブルシューティング

### コンテナが起動しない

ログを確認:
```bash
docker-compose logs mcpo-bridge
docker-compose logs nginx
```

ヘルスチェック確認:
```bash
curl http://localhost/health
```

### ファイルがダウンロードできない

1. Nginxログ確認:
```bash
docker-compose logs nginx
```

2. ジョブディレクトリの確認:
```bash
docker-compose exec mcpo-bridge ls -la /tmp/mcpo-jobs
```

3. 有効期限の確認（デフォルト1時間）

### スケーリングが機能しない

Nginxアップストリーム確認:
```bash
docker-compose exec nginx cat /etc/nginx/conf.d/default.conf
```

Bridgeインスタンス数確認:
```bash
docker-compose ps mcpo-bridge
```

## セキュリティ

- Dockerコンテナはroot権限で実行（シンプル化）
- ジョブディレクトリはUUID v4で一意に識別
- ダウンロードURLは推測困難なUUID使用
- 有効期限付きファイルアクセス
- 内部ネットワーク分離
- 入力検証はMCPサーバーに委譲
- Nginxによる外部公開制御

## ライセンス

（ライセンス情報を記載）

## コントリビューション

（コントリビューションガイドラインを記載）

## サポート

問題が発生した場合は、GitHubのIssueで報告してください。

---

**MCPO On-Demand Bridge** - Scalable, Secure, and Stateless MCP Server Bridge with Nginx Integration
