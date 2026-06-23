"""W-MOS adapters — each wraps one subsystem behind the engine's AgentAdapter
protocol (`run(action) -> dict`). Generative adapters take an injected
`generate` callable so they stay pure + testable. The registry + builders
(adapter_for / ctx_for) are appended in Task 3."""
