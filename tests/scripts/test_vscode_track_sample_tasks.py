import json
from pathlib import Path


def test_track_sample_manifest_task_paths_with_spaces_are_shell_quoted():
    tasks_path = Path(".vscode/tasks.json")
    data = json.loads(tasks_path.read_text(encoding="utf-8"))

    found = 0
    for task in data.get("tasks", []):
        args = task.get("args") or []
        for index, arg in enumerate(args[:-1]):
            if arg != "--track-sample-manifest":
                continue
            found += 1
            manifest_arg = args[index + 1]
            if isinstance(manifest_arg, dict):
                value = str(manifest_arg.get("value") or "")
                assert manifest_arg.get("quoting") == "strong"
            else:
                value = str(manifest_arg)
                assert " " not in value
            assert "Tracks_NA_Guadeloupe" in value

    assert found >= 4
