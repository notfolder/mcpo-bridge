# MCPO On-Demand Bridge - Docker デプロイメント設計書

## 1. Docker化の概要

### 1.1 目的

MCPO On-Demand BridgeをDocker化し、OpenWebUIと連携させることで、以下を実現する：

- 環境の再現性確保
- 依存関係の分離
- デプロイの簡易化
- 開発環境と本番環境の統一

### 1.2 Docker構成の特徴

- OpenWebUIとMCPO Bridgeを単一のDocker Composeで管理
- コンテナ間通信は専用Dockerネットワーク経由
- 一時ファイルはDocker Volumeで管理
- 設定ファイルはマウント経由で注入

## 2. Dockerfile設計

### 2.1 ベースイメージ選定

#### 選定基準

- 公式Pythonイメージを使用（セキュリティ・安定性）
- Python 3.11以上（最新安定版）
- uvコマンドをインストールしてuvxを利用可能に

#### 採用イメージ

- ベース：python:3.11
- uvインストール：curlコマンドでインストール

### 2.2 ビルド構成

#### シンプルな単一ステージビルド

目的：シンプルで理解しやすいDockerfile

実施内容：
- ベースイメージから直接構築
- uvコマンドインストール
- Pythonパッケージインストール
- アプリケーションコード配置

### 2.3 ディレクトリ構造

コンテナ内ディレクトリ配置：

```
/app/
  ├── main.py                 # アプリケーションエントリーポイント
  ├── requirements.txt        # Python依存パッケージ
  ├── config/                 # 設定ファイルディレクトリ（マウント）
  │   └── mcp-servers.json    # MCPサーバー定義
  └── src/                    # ソースコードディレクトリ
      ├── api/                # APIエンドポイント
      ├── core/               # コアロジック
      ├── models/             # データモデル
      └── utils/              # ユーティリティ

/tmp/mcpo-jobs/             # 一時ファイル作業領域（Volume）
```

### 2.4 依存パッケージ管理

#### Python依存パッケージ

requirements.txtで管理する主要パッケージ：

- FastAPI：Webフレームワーク
- Uvicorn：ASGIサーバー
- Pydantic：データバリデーション
- aiofiles：非同期ファイルI/O
- python-multipart：ファイルアップロード対応

#### システムパッケージ

実行時に必要な最小限のパッケージ：

- curl：ヘルスチェック用、uvインストール用
- ca-certificates：HTTPS通信用
- uv：uvxコマンドでMCPサーバーを起動するために必要

### 2.5 レイヤー最適化

#### キャッシュ効率化

レイヤー構成順序：

1. システムパッケージ更新（変更頻度：低）
2. Python依存パッケージインストール（変更頻度：中）
3. アプリケーションコードコピー（変更頻度：高）

### 2.6 .dockerignore活用

ビルドコンテキストから除外するファイル：

- .git ディレクトリ
- テストファイル
- ドキュメント（docs配下）
- 一時ファイル（__pycache__、*.pyc）
- 開発環境設定（.vscode、.ideaなど）

### 2.7 ヘルスチェック組み込み

#### Dockerfileでのヘルスチェック定義

定義内容：
- コマンド：curl -f http://localhost:8080/health
- 間隔：30秒
- タイムアウト：10秒
- リトライ回数：3回
- 開始遅延：10秒

#### ヘルスチェックの意義

- コンテナ状態監視
- 依存関係制御（depends_on condition: service_healthy）
- オーケストレーター連携（Kubernetes Liveness/Readiness）

## 3. Docker Compose設計

### 3.1 サービス構成

#### OpenWebUIサービス

役割：ユーザーインターフェース提供

設定項目：
- コンテナ名：openwebui
- イメージ：公式OpenWebUIイメージ
- ポート公開：ホスト3000番→コンテナ8080番
- ボリューム：永続データ保存用
- 環境変数：MCPエンドポイント指定
- ネットワーク：mcpo-network接続
- 依存関係：mcpo-bridge healthyまで待機
- 再起動ポリシー：unless-stopped

#### MCPO Bridgeサービス

役割：MCPリクエスト処理とMCPサーバー管理

設定項目：
- コンテナ名：mcpo-bridge
- ビルド：ローカルDockerfile使用
- ポート公開：ホスト8080番→コンテナ8080番
- ボリューム：一時ファイル、設定ファイル
- 環境変数：Bridge動作設定
- ネットワーク：mcpo-network接続
- ヘルスチェック：有効
- 再起動ポリシー：unless-stopped

