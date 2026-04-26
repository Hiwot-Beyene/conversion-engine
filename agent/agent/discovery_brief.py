"""Discovery call context brief (Markdown) for HubSpot / operators."""
from __future__ import annotations

import html
from typing import Any, Dict, List, Sequence


def build_discovery_context_markdown(
    company_name: str,
    hiring_summary: str,
    gap_lines: Sequence[str],
    *,
    test_email: str = "",
) -> str:
    lines = [
        f"# Discovery call brief — {html.escape(company_name)}",
        "",
        "## Hiring / signal summary",
        hiring_summary or "_No summary._",
        "",
        "## Competitor gap (research framing)",
    ]
    for g in gap_lines[:8]:
        lines.append(f"- {g}")
    if test_email:
        lines.extend(["", f"**Prospect email:** `{html.escape(test_email)}`"])
    lines.extend(
        [
            "",
            "_Generated for human-led discovery. Public signals only; verify on call._",
        ]
    )
    return "\n".join(lines)


def discovery_brief_to_hubspot_html(md: str) -> str:
    """Wrap markdown-like text as safe HTML note body."""
    escaped = html.escape(md)
    return f"<pre style='white-space:pre-wrap;font-family:system-ui,sans-serif'>{escaped}</pre>"
