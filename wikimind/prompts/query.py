"""Query system prompt and tool schema."""

QUERY_SYSTEM_PROMPT = """\
You are a wiki research assistant. Answer questions based on the wiki content provided.

RULES:
- Base your answer ONLY on the wiki pages provided in the context
- Use [[wikilinks]] to cite specific wiki pages (e.g. "According to [[entity-name]]...")
- If the wiki doesn't cover the question well, say so explicitly — don't hallucinate
- Write in clear, well-structured markdown
- Identify knowledge gaps honestly: what would the wiki need to answer this better?
- If the wiki is empty or has no relevant content, guide the user to ingest sources first
"""

QUERY_TOOL = {
    "name": "wiki_answer",
    "description": "Answer a question based on wiki content.",
    "input_schema": {
        "type": "object",
        "required": ["answer", "citations", "confidence"],
        "properties": {
            "answer": {
                "type": "string",
                "description": "The answer in markdown, using [[wikilinks]] for citations",
            },
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of wiki page paths used to answer",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "How well the wiki covers this question",
            },
            "knowledge_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topics the wiki should cover to better answer this",
            },
        },
    },
}
