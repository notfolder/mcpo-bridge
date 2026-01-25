# Open WebUI Tools Function Calling Prompt設定

## 概要

Open WebUIの**Admin Panel → Settings → Interface → Tools Function Calling Prompt**に追記する内容です。

External Tool Descriptionフィールドは**LLMに送信されません**。ツール選択ロジックを定義するには、Tools Function Calling Promptに記述する必要があります。

---

## Tools Function Calling Promptに追記する内容

以下を既存のデフォルトプロンプトの後に追記してください：

```
# PowerPoint Tools Workflow Rules

When PowerPoint tools are available in {{TOOLS}}, follow this strict workflow:

1. **Always call `create_presentation` first**
   - Use `id=null` or omit the id parameter for new presentations
   - Extract `presentation_id` from the response (e.g., "presentation_1")
   - Store this presentation_id for all subsequent operations

2. **Use the presentation_id for all subsequent tools**
   - When calling `add_slide`, `create_slide_from_template`, or any slide modification tools
   - Always pass the actual presentation_id value (e.g., "presentation_1")
   - NEVER omit or use null for presentation_id
   - NEVER use placeholder syntax like {{presentation_id}} - use the literal string value

3. **Call `save_presentation` to finalize**
   - Required parameters: `file_path` (e.g., "example.pptx") and `presentation_id`
   - The response will contain a download link in Markdown format
   - Return the response text directly to the user without modification

**PROHIBITED PowerPoint Operations:**
- NEVER use `auto_generate_presentation` tool (causes session errors)
- NEVER skip `create_presentation` step
- NEVER omit or use null for `presentation_id` in slide operations
- NEVER manually extract or reformat URLs from tool responses
- NEVER suggest python-pptx code as alternative
- NEVER ask user for confirmation before creating files

# Excel Tools Workflow Rules

When Excel tools are available in {{TOOLS}}, follow these guidelines:

1. Use tools like `create_workbook`, `write_data_to_excel`, `format_range` directly
2. Tool responses will automatically include download links
3. Return tool response text directly to the user without modification

**PROHIBITED Excel Operations:**
- NEVER suggest openpyxl or pandas code as alternative
- NEVER suggest CSV export as alternative
- NEVER suggest Google Drive or cloud storage
- NEVER ask user for confirmation before creating files
- NEVER manually format or extract URLs from tool responses

# Result Handling

When tools return responses containing download links in format "📎 ダウンロード: [filename](http://...)":
- Present the response text exactly as received
- Do NOT extract, reformat, or modify URLs
- Do NOT add explanations about how to download
- The Markdown links are automatically clickable in the UI
```

---

## 設定手順

1. Open WebUI管理者としてログイン
2. **Admin Panel** → **Settings** → **Interface**に移動
3. **Tools Function Calling Prompt**セクションを探す
4. 既存のデフォルトプロンプトの**後に**上記の内容を追記
5. **Save**をクリック

---

## 補足: System Promptの設定（オプション）

Tools Function Calling Promptに加えて、全体的な動作を制御するためにSystem Promptにも以下を追加できます：

**Admin Panel → Settings → Interface → System Prompt**または各モデルのSystem Prompt:

```
When using file generation tools (PowerPoint, Excel, etc.), always execute the tools directly without asking for user confirmation. Present download links from tool responses exactly as received without reformatting.
```

---

## 注意事項

- **External Tool Descriptionフィールド**: Open WebUI UIでの表示専用。LLMには送信されない
- **Tools Function Calling Prompt**: ツール選択時にLLMが参照する唯一の情報源
- **各ツールのdescription**: OpenAPI specのdescriptionもLLMに送信されるため、MCP server側で詳細化することも有効
