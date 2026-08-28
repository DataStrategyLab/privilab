"""Placeholder for demo reset behavior owned by a later issue."""

import sys


def main() -> int:
    """Fail closed until local demo persistence exists."""
    print("reset_demo is not implemented in DSL-105", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
