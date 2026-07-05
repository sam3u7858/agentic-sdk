# Web debug UI

`web_app.py` ships an **Agent Debug UI** for local inspection of conversations, streaming events, and background runs.

## Run the server

From the repository root:

```bash
python web_app.py
```

Check `app.run(..., port=...)` at the bottom of `web_app.py` for the port.

## UI layout

- **Left**: conversation list (backed by `LocalChatHistory`).
- **Center**: transcript + prompt box; optional `max_steps`.
- **Right**: **Debug Stream** via **Server-Sent Events (SSE)**.

## API cheat sheet

| Purpose | Route |
|--------|-------|
| Main page | `GET /` |
| Start / continue a run | `POST /api/chat` |
| Fetch stored conversation | `GET /api/conversations/<id>` |
| Event stream | `GET /api/stream/<id>` |

If `conversation_id` is omitted in `POST /api/chat`, the server allocates a new id and starts a background `AgentRuntime` run.

## SDK cross-reference

The **`web_app`** module entry in the generated SDK docs maps these routes to symbols for quick navigation.

## Next

- [Runtime, tools, and history](04-architecture.md)
