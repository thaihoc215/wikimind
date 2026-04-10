# WikiMind — Bản kế hoạch tổng hợp hoàn chỉnh

> Hiện thực hóa đúng tinh thần Karpathy: "Most people's experience with LLMs and documents looks like RAG... This works, but the LLM is rediscovering knowledge from scratch on every question. There's no accumulation."

> Nguyên tắc cốt lõi từ cộng đồng: "Write-back is the key to compounding. The gist mentions filing outputs back into the wiki almost in passing, but after two years I think it's the single most important part. The knowledge base should grow through use, not just ingestion."

---

## I. WikiMind là gì?

Một **Python daemon + CLI + MCP Server** chạy song song với bất kỳ project nào. Tự động biến mọi hoạt động (code changes, conversations, tài liệu mới) thành tri thức tích lũy trong wiki — **không cần nhắc, không cần thao tác thủ công**.

Cấu trúc dựa trên 3 layers từ gist gốc: Raw sources (immutable), Wiki (markdown, LLM writes & updates, humans read & review), và Schema (rules cho LLM vận hành wiki). Giữ memory explicit và file-based thay vì dựa vào model's internal state.

### Nguyên tắc thiết kế

```
1. ZERO FRICTION      — Bạn không bao giờ phải nhớ "update wiki"
2. COST AWARE         — Thông minh về khi nào gọi LLM, model nào
3. PORTABLE           — Chỉ là markdown files + SQLite, không vendor lock-in
4. COMPOSABLE         — CLI commands có thể pipe, script, cron
5. OBSERVABLE         — Mọi thứ có log, cost tracking, dry-run
6. WRITE-BACK FIRST   — Mọi output đều quay lại wiki, không chỉ ingest
```

---

## II. Kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────────┐
│                         WikiMind Engine                               │
│                                                                       │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────────────┐  │
│  │   Watchers    │──▶│  Event Queue  │──▶│   Processing Engine    │  │
│  │              │   │               │   │                        │  │
│  │ • Git hooks  │   │ • Filter      │   │ • Classifier           │  │
│  │ • FS watch   │   │ • Debounce    │   │ • Analyzer             │  │
│  │ • Manual CLI │   │ • Prioritize  │   │ • Planner              │  │
│  │ • MCP input  │   │ • Batch       │   │ • Writer               │  │
│  │              │   │ • Outbox      │   │ • Linker               │  │
│  └──────────────┘   └───────────────┘   │ • Validator            │  │
│                                          └───────────┬────────────┘  │
│                                                       │              │
│                                                       ▼              │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────────────┐  │
│  │  Query API   │◀──│  Wiki Store   │◀──│     LLM Router         │  │
│  │              │   │               │   │                        │  │
│  │ • CLI        │   │ • Markdown FS │   │ • Strong model         │  │
│  │ • MCP Server │   │ • SQLite meta │   │   (analysis, query)    │  │
│  │ • HTTP API   │   │ • Index + Log │   │ • Cheap model          │  │
│  │              │   │ • Search      │   │   (write, link, file)  │  │
│  └──────────────┘   └───────────────┘   │ • Local model          │  │
│                                          │   (classify, lint)     │  │
│                                          │ • Budget Guard         │  │
│                                          └────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                      Scheduler                                  │  │
│  │  • Batch process (hourly)  • Lint (daily)  • Deep lint (weekly)│  │
│  │  • Cost report (daily)     • Reindex       • Metrics collector │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                      Config per Project                         │  │
│  │  wikimind.toml — schema, rules, model routing, budget, filters │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 4 Cơ chế cập nhật wiki — hoạt động đồng thời

```
Layer 1 — MCP Server (PRIMARY)
  Claude Code TỰ đọc/viết wiki trong flow vì wiki là tool available.
  Capture ~90% updates, tiết kiệm token vì đọc wiki thay vì code.
  ⚠️ Token cost nằm ở phía Claude Code, WikiMind không track được.

Layer 2 — Git Hook (BACKUP, chỉ cho code projects)
  Bắt lại những gì MCP miss. Post-commit kiểm tra:
  "commit này có changes mà wiki chưa reflect?" → queue update.
  → Optional: không cần cho research/book/personal use cases.

Layer 3 — File Watcher (RAW SOURCES)
  Chỉ watch raw/ directory. Drop file mới → auto ingest.

Layer 4 — Scheduler (MAINTENANCE)
  Daily lint, weekly deep check. Bắt mọi thứ 3 layers trên miss.
```

> **Lưu ý:** Layer 1 (MCP) + Layer 3 (File Watcher) là đủ cho mọi use case.
> Layer 2 (Git Hook) chỉ cần cho code projects. Hệ thống hoạt động fine
> chỉ với CLI + MCP, không bắt buộc daemon.

### Flow khởi động hàng ngày

```bash
$ wikimind watch --daemon    # Start daemon (watcher + scheduler + MCP server)
$ claude                     # Claude Code tự connect MCP → tự dùng wiki tools
                             # Bạn không cần nhắc wiki một lần nào cả
```

---

## III. Cấu trúc Project

```
wikimind/
│
├── wikimind/                          # Python package chính
│   │
│   ├── core/                          # ═══ FOUNDATION ═══
│   │   ├── __init__.py
│   │   ├── config.py                  # Load & validate wikimind.toml
│   │   ├── schema.py                  # Wiki schema definitions
│   │   └── models.py                  # Data models (Page, Source, Task, Cost...)
│   │
│   ├── llm/                           # ═══ LLM LAYER ═══
│   │   ├── __init__.py
│   │   ├── base.py                    # Abstract LLM interface
│   │   ├── router.py                  # Route tasks → model phù hợp
│   │   ├── budget.py                  # Budget guard — hard limit spending
│   │   ├── cost_tracker.py            # Track every token & dollar
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── anthropic.py           # Claude API
│   │       ├── openai.py              # OpenAI API
│   │       └── ollama.py              # Local LLM (free)
│   │
│   ├── queue/                         # ═══ EVENT QUEUE LAYER ═══
│   │   ├── __init__.py
│   │   ├── events.py                  # Event types (CommitEvent, FileEvent...)
│   │   ├── filter.py                  # Drop noise (test-only, formatting, .lock)
│   │   ├── debounce.py                # Collapse rapid events (5s window)
│   │   ├── priority.py                # Assign priority (IMMEDIATE → BATCH)
│   │   ├── batcher.py                 # Group related events into 1 task
│   │   └── queue.py                   # Persistent queue (SQLite-backed)
│   │
│   ├── pipeline/                      # ═══ PROCESSING ENGINE ═══
│   │   ├── __init__.py
│   │   ├── classifier.py              # "What type of change is this?"
│   │   ├── analyzer.py                # Extract entities, concepts, claims
│   │   ├── planner.py                 # Decide which wiki pages to CRUD
│   │   ├── writer.py                  # Write/update markdown content
│   │   ├── linker.py                  # Create/update [[wikilinks]]
│   │   └── validator.py               # Verify frontmatter, links, index sync
│   │
│   ├── watchers/                      # ═══ INPUT LAYER ═══
│   │   ├── __init__.py
│   │   ├── git_watcher.py             # Post-commit hook → emit CommitEvent
│   │   ├── file_watcher.py            # raw/ dir changed → emit FileEvent
│   │   └── cli_trigger.py             # Manual "wikimind ingest" → emit ManualEvent
│   │
│   ├── wiki/                          # ═══ WIKI STORE ═══
│   │   ├── __init__.py
│   │   ├── store.py                   # CRUD wiki pages (filesystem)
│   │   ├── index.py                   # Maintain index.md
│   │   ├── log.py                     # Maintain log.md
│   │   ├── search.py                  # BM25 + semantic search
│   │   └── graph.py                   # Traverse [[wikilinks]] graph
│   │
│   ├── operations/                    # ═══ 3 CORE OPERATIONS (Karpathy) ═══
│   │   ├── __init__.py
│   │   ├── ingest.py                  # Ingest: raw source → wiki pages
│   │   ├── query.py                   # Query: question → answer + citations
│   │   └── lint.py                    # Lint: health check → auto-fix
│   │
│   ├── scheduler/                     # ═══ SCHEDULER LAYER ═══
│   │   ├── __init__.py
│   │   ├── runner.py                  # Process queue by priority
│   │   ├── cron.py                    # Scheduled jobs (lint, reindex, reports)
│   │   └── metrics.py                 # Wiki health score, stats collector
│   │
│   ├── server/                        # ═══ API LAYER ═══
│   │   ├── __init__.py
│   │   ├── mcp_server.py              # MCP server — Claude Code/Cursor connect
│   │   └── api.py                     # REST API (optional)
│   │
│   ├── db/                            # ═══ STORAGE ═══
│   │   ├── __init__.py
│   │   ├── database.py                # SQLite connection & migrations
│   │   └── migrations/                # Schema versioning
│   │       └── 001_initial.sql
│   │
│   └── cli/                           # ═══ CLI INTERFACE ═══
│       ├── __init__.py
│       └── main.py                    # Typer CLI app
│
├── tests/
│   ├── test_queue/
│   ├── test_pipeline/
│   ├── test_operations/
│   ├── test_wiki/
│   ├── test_watchers/
│   └── test_llm/
│
├── pyproject.toml
├── README.md
└── wikimind.toml.example              # Example config
```

