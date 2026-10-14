# anim_thin SOP（素材成片）

## 工具
- `aam(args)`：影片 CLI，args 是字串陣列。下表的 RUN 換成 create 回傳的 run_id。
- `aam_media_sheet(media_dir)`：看素材縮圖並描述每一張。
- `aam_storyboard_segment(...)`／`aam_storyboard_commit(run_id)`：一段一段送分鏡，最後寫入。
- `aam_snap_review(run_id, seg_id)`：送出一段的截圖檢查，**背景執行、立刻回來**。
- `aam_wait(seconds, all)`：等背景工作（截圖檢查、渲染）的結果；沒其他事可做時才用。
- 背景完成的結果會附在任何工具回傳的 `background_done` 裡（`review` 是 PASS 或問題清單）。

| 子指令 | args |
|---|---|
| brief | `["brief", 題目資料夾]` |
| create | `["create", "--title", "touhou-intro", "--theme", 風格, "--script", 全片口白]` → run_id（title 只能英數與連字號） |
| add | `["add", RUN, "seg_01", "pk-title-card"]` → 回傳 CONFIG（鍵與上限）、素材槽 |
| config | `["config", RUN, "seg_01", "--set", "title=紅魔館", "--set", "items=[\"甲\",\"乙\"]", "--set", "duration=8"]` |
| media | `["media", RUN, "seg_02", 槽名, "temppad/.../media/x.png", "--cutout"]`（照片、截圖不加 --cutout） |
| show | `["show", RUN, "seg_01"]` → 目前的 CONFIG |
| blocks | `["blocks", "--theme", 風格]`（速查表不夠時才用） |
| render | `["render", RUN]` → 背景渲染，立刻回來 |
| export | `["export", RUN, "--transition", "fade"]` → 會自動等渲染完成，回傳成片路徑 |

## 流程（照順序，不要跳步也不要重做已成功的步驟）
1. `aam(["brief", 題目資料夾])`
2. `aam_media_sheet(media_dir)`
3. 選一個風格（全片一個）：角色主色吵、照片多 slash｜數字 infographic｜高質感作品 atelier｜安靜文青 speckle｜宇宙科技 cosmos｜紀錄片夜景 explore｜柔和情緒 chroma｜藝術人物 collage｜幾何海報 bauhaus｜科幻規格 stellar
4. `aam(["create", ...])`
5. 分鏡 8–12 段，每段呼叫一次 `aam_storyboard_segment`（seg_01 起連號）；送完呼叫 `aam_storyboard_commit`。
   第一段 pk-title-card、最後一段 pk-outro-cta；至少 6 種骨架；每張素材都要用到。
6. 每段依序：`add` → `config`（一次改完所有範例字與 duration）→ 需要時 `media` → `aam_snap_review`（送出就好，不用等）→ 直接做下一段。
7. 看到 `background_done` 裡某段的 review 不是 PASS：回頭改那段的 config／media，再送一次 `aam_snap_review`（同一段最多 3 輪）。
8. 所有段落都送出後：`aam_wait(all=true)` 取回剩下的結果並修完；全部 PASS 後 `render` → `export`，回報成片路徑與摘要，結尾加 <?final>。

## 骨架速查（括號內是素材槽）
pk-title-card(hero)｜pk-pal-card(pal)｜pk-versus(left,right)｜pk-base-roster(p1–p4)｜pk-stage-list(i1–i3)｜
pk-recipe-formula(m1–m4,product)｜pk-map-pin(map)｜pk-outro-cta(avatar)｜pk-big-stat｜pk-rank-bars｜pk-level-timeline｜
pk-tier-scale｜pk-price-drop｜pk-profit-ratio｜pk-calc-chain｜pk-table｜pk-flow｜pk-media-grid(m1–m6)｜pk-album(p1–p6)｜
pk-showcase(s1–s4)｜pk-site-mockup(site)｜pk-media-frame(media)｜pk-chat(them)｜pk-column-chart｜pk-pie｜pk-links

## 硬規則
- 畫面上的數字、年份、名字只能來自 brief 或素材。
- key_text 每項 ≤5 字（「東方」可以，「東方Project」不行）、最多 4 項；主字 ≤6 字、名字 ≤4 字。
- 範例字全部改掉：帕魯、金幣、碎岩龜、塑鋼、弦月、bmon、訂閱、挖礦、原油、傳奇。
- duration 6–12 秒；一段一個概念；不要編號、RESULT、資料來源這類 UI 字。
- 回傳 ok=false：照 fix 和 example 改參數再送，不要原封不動重送。
