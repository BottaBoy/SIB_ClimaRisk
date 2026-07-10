from pathlib import Path

from scripts import run_complete_analysis


def test_track_sample_manifest_directory_resolves_by_dynamic_track_count(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs" / "Échantillons Tracks_NA_Guadeloupe"
    manifest = output_root / "sample_0050" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_complete_analysis, "TRACK_SAMPLE_OUTPUT_ROOT", output_root)

    resolved = run_complete_analysis._resolve_track_sample_manifest_path(
        str(output_root),
        50,
    )

    assert resolved == manifest


def test_track_sample_manifest_truncated_directory_prefix_resolves_by_dynamic_track_count(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs" / "Échantillons Tracks_NA_Guadeloupe"
    manifest = output_root / "sample_0050" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_complete_analysis, "TRACK_SAMPLE_OUTPUT_ROOT", output_root)

    resolved = run_complete_analysis._resolve_track_sample_manifest_path(
        str(tmp_path / "outputs" / "Échantillons"),
        50,
    )

    assert resolved == manifest


def test_track_sample_manifest_sample_directory_resolves_to_manifest(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs" / "Échantillons Tracks_NA_Guadeloupe"
    manifest = output_root / "sample_0050" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_complete_analysis, "TRACK_SAMPLE_OUTPUT_ROOT", output_root)

    resolved = run_complete_analysis._resolve_track_sample_manifest_path(
        str(manifest.parent),
        50,
    )

    assert resolved == manifest


def test_track_sample_manifest_file_path_is_preserved(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs" / "Échantillons Tracks_NA_Guadeloupe"
    manifest = output_root / "sample_0800" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_complete_analysis, "TRACK_SAMPLE_OUTPUT_ROOT", output_root)

    resolved = run_complete_analysis._resolve_track_sample_manifest_path(
        str(manifest),
        800,
    )

    assert resolved == manifest