---

## IV. Data Models

```python
# wikimind/core/models.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


# ═══ Enums ═══

class PageType(Enum):
    SOURCE = "source"           # Tóm tắt 1 raw source
    ENTITY = "entity"           # Module, service, người, tổ chức
    CONCEPT = "concept"         # Khái niệm, pattern, principle
    ANALYSIS = "analysis"       # So sánh, synthesis, saved answers
    DECISION = "decision"       # Architecture Decision Records
    OVERVIEW = "overview"       # Tổng quan project/topic


class TaskType(Enum):
    INGEST = "ingest"           # Raw source → wiki
    UPDATE = "update"           # Code changed → update wiki pages
    QUERY = "query"             # User question → answer
    LINT = "lint"               # Health check
    CROSSREF = "crossref"       # Rebuild cross-references


class TaskPriority(Enum):
    IMMEDIATE = 1               # User query — chạy ngay
    HIGH = 2                    # New source in raw/
    NORMAL = 3                  # Auto-update after code change
    LOW = 4                     # Lint, orphan check
    BATCH = 5                   # Gom lại chạy cuối ngày


class ChangeType(Enum):
    # Domain-agnostic (mọi use case)
    NEW_CONTENT = "new_content"         # Nội dung mới (source, chapter, article)
    UPDATE = "update"                   # Cập nhật nội dung đã có
    RESTRUCTURE = "restructure"         # Tổ chức lại (refactor, reorganize)
    NEW_ENTITY = "new_entity"           # Entity mới (person, module, concept)
    CORRECTION = "correction"           # Sửa lỗi, fix sai sót
    CONTRADICTION = "contradiction"     # Mâu thuẫn với claims hiện tại
    MINOR = "minor"                     # Skip wiki update
    # Code-specific (chỉ dùng khi template = "code")
    CONFIG_CHANGE = "config_change"
    NEW_DEPENDENCY = "new_dependency"
    API_CHANGE = "api_change"


class EventType(Enum):
    COMMIT = "commit"
    FILE_CHANGE = "file_change"
    MANUAL = "manual"
    MCP_WRITE = "mcp_write"


# ═══ Core Models ═══

@dataclass
class WikiPage:
    path: Path                  # .wiki/modules/auth.md
    title: str
    page_type: PageType
    tags: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    inbound_links: list[str] = field(default_factory=list)
    outbound_links: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
    content_hash: str = ""


@dataclass
class Event:
    event_type: EventType
    source: str                 # "git", "filesystem", "cli", "mcp"
    payload: dict               # Context-specific data
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class WikiTask:
    task_type: TaskType
    priority: TaskPriority
    payload: dict
    created: datetime = field(default_factory=datetime.now)
    estimated_tokens: int = 0
    estimated_cost: float = 0.0
    status: str = "pending"     # pending, processing, done, failed


@dataclass
class UpdatePlan:
    """Output of Planner — danh sách actions cần thực hiện."""
    creates: list[dict] = field(default_factory=list)   # New pages
    updates: list[dict] = field(default_factory=list)   # Modified pages
    deletes: list[str] = field(default_factory=list)    # Removed pages
    log_entry: str = ""


@dataclass
class CostRecord:
    timestamp: datetime
    task_type: TaskType
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    pages_affected: int


@dataclass
class LintIssue:
    issue_type: str             # stale, contradiction, orphan, missing, gap
    severity: str               # error, warning, info
    page: str                   # Affected page path
    description: str
    auto_fixable: bool = False
    fix_action: str = ""        # Mô tả cách fix
```

---

## V. Config System

```toml
# wikimind.toml

[project]
name = "My Project"
description = "E-commerce platform with microservices"
language = "vi"                     # vi, en, both

[paths]
raw_sources = "raw/"
wiki = ".wiki/"
db = ".wiki/.wikimind.db"

# ═══ LLM Configuration ═══

[llm]
primary = "claude-sonnet-4-20250514"
maintenance = "claude-haiku"
local = "ollama/qwen2.5"

[llm.budget]
daily_usd = 2.00
warn_at_usd = 1.50

[llm.providers.anthropic]
api_key_env = "ANTHROPIC_API_KEY"

[llm.providers.openai]
api_key_env = "OPENAI_API_KEY"

[llm.providers.ollama]
base_url = "http://localhost:11434"

# ═══ Event Queue Configuration ═══

[queue]
debounce_seconds = 5                # Collapse rapid events
max_batch_size = 10                 # Max events per batch

[queue.filters]
min_files_changed = 2               # Skip trivial commits
ignore_patterns = [
    "*.test.*", "*.spec.*",
    "*.lock", "*.log",
    ".wiki/*",
    "node_modules/*", "__pycache__/*",
]
always_track_patterns = [
    "src/*/README.md",
    "docs/*",
    "*.config.*",
    "docker-compose.*",
    "Dockerfile*",
]

# ═══ Scheduler Configuration ═══

[scheduler]
mode = "smart"                      # realtime | batch | smart
batch_interval_minutes = 60
lint_schedule = "daily"             # hourly | daily | weekly
deep_lint_schedule = "weekly"

# ═══ Wiki Schema ═══

[wiki.schema]
categories = [
    { name = "modules",   description = "Mỗi module/service" },
    { name = "concepts",  description = "Domain concepts & patterns" },
    { name = "decisions", description = "Architecture Decision Records" },
    { name = "sources",   description = "Tóm tắt từng raw source" },
    { name = "analyses",  description = "So sánh, synthesis, saved Q&A" },
]

[wiki.frontmatter]
required_fields = ["title", "type", "created", "updated", "tags"]
```

---

## VI. Layer-by-Layer Implementation

### Layer 1: Event Queue

```python
# wikimind/queue/events.py

@dataclass
class CommitEvent(Event):
    """Emitted by GitWatcher after each commit."""
    commit_hash: str = ""
    commit_message: str = ""
    files_changed: list[str] = field(default_factory=list)
    diff_summary: str = ""


@dataclass
class FileEvent(Event):
    """Emitted by FileWatcher when raw/ changes."""
    file_path: Path = Path()
    change_type: str = ""       # created, modified, deleted


@dataclass
class ManualEvent(Event):
    """Emitted by CLI trigger."""
    command: str = ""           # ingest, query, lint
    args: dict = field(default_factory=dict)
```

