from __future__ import annotations

import argparse
import json

from .checkpoint import plan_in_fresh_session
from .domain import JobRequest
from .sibyl_store import SibylStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-db", required=True)
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args()
    request = JobRequest.from_dict(json.loads(args.request_json))
    strategy, lessons = plan_in_fresh_session(request, SibylStore(args.memory_db))
    print(json.dumps({"strategy": strategy.to_dict(), "recalledLessons": [item.to_dict() for item in lessons]}))


if __name__ == "__main__":
    main()

