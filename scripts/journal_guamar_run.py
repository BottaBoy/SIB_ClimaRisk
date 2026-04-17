#!/usr/bin/env python3
"""Journal helper for Guadeloupe / Martinique reruns.

Rule: every completed Guadeloupe/Martinique run must be journalized here
immediately after the page-analysis artefacts are written.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import zlib
from typing import Any


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL_JSONL = REPO_ROOT / "docs" / "Journalisation_Run_GuaMar.jsonl"
JOURNAL_MD = REPO_ROOT / "docs" / "Journalisation_Run_GuaMar.md"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_meta(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return meta if isinstance(meta, dict) else {}


def _load_meta_from_value(raw_path: Any) -> dict[str, Any]:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    return _load_meta(path)


def _is_case_study_row(payload: dict[str, Any]) -> bool:
    territory = str(payload.get("territory") or "").strip().lower()
    hazard = str(payload.get("hazard") or "").strip().lower()
    if territory not in {"guadeloupe", "martinique"}:
        return False
    if hazard not in {"storm", "storm_cmcc"}:
        return False
    generated_at = str(payload.get("generated_at") or "").strip()
    return bool(generated_at)


def _normalize_track_ids(track_ids: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in track_ids or []:
        sid = str(raw or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def encode_track_ids(track_ids: Any) -> dict[str, Any]:
    ids = sorted(_normalize_track_ids(track_ids))
    raw = "\n".join(ids).encode("utf-8")
    compressed = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
    preview: list[str]
    if len(ids) <= 6:
        preview = ids
    else:
        preview = ids[:3] + ["..."] + ids[-3:]
    return {
        "encoding": "zlib+base64",
        "data": compressed,
        "count": len(ids),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "preview": preview,
    }


def decode_track_ids(blob: dict[str, Any] | None) -> list[str]:
    if not isinstance(blob, dict):
        return []
    data = str(blob.get("data") or "").strip()
    if not data:
        return []
    encoding = str(blob.get("encoding") or "").strip().lower()
    if encoding not in {"zlib+base64", "base64+zlib"}:
        return []
    try:
        raw = zlib.decompress(base64.b64decode(data.encode("ascii"))).decode("utf-8")
    except Exception:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _read_history() -> list[dict[str, Any]]:
    if not JOURNAL_JSONL.exists():
        return []
    history: list[dict[str, Any]] = []
    for raw_line in JOURNAL_JSONL.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict) and _is_case_study_row(payload):
            history.append(payload)
    return history


def _write_history(history: list[dict[str, Any]]) -> None:
    JOURNAL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in history)
    JOURNAL_JSONL.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def _row_track_digest(blob: dict[str, Any] | None) -> str:
    if not isinstance(blob, dict):
        return "-"
    count = int(blob.get("count") or 0)
    sha = str(blob.get("sha256") or "")[:12]
    preview = blob.get("preview")
    if isinstance(preview, list) and preview:
        preview_text = ", ".join(str(item) for item in preview)
    else:
        preview_text = "-"
    # Markdown table cells must not contain unescaped pipes.
    return f"{count} ids / {sha} / {preview_text}"


def _format_value(value: Any, *, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def _format_bool(value: Any) -> str:
    if value is None:
        return "-"
    return "oui" if bool(value) else "non"


def _compute_overlap_pct(current_ids: list[str], previous_ids: list[str] | None) -> float | None:
    if not current_ids or not previous_ids:
        return None
    current_set = set(current_ids)
    previous_set = set(previous_ids)
    if not current_set:
        return None
    shared = len(current_set & previous_set)
    return round((shared / float(len(current_set))) * 100.0, 2)


def _extract_run_entry(
    *,
    territory: str,
    hazard_key: str,
    wind_meta: dict[str, Any],
    page_meta: dict[str, Any],
    proxy_meta: dict[str, Any],
    impact_summary: dict[str, Any],
    session_run_id: str | None = None,
) -> dict[str, Any]:
    track_journal = wind_meta.get("track_journal")
    if not isinstance(track_journal, dict) or hazard_key not in track_journal:
        raise ValueError(
            f"Missing track_journal for territory={territory}, hazard={hazard_key}"
        )
    hazard_journal = track_journal.get(hazard_key) or {}
    track_blob = hazard_journal.get("track_ids_compressed") if isinstance(hazard_journal, dict) else None
    current_track_ids = decode_track_ids(track_blob if isinstance(track_blob, dict) else None)
    if not current_track_ids:
        raise ValueError(
            f"Unable to decode selected track IDs for territory={territory}, hazard={hazard_key}"
        )
    n_events = int(hazard_journal.get("n_events") or len(current_track_ids))
    sum_event_frequency = float(hazard_journal.get("event_frequency_sum") or 0.0)

    summary = impact_summary.get(hazard_key) if isinstance(impact_summary, dict) else {}
    if not isinstance(summary, dict):
        raise ValueError(
            f"Missing impact summary for territory={territory}, hazard={hazard_key}"
        )
    wind_pml_50 = float(summary.get("rp50_total_loss_eur") or 0.0)
    wind_pml_100 = float(summary.get("rp100_total_loss_eur") or 0.0)
    component_light_rerun = page_meta.get("component_light_rerun")
    sampling_spacing_m = float(page_meta.get("sampling_spacing_m") or 0.0)
    max_points_total = int(proxy_meta.get("max_points_total") or 0)
    max_points_per_feature = int(proxy_meta.get("max_points_per_feature") or 0)
    component_light_rerun_active = isinstance(component_light_rerun, dict) and bool(component_light_rerun)
    if (not max_points_total or not max_points_per_feature) and component_light_rerun_active:
        max_points_total = int(component_light_rerun.get("max_points_total") or max_points_total or 0)
        max_points_per_feature = int(component_light_rerun.get("max_points_per_feature") or max_points_per_feature or 0)

    return {
        "territory": territory,
        "hazard": hazard_key.upper(),
        "generated_at": str(page_meta.get("generated_at") or wind_meta.get("generated_at") or datetime.now(UTC).replace(microsecond=0).isoformat()),
        "case_study_run_id": str(page_meta.get("case_study_run_id") or wind_meta.get("case_study_run_id") or ""),
        "session_run_id": str(session_run_id or page_meta.get("case_study_run_id") or wind_meta.get("case_study_run_id") or ""),
        "dynamic_max_tracks": int(wind_meta.get("dynamic_max_tracks") or wind_meta.get("native_dynamic_max_tracks") or 0),
        "sampling_spacing_m": round(sampling_spacing_m, 2),
        "max_points_total": max_points_total,
        "max_points_per_feature": max_points_per_feature,
        "component_light_rerun_active": component_light_rerun_active,
        "sum_event_frequency": round(sum_event_frequency, 8),
        "n_events": n_events,
        "wind_pml_50": round(wind_pml_50, 2),
        "wind_pml_100": round(wind_pml_100, 2),
        "track_ids_compressed": track_blob if isinstance(track_blob, dict) else None,
        "track_ids_count": int(track_blob.get("count") or n_events) if isinstance(track_blob, dict) else n_events,
        "track_ids_sha256": str(track_blob.get("sha256") or "") if isinstance(track_blob, dict) else "",
        "_current_track_ids": current_track_ids,
    }


def record_guamar_run(territory: str, *, session_run_id: str | None = None) -> list[dict[str, Any]]:
    territory = str(territory).strip().lower()
    if territory not in {"guadeloupe", "martinique"}:
        raise ValueError("territory must be 'guadeloupe' or 'martinique'")

    wind_map_path = REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"
    page_suffix = "page2" if territory == "martinique" else "page1"
    page_path = REPO_ROOT / "web" / "data" / f"{territory}-{page_suffix}-analysis.json"

    wind_meta = _load_meta(wind_map_path)
    page_payload = _load_json(page_path)
    page_meta = page_payload.get("meta") if isinstance(page_payload, dict) else {}
    impact = page_payload.get("impact") if isinstance(page_payload, dict) else {}
    impact_summary = impact.get("summary_metrics") if isinstance(impact, dict) else {}
    if not isinstance(page_meta, dict):
        page_meta = {}
    if not isinstance(impact_summary, dict):
        impact_summary = {}
    proxy_meta = _load_meta_from_value(page_meta.get("multi_hazard_proxy_json"))

    history = _read_history()
    new_rows: list[dict[str, Any]] = []
    current_case_study_run_id = str(page_meta.get("case_study_run_id") or wind_meta.get("case_study_run_id") or session_run_id or "")
    if current_case_study_run_id:
        history = [
            row
            for row in history
            if not (
                str(row.get("case_study_run_id") or "") == current_case_study_run_id
                and str(row.get("territory") or "").lower() == territory
                and str(row.get("hazard") or "").lower() in {"storm", "storm_cmcc"}
            )
        ]
    for hazard_key in ("storm", "storm_cmcc"):
        row = _extract_run_entry(
            territory=territory,
            hazard_key=hazard_key,
            wind_meta=wind_meta,
            page_meta=page_meta,
            proxy_meta=proxy_meta,
            impact_summary=impact_summary,
            session_run_id=session_run_id,
        )
        previous_ids: list[str] | None = None
        previous_row: dict[str, Any] | None = None
        for prev in reversed(history):
            if (
                str(prev.get("territory") or "").lower() == territory
                and str(prev.get("hazard") or "").lower() == hazard_key.lower()
            ):
                previous_ids = decode_track_ids(prev.get("track_ids_compressed"))
                previous_row = prev
                break
        if previous_row is not None:
            row["previous_case_study_run_id"] = str(previous_row.get("case_study_run_id") or "")
            row["previous_generated_at"] = str(previous_row.get("generated_at") or "")
            row["common_track_share_pct"] = _compute_overlap_pct(row["_current_track_ids"], previous_ids)
        else:
            row["previous_case_study_run_id"] = ""
            row["previous_generated_at"] = ""
            row["common_track_share_pct"] = None
        row.pop("_current_track_ids", None)
        new_rows.append(row)

    history.extend(new_rows)
    _write_history(history)
    _render_markdown(history)
    return new_rows


def _render_markdown(history: list[dict[str, Any]]) -> None:
    JOURNAL_MD.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(
        history,
        key=lambda row: (
            str(row.get("generated_at") or ""),
            str(row.get("territory") or ""),
            str(row.get("hazard") or ""),
        ),
        reverse=True,
    )
    lines: list[str] = []
    lines.append("# Journalisation_Run_GuaMar")
    lines.append("")
    lines.append("Journal des reruns Guadeloupe / Martinique.")
    lines.append("")
    lines.append("Règle: chaque run terminé doit être journalisé automatiquement juste après la génération des artefacts de page.")
    lines.append("")
    lines.append("Le journal brut est stocke dans `docs/Journalisation_Run_GuaMar.jsonl`.")
    lines.append("Les identifiants de tracks sont stockes compresses en `zlib+base64` dans le journal brut.")
    lines.append("Le pourcentage de tracks communs correspond a `|A ∩ B| / |A|` entre le run courant et le run precedent du meme territoire et du meme alea.")
    lines.append("`sampling_spacing_m` vient du JSON de page; `max_points_total` et `max_points_per_feature` viennent du proxy multi-aléas léger utilisé pour la page; `component_light_rerun_active` indique si la page contient un bloc `component_light_rerun`.")
    lines.append("")
    if not sorted_rows:
        lines.append("Aucune entree journalisee pour le moment.")
        lines.append("")
        JOURNAL_MD.write_text("\n".join(lines), encoding="utf-8")
        return

    lines.append("| Date du run | ID de session | Territoire | Alea | dynamic_max_tracks | sampling_spacing_m | max_points_total | max_points_per_feature | component_light_rerun_active | sum(event_frequency) | n_events | % tracks communs vs run precedent | wind_pml_50 | wind_pml_100 | Track IDs compacts |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|")
    for row in sorted_rows:
        overlap = row.get("common_track_share_pct")
        overlap_text = "-" if overlap is None else _format_value(overlap, digits=2)
        session_id = str(row.get("session_run_id") or row.get("case_study_run_id") or "-")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("generated_at") or "-"),
                    session_id,
                    str(row.get("territory") or "-"),
                    str(row.get("hazard") or "-"),
                    str(int(row.get("dynamic_max_tracks") or 0)),
                    _format_value(row.get("sampling_spacing_m"), digits=2),
                    str(int(row.get("max_points_total") or 0)) if row.get("max_points_total") is not None else "-",
                    str(int(row.get("max_points_per_feature") or 0)) if row.get("max_points_per_feature") is not None else "-",
                    _format_bool(row.get("component_light_rerun_active")),
                    _format_value(row.get("sum_event_frequency"), digits=6),
                    str(int(row.get("n_events") or 0)),
                    overlap_text,
                    _format_value(row.get("wind_pml_50"), digits=2),
                    _format_value(row.get("wind_pml_100"), digits=2),
                    _row_track_digest(row.get("track_ids_compressed")),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("Notes:")
    lines.append("- `ID de session` est identique pour les quatre lignes produites par un meme rerun Guadeloupe + Martinique.")
    lines.append("- La comparaison `% tracks communs vs run precedent` se fait avec le dernier run du meme territoire et du meme alea.")
    lines.append("- `n_events` correspond au nombre de tracks uniques journalises pour le run courant.")
    lines.append("- `max_points_total` et `max_points_per_feature` journalisent le proxy multi-aléas léger utilisé pour la page, pas le maillage principal de la page.")
    lines.append("- `component_light_rerun_active` signale la présence du bloc `component_light_rerun` dans le JSON de page.")
    lines.append("- `Track IDs compacts` affiche `count | sha256[0:12] | preview` ; la liste complete est stockee dans le JSONL compressé.")
    lines.append("")
    JOURNAL_MD.write_text("\n".join(lines), encoding="utf-8")
