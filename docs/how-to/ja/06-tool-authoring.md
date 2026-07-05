# カスタムツールの開発 (Tool)

ツール（Tool）はエージェントの「手」であり、モデルがテキストのみの対話を超えて、実際にコードを実行したり外部データを読み取ったりすることを可能にします。このフレームワークでは、ツールの開発は非常に直感的です。

## BaseTool の継承

すべてのツールは `src.ai_core.tool_executor.BaseTool` を継承し、以下の4つのメンバーを実装する必要があります。

### 1. name
**モデル向けの ID です。** 英数字とアンダースコアのみ使用可能です。例：`search_database`。

### 2. description
**モデル向けのガイドです。** これが最も重要な部分です！モデルに「いつこのツールを呼び出すべきか」を伝えます。例：「ユーザーが注文ステータスについて尋ねた時にこのツールを使用してください。」

### 3. parameters
**JSON Schema です。** ツールが受け取るパラメータ、その型、どれが必須かを定義します。モデルはこの定義に基づいて呼び出し命令を生成します。

### 4. execute()
**実際に実行される Python コードです。** ここにロジックを記述します。
- **入力**：`parameters` で定義されたキーと値のペアに対応します。
- **出力**：**プレーンテキスト（文字列）**を返す必要があります。結果がオブジェクトやリストの場合は、事前に JSON dump するか、読みやすいテキストに変換してください。

## 例：天気検索ツール

```python
from src.ai_core.tool_executor import BaseTool

class GetWeatherTool(BaseTool):
    @property
    def name(self):
        return "get_weather"

    @property
    def description(self):
        return "指定された都市の現在の天気を取得します。"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "都市名、例：東京"}
            },
            "required": ["city"]
        }

    def execute(self, city: str, **kwargs):
        # ここで API 呼び出しをシミュレートします
        return f"{city}の天気は：晴れ、25度です。"
```

## 注意事項
- **例外処理**：`execute()` が失敗した場合は、例外をキャッチしてエラーメッセージ文字列（例：`Error: 都市が見つかりません`）を返すことをお勧めします。モデルはエラーメッセージを見ると、通常は修正を試みるかユーザーに報告します。
- **セキュリティ**：モデルがパラメータを生成して渡してくることを忘れないでください。ファイルを削除したり SQL を実行したりするツールの場合は、必ず適切な検証を行ってください！

---
- 次へ：[スキル SOP の執筆 (Skill)](07-skill-authoring.md)
- ツールの登録：[ツール登録と SDK ガイド](09-tool-registration-sdk.md)
- SDKを表示：[`src.ai_core.tool_executor`](/docs/module/src.ai_core.tool_executor)