### 3.2 ボリューム設計詳細

#### openwebui-dataボリューム

用途：OpenWebUIの永続データ保存

内容：
- ユーザー設定
- チャット履歴
- モデル設定
- その他アプリケーションデータ

管理：
- Dockerが自動管理
- バックアップ推奨

#### mcpo-jobsボリューム

用途：MCPO Bridgeの一時ファイル保存

内容：
- ジョブディレクトリ（/tmp/mcpo-jobs/{job-uuid}/）
- 生成ファイル
- メタデータ
- リクエスト・レスポンスログ

管理：
- ガーベジコレクションにより自動削除
- 定期的なバックアップは不要

#### mcpo-configボリューム

用途：MCP設定ファイル配置

内容：
- mcp-servers.json
- その他設定ファイル

管理：
- 読み取り専用マウント
- 変更時はコンテナ再起動必要

### 3.3 ネットワーク設計詳細

#### mcpo-networkネットワーク

タイプ：bridge（デフォルト）

特徴：
- コンテナ間通信専用
- サービス名でDNS解決
- 外部から直接アクセス不可（OpenWebUI経由）

通信フロー：
1. ユーザー → OpenWebUI（ポート3000）
2. OpenWebUI → MCPO Bridge（mcpo-network経由、内部）
3. MCPO Bridge → MCPサーバープロセス（同一コンテナ内）
4. MCPO Bridge → ユーザー（ダウンロードURL、ポート8080経由）

セキュリティ：
- 内部通信は暗号化なし（同一ホスト前提）
- 外部公開はOpenWebUIのみ
- Bridge APIへの直接アクセス制限

### 3.4 環境変数設計詳細

#### OpenWebUI環境変数

必須変数：
- OPENAI_API_BASE：MCPOエンドポイントURL
  - 設定値：http://mcpo-bridge:8080/mcp
  - 説明：MCPリクエスト送信先を指定

オプション変数：
- WEBUI_AUTH：認証有効化フラグ
  - 設定値：false（開発環境）、true（本番環境）
- その他OpenWebUI固有設定

#### MCPO Bridge環境変数

必須変数：
- MCPO_BASE_URL：ダウンロードURL生成用ベースURL
  - 設定値：http://mcpo-bridge:8080
  - 説明：外部からアクセス可能なBridgeのURL

- MCPO_CONFIG_FILE：MCP設定ファイルパス
  - 設定値：/app/config/mcp-servers.json
  - 説明：MCPサーバー定義ファイルの場所

オプション変数：
- MCPO_JOBS_DIR：ジョブディレクトリルートパス
  - デフォルト：/tmp/mcpo-jobs
  
- MCPO_FILE_EXPIRY：ファイル有効期限（秒）
  - デフォルト：3600（1時間）
  
- MCPO_MAX_CONCURRENT：最大同時実行プロセス数
  - デフォルト：CPUコア数×4
  - 推奨：16（4コアCPU想定）
  
- MCPO_TIMEOUT：MCPサーバータイムアウト（秒）
  - デフォルト：300（5分）
  
- MCPO_LOG_LEVEL：ログレベル
  - デフォルト：INFO
  - 選択肢：DEBUG、INFO、WARNING、ERROR、CRITICAL

### 3.5 起動順序制御詳細

#### depends_on設定

OpenWebUIサービスの依存関係：

```
depends_on:
  mcpo-bridge:
    condition: service_healthy
```

動作：
- mcpo-bridgeがhealthy状態になるまでOpenWebUIは起動しない
- ヘルスチェックで判定
- タイムアウトなし（healthy確認まで待機）

#### 起動シーケンス詳細

1. docker-compose up 実行
2. ネットワーク「mcpo-network」作成
3. ボリューム作成（初回のみ）
4. mcpo-bridgeコンテナ起動
5. mcpo-bridge内でアプリケーション起動
6. ヘルスチェック開始（10秒後）
7. ヘルスチェック成功（healthy状態）
8. openwebuiコンテナ起動
9. openwebui内でアプリケーション起動
10. 全サービス利用可能

#### 障害時の動作

- mcpo-bridgeがunhealthy状態の場合
  - OpenWebUIは起動しない
  - mcpo-bridgeの再起動ポリシーが動作
  - healthy復帰後にOpenWebUI起動

