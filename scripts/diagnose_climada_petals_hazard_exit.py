from __future__ import annotations

import json
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _normalized_exit_code(returncode: int) -> int:
    if returncode < 0:
        return 128 + abs(int(returncode))
    return int(returncode)


def _signal_name(returncode: int) -> str | None:
    if returncode >= 0:
        return None
    signum = abs(int(returncode))
    if signum == 11:
        return "SIGSEGV"
    return f"SIG{signum}"


def _run_case(case_id: str, description: str, code: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "case_id": case_id,
        "description": description,
        "returncode": int(completed.returncode),
        "normalized_exit_code": _normalized_exit_code(completed.returncode),
        "signal": _signal_name(completed.returncode),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main() -> int:
    purelib = Path(sysconfig.get_paths()["purelib"])
    landslide_path = purelib / "climada_petals" / "hazard" / "landslide.py"
    if not landslide_path.exists():
        raise SystemExit(f"Cannot locate landslide.py in current environment: {landslide_path}")

    cases = [
        (
            "hazard_package_import",
            "Import climada_petals.hazard through the package initializer",
            "import climada_petals.hazard; print('hazard-package-ok')",
        ),
        (
            "isolated_landslide_file_import",
            "Load landslide.py directly without importing climada_petals.hazard.__init__",
            (
                "import importlib.util; "
                f"spec = importlib.util.spec_from_file_location('isolated_landslide', {str(landslide_path)!r}); "
                "mod = importlib.util.module_from_spec(spec); "
                "spec.loader.exec_module(mod); "
                "print('isolated-landslide-ok')"
            ),
        ),
    ]

    results = [_run_case(case_id, description, code) for case_id, description, code in cases]
    result_by_id = {result["case_id"]: result for result in results}

    package_import = result_by_id["hazard_package_import"]
    isolated_import = result_by_id["isolated_landslide_file_import"]
    reproduced = (
        package_import["normalized_exit_code"] == 139
        and package_import["signal"] == "SIGSEGV"
        and isolated_import["normalized_exit_code"] == 0
    )

    summary = {
        "python_executable": sys.executable,
        "repo_root": str(REPO_ROOT),
        "landslide_path": str(landslide_path),
        "segfault_isolated_to_package_initializer": bool(reproduced),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())