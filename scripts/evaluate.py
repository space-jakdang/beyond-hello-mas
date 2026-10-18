"""Foundation checks only; full evaluation must not report a false pass."""
import json
from scripts.sample import sample

if __name__ == "__main__":
    sample()
    print(json.dumps({"status": "incomplete", "mode": "sample/fake", "checks_passed": ["scenario_contract"],
                      "evaluated_scenarios": 0, "missing": ["agents", "catalog", "labels", "suite", "live_evaluation"]}))
    raise SystemExit(2)