- OpenWebUI起動失敗の場合
  - mcpo-bridgeは稼働継続
  - OpenWebUIの再起動ポリシーが動作

### 3.6 再起動ポリシー

#### unless-stoppedポリシー

採用理由：
- 異常終了時の自動復旧
- ホスト再起動時の自動起動
- 手動停止時は再起動しない

動作：
- コンテナ異常終了時：自動再起動
- Docker daemon再起動時：自動再起動
- docker-compose stop実行時：再起動しない

#### 代替ポリシー（参考）

開発環境：
- no：再起動なし（デバッグ容易）
- on-failure：異常終了時のみ再起動

本番環境：
- unless-stopped：推奨
- always：常に再起動（Docker停止時も）

## 4. 開発環境と本番環境の差異

### 4.1 開発環境設定

#### ボリュームマウント

バインドマウント活用：
- ./config:/app/config：設定ファイル編集容易
- ./src:/app/src：コードホットリロード（オプション）
- ./logs:/app/logs：ログ確認容易

#### ポート公開

すべてのポートをホストに公開：
- OpenWebUI：3000
- MCPO Bridge：8080（直接アクセス可能）

#### ログレベル

- MCPO_LOG_LEVEL=DEBUG
- 詳細なデバッグ情報出力

#### 認証

- WEBUI_AUTH=false
- 開発効率優先

### 4.2 本番環境設定

#### ボリュームマウント

名前付きボリュームのみ：
- mcpo-config：設定ファイル（読み取り専用）
- バインドマウント不使用（セキュリティ）

#### ポート公開

必要最小限：
- OpenWebUI：3000のみ
- MCPO Bridge：内部のみ（ホストに非公開）

#### ログレベル

- MCPO_LOG_LEVEL=INFO
- 必要な情報のみ記録

#### 認証

- WEBUI_AUTH=true
- ユーザー認証必須

#### TLS/SSL

- リバースプロキシ（nginx）経由でTLS終端
- 証明書管理（Let's Encrypt等）

### 4.3 docker-compose.override.yml活用

#### 開発環境用オーバーライド

ファイル名：docker-compose.override.yml

用途：
- 開発環境固有設定の分離
- 本番設定への影響防止
- バージョン管理除外可能

適用方法：
- docker-compose upで自動適用
- -f オプションで明示的指定も可能

## 5. 運用コマンド

### 5.1 初回起動

#### 準備

1. 設定ファイル作成：
   - config/mcp-servers.jsonを作成
   - サンプルをコピーして編集

2. 環境変数確認：
   - docker-compose.yml内の環境変数調整
   - 必要に応じて.envファイル作成

#### 起動

バックグラウンド起動：
- コマンド：docker-compose up -d
- 動作：デーモンモードで起動
- 確認：docker-compose ps

フォアグラウンド起動：
- コマンド：docker-compose up
- 動作：ログをリアルタイム表示
- 終了：Ctrl+C

初回ビルド付き起動：
- コマンド：docker-compose up -d --build
- 動作：イメージビルド後に起動

### 5.2 停止・再起動

#### 停止

一時停止：
- コマンド：docker-compose stop
- 動作：コンテナ停止（削除なし）
- データ：保持

完全停止：
- コマンド：docker-compose down
- 動作：コンテナ停止＋削除
- データ：ボリュームは保持

ボリューム含め削除：
- コマンド：docker-compose down -v
- 注意：全データ削除

#### 再起動

全サービス再起動：
- コマンド：docker-compose restart

特定サービスのみ：
- コマンド：docker-compose restart mcpo-bridge

設定変更後の再起動：
- コマンド：docker-compose up -d
- 動作：変更検出して再作成

### 5.3 ログ確認

#### 全サービスログ

リアルタイム追跡：
- コマンド：docker-compose logs -f

過去ログ表示：
- コマンド：docker-compose logs
- オプション：--tail=100（最新100行）

#### 特定サービスログ

MCPO Bridgeのみ：
- コマンド：docker-compose logs -f mcpo-bridge

OpenWebUIのみ：
- コマンド：docker-compose logs -f openwebui

#### ログフィルタリング

時刻指定：
- コマンド：docker-compose logs --since 1h
- 説明：直近1時間のログ

