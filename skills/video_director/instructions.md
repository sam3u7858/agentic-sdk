# Video Director SOP

## 0) Load this skill

Use `lookup_skill` with query `video_director` if instructions are not already in context.

## 1) Planning

- Call `manage_todo_list` with `action=get` to see current tasks, then `add` / `update` for your scene plan.
- Keep items short; mark `done` when a scene ships.

## 2) Templates (orchestrator reads meta only)

- `list_video_templates` → pick a template id.
- `read_video_template` with `include_system_prompt: true` for worker context.
- **Do not** paste full `base.html` into user chat; delegate HTML to the worker.

## 3) Assets (mock catalog)

- `find_images` for stock paths and `[IMAGE_RESOURCE]` hints (hardcoded backend; not embeddings).
- Optional: `analyze_image` on URLs or `templates/` / `output/` / `materials/` paths when you need vision detail.

## 4) Delegation — HTML worker

- Call `html_worker_subagent` with `template_id` matching `templates/<id>/`.
- Worker may write only under `output/` and read `templates/` + `output/`.
- For readonly research, use `readonly_subagent` instead (no writes).

## 5) QA loop

- After worker writes HTML under `output/`, run `screenshot_and_review_html` with `relative_html_path`.
- Track fixes as TODO updates; re-run worker if layout issues remain.

## 6) Token hygiene

- Large catalogs from `find_images`: prefer `save_policy=file` / `history_mode=file` when supported.
- Summarize tool JSON for the user; avoid dumping long markdown tables wholesale unless necessary.
