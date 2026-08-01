from docsift.core.models import ComparisonResult


def render_report(comparison: ComparisonResult) -> str:
    return f"# Comparison: {comparison.source.filename}\n"
