"""Remove staging paths from the managed Python shipped in the app bundle."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


def main(managed_root: Path) -> None:
    installations = [
        path for path in managed_root.iterdir() if path.is_dir() and not path.is_symlink()
    ]
    for alias in managed_root.iterdir():
        if not alias.is_symlink():
            continue
        matches = [path for path in installations if alias.resolve() == path.resolve()]
        if len(matches) != 1:
            raise RuntimeError(f"managed Python alias has an unexpected target: {alias}")
        alias.unlink()
        alias.symlink_to(matches[0].name)
    configs = [
        path / "lib/python3.11/_sysconfigdata__darwin_darwin.py"
        for path in installations
        if (path / "lib/python3.11/_sysconfigdata__darwin_darwin.py").is_file()
    ]
    libraries = [
        path / "lib/libpython3.11.dylib"
        for path in installations
        if (path / "lib/libpython3.11.dylib").is_file()
    ]
    if not configs and not libraries:
        return  # The publication tests use a minimal fake Python producer.
    if len(configs) != 1 or len(libraries) != 1:
        raise RuntimeError(
            f"managed Python layout: root={managed_root}, "
            f"sysconfig={len(configs)}, libpython={len(libraries)}"
        )

    config = configs[0]
    source = config.read_text(encoding="utf-8")
    module = ast.parse(source)
    assignment = module.body[0]
    if not isinstance(assignment, ast.Assign):
        raise RuntimeError("managed Python sysconfig has an unexpected format")
    values = ast.literal_eval(assignment.value)
    prefix = values.get("prefix")
    if not isinstance(prefix, str) or Path(prefix).resolve() != config.parents[2].resolve():
        raise RuntimeError("managed Python sysconfig prefix differs from its bundle path")
    if source.count(prefix) < 2:
        raise RuntimeError("managed Python sysconfig has no staging paths to rewrite")
    marker = "__MONEYWIZ_MANAGED_PREFIX__"
    source = source.replace(prefix, marker)
    source += (
        "\nfrom pathlib import Path as _Path\n"
        "_managed_prefix = str(_Path(__file__).resolve().parents[2])\n"
        "build_time_vars = {\n"
        f"    key: value.replace({marker!r}, _managed_prefix)\n"
        "    if isinstance(value, str) else value\n"
        "    for key, value in build_time_vars.items()\n"
        "}\n"
    )
    config.write_text(source, encoding="utf-8")
    subprocess.run(
        ["install_name_tool", "-id", "@rpath/libpython3.11.dylib", str(libraries[0])],
        check=True,
    )
    subprocess.run(["codesign", "--force", "--sign", "-", str(libraries[0])], check=True)
    if any(b".staging." in path.read_bytes() for path in (config, libraries[0])):
        raise RuntimeError("managed Python still discloses a staging path")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: sanitize_bundle_python.py MANAGED_ROOT")
    main(Path(sys.argv[1]))
