import json
from pathlib import Path
from backend.app import contracts

if __name__ == "__main__":
    names = ("Segment", "Scenario", "EvaluationLabel", "Resource", "Run", "Trace", "Approval", "Alert")
    target = Path("frontend/src/contracts.schema.json")
    target.write_text(json.dumps({name: getattr(contracts, name).model_json_schema()
                                  for name in names}, ensure_ascii=False, indent=2) + "\n")
