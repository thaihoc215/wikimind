"""Lint system prompt and tool schema (for semantic checks)."""

LINT_SYSTEM_PROMPT = """\
You are a wiki health inspector. Analyze the wiki content for quality issues.

Look for:
- Contradictions between pages (same claim stated differently)
- Important topics mentioned across pages but lacking their own dedicated page
- Outdated claims that newer content contradicts
- Concepts that are heavily cross-referenced but poorly explained
- Suggested new sources to investigate based on knowledge gaps

Be specific — name the pages involved, quote the conflicting claims.
"""

LINT_TOOL = {
    "name": "wiki_lint_report",
    "description": "Report semantic issues found in the wiki.",
    "input_schema": {
        "type": "object",
        "required": ["contradictions", "missing_pages", "suggested_sources"],
        "properties": {
            "contradictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["pages", "description"],
                    "properties": {
                        "pages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Page paths involved in contradiction",
                        },
                        "description": {
                            "type": "string",
                            "description": "What the contradiction is",
                        },
                    },
                },
            },
            "missing_pages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topics mentioned frequently but lacking their own page",
            },
            "suggested_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Suggested sources to investigate to fill knowledge gaps",
            },
        },
    },
}
