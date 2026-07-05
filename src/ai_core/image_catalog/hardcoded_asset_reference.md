# Asset Reference List

---

## 1. Base Paths

- **Static root** `{{IMAGE_STATIC_BASE}}/static/`
- **Monster Hunter items** `{{IMAGE_STATIC_BASE}}/static/mh-items/`
- **Example backgrounds** `{{IMAGE_STATIC_BASE}}/static/examplevideo/`
- **Memes** `{{IMAGE_STATIC_BASE}}/static/memes/`

---

## 2. Common Images (direct use)

| File          | Full URL                                                   |
| ------------- | ---------------------------------------------------------- |
| dora.png      | `{{IMAGE_STATIC_BASE}}/static/mh-items/dora.png`      |
| user_icon.png | `{{IMAGE_STATIC_BASE}}/static/mh-items/user_icon.png` |
| sheep.png     | `{{IMAGE_STATIC_BASE}}/static/mh-items/sheep.png`     |
| demo.png      | `{{IMAGE_STATIC_BASE}}/static/mh-items/demo.png`      |

---

## 3. Placeholder Pattern

`<img src="{{IMAGE_STATIC_BASE}}/static/assets/bird.png" alt="logo" data-actual="company_logo">`

---

## 4. Monster Hunter Icons

| Category        | Files (append to `/static/mh-items/` …)                                                                                                                                                                                                                                                                                                |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Skill icons     | 7a4645.png · 8b5760.png · 75b058.png · 564471.png · 787042.png · a38b6f.png · 41726e.png · 495780.png · 857d4a.png · ceb459.png · a99967.png · 737a7f.png                                                                                                                                                                              |
| Skill list      | SKILL_0000.webp ∼ SKILL_0013.webp · fallback.webp（子路徑 `skill_list/`）                                                                                                                                                                                                                                                              |
| Slot            | armor_lv0_empty.png · armor_lv1_empty.png · armor_lv2_empty.png · armor_lv0_fill_color.png · armor_lv1_fill_color.png · armor_lv2_fill_color.png · weapon_lv0_empty.png · weapon_lv0_fill_color.png · weapon_lv1_empty.png · weapon_lv1_fill_color.png · weapon_lv2_empty.png · weapon_lv2_fill_color.png · none.png（子路徑 `Slot/`） |
| Weapon slot     | 0-0-0.png · 1-0-0.png · 1-1-0.png · 2-0-0.png · 2-1-0.png · 3-0-0.png · 1.png · 2.png · 3.png · w1-0-0.png · w1-1-0.png · w1-1-1.png · w1.png（子路徑 `slot_icons/`）                                                                                                                                                                  |
| Equipment       | weapon_base.png · helmet_base.png · armor_base.png · glove_base.png · belt_base.png · shoe_bass.png · marksman_base.png                                                                                                                                                                                                                |
| UI / misc       | stone_template.png · logo.png · user_icon.png · trash.png · placeholder_icon.png · favicon.ico · demo.png · sheep.png · 404.png                                                                                                                                                                                                        |
| Social / meta   | social-calculator.png                                                                                                                                                                                                                                                                                                                  |
| Background / 3D | background-small.png · background-big.png · blink.jpg · open.png · character.png                                                                                                                                                                                                                                                       |
| Share           | share/template.png                                                                                                                                                                                                                                                                                                                     |

---

## 5. 各類用途簡述

- **Skill icons（色碼檔名）**：技能依顏色對應的圖示，JS 以 `imgs/${skillData.color}.png` 載入。
- **Skill list**：技能選擇器／列表用的小圖，路徑 `skill_list/${iconName}`。
- **Slot**：防具／武器鑲嵌孔「空槽」與「已填色」圖；左側裝備孔位與右側統計、`slot-renderer` 會用。
- **slot_icons**：武器孔位組合示意圖（如 1-0-0、2-1-0），用於武器孔位選擇。
- **Equipment**：左側「裝備設定」各部位圖示（武器、頭/身/手/腰/腳、護石）。**注意**：`shoe_bass.png` 為既有檔名，實作拼 URL 時沿用目錄實際檔名。
- **UI / misc**：logo、使用者頭像、清除按鈕、護石自訂器預覽（stone_template）、通用 fallback（placeholder_icon）、favicon。
- **Social**：OG/Twitter 預覽圖。
- **Background / 3D**：全頁或 3D 背景圖、眨眼貼圖、匯出用角色圖。
- **Share**：圖片匯出時的版面模板。
- **其他（專案內有，頁面未直接引用）**：demo.png · sheep.png · 404.png · thumbnail.png · icons.png · open.png 等，由 SubAgent 依 meta 挑選。

---

## Structured mock entries (for agents)

[IMAGE_RESOURCE]
path: /static/mh-items/dora.png
description: Example icon asset under mh-items
tags: demo, icon
image_size: unknown

[IMAGE_RESOURCE]
path: /static/examplevideo/background-small.png
description: Example compact background plate
tags: background, layout
image_size: unknown