```python
# wikimind/queue/filter.py

class EventFilter:
    """
    Drop events không đáng xử lý.
    KHÔNG gọi LLM — chỉ dùng pattern matching.
    """

    def __init__(self, config: Config):
        self.ignore = config.queue.filters.ignore_patterns
        self.always_track = config.queue.filters.always_track_patterns
        self.min_files = config.queue.filters.min_files_changed

    def should_process(self, event: Event) -> bool:
        if isinstance(event, ManualEvent):
            return True  # User trigger luôn process

        if isinstance(event, CommitEvent):
            # Always track important files
            for f in event.files_changed:
                if self._matches_any(f, self.always_track):
                    return True
            # Skip trivial commits
            if len(event.files_changed) < self.min_files:
                return False
            # Skip if ALL files match ignore patterns
            significant = [f for f in event.files_changed
                          if not self._matches_any(f, self.ignore)]
            return len(significant) > 0

        if isinstance(event, FileEvent):
            return not self._matches_any(str(event.file_path), self.ignore)

        return True
```

```python
# wikimind/queue/debounce.py

class Debouncer:
    """
    Collapse rapid events.
    Ví dụ: Claude Code save file 10 lần trong 5 giây → 1 event.
    """

    def __init__(self, window_seconds: int = 5):
        self.window = window_seconds
        self._pending: dict[str, list[Event]] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}

    async def add(self, event: Event) -> Event | None:
        key = self._group_key(event)

        if key in self._pending:
            self._pending[key].append(event)
            # Reset timer
            self._timers[key].cancel()
        else:
            self._pending[key] = [event]

        # Set timer — khi hết window, emit merged event
        self._timers[key] = asyncio.get_event_loop().call_later(
            self.window, self._flush, key
        )
        return None  # Chưa emit — đang đợi

    def _flush(self, key: str):
        events = self._pending.pop(key)
        self._timers.pop(key)
        merged = self._merge(events)
        self._output_queue.put_nowait(merged)

    def _group_key(self, event: Event) -> str:
        """Group events by source directory."""
        if isinstance(event, CommitEvent):
            return "commit"
        if isinstance(event, FileEvent):
            return str(event.file_path.parent)
        return event.event_type.value
```

```python
# wikimind/queue/priority.py

class Prioritizer:
    """Assign priority to each task."""

    def assign(self, event: Event) -> TaskPriority:
        if isinstance(event, ManualEvent):
            if event.command == "query":
                return TaskPriority.IMMEDIATE
            if event.command == "ingest":
                return TaskPriority.HIGH
            return TaskPriority.NORMAL

        if isinstance(event, FileEvent):
            return TaskPriority.HIGH     # New source

        if isinstance(event, CommitEvent):
            return TaskPriority.NORMAL   # Code change

        return TaskPriority.LOW
```

```python
# wikimind/queue/batcher.py

class Batcher:
    """
    Group related tasks.
    3 commits touching auth/ → 1 batch "auth module changed".
    """

    def batch(self, tasks: list[WikiTask]) -> list[WikiTask]:
        groups: dict[str, list[WikiTask]] = {}

        for task in tasks:
            key = self._affinity_key(task)
            groups.setdefault(key, []).append(task)

        batched = []
        for key, group in groups.items():
            if len(group) == 1:
                batched.append(group[0])
            else:
                batched.append(self._merge_tasks(group))

        return batched

    def _affinity_key(self, task: WikiTask) -> str:
        """Group by affected wiki area."""
        files = task.payload.get("files_changed", [])
        if not files:
            return task.task_type.value
        # Extract common directory
        dirs = set(str(Path(f).parent) for f in files)
        return ",".join(sorted(dirs))
```

### Layer 2: Processing Pipeline

```python
# wikimind/pipeline/classifier.py

class Classifier:
    """
    "What type of change is this?"
    Dùng cheap/local model — chỉ cần categorize.
    """

    async def classify(self, task: WikiTask) -> ChangeType:
        if task.task_type == TaskType.INGEST:
            return ChangeType.NEW_CONTENT

        # For code changes — heuristic first (no LLM)
        files = task.payload.get("files_changed", [])
        commit_msg = task.payload.get("commit_message", "")

        # Simple heuristics
        # Domain-agnostic heuristics (hoạt động cho mọi template)
        if any("config" in f.lower() for f in files):
            return ChangeType.CONFIG_CHANGE
        if any(self._is_new_directory(f) for f in files):
            return ChangeType.NEW_ENTITY
        if "fix" in commit_msg.lower() or "bug" in commit_msg.lower():
            return ChangeType.CORRECTION
        if "refactor" in commit_msg.lower() or "restructure" in commit_msg.lower():
            return ChangeType.RESTRUCTURE
        if len(files) < 2 and "typo" in commit_msg.lower():
            return ChangeType.MINOR

        # Ambiguous → ask cheap LLM
        result = await self.llm.classify(
            files=files,
            commit_message=commit_msg,
            model_tier="local"          # Free
        )
        return ChangeType(result)
```

```python
# wikimind/pipeline/analyzer.py

class Analyzer:
    """
    Deep analysis — extract entities, concepts, claims, relationships.
    Dùng strong model — cần comprehension tốt.
    """

    async def analyze(self, task: WikiTask, change_type: ChangeType) -> AnalysisResult:
        if change_type == ChangeType.MINOR:
            return AnalysisResult.empty()  # Skip

        # Read relevant content
        if task.task_type == TaskType.INGEST:
            content = await self.reader.read(task.payload["source_path"])
        else:
            content = await self.git.get_diff(task.payload["commit_hash"])

        # Read current wiki index for context
        index = self.wiki.read_index()

        # LLM analysis
        result = await self.llm.analyze(
            content=content,
            existing_index=index,
            change_type=change_type,
            model_tier="primary"        # Strong model
        )

        return result  # entities, concepts, claims, relationships, contradictions
```

```python
# wikimind/pipeline/planner.py

class Planner:
    """
    Decide which wiki pages to create, update, or flag.
    Dùng strong model — cần đọc wiki hiện tại + quyết định.
    """

    async def plan(self, analysis: AnalysisResult) -> UpdatePlan:
        # Find related existing pages
        affected_pages = self.wiki.find_related_pages(
            analysis.entities + analysis.concepts
        )

        # Read those pages
        page_contents = {}
        for page_path in affected_pages:
            page_contents[page_path] = self.wiki.read_page(page_path)

        # Ask LLM to create plan
        plan = await self.llm.create_plan(
            analysis=analysis,
            existing_pages=page_contents,
            wiki_schema=self.config.wiki.schema,
            model_tier="primary"
        )

        return plan  # creates[], updates[], deletes[], log_entry
```

```python
# wikimind/pipeline/writer.py

class Writer:
    """
    Write/update markdown content.
    Dùng cheap model — writing quality đủ tốt.
    """

    async def execute(self, plan: UpdatePlan) -> list[PageDraft]:
        drafts = []

        for create in plan.creates:
            content = await self.llm.write_page(
                title=create["title"],
                page_type=create["type"],
                source_content=create["content"],
                schema=self.config.wiki.schema,
                model_tier="maintenance"    # Cheap model
            )
            drafts.append(PageDraft(
                path=create["path"],
                content=content,
                action="create"
            ))

        for update in plan.updates:
            existing = self.wiki.read_page(update["path"])
            content = await self.llm.update_page(
                existing_content=existing,
                new_information=update["changes"],
                model_tier="maintenance"
            )
            drafts.append(PageDraft(
                path=update["path"],
                content=content,
                action="update"
            ))

        return drafts
```

```python
# wikimind/pipeline/linker.py

class Linker:
    """
    Create/update [[wikilinks]] between pages.
    Dùng cheap/no LLM — pattern matching đủ.
    """

    def link(self, drafts: list[PageDraft]) -> list[PageDraft]:
        all_pages = self.wiki.list_all_page_titles()
        # Sort longest-first để "jwt-rotation" match trước "jwt"
        all_pages.sort(key=len, reverse=True)

        for draft in drafts:
            # Find mentions of other page titles in content
            for title in all_pages:
                if f"[[{title}]]" in draft.content:
                    continue  # Already linked

                # Word-boundary matching — tránh "Auth" match trong "authentication"
                pattern = re.compile(
                    r'(?<!\[\[)' +          # Không nằm trong [[...]] sẵn
                    r'\b' + re.escape(title) + r'\b' +
                    r'(?!\]\])',             # Không phải closing ]]
                    re.IGNORECASE
                )
                # Chỉ link lần xuất hiện đầu tiên (ngoài frontmatter)
                content_start = draft.content.find('---', 3)  # Skip frontmatter
                if content_start == -1:
                    content_start = 0
                match = pattern.search(draft.content, content_start)
                if match:
                    draft.content = (
                        draft.content[:match.start()] +
                        f"[[{title}]]" +
                        draft.content[match.end():]
                    )

            # Extract outbound links
            draft.outbound_links = re.findall(r'\[\[(.+?)\]\]', draft.content)

        return drafts
```

