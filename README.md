# MCPO On-Demand MCP Bridge

MCPO On-Demand Bridgeは、OpenWebUI + MCPO環境において、PowerPoint等の「ファイル生成系MCPサーバー」を数百人規模で安全に利用可能にするシステムです。

## 概要

本システムは、MCP/MCPOの同期モデルを維持したまま、以下を実現します：

- **マルチユーザー対応**: 数百ユーザーの同時利用
- **リソース分離**: ユーザー間の完全な成果物分離
- **自動ファイル削除**: ガーベジコレクションによる自動クリーンアップ
- **スケーラビリティ**: Nginxロードバランサーとdocker-compose replicasによる水平スケール対応

## 特徴

### Ephemeral（短命）プロセスモデル

- **1リクエスト = 1プロセス**: リクエスト毎にMCPサーバープロセスを起動
- **即座に終了**: 処理完了後は即座にプロセス終了
- **リソース効率**: メモリ常駐を避け、必要時のみリソース消費

### セキュアなファイル管理

- **ジョブ単位の分離**: UUID v4による一意なジョブディレクトリ
- **自動削除**: ガーベジコレクションによる定期的なファイル削除

### Nginx統合アーキテクチャ

- **効率的なファイル配信**: Nginxによる高速な静的ファイル配信
- **ロードバランシング**: 複数Bridgeインスタンスへの自動負荷分散
- **透過的なプロキシ**: MCP/MCPOリクエストの透過的な転送

### Docker完全対応

- **OpenWebUIと統合**: docker-compose.ymlで同時起動
- **簡単デプロイ**: docker-compose up -dで即座に利用開始
- **簡単スケール**: replicas設定で複数インスタンス起動
- **バインドマウント**: ローカルディレクトリを直接マウント（gitignore対象）

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
   +-- Static Files ----> Bind Mount (./data/mcpo-jobs)


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
Temporary File Store (Bind Mount ./data/)
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

**注意**: 初回起動時、`./data/mcpo-jobs`と`./data/mcpo-logs`ディレクトリが自動作成されます（gitignore対象）。

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
7. 環境変数設計
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

## 設定

### MCP設定ファイル

`config/mcp-servers.json`でMCPサーバーを定義します。Claude等で使用される標準的なJSON形式に準拠しています。

設定ファイルはソースコード配下のconfigディレクトリに配置され、サンプルが`config/mcp-servers.json.example`として用意されています。

デフォルトでは[Office-PowerPoint-MCP-Server](https://github.com/GongRzhe/Office-PowerPoint-MCP-Server)を使用する設定例が含まれています。

設定例の構造:
```
{
  "mcpServers": {
    "powerpoint": {
      "command": "uvx",
      "args": ["office-powerpoint-mcp-server"]
    }
  }
}
```

注意：Dockerfileでuvコマンドをインストールする必要があります。

### 環境変数

docker-compose.ymlで以下の環境変数を設定できます:

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| MCPO_BASE_URL | http://nginx | ダウンロードURL生成用ベースURL |
| MCPO_CONFIG_FILE | /app/config/mcp-servers.json | MCP設定ファイルパス |
| MCPO_JOBS_DIR | /tmp/mcpo-jobs | ジョブディレクトリルート |
| MCPO_MAX_CONCURRENT | 16 | 最大同時実行プロセス数 |
| MCPO_TIMEOUT | 300 | プロセスタイムアウト（秒） |
| MCPO_LOG_LEVEL | INFO | ログレベル |

### ディレクトリ構造

プロジェクトのディレクトリ構造:

```
mcpo-bridge/
├── config/
│   ├── mcp-servers.json          # MCP設定（要作成）
│   └── mcp-servers.json.example  # サンプル設定
├── nginx/
│   ├── nginx.conf                # Nginx設定
│   └── conf.d/
│       └── default.conf          # サイト設定
├── docs/
│   ├── detailed-design.md        # 詳細設計書
│   └── docker-deployment.md      # Docker設計書
├── data/                         # バインドマウント（gitignore）
│   ├── mcpo-jobs/                # 一時ファイル
│   └── mcpo-logs/                # ログファイル
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## API

### MCP/MCPOエンドポイント（複数サーバータイプ対応）

各MCPサーバータイプごとに独立したエンドポイント:

#### MCPOエンドポイント

- **URL**: `http://localhost/mcpo/{server-type}`
- 例：`/mcpo/powerpoint`
- **メソッド**: POST
- **形式**: JSON-RPC 2.0

#### MCPエンドポイント

- **URL**: `http://localhost/mcp/{server-type}`
- 例：`/mcp/powerpoint`
- **メソッド**: POST
- **形式**: MCP標準プロトコル

### ヘルスチェックエンドポイント

- **URL**: `http://localhost/health`（Nginx経由）
- **メソッド**: GET
- **レスポンス**: JSON形式のステータス情報

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

ローカルログファイルから直接確認:
```bash
ls -la ./data/mcpo-logs/
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

### データディレクトリ管理

一時ファイルとログは`./data`ディレクトリに保存されます:

- `./data/mcpo-jobs/`: 生成されたファイルとメタデータ
- `./data/mcpo-logs/`: アプリケーションログ

これらのディレクトリは`.gitignore`で除外されているため、Gitにコミットされません。

#### ディスク容量管理

ガーベジコレクションは定期的に古いファイルを削除しますが、手動でもクリーンアップ可能:

```bash
# 古いジョブディレクトリを削除
find ./data/mcpo-jobs -type d -mtime +1 -exec rm -rf {} +
```

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
ls -la ./data/mcpo-jobs/
```

3. ファイルが生成されているか確認

### スケーリングが機能しない

Nginxアップストリーム確認:
```bash
docker-compose exec nginx cat /etc/nginx/conf.d/default.conf
```

Bridgeインスタンス数確認:
```bash
docker-compose ps mcpo-bridge
```

### データディレクトリの権限エラー

権限を確認:
```bash
ls -ld ./data/
```

必要に応じて権限を修正:
```bash
chmod 755 ./data
chmod 755 ./data/mcpo-jobs ./data/mcpo-logs
```

## セキュリティ

- Dockerコンテナはroot権限で実行（シンプル化）
- ジョブディレクトリはUUID v4で一意に識別
- ダウンロードURLは推測困難なUUID使用
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
