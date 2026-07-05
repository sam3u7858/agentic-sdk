# ゼロから始める：最初のエージェントの構築とカスタマイズ

このガイドでは、本フレームワークを使用して、思考し、タスクを実行し、進捗を報告できるエージェントをゼロから作成する方法を学びます。これまでの内容を読んでいないことを前提とした、独立した詳細な開発マニュアルです。

---

## ステップ 0：環境準備

コードを書く前に、エージェントがどの LLM（大規模言語モデル）を呼び出すべきかを設定する必要があります。

1. **環境設定ファイルの作成**：プロジェクトのルートに `.env` ファイルを作成します。
2. **設定の入力**：
   ```text
   GEMINI_KEY=あなたの_GEMINI_API_キー
   GEMINI_MODEL=gemini-3.1-flash-lite-preview
   ```

---

## ステップ 1：エージェントの作成

フレームワークは「自動組み立てライン」関数 `create_agent_components` を提供しています。これにより、モデル設定、プロンプトの読み込み、ツールの登録を一括で行えます。

### 基本的なコード構成
```python
from src.agent_factory import create_agent_components

# 1. エージェントコンポーネントの起動
# 'my-agent' は会話 ID です。ログは my-agent.json として保存されます。
components = create_agent_components("my-agent")

# 2. 実行ループオブジェクト (Runtime) の取得
runtime = components["runtime"]

# 3. タスクの実行
task = input("命令を入力してください：")
result = runtime.run(task)
print(result)
```

---

## ステップ 2：モデルパラメータとコンテンツのカスタマイズ

モデルの挙動を調整したり（創造性を高めるなど）、キャラクターを変えたい場合は、以下の方法を参考にしてください。

### 1. モデルパラメータのカスタマイズ (Temperature, Provider)
いまは `create_agent_components(...)` に直接 LLM の設定を渡せるため、別モデルを試すだけなら `src/agent_factory.py` 本体を編集する必要はありません。

```python
# 初期化時にモデル設定を直接渡す：
components = create_agent_components(
    "my-agent",
    provider="gemini", # "openai" や "local" も指定可能
    model="gemini-3.1-pro",
    api_key="YOUR_API_KEY",
    request_options={
        "temperature": 0.7,  # 0.0 は安定重視、1.0 は創造性重視
        "max_tokens": 2048
    }
)
```

`"openai"` や `"local"` のような OpenAI 互換 provider を使う場合は、`lm_api_url` も合わせて渡してください。

```python
components = create_agent_components(
    "my-agent",
    provider="openai",
    model="gpt-4o-mini",
    api_key="YOUR_OPENAI_KEY",
    lm_api_url="https://api.openai.com/v1",
    request_options={
        "temperature": 0.2,
        "max_tokens": 2048
    }
)
```

現在の既定値は次のままです：
- `provider="gemini"`
- `model` は `GEMINI_MODEL` にフォールバック
- `api_key` は `GEMINI_KEY` にフォールバック

### 2. カスタムプロンプトの導入
エージェントの「個性」は `prompts/` フォルダ内の Markdown ファイルで決まります。
- **修正場所**：`prompts/system_core.md` を編集します。
- **動的置換**：Markdown 内で `$user_name` と書くと、コード内で `load_prompt(..., user_name="タロウ")` と呼び出した際に自動的に置換されます。

### 3. カスタムスキル (マニュアル)
スキル (Skill) はエージェントの「脳内メモ」で、`skills/` フォルダに保存されます。
- **構成**：1つのフォルダが1つのスキルを表し（例：`skills/web_search/`）、中に `meta.json` (名前) と `instructions.md` (詳細手順) を置きます。
- **自動化**：コードでスキルを「登録」する必要はありません。フォルダを置くだけで、エージェントが必要と判断した時に自動的に `lookup_skill` ツールを使って参照します。

### 4. 自動ツール (道具箱)
ツール (Tool) はエージェントの「手」であり、ファイルの書き込みやディレクトリの走査、スクレイピングなどを可能にします。
- **開発方法**：`BaseTool` を継承した Python クラスを作成します。
- **登録方法**：`create_agent_components` 内の `tool_executor.register_tools([...])` にインスタンスを追加します。

---

## ステップ 3：リアルタイムの進捗報告

複雑なタスクを実行している間、画面が動かないと不安になります。報告用関数を自作して、エージェントの動作を出力できます。

```python
def my_reporter(event):
    etype = event.get("type")
    if etype == "step_started":
        print(f"🌀 エージェントが思考中 (ステップ {event['step']})...")
    elif etype == "tool_requested":
        print(f"🛠️  ツールを呼び出します：{event['tool_name']}")
    elif etype == "run_finished":
        print("✅ タスクが正常に終了しました。")

# この関数をファクトリに渡す
components = create_agent_components("demo-session", event_handler=my_reporter)
runtime = components["runtime"]
runtime.run("プロジェクト構成を走査して概要をまとめてください")
```

---

## 高度な機能の実装演習例

さらにステップアップしたい場合は、以下の3つのプロジェクト演習に挑戦してみてください：

### 1. Discord Bot 生成エージェント
- **タスク**：要件に応じて完全な Discord.py のコードを生成する助手。
- **方法**：`skills/` に `discord_dev` スキルを追加し、`prompts/` に `discord_expert.md` を作成してエージェントの魂を吹き込みます。

### 2. 株価情報の定期取得エージェント
- **タスク**：1時間ごとに自動で株価をチェックする。
- **方法**：`BaseTool` を継承した `GetStockTool` を作成し、メインプログラムの `while` ループで1時間おきに `runtime.run()` を実行します。

### 3. Reddit 自動収集 & 動画台本生成エージェント
- **タスク**：Reddit の人気記事を収集し、YouTube の台本を作成する。
- **方法**：Web を読み取る `RedditTool` と、台本のフォーマット（導入、本編、結末）を定義した `Skill` を組み合わせます。

---
- より低層の API について知りたい場合は：[エージェント構築ガイド](05-builder-guide.md)
