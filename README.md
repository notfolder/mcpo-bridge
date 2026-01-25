# MCPO On-Demand MCP Bridge

MCPO On-Demand Bridgeは、OpenWebUI + MCPO環境において、PowerPoint等の「ファイル生成系MCPサーバー」を数百人規模で安全に利用可能にするシステムです。

## 概要

本システムは、MCP/MCPOの同期モデルを維持したまま、以下を実現します：

- **マルチユーザー対応**: 数百ユーザーの同時利用
- **リソース分離**: ユーザー間の完全な成果物分離
- **自動ファイル削除**: ガーベジコレクションによる自動クリーンアップ
- **スケーラビリティ**: Nginxロードバランサーとdocker-compose replicasによる水平スケール対応

## 特徴

### Hybrid（ステートフル/ステートレス）プロセスモデル

#### Stateless（ステートレス）モード

- **1リクエスト = 1プロセス**: リクエスト毎にMCPサーバープロセスを起動
- **即座に終了**: 処理完了後は即座にプロセス終了
- **リソース効率**: メモリ常駐を避け、必要時のみリソース消費
- **用途**: ファイルを生成しない読み取り専用ツール向け（例: 検索、計算、データ取得）

#### Stateful（ステートフル）モード（ファイル操作ツール必須）

- **セッション維持**: OpenWebUIからのヘッダ情報（User ID/Chat ID）単位でプロセスとワーキングディレクトリを維持
- **状態保持**: PowerPoint、Excel等の複数リクエスト間での状態保持が必要なサーバーに対応
- **ファイル共有**: 同一セッション内の全リクエストが同じワーキングディレクトリを共有
- **アイドルタイムアウト**: 非アクティブ時は自動的にプロセスを終了
- **Chat単位の分離**: 同一ユーザーでも異なるChat IDなら別セッション（完全分離）

**重要**: ファイルを生成・編集するMCPツール（Excel、PowerPoint等）は**必ずステートフルモード**で設定してください。ステートレスモードでは各リクエストで別のディレクトリが作成されるため、前のリクエストで作成したファイルにアクセスできません。

詳細は[ステートフル機能](#ステートフル機能チャット単位セッション管理)セクションを参照してください。

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

**注意**: 
- 初回起動時、Docker Composeが自動的に`./data/mcpo-jobs`と`./data/mcpo-logs`ディレクトリを作成します（gitignore対象）
- これらのディレクトリが存在しない場合、Dockerのバインドマウント機能により自動的にホスト側に作成されます

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
```json
{
  "mcpServers": {
    "powerpoint": {
      "command": "npx",
      "args": ["-y", "@gongrzhe/office-powerpoint-mcp-server"],
      "env": {
        "NODE_ENV": "production"
      }
    },
    "excel": {
      "command": "uvx",
      "args": ["excel-mcp-server", "stdio"]
    }
  }
}
```

注意事項：
- office-powerpoint-mcp-serverはNode.js製のため、DockerfileでNode.jsのインストールが必要です
- excel-mcp-serverはPython製のため、Dockerfileでuvのインストールが必要です
- npxはNode.jsパッケージ用、uvxはPythonパッケージ用です

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
| MCPO_STATEFUL_ENABLED | true | ステートフル機能の有効化 |
| MCPO_STATEFUL_DEFAULT_IDLE_TIMEOUT | 1800 | ステートフルプロセスのデフォルトアイドルタイムアウト（秒） |
| MCPO_STATEFUL_MAX_PROCESSES_PER_IP | 1 | クライアントIPごとの最大プロセス数 |
| MCPO_STATEFUL_MAX_TOTAL_PROCESSES | 100 | 全体の最大ステートフルプロセス数 |
| MCPO_STATEFUL_CLEANUP_INTERVAL | 300 | ステートフルプロセスのクリーンアップ間隔（秒） |

### ステートフル機能（チャット単位セッション管理）

`MCPO_STATEFUL_ENABLED=true`の場合、ステートフルMCPサーバーのサポートが有効になります。

#### 設計概要

- **セッション識別**: OpenWebUIヘッダ（`X-OpenWebUI-User-Id`、`X-OpenWebUI-Chat-Id`）ベース
  - セッションキー形式: `user:{user_id}:chat:{chat_id}`
  - ヘッダがない場合のフォールバック: `ip:{ip_address}`
- **対象サーバー**: `mcp-servers.json`で`"mode": "stateful"`を指定したサーバー
- **プロセス管理**: Chat IDごとに専用プロセスとワーキングディレクトリを維持し、セッション状態を保持
- **Chat単位の分離**: 同一ユーザーでも異なるChat IDなら別セッション（別プロセス、別ディレクトリ）
- **負荷分散**: Nginxの`hash $hash_key consistent`により、同一Chat IDからのリクエストを同一Bridgeインスタンスにルーティング
- **アイドルタイムアウト**: 指定時間リクエストがない場合、プロセスを自動終了

#### ファイル操作ツールは必ずステートフルモード

**重要**: Excel、PowerPoint等のファイルを生成・編集するMCPツールは**必ずステートフルモード**で設定してください。理由：

1. **ファイル共有の必要性**: create → write → save の複数リクエストで同じファイルにアクセスする必要がある
2. **ステートレスの問題**: 各リクエストで別のディレクトリが作成されるため、前のリクエストで作成したファイルにアクセスできない
3. **ステートフルの利点**: 同じセッション内の全リクエストが同じワーキングディレクトリを共有

#### 設定方法

`config/mcp-servers.json`:
```json
{
  "mcpServers": {
    "powerpoint": {
      "command": "npx",
      "args": ["-y", "@gongrzhe/office-powerpoint-mcp-server"],
      "mode": "stateful",
      "idle_timeout": 1800,
      "max_processes_per_ip": 1,
      "session_persistence": true
    },
    "excel": {
      "command": "uvx",
      "args": ["excel-mcp-server", "stdio"],
      "mode": "stateful",
      "idle_timeout": 3600,
      "max_processes_per_ip": 1,
      "session_persistence": true
    }
  }
}
```

#### 運用上の注意

- **適用環境**: OpenWebUI連携環境（推奨）、プライベートネットワーク、企業ネットワーク
- **ヘッダ転送**: NginxがOpenWebUIからのヘッダを転送する設定が必要（`MCPO_ENABLE_FORWARD_USER_INFO_HEADERS=true`）
- **セキュリティ**: ヘッダ情報は認証情報ではなく、信頼されたネットワーク内での使用を想定
- **負荷集中**: Chat ID単位のconsistent hashingにより特定Bridgeインスタンスに負荷が集中する可能性があります

詳細設計は[docs/detailed-design.md](docs/detailed-design.md)のセクション19を参照してください。

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

**MCPO On-Demand Bridge** - Scalable, Secure MCP Server Bridge with Stateful/Stateless Support and Nginx Integration
