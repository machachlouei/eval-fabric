# Agentic Support Audit Example

This example showcases the real-world value of `eval-fabric` as a **pluggable orchestration framework** for agentic systems.

## Why this is the "Real Value"

Traditional evaluation often just compares a string input to a string output. Agentic systems are more complex: they have internal reasoning, they call tools, and they have multi-step traces.

This example demonstrates how `eval-fabric` handles that complexity:

1.  **Complex Evaluator State:** The `SupportAgent` returns not just a response, but a list of `tool_calls` in its metadata.
2.  **Multi-Dimensional Judging:** We use two different judges on every single interaction:
    -   **LLM Judge:** Evaluates "Soft" qualities like politeness and helpfulness.
    -   **Custom Rule Judge:** Evaluates "Hard" system integrity by inspecting the tool-use trace in the metadata.
3.  **Weighted Scoring:** We weigh `tool_accuracy` more heavily (2.0) than `satisfaction` (1.0), reflecting that for a support bot, calling the right tool is more critical than its tone.
4.  **Durable Traces:** Every tool call and reasoning step is persisted in the `TraceStore`, allowing developers to "replay" and debug exactly why an agent failed to call a tool.

## How to run

### 1. Register the Plugins
In a real project, you'd use entry points. For this example, ensure the current directory is in your `PYTHONPATH`.

### 2. Run the Audit

```bash
ef run spec.yaml --dataset data.jsonl
```

### 3. Analyze the Orchestration
Look at the output:
- You'll see `user_satisfaction` and `tool_accuracy` calculated separately.
- Use `ef show <run_id> --traces` to see the full metadata of each task, including the `tool_calls`.

## Features Demonstrated

- **Metadata Inspection:** Writing judges that look "under the hood" of the evaluator.
- **Orchestration:** Handling multiple asynchronous judges per task.
- **Agent Integrity:** Testing the "process" of the AI, not just the "result".
