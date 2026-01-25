# Open WebUI External Tools - Description設定

## PowerPoint MCP Server

```
PowerPointプレゼンテーション生成（Stateful/30分セッション維持）。必須: create_presentationでpresentation_idを取得→全操作で実際の値を使用（{{変数}}禁止）→save_presentation後に_download_urlをユーザーに提示（file_path提示禁止）。段階的編集可能。
```

## Excel MCP Server

```
Excelファイル生成・編集。主要ツール: create_workbook（新規作成）, write_data_to_excel（データ書込）, read_data_from_excel（データ読取）, format_range（書式設定）, apply_formula（数式）, create_chart（グラフ）, create_pivot_table（ピボット）, create_table（テーブル）。必須: 実行後_download_url提示（filepath提示禁止）。
```

---

## 使用方法

1. Open WebUI → Settings → External Tools
2. 新規ツール追加
3. Name: `PowerPoint Generator (mcpo-bridge)` または `Excel File Generator (mcpo-bridge)`
4. URL: `http://nginx/mcp/powerpoint` または `http://nginx/mcp/excel`
5. Description: 上記の該当するテキストをコピー&ペースト
6. Headers: `{"Content-Type": "application/json"}`

LLMはdescriptionを参照して適切にツールを使用します。
