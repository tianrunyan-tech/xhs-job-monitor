from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NoteSummary:
    note_id: str
    note_url: str
    keyword: str
    xsec_token: str = ""
    title: str = ""
    author_name: str = ""
    author_id: str = ""
    publish_time: Optional[str] = None


@dataclass
class NoteDetail(NoteSummary):
    raw_text: str = ""
    image_text: str = ""
    first_comment: str = ""
    crawl_time: Optional[str] = None


@dataclass
class JobExtraction:
    is_job_post: bool
    confidence: float
    company: Optional[str] = None
    job_title: Optional[str] = None
    position_info: Optional[str] = None
    location: Optional[str] = None
    requirement: Optional[str] = None
    contact_info: Optional[str] = None

    @classmethod
    def empty_failure(cls):
        return cls(is_job_post=False, confidence=0.0)


@dataclass
class RunStats:
    keywords: int = 0
    notes_seen: int = 0
    notes_parsed: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    errors: int = 0


@dataclass
class RunResult:
    ok: bool
    schema_version: str
    run_type: str
    stats: RunStats
    data: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["stats"] = asdict(self.stats)
        return result
