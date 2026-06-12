#!/usr/bin/env python3
# SCOPE: os-only
"""cos-coverage — Agent Capability Coverage (ACC) metric CLI.

Composes data from:
  - .cognitive-os/metrics/aspirational-audit.jsonl   (REAL/DORMANT/ASPIRATIONAL counts)
  - .cognitive-os/coverage-tiers.json                (tier breakdown A/B/C/D)
  - docs/06-Daily/reports/claim-proof-latest.md               (mapped/unmapped/weak-proof counts)
  - .cognitive-os/metrics/coverage-history.jsonl     (trend vs last snapshot)

Cache: .cognitive-os/runtime/coverage-snapshot.json (TTL 30s) to keep p95 < 300ms.
Daily snapshot appended to .cognitive-os/metrics/coverage-history.jsonl.

On every recompute (cache miss or --refresh) a stable per-project artifact is
written to .cognitive-os/reports/coverage-latest.json using the
``cos-project-coverage.v1`` schema (consumed by the cos-glass GUI):

  - mode "project": the directory is an INSTALLED project
    (.cognitive-os/install-meta.json present, ACC source inputs absent).
    Counts come from actual entries in .cognitive-os/{hooks,rules,skills}.
  - mode "source-repo": ACC numbers are mapped into the same summary shape
    and components reflect the repo's own hooks/, rules/, skills/ dirs.

Usage:
  python3 scripts/cos_coverage.py          # human summary (default)
  python3 scripts/cos_coverage.py --json   # machine-readable JSON
  python3 scripts/cos_coverage.py --brief  # one-line statusline output
  python3 scripts/cos_coverage.py --refresh # force cache refresh
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

CACHE_TTL_SECONDS = 30
SNAPSHOT_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"


# ── Project root resolution ────────────────────────────────────────────────────

def find_project_dir(hint: str | None = None) -> Path:
    if hint:
        return Path(hint).resolve()
    for env in ("COGNITIVE_OS_PROJECT_DIR", "CODEX_PROJECT_DIR", "CLAUDE_PROJECT_DIR"):
        val = os.environ.get(env, "")
        if val:
            return Path(val).resolve()
    # walk up for .git
    candidate = Path.cwd()
    while candidate != candidate.parent:
        if (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    return Path.cwd()


# ── Claim-proof data ──────────────────────────────────────────────────────────

def parse_claim_proof(project_dir: Path) -> dict[str, int]:
    """Return {mapped, weak_proof, unmapped} from claim-proof-latest.md."""
    report = project_dir / "docs" / "06-Daily" / "reports" / "claim-proof-latest.md"
    result = {"mapped": 0, "weak_proof": 0, "unmapped": 0}
    if not report.exists():
        return result
    text = report.read_text(errors="replace")
    patterns = {
        "mapped": r"mapped:\s*(\d+)",
        "weak_proof": r"weak-proof:\s*(\d+)",
        "unmapped": r"unmapped:\s*(\d+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result[key] = int(m.group(1))
    return result


# ── Aspirational-audit counts ─────────────────────────────────────────────────

def parse_audit_counts(project_dir: Path) -> dict[str, int]:
    """Return classification counts from aspirational-audit.jsonl (deduplicated)."""
    audit = project_dir / ".cognitive-os" / "metrics" / "aspirational-audit.jsonl"
    if not audit.exists():
        return {}
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    with audit.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload", {})
            component = payload.get("component", "")
            classification = payload.get("classification", "UNKNOWN")
            key = (component, classification)
            if key not in seen:
                seen.add(key)
                counts[classification] += 1
    return dict(counts)


# ── Tier breakdown ─────────────────────────────────────────────────────────────

def parse_tier_counts(project_dir: Path) -> dict[str, int]:
    """Return tier counts from coverage-tiers.json if present."""
    tiers_file = project_dir / ".cognitive-os" / "coverage-tiers.json"
    if not tiers_file.exists():
        return {}
    try:
        tiers: dict[str, str] = json.loads(tiers_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    counts: Counter[str] = Counter(tiers.values())
    return dict(counts)


# ── Coverage percentage ────────────────────────────────────────────────────────

def compute_coverage_pct(audit_counts: dict[str, int]) -> float:
    """Coverage = REAL / (REAL + DORMANT + ASPIRATIONAL) * 100."""
    real = audit_counts.get("REAL", 0)
    dormant = audit_counts.get("DORMANT", 0)
    aspirational = audit_counts.get("ASPIRATIONAL", 0)
    total = real + dormant + aspirational
    if total == 0:
        return 0.0
    return round(real / total * 100, 1)


# ── History / trend ───────────────────────────────────────────────────────────

def load_last_snapshot(project_dir: Path) -> dict | None:
    """Return last daily snapshot from coverage-history.jsonl, or None."""
    history = project_dir / ".cognitive-os" / "metrics" / "coverage-history.jsonl"
    if not history.exists():
        return None
    last_acc: dict | None = None
    with history.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Accept both pre-existing coverage_measurement events and our own acc_snapshot events
            event_type = record.get("event_type", "")
            if event_type in ("acc_snapshot", "coverage_measurement"):
                last_acc = record
    return last_acc


def compute_trend(current: dict, last: dict | None) -> dict[str, str]:
    """Return trend arrows for coverage_pct, real, dormant."""
    if last is None:
        return {}
    lp = last.get("payload", {})
    trend: dict[str, str] = {}

    def arrow(curr: float, prev: float) -> str:
        if curr > prev:
            return "up"
        if curr < prev:
            return "down"
        return "flat"

    if "coverage_pct" in lp:
        trend["coverage_pct"] = arrow(current["coverage_pct"], lp["coverage_pct"])
    if "real" in lp:
        trend["real"] = arrow(current["real"], lp.get("real", 0))
    if "dormant" in lp:
        trend["dormant"] = arrow(current["dormant"], lp.get("dormant", 0))

    return trend


ARROW_MAP = {"up": "↑", "down": "↓", "flat": "→", "": ""}


def append_daily_snapshot(project_dir: Path, snapshot: dict) -> None:
    """Append a daily acc_snapshot to coverage-history.jsonl if not already done today."""
    history = project_dir / ".cognitive-os" / "metrics" / "coverage-history.jsonl"
    today = time.strftime("%Y-%m-%d", time.gmtime())

    # Check if today's snapshot already exists
    if history.exists():
        with history.open(errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event_type") == "acc_snapshot":
                    ts = record.get("timestamp", "")
                    if ts.startswith(today):
                        return  # Already wrote today

    history.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.strftime(SNAPSHOT_TIMESTAMP_FMT, time.gmtime()),
        "source": "cos-coverage",
        "event_type": "acc_snapshot",
        "payload": snapshot,
    }
    with history.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── Cache management ──────────────────────────────────────────────────────────

def load_cache(project_dir: Path) -> dict | None:
    cache_path = project_dir / ".cognitive-os" / "runtime" / "coverage-snapshot.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    cached_at = data.get("_cached_at", 0)
    if time.time() - cached_at > CACHE_TTL_SECONDS:
        return None
    return data


def write_cache(project_dir: Path, data: dict) -> None:
    cache_path = project_dir / ".cognitive-os" / "runtime" / "coverage-snapshot.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data["_cached_at"] = time.time()
    cache_path.write_text(json.dumps(data))


# ── Per-project coverage artifact (cos-project-coverage.v1) ──────────────────

ARTIFACT_SCHEMA_VERSION = "cos-project-coverage.v1"
ARTIFACT_SURFACES = ("hooks", "rules", "skills")
INSTALL_META_COUNT_KEYS = {
    "hooks": "hooks_installed",
    "rules": "rules_installed",
    "skills": "skills_installed",
}


def acc_inputs_present(project_dir: Path) -> bool:
    """True when any ACC source input exists in the directory."""
    candidates = (
        project_dir / ".cognitive-os" / "metrics" / "aspirational-audit.jsonl",
        project_dir / ".cognitive-os" / "coverage-tiers.json",
        project_dir / "docs" / "06-Daily" / "reports" / "claim-proof-latest.md",
    )
    return any(path.exists() for path in candidates)


def detect_mode(project_dir: Path) -> str:
    """Return 'project' for installed projects, 'source-repo' otherwise.

    'project' requires .cognitive-os/install-meta.json AND no ACC source
    inputs (aspirational-audit.jsonl / coverage-tiers.json / claim-proof md).
    """
    install_meta = project_dir / ".cognitive-os" / "install-meta.json"
    if install_meta.exists() and not acc_inputs_present(project_dir):
        return "project"
    return "source-repo"


def read_install_meta(project_dir: Path) -> dict:
    """Return parsed install-meta.json, or {} when missing/invalid."""
    meta_path = project_dir / ".cognitive-os" / "install-meta.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _skip_entry(name: str) -> bool:
    """Skip hidden and underscore-prefixed entries (e.g. _lib, __contracts__)."""
    return name.startswith(".") or name.startswith("_")


def _iter_entries(root: Path, _visited: set[Path] | None = None):
    """Recursively yield (path, is_dir) under root.

    Follows symlinked directories with loop protection (resolved-dir visited
    set). Hidden and underscore-prefixed names are skipped at every level.
    """
    if _visited is None:
        _visited = set()
    try:
        real_root = root.resolve()
    except OSError:
        return
    if real_root in _visited:
        return
    _visited.add(real_root)
    try:
        children = sorted(root.iterdir())
    except OSError:
        return
    for child in children:
        if _skip_entry(child.name):
            continue
        if child.is_dir():  # follows symlinks to directories
            yield child, True
            yield from _iter_entries(child, _visited)
        elif child.is_file():  # follows symlinks to files
            yield child, False


def _resolve_safe(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def count_hook_components(root: Path) -> int:
    """Count hook scripts (*.sh files) under root, symlink-deduplicated."""
    if not root.is_dir():
        return 0
    seen: set[Path] = set()
    for entry, is_dir in _iter_entries(root):
        if not is_dir and entry.suffix == ".sh":
            seen.add(_resolve_safe(entry))
    return len(seen)


def count_rule_components(root: Path) -> int:
    """Count rule files (*.md) under root, symlink-deduplicated."""
    if not root.is_dir():
        return 0
    seen: set[Path] = set()
    for entry, is_dir in _iter_entries(root):
        if not is_dir and entry.suffix == ".md":
            seen.add(_resolve_safe(entry))
    return len(seen)


def count_skill_components(root: Path) -> int:
    """Count skill dirs (directories containing SKILL.md), symlink-deduplicated."""
    if not root.is_dir():
        return 0
    seen: set[Path] = set()
    for entry, is_dir in _iter_entries(root):
        if is_dir and (entry / "SKILL.md").is_file():
            seen.add(_resolve_safe(entry))
    return len(seen)


_SURFACE_COUNTERS = {
    "hooks": count_hook_components,
    "rules": count_rule_components,
    "skills": count_skill_components,
}


def count_installed_components(project_dir: Path, mode: str) -> dict[str, int]:
    """Actual on-disk component counts per surface.

    project mode: .cognitive-os/{hooks,rules,skills}
    source-repo mode: the repo's own {hooks,rules,skills} dirs
    """
    base = project_dir / ".cognitive-os" if mode == "project" else project_dir
    return {
        surface: _SURFACE_COUNTERS[surface](base / surface)
        for surface in ARTIFACT_SURFACES
    }


def build_coverage_artifact(project_dir: Path, acc_data: dict | None = None) -> dict:
    """Build the cos-project-coverage.v1 artifact payload."""
    mode = detect_mode(project_dir)
    actual = count_installed_components(project_dir, mode)
    components = {
        surface: {"installed": actual[surface]} for surface in ARTIFACT_SURFACES
    }

    if mode == "project":
        meta = read_install_meta(project_dir)
        expected: dict[str, int] = {}
        for surface, key in INSTALL_META_COUNT_KEYS.items():
            value = meta.get(key)
            # Fall back to the actual count when install-meta lacks the field.
            expected[surface] = value if isinstance(value, int) and value >= 0 \
                else actual[surface]
        total = sum(expected.values())
        wired = min(sum(actual.values()), total)
        summary = {
            "total": total,
            "wired": wired,
            "partial": 0,
            "missing": total - wired,
        }
    else:
        acc = acc_data or {}
        real = int(acc.get("real", 0))
        dormant = int(acc.get("dormant", 0))
        aspirational = int(acc.get("aspirational", 0))
        summary = {
            "total": real + dormant + aspirational,
            "wired": real,
            "partial": dormant,
            "missing": aspirational,
        }

    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_at": time.strftime(SNAPSHOT_TIMESTAMP_FMT, time.gmtime()),
        "mode": mode,
        "summary": summary,
        "components": components,
        "surfaces": list(ARTIFACT_SURFACES),
    }


def write_coverage_artifact(project_dir: Path, acc_data: dict | None = None) -> Path:
    """Atomically write coverage-latest.json; returns the artifact path."""
    artifact = build_coverage_artifact(project_dir, acc_data)
    reports_dir = project_dir / ".cognitive-os" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    final_path = reports_dir / "coverage-latest.json"
    tmp_path = reports_dir / f".coverage-latest.json.tmp.{os.getpid()}"
    try:
        tmp_path.write_text(json.dumps(artifact, indent=2) + "\n")
        os.replace(tmp_path, final_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return final_path


# ── Data composition ──────────────────────────────────────────────────────────

def compose_data(project_dir: Path) -> dict:
    """Compose all coverage metrics into a single dict."""
    claim_proof = parse_claim_proof(project_dir)
    audit_counts = parse_audit_counts(project_dir)
    tier_counts = parse_tier_counts(project_dir)
    coverage_pct = compute_coverage_pct(audit_counts)

    snapshot_payload = {
        "coverage_pct": coverage_pct,
        "real": audit_counts.get("REAL", 0),
        "dormant": audit_counts.get("DORMANT", 0),
        "aspirational": audit_counts.get("ASPIRATIONAL", 0),
        "on_demand": audit_counts.get("ON_DEMAND", 0),
        "metadata": audit_counts.get("METADATA", 0),
        "mapped": claim_proof.get("mapped", 0),
        "weak_proof": claim_proof.get("weak_proof", 0),
        "unmapped": claim_proof.get("unmapped", 0),
        "tiers": tier_counts,
    }

    last_snapshot = load_last_snapshot(project_dir)
    trend = compute_trend(snapshot_payload, last_snapshot)

    return {
        "project": str(project_dir),
        "generated_at": time.strftime(SNAPSHOT_TIMESTAMP_FMT, time.gmtime()),
        **snapshot_payload,
        "trend": trend,
    }


# ── Formatters ────────────────────────────────────────────────────────────────

def format_human(data: dict) -> str:
    trend = data.get("trend", {})

    def t(key: str) -> str:
        return ARROW_MAP.get(trend.get(key, ""), "")

    lines = [
        f"Agent Capability Coverage (ACC)  {data.get('generated_at', '')}",
        "",
        f"  Coverage:   {data['coverage_pct']}%{t('coverage_pct')}",
        "",
        "  Component classifications:",
        f"    REAL:         {data['real']:>6}{t('real')}",
        f"    DORMANT:      {data['dormant']:>6}{t('dormant')}",
        f"    ASPIRATIONAL: {data['aspirational']:>6}",
        f"    ON_DEMAND:    {data['on_demand']:>6}",
        f"    METADATA:     {data['metadata']:>6}",
        "",
        "  Claim-proof audit:",
        f"    Mapped:       {data['mapped']:>6}",
        f"    Weak-proof:   {data['weak_proof']:>6}",
        f"    Unmapped:     {data['unmapped']:>6}",
    ]

    tiers = data.get("tiers", {})
    if tiers:
        lines.append("")
        lines.append("  Dormant/Aspirational tiers (from coverage-tiers.json):")
        for tier in ("A", "B", "C", "D"):
            label = {
                "A": "Safety-critical",
                "B": "Infrastructure",
                "C": "Advisory/feature-gated",
                "D": "Skills+rules metadata",
            }.get(tier, tier)
            count = tiers.get(tier, 0)
            lines.append(f"    Tier {tier} ({label}): {count}")

    if trend:
        lines.append("")
        arrows = [f"{k} {ARROW_MAP[v]}" for k, v in trend.items() if v in ("up", "down")]
        if arrows:
            lines.append(f"  Trend vs last snapshot: {', '.join(arrows)}")

    return "\n".join(lines)


def format_brief(data: dict) -> str:
    """One-line output for statusline: ACC: 85% | REAL: 1860 DORM: 1393"""
    pct = data["coverage_pct"]
    real = data["real"]
    dorm = data["dormant"]
    trend = data.get("trend", {})
    pct_arrow = ARROW_MAP.get(trend.get("coverage_pct", ""), "")
    return f"ACC: {pct}%{pct_arrow} | REAL: {real} DORM: {dorm}"


def format_json(data: dict) -> str:
    # Remove internal cache field before output
    out = {k: v for k, v in data.items() if not k.startswith("_")}
    return json.dumps(out, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show Agent Capability Coverage (ACC) metrics."
    )
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output as JSON for machine consumption.")
    parser.add_argument("--brief", action="store_true",
                        help="One-line output for statusline integration.")
    parser.add_argument("--refresh", action="store_true",
                        help="Force cache refresh (ignore TTL).")
    parser.add_argument("--project-dir", default=None,
                        help="Project root directory.")
    args = parser.parse_args()

    project_dir = find_project_dir(args.project_dir)

    # Try cache first (unless refresh requested)
    data: dict | None = None
    if not args.refresh:
        data = load_cache(project_dir)

    if data is None:
        data = compose_data(project_dir)
        write_cache(project_dir, data)
        # Append daily snapshot for trend history
        snapshot_payload = {
            k: data[k]
            for k in (
                "coverage_pct", "real", "dormant", "aspirational",
                "on_demand", "metadata", "mapped", "weak_proof", "unmapped", "tiers",
            )
            if k in data
        }
        append_daily_snapshot(project_dir, snapshot_payload)
        # Stable per-project artifact for GUI consumers (cos-glass).
        write_coverage_artifact(project_dir, data)

    if args.json_out:
        print(format_json(data))
    elif args.brief:
        print(format_brief(data))
    else:
        print(format_human(data))


if __name__ == "__main__":
    main()