```python
# wikimind/pipeline/validator.py

class Validator:
    """
    Verify everything is correct. KHÔNG cần LLM.
    """

    def validate(self, drafts: list[PageDraft]) -> list[str]:
        issues = []

        for draft in drafts:
            # Check frontmatter
            fm = frontmatter.loads(draft.content)
            for field in self.config.wiki.frontmatter.required_fields:
                if field not in fm.metadata:
                    issues.append(f"{draft.path}: missing frontmatter '{field}'")

            # Check wikilinks resolve
            for link in draft.outbound_links:
                if not self.wiki.page_exists(link):
                    issues.append(f"{draft.path}: broken link [[{link}]]")

        # Check index consistency
        if not self._index_includes_all(drafts):
            issues.append("index.md: missing new pages")

        return issues
```

---

### Layer 3: LLM Router + Budget Guard

```python
# wikimind/llm/router.py

class ModelRouter:
    """
    Route tasks → model. Nguyên tắc: model RẺ NHẤT có thể hoàn thành.

    ┌───────────────┬──────────────────┬───────────────┐
    │ Pipeline Step │ Cần gì           │ Model         │
    ├───────────────┼──────────────────┼───────────────┤
    │ Classifier    │ Categorize       │ Local (free)  │
    │ Analyzer      │ Deep comprehend  │ Primary       │
    │ Planner       │ Read + decide    │ Primary       │
    │ Writer        │ Write markdown   │ Maintenance   │
    │ Linker        │ Pattern match    │ No LLM        │
    │ Validator     │ Check rules      │ No LLM        │
    │ Lint (struct) │ Date/link check  │ No LLM        │
    │ Lint (semantic)│ Contradictions  │ Local/Maint.  │
    │ Query         │ Synthesize       │ Primary       │
    └───────────────┴──────────────────┴───────────────┘
    """

    def select(self, step: str, priority: TaskPriority,
               budget_remaining: float) -> str:

        if budget_remaining < 0.10:
            return self.config.local    # Hết budget → free model

        if priority == TaskPriority.IMMEDIATE:
            return self.config.primary  # User đang chờ

        routing = {
            "classifier": self.config.local,
            "analyzer": self.config.primary,
            "planner": self.config.primary,
            "writer": self.config.maintenance,
            "linker": None,             # No LLM
            "validator": None,          # No LLM
            "query": self.config.primary,
            "lint_semantic": self.config.local,
        }

        return routing.get(step, self.config.maintenance)
```

```python
# wikimind/llm/budget.py

class BudgetGuard:
    """
    Hard limit on spending. Check BEFORE every LLM call.
    """

    async def check(self, estimated_cost: float) -> BudgetDecision:
        spent = await self.cost_tracker.get_daily_spent()
        remaining = self.config.daily_usd - spent

        if remaining <= 0:
            return BudgetDecision(
                allowed=False,
                reason=f"Daily budget exhausted: ${spent:.2f}/${self.config.daily_usd}",
                fallback="local"
            )

        if remaining < estimated_cost:
            return BudgetDecision(
                allowed=True,
                downgrade_to="maintenance",  # Dùng model rẻ hơn
                reason=f"Budget low: ${remaining:.2f} remaining"
            )

        if spent >= self.config.warn_at_usd:
            logger.warning(f"Budget warning: ${spent:.2f} spent today")

        return BudgetDecision(allowed=True)
```

---

### Layer 4: Wiki Store

```python
# wikimind/wiki/store.py

class WikiStore:
    """
    Read/write wiki pages. Filesystem + SQLite metadata.

    Filesystem (.wiki/):           SQLite (.wikimind.db):
    ├── index.md                   ├── pages (path, type, hash, updated)
    ├── log.md                     ├── sources (path, hash, ingested_at)
    ├── overview.md                ├── links (from_page, to_page)
    ├── modules/                   ├── costs (timestamp, model, tokens, usd)
    ├── concepts/                  ├── tasks (type, status, created, cost)
    ├── decisions/                 └── embeddings (page, vector)
    ├── sources/
    └── analyses/
    """

    def create_page(self, path: Path, content: str, page_type: PageType):
        """Atomic write: temp file → rename."""
        full_path = self.wiki_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp first
        tmp = full_path.with_suffix('.tmp')
        tmp.write_text(content, encoding='utf-8')
        tmp.rename(full_path)

        # Update SQLite metadata
        self.db.upsert_page(
            path=str(path),
            page_type=page_type.value,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            updated=datetime.now()
        )

        # Update search index
        self.search.index_page(path, content)

    def read_page(self, path: str) -> str:
        full_path = self.wiki_root / path
        if not full_path.exists():
            raise PageNotFound(path)
        return full_path.read_text(encoding='utf-8')

    def find_related_pages(self, terms: list[str]) -> list[str]:
        """Find pages related to given entities/concepts."""
        results = self.search.find_relevant(
            query=" ".join(terms),
            top_k=10
        )
        return [r.path for r in results]

    def is_already_ingested(self, content_hash: str) -> bool:
        return self.db.source_exists(content_hash)

    def list_all_page_titles(self) -> list[str]:
        return self.db.get_all_page_titles()

    def page_exists(self, title: str) -> bool:
        return self.db.page_exists_by_title(title)
```

---

### Layer 5: 3 Core Operations

```python
# wikimind/operations/ingest.py

class IngestOperation:
    """
    raw source → wiki pages.
    Full pipeline: classify → analyze → plan → write → link → validate → save.
    """

    async def execute(self, source_path: Path, interactive: bool = False) -> IngestResult:
        # 1. Read & check duplicate
        content = await self.reader.read(source_path)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if self.wiki.is_already_ingested(content_hash):
            return IngestResult(skipped=True, reason="Already ingested")

        # 2. Full pipeline
        change_type = ChangeType.NEW_CONTENT
        analysis = await self.pipeline.analyzer.analyze(
            task=WikiTask(TaskType.INGEST, TaskPriority.HIGH,
                         {"source_path": str(source_path), "content": content}),
            change_type=change_type
        )

        plan = await self.pipeline.planner.plan(analysis)

        if interactive:
            approved = self.ui.present_plan(plan)
            if not approved:
                return IngestResult(skipped=True, reason="User rejected")

        drafts = await self.pipeline.writer.execute(plan)
        drafts = self.pipeline.linker.link(drafts)
        issues = self.pipeline.validator.validate(drafts)

        if issues:
            drafts = await self._fix_issues(drafts, issues)

        # 3. Commit to wiki store
        for draft in drafts:
            self.wiki.create_page(draft.path, draft.content, draft.page_type)

        # 4. Update index + log
        await self.wiki.update_index(drafts)
        await self.wiki.append_log(plan.log_entry)

        # 5. Record cost
        self.cost_tracker.record_batch(self.pipeline.get_costs())

        # 6. Mark source as ingested
        self.db.mark_ingested(str(source_path), content_hash)

        return IngestResult(pages_created=len(plan.creates),
                           pages_updated=len(plan.updates))
```

