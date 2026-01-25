# Open WebUI External Tools - Description設定

## PowerPoint MCP Server

```
【重要】PowerPointファイル作成は必ずこのツールを使用。【必須手順】1)create_presentation呼出→レスポンスのresult.presentation_idを抽出して記憶（例:"presentation_1"）、2)そのpresentation_idを使ってadd_slide/create_slide_from_template等でスライド追加（presentation_idパラメータに実際の値のみ使用、{{変数}}や省略禁止）、3)save_presentation呼出（file_path="example.pptx", presentation_id="presentation_1"）→レスポンスのresult.content[0].textに「📎 ダウンロード: [example.pptx](http://...)」形式のリンクが自動追加される→そのtextをそのままユーザーへ提示（追加の編集不要）。【禁止事項】auto_generate_presentation使用（セッションエラー発生）、presentation_idの省略/null指定、textからURLを手動抽出して再フォーマット、python-pptxコード提案、Base64提案、「ファイルを作成しますか？」等の確認。
```

## Excel MCP Server

```
【重要】Excelファイル作成は必ずこのツールを使用。create_workbook/write_data_to_excel/format_range等を呼出→ツールが自動的にダウンロードリンクを応答に含める（ユーザーがクリック可能）。【絶対禁止】openpyxlコード提案、pandasコード提案、CSV提案、Base64提案、Googleドライブ提案、filepath提示、「ファイルを作成しますか？」等の確認、URLの手動提示（ツールが自動生成）。
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
