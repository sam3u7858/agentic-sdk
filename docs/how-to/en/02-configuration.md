# Configuration

The project typically loads **python-dotenv** so a root `.env` file is picked up when present. Exact variable names depend on `src/agent_factory.py` and the LLM backend—always verify with `os.getenv(...)` in code.

## Recommended practices

- Keep `.env` **out of version control**.
- Use the **same variable names** locally and in deployment to reduce “works on my machine” issues.

## Common variables (patterns)

Typical patterns include:

- **API key** for the remote model provider.
- **Model id** string accepted by that provider.
- **OpenAI-compatible base URL** when `provider` is `local`, `openai`, `grok`, or similar.

## Debugging checklist

1. Empty keys, trailing spaces, or accidental quotes in `.env`.
2. Model string matches a model your account can call.
3. For OpenAI-compatible stacks, `lm_api_url` is set and reachable.

## Next

- [Web debug UI](03-web-ui.md)