```python
# wikimind/operations/query.py

class QueryOperation:
    """
    Question → answer with [[citations]].
    High-value answers saved back as wiki page (write-back).
    """

    async def execute(self, question: str, save: bool = False) -> QueryResult:
        # 0. Cold-start check: wiki trống?
        page_count = self.wiki.get_page_count()
        if page_count == 0:
            unprocessed = self.wiki.find_unprocessed_sources()
            if unprocessed:
                return QueryResult(
                    answer="Wiki is empty. Run `wikimind ingest` first.\n"
                           f"Found {len(unprocessed)} unprocessed sources in raw/: "
                           f"{', '.join(str(s) for s in unprocessed[:5])}",
                    confidence=0.0
                )
            return QueryResult(
                answer="Wiki is empty and no sources found in raw/. "
                       "Add source files to raw/ and run `wikimind ingest`.",
                confidence=0.0
            )

        # 1. Search wiki
        results = await self.wiki.search.find_relevant(question, top_k=10)

        if not results:
            # Check: any raw sources not yet ingested?
            unprocessed = self.wiki.find_unprocessed_sources()
            if unprocessed:
                return QueryResult(
                    answer="Wiki doesn't have enough info for this question. "
                           f"Consider ingesting: {unprocessed[:3]}",
                    confidence=0.0
                )

        # 2. Read relevant pages
        context = []
        for r in results:
            content = self.wiki.read_page(r.path)
            context.append({"path": r.path, "content": content, "score": r.score})

        # 3. Synthesize answer (strong model)
        answer = await self.llm.synthesize(
            question=question,
            context=context,
            model_tier="primary"
        )

        # 4. Write-back: save valuable answers as wiki page
        if save or self._is_high_value(answer):
            slug = slugify(question)[:60]
            self.wiki.create_page(
                path=Path(f"analyses/{slug}.md"),
                content=answer.as_wiki_page(),
                page_type=PageType.ANALYSIS
            )
            await self.wiki.update_index_single(f"analyses/{slug}.md")
            await self.wiki.append_log(f"Saved query: {question}")

        return answer
```

```python
# wikimind/operations/lint.py

class LintOperation:
    """
    Health check. Structural checks (no LLM) + semantic checks (cheap LLM).
    """

    async def execute(self, auto_fix: bool = False) -> LintReport:
        issues = []

        # ═══ Structural checks (NO LLM — free) ═══

        # 1. Stale pages: source file changed since wiki page last updated
        for page in self.wiki.all_pages():
            for ref in page.related_files:
                if self._file_changed_since(ref, page.updated):
                    issues.append(LintIssue(
                        issue_type="stale", severity="warning",
                        page=str(page.path),
                        description=f"Source {ref} changed since last update",
                        auto_fixable=True,
                        fix_action="re-analyze and update page"
                    ))

        # 2. Orphan pages: zero inbound links
        for page in self.wiki.all_pages():
            if not page.inbound_links and page.path.name != "index.md":
                issues.append(LintIssue(
                    issue_type="orphan", severity="info",
                    page=str(page.path),
                    description="No pages link to this page",
                    auto_fixable=True
                ))

        # 3. Broken links: [[wikilink]] to non-existent page
        for page in self.wiki.all_pages():
            for link in page.outbound_links:
                if not self.wiki.page_exists(link):
                    issues.append(LintIssue(
                        issue_type="missing", severity="error",
                        page=str(page.path),
                        description=f"Broken link: [[{link}]]",
                        auto_fixable=True,
                        fix_action="create stub page or remove link"
                    ))

        # 4. Index sync
        indexed = self._parse_index_pages()
        actual = set(str(p.path) for p in self.wiki.all_pages())
        missing_from_index = actual - indexed
        for p in missing_from_index:
            issues.append(LintIssue(
                issue_type="index_desync", severity="warning",
                page=p, description="Page exists but not in index.md",
                auto_fixable=True
            ))

        # 5. Coverage gaps: source files with no wiki page
        for source_file in self._get_project_source_files():
            if not self.wiki.has_page_for_file(source_file):
                issues.append(LintIssue(
                    issue_type="coverage_gap", severity="info",
                    page="", description=f"No wiki page covers: {source_file}",
                    auto_fixable=False
                ))

        # ═══ Semantic checks (cheap/local LLM) ═══

        # 6. Contradictions
        contradictions = await self.llm.find_contradictions(
            pages=self.wiki.all_pages(),
            model_tier="local"          # Free
        )
        issues.extend(contradictions)

        # ═══ Auto-fix ═══

        if auto_fix:
            fixed = 0
            for issue in issues:
                if issue.auto_fixable:
                    await self._fix(issue)
                    fixed += 1
            return LintReport(issues=issues, fixed=fixed)

        return LintReport(issues=issues)
```

---

### Layer 6: MCP Server

FastMCP class dùng Python type hints và docstrings để tự động generate tool definitions, giúp việc build MCP server rất đơn giản:

```python
# wikimind/server/mcp_server.py

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wikimind")


@mcp.tool()
async def wiki_search(query: str, top_k: int = 5) -> list[dict]:
    """Search wiki pages. Call this FIRST before reading source files —
    wiki contains pre-compiled summaries of all modules and concepts."""
    results = await store.search.find_relevant(query, top_k)
    return [{"path": r.path, "title": r.title, "score": r.score,
             "snippet": r.snippet} for r in results]


@mcp.tool()
async def wiki_read(page_path: str) -> str:
    """Read a wiki page. Check wiki before reading multiple source files."""
    return store.read_page(page_path)


@mcp.tool()
async def wiki_query(question: str, save: bool = False) -> dict:
    """Ask a question against the wiki knowledge base.
    Returns answer with [[citations]] to wiki pages."""
    op = QueryOperation(store, llm, config)
    result = await op.execute(question, save=save)
    return {"answer": result.answer, "citations": result.citations,
            "confidence": result.confidence}


@mcp.tool()
async def wiki_write(page_path: str, content: str,
                     page_type: str = "entity") -> dict:
    """Update a wiki page. Call this after significant code changes
    to keep the wiki in sync."""
    store.create_page(Path(page_path), content, PageType(page_type))
    await store.update_index_single(page_path)
    await store.append_log(f"MCP update: {page_path}")
    return {"status": "updated", "path": page_path}


@mcp.tool()
async def wiki_log(entry: str) -> dict:
    """Append an entry to wiki log. Use after completing significant tasks."""
    await store.append_log(entry)
    return {"status": "logged"}


@mcp.tool()
async def wiki_status() -> dict:
    """Get wiki stats: page count, health score, last update, daily cost."""
    stats = store.get_stats()
    cost = cost_tracker.get_daily_spent()
    return {"pages": stats.page_count, "health_score": stats.health,
            "last_update": stats.last_update.isoformat(),
            "cost_today_usd": cost}


@mcp.tool()
async def wiki_ingest(source_path: str) -> dict:
    """Ingest a new source into the wiki."""
    op = IngestOperation(store, llm, config, pipeline)
    result = await op.execute(Path(source_path))
    return {"pages_created": result.pages_created,
            "pages_updated": result.pages_updated}
```

Config để Claude Code tự connect:

```json
// .mcp.json (project-level) hoặc ~/.claude/claude_code_config.json
{
  "mcpServers": {
    "wikimind": {
      "command": "wikimind",
      "args": ["serve", "--mcp"]
    }
  }
}
```

---

### Layer 7: CLI Interface

