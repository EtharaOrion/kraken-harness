# Evaluation

This directory contains scripts for evaluating model predictions on SWE-fficiency.

## Recommended: Use the CLI

The simplest way to run evaluation is via the `swefficiency` CLI:

```bash
# Step 1: Run gold baseline (establishes reference performance)
swefficiency eval --run_id my_eval

# Step 2: Run your model predictions
swefficiency eval --run_id my_eval --prediction_path predictions.jsonl

# Step 3: Generate report (CSV + JSON with performance breakdown)
swefficiency report --run_id my_eval --pred_run <model_name>
```

See `swefficiency eval --help` and `swefficiency report --help` for all options.

## Prediction File Format

Your predictions file should be JSONL with each line containing:
```json
{"instance_id": "<id>", "model_patch": "<patch_text>", "model_name_or_path": "<model_name>"}
```

## Outputs

- **Evaluation logs**: `logs/run_evaluation/<run_id>/<model_name>/<instance_id>/`
- **CSV report**: `eval_reports/eval_report_<model_name>.csv`
- **JSON report**: `eval_reports/eval_report_<model_name>.json` (includes overall score and breakdown)

## Advanced: Shell Scripts

For batch processing or custom workflows, shell scripts are also available:

```bash
# Run evaluation
scripts/eval/run_eval.sh <run_id> <num_workers> <path_to_predictions>

# Generate reports for multiple runs
scripts/eval/run_multiple_eval_reports.sh
```

## Tips

- Use `--num_workers` to control parallelism (default: 4)
- Keep `run_id` unique per experiment to avoid overwriting
- Dry run with `--instances_regex "pandas.*"` to test on a subset
