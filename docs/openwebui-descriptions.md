# Open WebUI設定ガイド

## ⚠️ 重要な更新

**mcpo-bridge v1.1以降では、`tools/list`レスポンスに使用方法ガイドが自動的に追加されます。**

### 自動追加される機能

mcpo-bridgeは、MCPサーバーの`tools/list`レスポンスに「📖_usage_instructions」という名前のダミーツールを自動的に追加します。このツールの`description`フィールドには、PowerPointやExcelツールの正しい使い方が詳細に記載されています。

**この情報はLLMに確実に伝達されます。**

### 動作フロー

```
Open WebUI
  ↓
MCPClient.list_tool_specs()
  ↓
mcpo-bridge tools/list
  ↓
実際のMCPサーバー → tools配列を返す
  ↓
mcpo-bridge: 使用方法ガイドツールを追加
  ↓
Open WebUI: 全ツール情報（ガイド含む）をLLMに送信
  ↓
LLM: ガイドのdescriptionを読んで正しいワークフローを学習
```

---

## Open WebUIでの追加設定（推奨）

自動追加されるガイドに加えて、Tools Function Calling Promptでも指示を強化することを推奨します。

### 重要な仕様理解

Open WebUIにおけるLLMへの情報伝達経路:

1. **ツール使用前**: MCPサーバーの各ツールの`description`フィールド + 📖_usage_instructionsのdescription
2. **ツール選択時**: Tools Function Calling Prompt + ツール仕様
3. **External Tool Description**: UI表示専用(LLMには送られない)

**結論**: 
- mcpo-bridgeが自動追加する使用方法ガイドツールがLLMに確実に伝達される
- Tools Function Calling Promptで追加の指示を与えることも可能

---

## 設定方法（オプション）

mcpo-bridgeの自動ガイド追加だけでも動作しますが、さらに強化したい場合は以下を設定できます。

**Admin Panel → Settings → Interface → Tools Function Calling Prompt**に以下を追記:

```
# File Generation Tools - Immediate Execution Policy

When file generation tools (PowerPoint, Excel, etc.) are available in {{TOOLS}}:

**EXECUTE IMMEDIATELY WITHOUT ASKING FOR CONFIRMATION**

Present download links from tool responses exactly as received, without reformatting or extracting URLs.

**NEVER suggest code alternatives** (python-pptx, openpyxl, pandas, etc.)
```

---

## 設定手順（オプション）

追加設定が必要な場合のみ:

1. Open WebUI管理者としてログイン
2. **Admin Panel** → **Settings** → **Interface**に移動
3. **Tools Function Calling Prompt**セクションを探す
4. 既存のデフォルトプロンプトの**後に**上記の内容を追記
5. **Save**をクリック

---

## 動作確認

mcpo-bridgeを再起動後、Open WebUIでPowerPointツールを選択してチャットを開始すると:

1. LLMが「📖_usage_instructions」ツールのdescriptionを読む
2. PowerPointの正しいワークフロー（create_presentation → add_slide → save_presentation）を学習
3. ユーザーの依頼に対して、確認なしで即座にツールを実行
4. ダウンロードリンクを含む結果を提示

---

## トラブルシューティング

### ガイドツールがLLMに届いているか確認

Open WebUIのログで以下を確認:

```
Added usage guide tool to tools/list response (X tools total)
```

### ガイドツールが表示されすぎる場合

現在の実装では、ツールリストUIにもガイドツールが表示されます。これは仕様上の制限です。
ツール名に「📖」絵文字と「_usage_instructions」という名前を付けることで、実行不可能なドキュメント用ツールであることを示しています。

---

## 補足: 旧設定との違い

### 旧方式（Tools Function Calling Promptのみ）

- ❌ 管理者が手動で設定する必要がある
- ❌ Open WebUIの設定変更が必要
- ❌ 複数サーバーで統一した指示が難しい

### 新方式（mcpo-bridgeの自動追加）

- ✅ mcpo-bridgeの再起動だけで有効化
- ✅ サーバーコードでバージョン管理可能
- ✅ 各MCPサーバー固有のガイドを配信可能
- ✅ Open WebUIの設定変更不要（オプションで追加可能）

---

## 注意事項

- **📖_usage_instructionsツール**: 実行できないドキュメント専用ツール。LLMへの指示伝達が目的
- **External Tool Descriptionフィールド**: Open WebUI UIでの表示専用。LLMには送信されない
- **ツールリスト汚染**: UIにガイドツールが表示されるが、名前と説明で区別可能
- **Tools Function Calling Prompt**: ツール選択時にLLMが参照する唯一の情報源
- **各ツールのdescription**: OpenAPI specのdescriptionもLLMに送信されるため、MCP server側で詳細化することも有効