```python
# wikimind/cli/main.py

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="wikimind", help="LLM-powered wiki that maintains itself")
console = Console()


@app.command()
def init(
    template: str = typer.Option("general", help="general | code | research | book"),
    name: str = typer.Option(None, help="Project name"),
):
    """Initialize WikiMind for current project."""
    # 1. Create wikimind.toml from template
    # 2. Create .wiki/ directory structure
    # 3. Create index.md, log.md, overview.md
    # 4. Generate CLAUDE.md / AGENTS.md — LLM schema instructions
    #    (Đây là "schema" layer trong kiến trúc gốc của Karpathy)
    # 5. Install git hook (chỉ khi template = "code")
    # 6. Create .mcp.json for Claude Code


@app.command()
def ingest(
    path: str = typer.Argument(..., help="File or directory"),
    all: bool = typer.Option(False, "--all", help="Ingest all unprocessed in raw/"),
    interactive: bool = typer.Option(False, "-i", help="Review each step"),
    dry_run: bool = typer.Option(False, help="Show plan without executing"),
):
    """Ingest raw sources into wiki."""


@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask"),
    save: bool = typer.Option(False, help="Save answer as wiki page"),
):
    """Query the wiki."""


@app.command()
def lint(
    fix: bool = typer.Option(False, "--fix", help="Auto-fix issues"),
    report: bool = typer.Option(False, help="Export report"),
):
    """Health check the wiki."""


@app.command()
def watch(
    daemon: bool = typer.Option(False, "-d", help="Run as background daemon"),
):
    """Start watching for changes. Runs MCP server + file watcher + git watcher."""
    # 1. Start MCP server
    # 2. Start file watcher on raw/
    # 3. Start git watcher
    # 4. Start scheduler (batch processing + cron jobs)
    # 5. Process queue loop


@app.command()
def cost(
    period: str = typer.Option("today", help="today | week | month | all"),
    detail: bool = typer.Option(False, help="Per-operation breakdown"),
):
    """Show token usage and cost."""


@app.command()
def status():
    """Wiki stats: pages, health score, last update."""


@app.command()
def search(query: str = typer.Argument(...)):
    """Search wiki pages."""


@app.command()
def serve(
    mcp: bool = typer.Option(False, "--mcp", help="Start MCP server"),
    port: int = typer.Option(8080, help="HTTP API port"),
):
    """Start servers (MCP and/or HTTP API)."""
```

---

## VII. Database Schema

```sql
-- wikimind/db/migrations/001_initial.sql

CREATE TABLE IF NOT EXISTS pages (
    path TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    page_type TEXT NOT NULL,       -- source, entity, concept, analysis, decision
    tags TEXT DEFAULT '[]',        -- JSON array
    related_files TEXT DEFAULT '[]',
    content_hash TEXT NOT NULL,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS links (
    from_page TEXT NOT NULL,
    to_page TEXT NOT NULL,
    PRIMARY KEY (from_page, to_page),
    FOREIGN KEY (from_page) REFERENCES pages(path),
    FOREIGN KEY (to_page) REFERENCES pages(path)
);

CREATE TABLE IF NOT EXISTS sources (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    priority INTEGER NOT NULL,
    payload TEXT NOT NULL,         -- JSON
    status TEXT DEFAULT 'pending', -- pending, processing, done, failed
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed TIMESTAMP,
    cost_usd REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    task_type TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    pages_affected INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS embeddings (
    page_path TEXT PRIMARY KEY,
    vector BLOB NOT NULL,         -- Serialized numpy array
    updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (page_path) REFERENCES pages(path)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_costs_date ON costs(timestamp);
CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_page);
```

---

## VIII. Dependencies

```toml
# pyproject.toml

[project]
name = "wikimind"
version = "0.1.0"
description = "LLM-powered wiki that maintains itself"
requires-python = ">=3.11"

dependencies = [
    # CLI + UI
    "typer>=0.9",
    "rich>=13.0",

    # LLM Providers
    "anthropic>=0.40",
    "openai>=1.0",
    "httpx>=0.27",              # For Ollama

    # MCP Server
    "mcp>=1.2",

    # File watching
    "watchdog>=4.0",

    # Search
    "rank-bm25>=0.2",

    # Storage
    "aiosqlite>=0.20",

    # Markdown
    "python-frontmatter>=1.1",

    # Git
    "gitpython>=3.1",

    # Utils
    "tomli>=2.0",
    "python-slugify>=8.0",
]

[project.optional-dependencies]
semantic = [
    "sentence-transformers>=2.0",   # Semantic search
]
api = [
    "fastapi>=0.110",              # HTTP API
    "uvicorn>=0.29",
]

[project.scripts]
wikimind = "wikimind.cli.main:app"
```

---

## IX. Wiki Output Structure

```
.wiki/                              # Được tạo bởi "wikimind init"
│
├── index.md                        # Master index — mục lục toàn bộ wiki
│   # Ví dụ:
│   # # Project Wiki Index
│   # ## Modules
│   # - [[auth]] — Authentication & authorization
│   # - [[payments]] — Payment processing
│   # ## Concepts
│   # - [[jwt-rotation]] — Token rotation strategy
│   # ## Decisions
│   # - [[adr-001-switch-to-postgres]] — Why we migrated
│
├── log.md                          # Append-only changelog
│   # ## [2026-04-08 14:30] ingest | Added paper on JWT best practices
│   # ## [2026-04-08 15:00] update | Refactored auth middleware → 3 guards
│   # ## [2026-04-08 16:00] query  | Saved: "How does auth handle expiry?"
│
├── overview.md                     # Project overview: tech stack, arch, team
│
├── modules/                        # Mỗi module/service một trang
│   ├── auth.md
│   └── payments.md
│
├── concepts/                       # Domain concepts
│   ├── jwt-rotation.md
│   └── rate-limiting.md
│
├── decisions/                      # Architecture Decision Records
│   └── adr-001-switch-to-postgres.md
│
├── sources/                        # Tóm tắt mỗi raw source
│   ├── jwt-best-practices-paper.md
│   └── oauth2-rfc.md
│
├── analyses/                       # Saved Q&A, comparisons
│   └── auth-token-expiry.md
│
└── .wikimind.db                    # SQLite metadata (không commit vào git)
```

Markdown page format:

```markdown
---
title: Authentication Module
type: entity
tags: [auth, security, middleware]
related_files: [src/auth/middleware.ts, src/auth/guards/]
created: 2026-04-08
updated: 2026-04-08
sources: [sources/jwt-best-practices-paper]
---

# Authentication Module

## Overview
Auth module handles user authentication via JWT tokens with automatic rotation...

## Architecture
Three guard layers: [[jwt-rotation]] validation, rate limiting, session check...

## Key Decisions
- Switched from session cookies to JWT — see [[adr-001-switch-to-postgres]]
- Token TTL = 30 minutes (configured in `src/auth/config.ts`)

## Dependencies
- [[payments]] module calls auth for transaction verification
- Uses Redis for token blacklist

## Recent Changes
- **2026-04-08**: Refactored into 3 separate guards (previously monolithic)
```

---

## IX-B. Generated CLAUDE.md — "Schema" Layer (Karpathy)

Karpathy's architecture có 3 layers: Raw sources, Wiki, và **Schema**. Schema được mô tả là "a document (e.g. CLAUDE.md for Claude Code or AGENTS.md for Codex) that tells the LLM how the wiki is structured, what the conventions are, and what workflows to follow."

`wikimind.toml` = tool configuration (cho WikiMind engine).
`CLAUDE.md` = LLM instructions (cho Claude Code / LLM agent).

**Cả hai đều cần.** `wikimind init` phải generate CLAUDE.md. Đây là sample cho template "code":

```markdown
# Wiki-Maintained Knowledge Base

This project uses WikiMind to maintain a persistent wiki in `.wiki/`.

## For the LLM Agent

**Before reading source files**, check the wiki first:
1. Use `wiki_search` to find relevant wiki pages
2. Read wiki pages (pre-compiled summaries) instead of reading multiple source files
3. Only read source files when wiki pages are insufficient or you need exact code

**After making significant changes**, update the wiki:
1. Use `wiki_write` to update affected wiki pages
2. Use `wiki_log` to record what changed and why

**When answering questions about the project**:
1. Use `wiki_query` for synthesized answers with citations
2. If the answer is valuable, use `save=true` to file it back into the wiki

## Wiki Structure

- `index.md` — Master index, read this first to find relevant pages
- `log.md` — Chronological record of changes
- `modules/` — One page per module/service
- `concepts/` — Domain concepts and patterns
- `decisions/` — Architecture Decision Records
- `sources/` — Summaries of raw sources in `raw/`
- `analyses/` — Saved query answers and comparisons

## Conventions

- All wiki pages have YAML frontmatter: title, type, tags, created, updated
- Use [[wikilinks]] to cross-reference between pages
- When new information contradicts existing wiki content, flag it explicitly
- The wiki is the source of truth for project knowledge; source files are the source of truth for code
```

> Mỗi template (general, research, book, personal) sẽ có CLAUDE.md khác nhau,
> phù hợp với conventions và page types của domain đó.

---

