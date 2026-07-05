# ランタイム・ツール・履歴

**AgentRuntime**・**ToolExecutor**・**LocalChatHistory** がどう協調するかを、人間向けに短く整理します。

## データの流れ（簡略）

1. ユーザーメッセージを履歴に追加。
2. モデルが履歴全体を読み、**tool_calls** を返した場合は assistant 内容を記録しツールを実行し、結果を履歴へ書き戻す。
3. ループは次のいずれかで終了：**終了マーカー**、**ユーザー確認マーカー**、または **`max_steps` 到達**。

## なぜ履歴中心か

- JSON トランスクリプトで推論とツール I/O を **再生** しやすい。
- CLI と Web が同じ factory/runtime を通すと挙動の分岐が減る。

## ツールとスキル

- **ツール**：副作用や外部読取（ワークスペース走査、materials 読取など）。
- **スキル**：多くは **手順書テキスト**（例：`lookup_skill`）。モデルの出力指針であり、**実行可能ツールと混同しない**こと。

## SDK JSON の読み方

- 各モジュールページ上部の **Reader guide**（多言語の説明文）から入る。
- 続けて **Symbol** でシグネチャと挙動、`examples` でコピペ用サンプルを確認。

## 参照モジュール

- `src.agent_factory` — 組み立て
- `src.ai_core.runtime` — 自律ループ
- `src.ai_core.tool_executor` — 登録と実行
- `src.ai_core.history` — 保存形式と一覧の挙動
