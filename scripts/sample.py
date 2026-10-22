import json
from pathlib import Path
from backend.app.contracts import Scenario


def sample():
    return Scenario(id="foundation-case", type="case", sim_time="2025-07-01T09:00:00",
                    payload={"text": "합성 테스트 사례입니다. 척도 응답은 아직 없습니다."})


if __name__ == "__main__":
    target = Path("data/sample/scenario.json")
    target.write_text(json.dumps(sample().model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    print(target)