エラーのみ：
- 手法：grep等と組み合わせ
- 例：docker-compose logs mcpo-bridge | grep ERROR

### 5.4 更新デプロイ

#### アプリケーション更新

手順：
1. 最新コードpull：git pull origin main
2. イメージ再ビルド：docker-compose build mcpo-bridge
3. サービス再作成：docker-compose up -d --no-deps mcpo-bridge
4. 動作確認：docker-compose logs -f mcpo-bridge

無停止更新：
- 複数インスタンス起動時
- ローリングアップデート可能

#### 設定ファイル更新

手順：
1. config/mcp-servers.json編集
2. サービス再起動：docker-compose restart mcpo-bridge
3. 動作確認：ヘルスチェック確認

#### Docker Compose設定更新

手順：
1. docker-compose.yml編集
2. 再起動：docker-compose up -d
3. 自動的に変更検出・適用

### 5.5 トラブルシューティング

#### コンテナ状態確認

全コンテナ状態：
- コマンド：docker-compose ps
- 情報：状態、ポート、コマンド

詳細情報：
- コマンド：docker-compose ps -a
- 停止コンテナも表示

#### ヘルスチェック確認

ヘルス状態：
- コマンド：docker inspect mcpo-bridge
- 確認項目：State.Health.Status

手動ヘルスチェック：
- コマンド：curl http://localhost:8080/health
- レスポンス確認

#### コンテナ内シェル

デバッグ用シェル起動：
- コマンド：docker-compose exec mcpo-bridge /bin/bash
- 用途：ファイル確認、手動コマンド実行

新規コンテナでシェル：
- コマンド：docker-compose run --rm mcpo-bridge /bin/bash
- 用途：クリーンな環境でのテスト

#### ネットワーク確認

ネットワーク一覧：
- コマンド：docker network ls

ネットワーク詳細：
- コマンド：docker network inspect mcpo-bridge_mcpo-network

接続確認：
- コンテナ内からpingやcurl実行

#### ボリューム確認

ボリューム一覧：
- コマンド：docker volume ls

ボリューム詳細：
- コマンド：docker volume inspect mcpo-bridge_mcpo-jobs

ボリューム内容確認：
- コンテナマウントして確認
- バインドマウントの場合はホストから直接アクセス

## 6. セキュリティ考慮事項

### 6.1 イメージセキュリティ

#### ベースイメージ選定

信頼性：
- 公式イメージ使用
- バージョンタグ固定（latest避ける）
- 定期的な更新

脆弱性スキャン：
- docker scan コマンド利用
- CI/CDパイプラインに組み込み
- 定期スキャン実施

最小化：
- 不要パッケージ除外
- マルチステージビルド活用
- Slimバリアント採用

#### イメージレジストリ

プライベートレジストリ：
- 本番環境では推奨
- アクセス制御
- イメージ署名

#### 定期更新

更新頻度：
- セキュリティアップデート即時適用
- 月次での定期更新
- 脆弱性情報モニタリング

### 6.2 ランタイムセキュリティ

#### Capabilities制限

ドロップ：
- デフォルトcapabilities削除
- 必要最小限のみ付与

設定：
- cap_drop: ALL
- cap_add: 必要なもののみ

#### Read-onlyファイルシステム

設定：
- read_only: true
- tmpfsマウント：/tmp、/var/tmp

例外：
- 書き込み必要な領域のみtmpfs

#### Seccompプロファイル

適用：
- デフォルトプロファイル使用
- カスタムプロファイル作成（上級）

効果：
- システムコール制限
- 攻撃面削減

### 6.3 ネットワークセキュリティ

#### 内部ネットワーク分離

設計：
- アプリケーション別ネットワーク
- 不要な通信遮断

実装：
- mcpo-network：OpenWebUI ↔ Bridge
- 外部ネットワーク：必要時のみ

#### ポート公開最小化

原則：
- 必要最小限のポートのみ公開
- 内部通信はネットワーク経由

設定：
- OpenWebUI：3000公開
- MCPO Bridge：8080は内部のみ（開発時以外）

#### TLS/SSL

本番環境：
- リバースプロキシでTLS終端
- コンテナ間通信は平文（同一ホスト前提）

証明書：
- Let's Encrypt等の利用
- 自動更新設定

### 6.4 データセキュリティ

#### ボリュームパーミッション

