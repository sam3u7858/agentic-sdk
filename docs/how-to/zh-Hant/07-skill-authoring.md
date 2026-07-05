# 撰寫技能 SOP (Skill)

如果說工具（Tool）是 Agent 的「手」，那麼技能（Skill）就是 Agent 的「腦中手冊」。

技能並不是程式碼，而是**一段高品質的 Markdown 指示 (SOP)**。它告訴模型如何運用現有的工具、遵循特定的風格或產出結構化的結果。

## 技能的檔案結構

所有的技能都存放在 `skills/` 資料夾中。每一個技能都是一個獨立的子資料夾：

```text
skills/
  └── video_planner/
      ├── meta.json        # 技能的身分證（名稱、簡介、依賴工具）
      └── instructions.md  # 技能的核心邏輯（具體的 SOP 指示）
```

**與 `templates/` 的區分**：可重複使用的 **HTML／版式／單一專案資產** SOP（例如某個 `base.html` 的改寫規則）請放在 `templates/<id>/system_prompt.md`，由 **`read_video_template` / worker** 讀取；跨情境的 **操作 playbook** 才放在 `skills/<name>/`，避免被 `SkillRegistry` 誤把模板目錄當成獨立技能載入。

### 1. meta.json
這裡定義了技能如何被檢索：
- `name`：技能名稱（例如 `video_planner`）。
- `description`：簡短描述，幫助模型在搜尋時決定要不要用這個技能。
- `required_tools`：一個清單，註明這個技能需要哪些 Tool 配合（目前僅供參考與前端標記）。

### 2. instructions.md
這裡是你揮灑 Prompt Engineering 的地方。寫法就像你平常在 ChatGPT 對話中給予的規則：
- 設定背景（例如「你是一個專業的影片企劃...」）
- 規定輸出格式（例如「請務必以 JSON 格式產出...」）
- 步驟指引（例如「第一步先掃描工作區，第二步...」）

## 為什麼要用技能？

1. **節省 Context 空間**：你不需要一開始就把所有 SOP 都塞進系統提示詞（System Prompt）。Agent 會透過 `lookup_skill` 工具，只在需要的時候去抓取對應的手冊。
2. **模組化管理**：當你需要 Agent 學會做「網站翻譯」時，只要新增一個 `translator` 資料夾，完全不需要修改核心程式。

## 核心觀念
**技能不是可執行的程式！** 
你寫在 `instructions.md` 裡的文字，最終會被模型「讀取」並加入對話背景。模型會閱讀這份手冊，然後**依照指示去呼叫真正的 Tool**。

---
- 接下來：[提示詞工程建議](08-prompt-engineering.md)
- 查看 SDK：[`src.ai_core.skill_registry`](/docs/module/src.ai_core.skill_registry)