## X. Data Flow — 3 Scenarios chi tiết

### Scenario 1: Commit code (tự động, bạn không cần làm gì)

```
git commit -m "refactor: split auth middleware into 3 guards"
       │
       ▼
  GitWatcher (post-commit hook)
    emit CommitEvent(hash, msg, files=[src/auth/...])
       │
       ▼
  Event Queue:
    Filter    → src/auth/*.ts passes (not ignored)
    Debounce  → wait 5s... no more commits → proceed
    Prioritize → 4 files, src/ → NORMAL
    Batch     → no related events → single task
    Outbox    → Task(UPDATE, NORMAL)
       │
       ▼
  Scheduler: mode=batch → hold 60min (or 5+ tasks)
       │
       ▼
  Processing Pipeline:
    Classifier  [Local]    → RESTRUCTURE
    Analyzer    [Primary]  → "Auth now uses 3 guards, JWT rotation..."
    Planner     [Primary]  → UPDATE auth.md, CREATE jwt-rotation.md
    Writer      [Maint.]   → Write markdown content
    Linker      [No LLM]   → auth.md ←→ jwt-rotation.md
    Validator   [No LLM]   → ✅ All checks pass
       │
       ▼
  Wiki Store: write files, update SQLite, update index + log
  Cost Tracker: Primary 4.2K tok + Maint 3.1K tok = $0.035
```

### Scenario 2: User query (qua MCP — Claude Code tự dùng)

```
User → Claude Code: "Auth module hoạt động thế nào?"

  Claude Code:
    → wiki_search("auth module")        ← TỰ ĐỘNG dùng MCP tool
    → wiki_read("modules/auth")         ← 500 tokens thay vì 5000
    → Trả lời user

User → Claude Code: "Refactor tách middleware"

  Claude Code:
    → wiki_read("modules/auth")         ← Hiểu context từ wiki
    → read_file("src/auth/...")         ← Chỉ đọc file cần sửa
    → write_file(...)                   ← Sửa code
    → wiki_write("modules/auth", ...)   ← TỰ ĐỘNG update wiki
    → wiki_log("Refactored auth")       ← TỰ ĐỘNG log
    → git commit
         │
         └→ git hook: wiki already updated? ✅ skip
```

### Scenario 3: Daily lint (scheduled, tự động)

```
  Scheduler: 2:00 AM daily

  Structural checks [No LLM]:
    • 2 orphan pages
    • 1 broken [[wikilink]]
    • 3 stale pages (source changed)
    • index.md missing 1 page

  Semantic checks [Local LLM]:
    • 1 contradiction found

  Auto-fix [Maint. LLM]:
    • Fixed broken link, updated index
    • Flagged contradiction → needs human
    • Queued re-process for 3 stale pages

  Log: "Wiki health: 87/100 (+2). Fixed 4, flagged 1."
```

---

## XI. Cost Tracking

```
$ wikimind cost --detail

╭──────────── WikiMind Cost Report ─────────────╮
│ Period: Today (2026-04-08)                     │
│                                                │
│ Operation      Count   Tokens     Cost         │
│ ─────────────────────────────────────────      │
│ Ingest           3     22,400    $0.18         │
│ Query            8     31,200    $0.24         │
│ Update (auto)   12     18,600    $0.05  ← Haiku│
│ Lint              1    15,000    $0.00  ← Local│
│ ─────────────────────────────────────────      │
│ TOTAL           24     87,200    $0.47         │
│                                                │
│ Budget: $2.00/day │ Remaining: $1.53           │
│ Wiki pages: 47 (+5 today)                      │
│ Health score: 87/100                           │
╰────────────────────────────────────────────────╯
```

---

## XII. Kế hoạch phát triển — 4 Phases

```
Phase 1A — MVP Core (Tuần 1)
════════════════════════════════
  ✅ Project scaffold + pyproject.toml
  ✅ Core models + config system (wikimind.toml)
  ✅ Wiki store (filesystem CRUD + markdown-as-source-of-truth)
  ✅ SQLite chỉ cho: tasks, costs, embeddings (3 tables)
  ✅ LLM abstraction (1 provider: Anthropic)
  ✅ index.md + log.md management
  ✅ IngestOperation (simple: LLM reads source + index → outputs wiki pages)
     Chưa cần full pipeline 6 bước. Single-prompt approach đủ cho MVP.
  ✅ CLI: init (generate wikimind.toml + CLAUDE.md + .wiki/ structure), ingest, status
  ✅ Cold-start: "wikimind init" tạo overview.md từ project scan (hoặc empty template)

  ✨ Milestone: "wikimind init → wikimind ingest article.md"
     tạo wiki pages, update index.md, append log.md


Phase 1B — Query + Pipeline (Tuần 2)
═════════════════════════════════════
  ✅ QueryOperation (search index.md → read pages → synthesize answer)
  ✅ Query cold-start: khi wiki trống, suggest "run wikimind ingest first"
  ✅ Full processing pipeline (classifier → analyzer → planner → writer → linker → validator)
     Thay thế single-prompt approach từ 1A khi cần quality cao hơn
  ✅ CLI: query, search
  ✅ Cost tracker (basic)
  ✅ Write-back: query --save

  ✨ Milestone: "wikimind query 'how does auth work?'" trả lời + citations


Phase 2 — Automation (Tuần 3-4)
════════════════════════════════
  ✅ MCP Server (wiki_search, wiki_read, wiki_write, wiki_query, wiki_log, wiki_status)
  ✅ Generate CLAUDE.md (schema layer) trong wikimind init
  ✅ Claude Code auto-connect (.mcp.json)
  ✅ File watcher (raw/ directory via watchdog)
  ✅ Git watcher — optional, chỉ cho code projects
  ✅ Event Queue layer (filter, debounce, prioritize, batch)
  ✅ Model router (primary / maintenance / local)
  ✅ Budget guard
  ✅ CLI: watch, watch --daemon

  ✨ Milestone: Claude Code TỰ ĐỘNG dùng wiki qua MCP + file watcher auto-ingest


Phase 3 — Quality (Tuần 5-6)
═════════════════════════════
  ✅ LintOperation (structural checks — no LLM)
  ✅ Lint semantic checks (contradiction detection — local LLM)
  ✅ Lint --fix (auto-fix)
  ✅ Scheduler (batch runner + cron: lint, reindex)
  ✅ Cross-reference engine (graph traversal từ markdown)
  ✅ BM25 search (thay thế index-only search khi wiki lớn)
  ✅ Multi-provider (OpenAI, Ollama)
  ✅ Detailed cost reports
  ✅ CLI: lint, cost

  ✨ Milestone: Wiki self-maintains: auto-fix broken links, flag contradictions


Phase 4 — Polish (Tuần 7-8)
════════════════════════════
  ✅ Semantic search (embeddings — optional dependency)
  ✅ Multiple templates (code, research, book, personal)
  ✅ HTTP API (FastAPI — optional dependency)
  ✅ Export: Obsidian-optimized, static HTML
  ✅ CI/CD integration (GitHub Actions)
  ✅ Comprehensive tests
  ✅ Documentation + README

  ✨ Milestone: Production-ready, publishable to PyPI
```

> **Triết lý phân phase:** Phase 1 phải usable standalone (CLI only, no daemon).
> MCP server lên Phase 2 vì nó biến WikiMind thành "invisible" — nhưng Phase 1
> phải hoạt động trước khi invisible. Phase 3 tập trung quality vì wiki cần
> trust trước khi scale.

---

## XIII. Tóm tắt — WikiMind theo tinh thần Karpathy

Karpathy viết bài gist như "an idea file, designed to be copy pasted to your own LLM Agent... Its goal is to communicate the high level idea, but your agent will build out the specifics in collaboration with you."

WikiMind hiện thực hóa ý tưởng đó thành ứng dụng cụ thể:

