"""Validate canonical fixture/license truth and the DSL-117 outer pack together."""

from validate_fixtures import ROOT, validate

from privilab.application.trade_regulatory_tasks import load_task_pack


def main() -> None:
    validate()
    pack = load_task_pack(ROOT)
    print(
        f"PASS: {len(pack.tasks)} DSL-117 tasks and "
        "canonical source/license controls validated"
    )


if __name__ == "__main__":
    main()
