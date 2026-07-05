# Web デバッグ UI

`web_app.py` は **Agent Debug UI** を提供し、会話・イベント・バックグラウンド実行をローカルで観察しやすくします。

## 起動

リポジトリのルートで:

```bash
python web_app.py
```

ポートは `web_app.py` 末尾の `app.run(..., port=...)` を参照してください。

## 画面構成

- **左**：会話一覧（`LocalChatHistory` 由来）
- **中央**：メッセージと入力、`max_steps` 指定
- **右**：**Debug Stream**（**SSE** でランタイムイベントを配信）

## API 早見表

| 用途 | ルート |
|------|--------|
| メイン画面 | `GET /` |
| 実行開始／継続 | `POST /api/chat` |
| 会話 JSON 取得 | `GET /api/conversations/<id>` |
| イベントストリーム | `GET /api/stream/<id>` |

`POST /api/chat` で `conversation_id` を省略すると、新しい ID が発行されバックグラウンドで `AgentRuntime` が動きます。

## SDK との対応

生成された SDK ドキュメントの **`web_app`** モジュールに、上記ルートとシンボルの対応がまとまっています。

## 次に読む

- [ランタイム・ツール・履歴](04-architecture.md)