```
Karpathy nói                         WikiMind implement
════════════                         ═══════════════════

"LLM is knowledge compiler"     →   Pipeline: classify → analyze →
                                     plan → write → link → validate

"Knowledge compounds"            →   Write-back: mọi output quay lại wiki.
                                     Query answers, code changes, new sources
                                     đều làm wiki giàu hơn

"Maintenance cost = 0"           →   3 cơ chế tự động:
                                     MCP (primary) + Git hook (backup)
                                     + File watcher (raw/) + Scheduler

"Human curates, LLM does rest"  →   CLI cho human: init, query, lint
                                     Daemon cho LLM: watch, auto-update

"3 operations: ingest/query/lint" → operations/ module, mỗi cái end-to-end

"Just markdown + local files"    →   .wiki/ = markdown, .wikimind.db = SQLite
                                     No cloud, no vendor lock-in

"Optional and modular"           →   Config per project (wikimind.toml),
                                     optional deps (semantic, api)
```

Karpathy's original insight stands: the bottleneck is bookkeeping, and LLMs eliminate that bottleneck. What we've added is the machinery that keeps the wiki healthy as it scales — lifecycle management so knowledge doesn't rot, structure so connections aren't lost, automation so humans stay focused on thinking rather than filing, quality controls so the wiki earns trust over time.

---

## Obsidian graph và SQLite giải quyết hai vấn đề KHÁC NHAU

```
Obsidian graph = VISUALIZATION của [[wikilinks]] trong markdown
SQLite         = OPERATIONAL DATABASE cho ứng dụng chạy nền
```

Chúng không thay thế nhau. Nhưng câu hỏi thực sự của Hoc là:

---

## "Nếu [[wikilinks]] đã nằm trong markdown, tại sao cần SQLite lưu links?"

**Đúng.** Obsidian chứng minh điều này — nó KHÔNG có database, chỉ parse markdown mỗi lần mở vault:

```
Obsidian cách hoạt động:

  Mở vault
     │
     ▼
  Scan tất cả *.md files
     │
     ▼
  Parse [[wikilinks]] + frontmatter
     │
     ▼
  Build graph IN MEMORY
     │
     ▼
  Render UI (graph view, backlinks panel, etc.)

  → Không có database file nào cả
  → Source of truth = markdown files
  → Graph được DERIVE mỗi lần mở app
```

WikiMind hoàn toàn có thể làm giống vậy cho links/graph:

```python
# Thay vì SQLite table "links":

class MarkdownGraphBuilder:
    """Build graph from markdown files — giống Obsidian."""

    def build(self, wiki_path: Path) -> dict:
        graph = {}
        for md_file in wiki_path.rglob("*.md"):
            content = md_file.read_text()
            links = re.findall(r'\[\[(.+?)\]\]', content)
            graph[md_file.stem] = links
        return graph

# 50 pages → ~5ms scan
# 200 pages → ~20ms scan
# 1000 pages → ~100ms scan (vẫn nhanh)
```

---

## Vậy SQLite thực sự cần cho cái gì?

```
CẦN SQLite:                          KHÔNG CẦN SQLite:
(markdown không làm được)             (markdown + parse đủ rồi)
═══════════════════════              ══════════════════════════

Task queue                           Links / graph
  → 5 tasks pending, survive crash     → Parse [[wikilinks]] từ markdown
  → Markdown không phải queue          → Giống Obsidian

Cost tracking                        Page metadata
  → SUM tokens theo ngày               → Frontmatter trong markdown
  → GROUP BY model, operation           → Parse khi cần
  → Markdown không phải spreadsheet

Embeddings (vectors)                 Source dedup
  → Binary data, 768 dimensions        → Có thể dùng JSON file đơn giản
  → Markdown không lưu vectors          → {"hash": "ingested_at"}

Dedup / content hashes               
  → Nhanh O(1) lookup                 
  → Có thể dùng JSON nhưng SQLite     
    tốt hơn khi data lớn              
```

---

## Thiết kế tối ưu: Kết hợp cả hai

```
┌──────────────────────────────────────────────────────┐
│                                                       │
│  MARKDOWN = Source of truth (giống Obsidian)          │
│  ════════════════════════════════════════             │
│                                                       │
│  .wiki/                                               │
│  ├── index.md          ← Mục lục                     │
│  ├── log.md            ← Changelog                   │
│  ├── modules/auth.md   ← Content + [[wikilinks]]     │
│  └── concepts/jwt.md   ← Content + frontmatter       │
│                                                       │
│  Từ markdown, derive được:                            │
│  • Graph (parse [[wikilinks]])                        │
│  • Page metadata (parse frontmatter)                  │
│  • Backlinks (reverse graph)                          │
│  • Orphan pages (nodes with 0 inbound)                │
│  • Broken links (link to non-existent page)           │
│                                                       │
│  → Mở Obsidian = thấy graph view ngay                │
│  → Không cần SQLite cho phần này                      │
│                                                       │
├──────────────────────────────────────────────────────┤
│                                                       │
│  SQLite = Operational data (WikiMind engine only)    │
│  ═══════════════════════════════════════              │
│                                                       │
│  .wikimind.db                                         │
│  ├── tasks    ← Queue: pending wiki updates           │
│  ├── costs    ← Token tracking: $0.47 today           │
│  └── vectors  ← Embeddings cho semantic search        │
│                                                       │
│  → Human không cần biết file này tồn tại              │
│  → Xóa đi? WikiMind rebuild được, chỉ mất history    │
│  → Không commit vào git (.gitignore)                  │
│                                                       │
└──────────────────────────────────────────────────────┘
```

---

## Cập nhật thiết kế: Bỏ tables thừa khỏi SQLite

```
TRƯỚC (6 tables):                    SAU (3 tables):
══════════════════                   ══════════════════

pages      ← metadata               ❌ BỎ → parse frontmatter
links      ← graph                   ❌ BỎ → parse [[wikilinks]]
sources    ← dedup hashes            ❌ BỎ → dùng JSON file đơn giản
tasks      ← queue                   ✅ GIỮ
costs      ← token tracking          ✅ GIỮ
embeddings ← vectors                 ✅ GIỮ
```

```python
# Thay thế pages + links + sources tables:

# 1. Page metadata → đọc từ frontmatter (giống Obsidian)
def get_page_metadata(path: Path) -> dict:
    post = frontmatter.load(path)
    return post.metadata  # {title, type, tags, created, updated, ...}

# 2. Graph → parse từ markdown (giống Obsidian)
def get_graph(wiki_path: Path) -> dict[str, list[str]]:
    graph = {}
    for md in wiki_path.rglob("*.md"):
        content = md.read_text()
        graph[md.stem] = re.findall(r'\[\[(.+?)\]\]', content)
    return graph

# 3. Source dedup → JSON file đơn giản
# .wiki/.sources.json
# {"raw/paper.pdf": {"hash": "abc123", "ingested_at": "2026-04-08"}}
```

```sql
-- Schema mới — chỉ 3 tables

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    priority INTEGER NOT NULL,
    payload TEXT NOT NULL,           -- JSON
    status TEXT DEFAULT 'pending',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed TIMESTAMP,
    cost_usd REAL DEFAULT 0.0
);

CREATE TABLE costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    task_type TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL
);

CREATE TABLE embeddings (
    page_path TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Lợi ích

```
1. Obsidian compatible 100%
   → Mở .wiki/ bằng Obsidian = graph view, backlinks, search hoạt động ngay
   → Không có file lạ nào trong vault (SQLite nằm ngoài hoặc .gitignore)

2. Đơn giản hơn
   → 3 tables thay vì 6
   → Ít code maintain hơn
   → Source of truth chỉ có 1 nơi: markdown files

3. Portable hơn
   → Copy .wiki/ folder đến máy khác = hoạt động
   → Không cần migrate database
   → SQLite mất? Chỉ mất cost history + queue (rebuild embeddings được)

4. Debug dễ hơn
   → "Auth page link đến gì?" → mở file, đọc bằng mắt
   → Không cần SQL query
```

Tóm lại: Hoc đúng — graph nên derive từ markdown giống Obsidian, không cần SQLite cho phần đó. SQLite chỉ giữ lại cho **operational data** mà markdown không thể thay thế: task queue, cost tracking, embeddings.