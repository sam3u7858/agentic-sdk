# エージェント構築ガイド

エージェントシステムの立ち上げや、既存プロジェクトへの統合を担当する場合、このガイドでは完全な運用スタックをどのように「組み立てる」かを説明します。

## ワンストップ組み立て：create_agent_components

CLIツールやWeb UIなど、異なる場所で設定を重複して記述することを避けるため、「組み立ての入口」として `src/agent_factory.py` の `create_agent_components()` を用意しています。

### 何をしてくれるのか？
1. **環境変数の読み込み**：`load_dotenv()` を介してAPIキーなどを読み込みます。
2. **マネージャーの準備**：`PromptManager`（プロンプト管理）と `SkillRegistry`（スキル登録）を作成します。
3. **実行器の初期化**：`ToolExecutor` を作成し、**既定のツール**（ワークスペース走査、スキル検索など）を登録します。
4. **モデル（LLM）の設定**：`LMWrapper` を初期化し、メインのシステムプロンプトを注入します。
5. **履歴とループの接続**：`LocalChatHistory`、`ChatSession` を設定し、最終的に `AgentRuntime` を生成します。

### 使い方
```python
from src.agent_factory import create_agent_components

# 一意の会話IDを指定すると、システムが自動的に対応するJSONログファイルを作成します
components = create_agent_components("my-unique-id")

# 返された辞書から必要なコンポーネントを取り出します
runtime = components["runtime"]
system_prompt = components["system_prompt"]
```

## どのような時に「手動で組み立てる」べきか？

`agent_factory` は便利ですが、以下のようなニーズがある場合は `create_agent_components` のコードを参考に、自身でコンポーネントをインスタンス化する必要があります。
- **アクセスパスの変更**：prompts フォルダを別の場所に移動したい場合。
- **カスタムツールセット**：既定の素材管理ツールを読み込まず、特定のツールのみを使用したい場合。
- **マルチモデルの切り替え**：ロジックに基づいて動的に使用する LLM プロバイダーを決定したい場合。

## コア統合ポイント
組み立て後、最も頻繁にやり取りするオブジェクトは **`AgentRuntime`** です。`runtime.run(message)` を呼び出すだけで、モデルとの対話、ツールの呼び出し、履歴の記録といった煩雑なプロセスを自動的に処理してくれます。

---
- 次へ：[カスタムツールの開発 (Tool)](06-tool-authoring.md)
- SDKを表示：[`src.agent_factory`](/docs/module/src.agent_factory)
