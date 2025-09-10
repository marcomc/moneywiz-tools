#!/usr/bin/env python3
import sys
import types

# Provide a minimal pytest shim if pytest isn't installed (used for approx in models)
try:
    import pytest  # type: ignore
except Exception:  # pragma: no cover - lightweight runtime shim
    pytest = types.ModuleType("pytest")

    class _Approx:
        def __init__(self, expected, abs=None, rel=None):
            self.expected = expected
            self.abs = abs
            self.rel = rel

        def __eq__(self, other):
            try:
                from decimal import Decimal
                exp = Decimal(str(self.expected))
                got = Decimal(str(other))
            except Exception:
                try:
                    exp = float(self.expected)
                    got = float(other)
                except Exception:
                    return False
            if self.abs is not None:
                return abs(got - exp) <= type(got)(self.abs)
            if self.rel is not None:
                return abs(got - exp) <= abs(exp) * type(got)(self.rel)
            return got == exp

    def approx(val, abs=None, rel=None):  # noqa: A002 - follow pytest signature
        return _Approx(val, abs=abs, rel=rel)

    pytest.approx = approx  # type: ignore[attr-defined]
    sys.modules["pytest"] = pytest

for mod_name, pip_name in (('click','click'), ('pandas','pandas')):
    try:
        __import__(mod_name)
    except Exception:  # pragma: no cover - runtime dependency check
        sys.stderr.write(
            f"Error: Missing dependency '{mod_name}'. Install with: pip install {pip_name}\n"
        )
        sys.exit(127)

from moneywiz_api.cli.cli import main as cli_main


if __name__ == "__main__":
    # Delegate to Click entrypoint; it will parse sys.argv
    cli_main()
