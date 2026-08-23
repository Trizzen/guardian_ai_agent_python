# Legacy Gemini coding-agent prototype

This folder preserves the previous root `main.py`, including its uncommitted agent-loop and error-handling improvements, as an execution-layer reference. The associated `call_function.py`, `functions/`, `prompts/`, and `calculator/` fixtures remain at the repository root so their original imports and tests are still legible.

It is intentionally disconnected from Jaza Sentinel v0.1. It can read, write, and execute files inside its calculator sandbox and therefore must not be presented as Star Reborn delegation. If revisited, it requires the optional `legacy-gemini` dependency and a separately supplied `GEMINI_API_KEY`.
