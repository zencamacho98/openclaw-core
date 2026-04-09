#!/bin/bash

echo "=== OpenClaw Overnight Run ==="

source .venv/bin/activate

# Run a labeled validation
python scripts/validate_strategy.py --experiment-name overnight_run

echo "=== Validation complete ==="

# Show latest result summary
python scripts/view_experiments.py --latest

echo "=== Done ==="
