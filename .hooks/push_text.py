"""The quick judgements of a push whose full check is left to CI: plan stage, plan records and changed-line text rules."""

from pathlib import Path


def push_text_checks(root: Path, base: str | None) -> int:
    from ci_setup import push_base, require_ci_base

    require_ci_base(base, root)
    base = push_base(root, base)
    try:
        import change_size
        import plans
        from comments import validate_rules

        change_size.judged_stage(root, base, "Complete")
        plans.validate_records(root, base)
        validate_rules(root, base)
    except ValueError as error:
        print(f"Hard Eng: {error}")
        return 1
    print("Hard Eng: the plan checks and the changed-line text rules passed.")
    return 0
