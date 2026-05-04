# Hello World Example

This is a minimal "smoke test" evaluation to verify that your `eval-fabric` installation is working correctly.

## What this demonstrates

This example uses the simplest possible components that require no external API keys or complex configuration:

1.  **Evaluator (`eval_fabric.examples.echo`):** A built-in evaluator that simply returns the input verbatim.
2.  **Judge (`eval_fabric.exact_match`):** A built-in rule-based judge that compares the evaluator's output against the `reference_output` in the dataset.
3.  **Dataset (`data.jsonl`):** A small set of inputs where the input and reference output are identical.

Because the evaluator "echoes" the input and the judge checks for an exact match, this evaluation should always result in an **accuracy score of 1.0**.

## How to run

Navigate to this directory and use the `ef run` command:

```bash
cd examples/hello-world
ef run spec.yaml --dataset data.jsonl
```

## Expected output

The CLI will print a summary of the run, including the run ID and the calculated metrics:

```text
run=run_... status=completed items=3 counts={"ok": 3, "timeout": 0, "error": 0, "skipped": 0} cost_usd=0.0000
  metric.accuracy: 1.0
runs/run_....json
```

## Next steps

Once you've verified the system is working, you can:
- Explore `spec.yaml` to see how the evaluation is configured.
- Try modifying `data.jsonl` with an incorrect reference to see the accuracy drop.
- Look at the [PiML Audit example](../piml-audit/) for a more advanced integration.
