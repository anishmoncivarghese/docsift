from docsift.core.models import ComparisonResult, EngineRunSummary

_METRICS: tuple[str, ...] = (
    "engine_version",
    "duration_ms",
    "characters",
    "words",
    "estimated_tokens",
    "heading_count",
    "table_count",
    "warning_count",
    "ocr_used",
)


def _cell(run: EngineRunSummary, metric: str) -> str:
    value = getattr(run, metric)
    if not run.success or value is None:
        return "—"
    return str(value)


def render_report(comparison: ComparisonResult) -> str:
    source = comparison.source
    lines = [
        f"# Comparison: {source.filename}",
        "",
        f"{source.size_bytes} bytes · sha256 {source.sha256[:12]} · "
        f"docsift {comparison.docsift_version} · {comparison.created_at.isoformat()}",
        "",
        "| metric | " + " | ".join(run.engine for run in comparison.runs) + " |",
        "|" + "---|" * (len(comparison.runs) + 1),
        "| status | "
        + " | ".join("ok" if run.success else "failed" for run in comparison.runs)
        + " |",
    ]
    for metric in _METRICS:
        lines.append(
            f"| {metric} | " + " | ".join(_cell(run, metric) for run in comparison.runs) + " |"
        )
    failures = [run for run in comparison.runs if not run.success]
    if failures:
        lines += ["", "## Errors", ""]
        lines += [f"- **{run.engine}**: {run.error}" for run in failures]
    return "\n".join(lines) + "\n"
