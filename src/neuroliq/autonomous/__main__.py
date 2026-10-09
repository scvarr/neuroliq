"""Русскоязычный CLI изолированного исследовательского стенда."""

import argparse
import json
from pathlib import Path
import sys

from .language import Unsupported, render
from .learning import Policy
from .memory import Memory
from .navigation import Budget, Navigator, Query
from .representation import Invalid, dumps
from .runner import run


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Neuroliq: ограниченный автономный исследовательский прототип")
    commands = parser.add_subparsers(dest="command", required=True)
    experiment = commands.add_parser("run", help="Воспроизвести финальный срез, обучение и экспорт")
    experiment.add_argument("--output", type=Path, required=True, help="Каталог артефактов")
    query = commands.add_parser("query", help="Извлечь содержание по формальному JSON-запросу без LLM")
    query.add_argument("--memory", type=Path, required=True)
    query.add_argument("--request", type=Path, required=True)
    query.add_argument("--output", type=Path, required=True)
    query.add_argument("--visits", type=int, default=1000)
    query.add_argument("--policy", type=Path, help="Сохранённая политика v1 либо learning.json")
    args = parser.parse_args()
    try:
        if args.command == "run":
            result = run(args.output)
            print(dumps({"проверки": result["bounded_validation_passed"], "результат": result["result"], "ресурсы": result["resources"]}))
        else:
            memory = Memory.load(args.memory)
            data = json.loads(args.request.read_text(encoding="utf-8"))
            data["roles"] = {int(key): value for key, value in data.get("roles", {}).items()}
            for field in ("wrappers", "modes"):
                if field in data:
                    data[field] = tuple(data[field])
            policy = None
            if args.policy is not None:
                learned = json.loads(args.policy.read_text(encoding="utf-8"))
                policy = Policy.restore(learned.get("after", learned))
            result = Navigator(memory).search(Query(**data), Budget(visits=args.visits), policy=policy)
            for answer in result["results"]:
                answer["expression"] = {}
                for language in ("ru", "en"):
                    try:
                        answer["expression"][language] = render(answer["scene"], language)
                    except Unsupported as error:
                        answer["expression"][language] = {"отказ": str(error)}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(dumps(result) + "\n", encoding="utf-8")
            print(dumps({"статус": result["status"], "полный": result["complete"], "ответов": len(result["results"]), "стоимость": result["cost"]}))
    except (Invalid, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"Отказ стенда: {error}\n")


if __name__ == "__main__":
    main()