設定：
- バインドマウントの場合、ホスト側で適切なパーミッション設定
- Dockerがファイルを作成する際のデフォルト権限に依存

#### 機密情報管理

環境変数：
- .envファイル使用
- バージョン管理除外（.gitignore）

シークレット：
- Docker Secrets使用（Swarmモード）
- Kubernetes Secrets（K8s環境）

#### バックアップ

対象：
- 設定ファイル
- OpenWebUIデータ（openwebui-data）

除外：
- 一時ファイル（mcpo-jobs）：自動削除前提

頻度：
- 設定変更時
- 定期バックアップ（日次・週次）

## 7. モニタリングと監視

### 7.1 ヘルスチェック

#### エンドポイント

URL：http://localhost:8080/health

レスポンス内容：
- status：ok / degraded / down
- timestamp：チェック実行時刻
- version：Bridgeバージョン
- uptime：稼働時間

#### 監視項目

コンテナレベル：
- ヘルスステータス
- 再起動回数
- CPU/メモリ使用率

アプリケーションレベル：
- エンドポイント応答
- エラー率
- レスポンスタイム

### 7.2 ログ収集

#### Docker logs

標準出力/エラー出力：
- docker-compose logs で確認
- JSON形式で出力

ログドライバー：
- json-file：デフォルト
- syslog、journald：統合管理時

#### 外部ログ集約

ツール例：
- ELKスタック（Elasticsearch、Logstash、Kibana）
- Fluentd
- Splunk

設定：
- logging: ドライバー指定
- docker-compose.ymlに記載

### 7.3 ログレベル設定

環境変数でログレベルを制御：

- DEBUG：開発環境、詳細なデバッグ情報
- INFO：本番環境、通常の情報
- WARNING：警告情報
- ERROR：エラー情報

設定方法：
- docker-compose.ymlの環境変数MCPO_LOG_LEVELで指定



## 8. スケーリング戦略

### 8.1 垂直スケール

#### リソース制限設定

CPU：
- cpus: "2.0"（2コア割り当て）
- cpu_shares: 1024（相対重み）

メモリ：
- mem_limit: "2g"（上限2GB）
- mem_reservation: "1g"（ソフトリミット）

#### 最適化指針

適切なリソース割り当て：
- 使用状況モニタリング
- ボトルネック特定
- 段階的増強

### 8.2 水平スケール

#### Docker Compose でのスケール

コマンド：
- docker-compose up -d --scale mcpo-bridge=3

制約：
- ポート競合問題
- ロードバランサー必要

#### ロードバランサー

選択肢：
- nginx
- HAProxy
- Traefik（Docker連携）

設定：
- ラウンドロビン
- ヘルスチェック連動
- セッションアフィニティ不要

#### 共有ストレージ

必要性：
- 複数インスタンス間でファイル共有
- ダウンロードURL一貫性

選択肢：
- NFS
- Ceph
- クラウドストレージ（S3、Azure Blob）

設定：
- docker-compose.ymlでボリュームドライバー変更
- 外部ボリューム使用

### 8.3 Kubernetes移行

#### 移行のメリット

- 自動スケーリング
- 自己修復
- ローリングアップデート
- 宣言的管理

#### 必要なマニフェスト

- Deployment：Pod定義
- Service：内部通信
- Ingress：外部公開
- ConfigMap：設定ファイル
- Secret：機密情報
- PersistentVolumeClaim：永続ストレージ

#### 移行手順

1. コンテナイメージレジストリ登録
2. Kubernetesマニフェスト作成
3. テスト環境でデプロイ
4. 動作確認
5. 本番環境移行

## 9. まとめ

### 9.1 Docker化の利点

- 環境の一貫性確保
- デプロイの簡易化
- スケーラビリティ向上
- 運用負荷軽減

### 9.2 ベストプラクティス

- マルチステージビルド採用
- 非rootユーザー実行
- ヘルスチェック実装
- ログ・メトリクス収集
- セキュリティ設定徹底

### 9.3 今後の展開

- Kubernetes対応
- CI/CDパイプライン構築
- 監視ダッシュボード整備
- 自動スケーリング実装

---

本Docker デプロイメント設計書は、MCPO On-Demand BridgeのDocker化とOpenWebUIとの連携に必要な全ての設計情報を提供している。本設計に基づきデプロイすることで、安全で運用しやすいコンテナ環境を構築できる。
