# 提示詞工程建議 (Prompt Engineering)

在本專案中，我們將提示詞（Prompt）視為一種資源，並透過 `PromptManager` 進行統一管理與動態注入。

## 使用 PromptManager

所有的核心提示詞都存放在 `prompts/` 資料夾的 `.md` 檔案中。

### 範例：核心系統提示詞
假設你有一個 `prompts/system_core.md`：
```markdown
你是 $agent_name。
你的目前可用技能如下：
$available_skills
請協助使用者完成任務。
```

在 Python 程式碼中，你可以這樣載入並替換變數：
```python
prompt = prompt_manager.load_prompt(
    "system_core", 
    agent_name="助手二號",
    available_skills="- 查天氣\n- 寫程式"
)
```

## 提示詞該放哪？（策略建議）

開發過程中，你可能會猶豫一段指示該放在「系統提示詞」、「技能 (Skill)」還是「工具說明 (Tool description)」？以下是我們的建議：

| 內容類型 | 推薦存放位置 | 原因 |
| :--- | :--- | :--- |
| **Agent 的性格、基本身分、核心行為準則** | 系統提示詞 (`prompts/`) | 這是 Agent 的基石，必須從對話開始就存在。 |
| **特定領域的複雜 SOP、報表格式、流程教學** | 技能 (`skills/`) | 這類資訊太長，適合等 Agent 發現需要時再「查手冊」。 |
| **工具的使用時機、參數限制、回傳值說明** | 工具說明 (`BaseTool.description`) | 讓模型知道這個「按鈕」按下去會發生什麼。 |

## 實用的寫作技巧

1. **變數替換**：善用 `$variable` 語法，讓同一份範本能適應不同的 session 或角色名稱。
2. **結構化輸出**：在提示詞中明確要求 `<?final>` 或 `<?ask_user>` 等標記，這是驅動 `AgentRuntime` 停止或互動的關鍵。
3. **少即是多**：系統提示詞保持精簡，把具體細節拆分到對應的 **Skill** 中，能有效降低模型的認知負擔與 Token 消耗。

---
- 接下來：[工具註冊與 SDK 教學](09-tool-registration-sdk.md)
- 查看 SDK：[`src.ai_core.prompt_manager`](/docs/module/src.ai_core.prompt_manager)
