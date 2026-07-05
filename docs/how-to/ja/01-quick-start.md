# クイックスタート

このプロジェクトは、**プロンプト・スキル・ツール・会話履歴・自律ループ（AgentRuntime）** を再利用可能なパイプラインとして接続します。最初に押さえるのは次の 3 点です：**環境**、**組み立ての入口**、**実行の仕方**。

## 重要な概念

- **`create_agent_components(conversation_id)`**：`runtime` / `session` / `llm` / `tool_executor` などを一度に構築し、設定のばらつきを防ぎます。
- **`AgentRuntime.run(user_message, max_steps)`**：複数ステップのループ。モデルがツール呼び出しを返した場合、結果を履歴に書き戻し、終了マーカーまたは `max_steps` まで繰り返します。
- **`LocalChatHistory`**：既定では `chat_history/<id>.json` に保存。デバッグ時の **正史（source of truth）** として扱うと理解しやすいです。

## 最小の流れ（概念）

1. 環境変数を用意（鍵・モデル名など → [設定](02-configuration.md)）。
2. `create_agent_components("my-conv")` を呼び、`components` を受け取る。
3. `components["runtime"].run("タスク", max_steps=...)` を実行。
4. 不具合時は対応する `chat_history` の JSON を開き、全文を追う。

## Web デバッグ UI との関係

`web_app.py` を動かすと、同じ runtime をブラウザから操作できます。SSE でイベントが流れます（[Web デバッグ UI](03-web-ui.md)）。

## 次に読む

- [設定と環境変数](02-configuration.md)
- [ランタイム・ツール・履歴](04-architecture.md)
