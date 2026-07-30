import json
from pathlib import Path


def test_track_sample_manifest_task_paths_with_spaces_are_shell_quoted():
    tasks_path = Path(".vscode/tasks.json")
    data = json.loads(tasks_path.read_text(encoding="utf-8"))

    found = 0
    for task in data.get("tasks", []):
        task_type = str(task.get("type") or "")
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
                if task_type != "process":
                    assert " " not in value
            assert "Tracks_NA_Guadeloupe" in value

    assert found >= 4


def test_v2_intensity_track_sample_tasks_point_to_quoted_manifests():
    tasks_path = Path(".vscode/tasks.json")
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    expected = {
        50: "${workspaceFolder}/outputs/Échantillons Tracks_NA_Guadeloupe/V2/sample_0050/manifest.json",
        100: "${workspaceFolder}/outputs/Échantillons Tracks_NA_Guadeloupe/V2/sample_0100/manifest.json",
        800: "${workspaceFolder}/outputs/Échantillons Tracks_NA_Guadeloupe/V2/sample_0800/manifest.json",
        1500: "${workspaceFolder}/outputs/Échantillons Tracks_NA_Guadeloupe/V2/sample_1500/manifest.json",
        5000: "${workspaceFolder}/outputs/Échantillons Tracks_NA_Guadeloupe/V2/sample_5000/manifest.json",
    }
    found: dict[int, str] = {}

    for task in data.get("tasks", []):
        label = str(task.get("label") or "")
        if not label.startswith("SIB: Run Complete Analysis V2 Intensity"):
            continue
        args = task.get("args") or []
        size = int(args[args.index("--dynamic-max-tracks") + 1])
        manifest_arg = args[args.index("--track-sample-manifest") + 1]
        assert isinstance(manifest_arg, dict)
        assert manifest_arg.get("quoting") == "strong"
        found[size] = str(manifest_arg.get("value") or "")

    assert found == expected


def test_full_tracks_single_territory_tasks_have_no_deploy_contract():
    tasks_path = Path(".vscode/tasks.json")
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = {str(task.get("label") or ""): task for task in data.get("tasks", [])}
    expected = {
        "SIB: Run Complete Analysis (Full Tracks: Guadeloupe Only, No Deploy)": "gua",
        "SIB: Run Complete Analysis (Full Tracks: Martinique Only, No Deploy)": "mar",
        "SIB: Run Complete Analysis (Full Tracks: Saint-Barthélemy Only, No Deploy)": "stb",
    }

    for label, territory in expected.items():
        task = tasks[label]
        args = task.get("args") or []
        assert args[args.index("--territories") + 1] == territory
        assert args[args.index("--dynamic-max-tracks") + 1] == "0"
        assert "--no-deploy" in args
        assert "--track-sample-manifest" not in args


def test_sensitivity_default_pack_v2_task_uses_v1_sample_and_significant_graph_task():
    tasks_path = Path(".vscode/tasks.json")
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = {str(task.get("label") or ""): task for task in data.get("tasks", [])}

    run_task = tasks["SIB: Run Sensitivity Analysis Default Pack V2"]
    run_args = run_task.get("args") or []
    assert run_task.get("type") == "process"
    assert run_args[run_args.index("--scenario-pack") + 1] == "config/sensitivity/default-scenario-pack-v2.json"
    assert run_args[run_args.index("--dynamic-max-tracks") + 1] == "1500"
    assert run_args[run_args.index("--track-sample-manifest") + 1] == "${workspaceFolder}/outputs/Échantillons Tracks_NA_Guadeloupe/sample_1500/manifest.json"
    assert run_args[run_args.index("--child-max-points-per-shard") + 1] == "3000"
    assert "--continue-on-error" in run_args

    graph_task = tasks["SIB: Generate Sensitivity V2 Significant Graphs - Choose Run ID"]
    graph_command = " ".join(str(arg) for arg in graph_task.get("args") or [])
    assert "--disable-default-exclusions" in graph_command
    assert "--significant-only" in graph_command
    assert "--impact-significance-threshold-pct 3" in graph_command
    assert "--network-significance-threshold-pp 3" in graph_command
    assert "graphs-significant" in graph_command
