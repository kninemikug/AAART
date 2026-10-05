"""State schema and contracts for the ART Master Agent router and pipeline graph.

Based on docs/langgraph_router_design.md (Task 13-1 / 13-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TypedDict


class Path(str, Enum):
    """Processing paths for the ART Master Agent."""

    DOC_QA = "DOC_QA"
    TROUBLESHOOT = "TROUBLESHOOT"
    EXECUTE = "EXECUTE"

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Path):
            return self.value == other.value
        if isinstance(other, str):
            mapping = {
                "P1": "DOC_QA",
                "docs_qa": "DOC_QA",
                "doc_qa": "DOC_QA",
                "DOC_QA": "DOC_QA",
                "P2": "TROUBLESHOOT",
                "troubleshoot": "TROUBLESHOOT",
                "troubleshooting": "TROUBLESHOOT",
                "TROUBLESHOOT": "TROUBLESHOOT",
                "P3": "EXECUTE",
                "execute": "EXECUTE",
                "execution_profile": "EXECUTE",
                "EXECUTE": "EXECUTE",
            }
            return self.value == mapping.get(other, other)
        return False


Path.P1 = Path.DOC_QA  # type: ignore[attr-defined]
Path.P2 = Path.TROUBLESHOOT  # type: ignore[attr-defined]
Path.P3 = Path.EXECUTE  # type: ignore[attr-defined]


class ResponseStatus(str, Enum):
    """Overall response status enum."""

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    WAITING_CLARIFICATION = "WAITING_CLARIFICATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass
class AssetRef:
    """Reference to an external asset (RAW image or profile file)."""

    asset_id: str
    kind: str  # "RAW" | "PROFILE"
    path: str


@dataclass
class OutputSpec:
    """Output image specification."""

    format: str = "JPEG"  # "JPEG" | "PNG" | "TIFF"
    destination: str = ""
    overwrite: bool = False


@dataclass
class RequestContext:
    """Pre-existing or user session context."""

    target_raw_id: Optional[str] = None
    base_profile_id: Optional[str] = None
    confirmed_goal: Optional[str] = None
    output: Optional[OutputSpec] = None
    art_version: Optional[str] = None
    os: Optional[str] = None


@dataclass
class RequestInput:
    """External user request input."""

    request_id: str
    text: str
    session_id: Optional[str] = None
    assets: list[AssetRef] = field(default_factory=list)
    context: Optional[RequestContext] = None


@dataclass
class ResumeInput:
    """Resume input answering a clarification question."""

    request_id: str
    clarification_id: str
    reply_text: str
    assets: list[AssetRef] = field(default_factory=list)


@dataclass
class RuntimeCapabilities:
    """Capabilities provided by current runtime environment."""

    search_ready: bool = False
    profile_ready: bool = False
    render_ready: bool = False
    ppversion: int = 1045


@dataclass
class IntentSignals:
    """Signals extracted from the request during routing."""

    wants_doc: bool = False
    wants_troubleshoot: bool = False
    wants_execute: bool = False
    execution_negated: bool = False
    ambiguous_reasons: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    goal: Optional[str] = None
    constraints: list[str] = field(default_factory=list)


@dataclass
class PlanStep:
    """A single step in the multi-step execution plan."""

    step_id: str
    path: Path
    query: str
    requires: list[str] = field(default_factory=list)


@dataclass
class RouteDecision:
    """Routing decision outcome."""

    primary_path: Optional[Path] = None
    candidate_paths: list[Path] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    plan: list[PlanStep] = field(default_factory=list)


@dataclass
class Clarification:
    """A clarification request when purpose or inputs are missing/ambiguous."""

    id: str
    question: str
    missing_fields: list[str] = field(default_factory=list)
    candidate_paths: list[Path] = field(default_factory=list)
    origin: str = "ROUTE"  # "ROUTE" | "CHECK_EXEC" | "CLARIFY"


@dataclass
class Evidence:
    """Retrieved evidence document chunk."""

    chunk_id: str
    doc_id: str
    source_group_id: str
    source_type: str  # "rawpedia" | "github"
    source_path: str
    source_location: str
    target_url: str
    text: str
    product_scope: str = "ART"


@dataclass
class RetrievalBundle:
    """Bundle of retrieved search results."""

    query: str
    source_filter: str  # "RAWPEDIA" | "GITHUB"
    hits: list[Evidence] = field(default_factory=list)
    snapshot_ref: str = ""


@dataclass
class Citation:
    """Citation reference for grounded answers."""

    doc_id: str
    title: str
    url: str
    source_location: str


@dataclass
class AnswerResult:
    """Answer generated from retrieval."""

    status: str  # "SUPPORTED" | "UNSUPPORTED" | "INSUFFICIENT_EVIDENCE"
    text: str
    citations: list[Citation] = field(default_factory=list)
    applicability: str = ""
    actionable_goal: Optional[str] = None


@dataclass
class ExecutionInput:
    """Validated input ready for profile generation and rendering."""

    raw: AssetRef
    goal: str
    constraints: list[str] = field(default_factory=list)
    base_profile: Optional[AssetRef] = None
    output: OutputSpec = field(default_factory=OutputSpec)


@dataclass
class PhotoFeatures:
    """Extracted EXIF and histogram features from a RAW image."""

    exif: dict[str, Any] = field(default_factory=dict)
    histogram: dict[str, list[float]] = field(default_factory=dict)
    raw_asset_id: str = ""


@dataclass
class ProfileData:
    """Structured ART .arp profile data."""

    ppversion: int = 1045
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed_keys: list[str] = field(default_factory=list)


@dataclass
class ValidationIssue:
    """Issue detected during profile validation."""

    field: str
    code: str
    message: str


@dataclass
class ValidationResult:
    """Profile validation outcome."""

    status: str  # "VALID" | "INVALID"
    issues: list[ValidationIssue] = field(default_factory=list)
    profile_ref: Optional[str] = None


@dataclass
class RenderResult:
    """ART-cli rendering outcome."""

    status: str  # "SUCCEEDED" | "FAILED" | "UNKNOWN"
    exit_code: Optional[int] = None
    output_path: Optional[str] = None
    output_verified: bool = False
    diagnostic: str = ""


@dataclass
class Artifact:
    """An artifact produced by the pipeline (profile or rendered image)."""

    kind: str  # "PROFILE" | "RENDER"
    path: str
    verified: bool = False


@dataclass
class ErrorInfo:
    """Error information recorded on failure."""

    code: str
    message: str
    node: str
    recoverable: bool = False


@dataclass
class StepResult:
    """Execution result for a single plan step."""

    step_id: str
    path: Path
    status: str  # "SUCCEEDED" | "UNSUPPORTED" | "INSUFFICIENT_EVIDENCE" | "FAILED" | "BLOCKED"
    answer: Optional[AnswerResult] = None
    artifacts: list[Artifact] = field(default_factory=list)
    error: Optional[ErrorInfo] = None


@dataclass
class ResponseOutput:
    """Final aggregated response returned to the caller."""

    request_id: str
    status: str  # ResponseStatus value
    primary_path: Optional[Path] = None
    planned_paths: list[Path] = field(default_factory=list)
    completed_steps: list[StepResult] = field(default_factory=list)
    message: str = ""
    citations: list[Citation] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    clarification: Optional[Clarification] = None
    error: Optional[ErrorInfo] = None


class AgentState(TypedDict, total=False):
    """Shared state dictionary for the LangGraph router and execution graph."""

    request: RequestInput
    signals: Optional[IntentSignals]
    decision: Optional[RouteDecision]
    cursor: int
    retrieval: Optional[RetrievalBundle]
    answer: Optional[AnswerResult]
    research_count: int
    clarification: Optional[Clarification]
    clarification_count: int
    clarification_field: Optional[str]
    execution: Optional[ExecutionInput]
    features: Optional[PhotoFeatures]
    profile: Optional[ProfileData]
    validation: Optional[ValidationResult]
    render: Optional[RenderResult]
    profile_attempts: int
    render_attempts: int
    step_results: dict[str, StepResult]
    error: Optional[ErrorInfo]
    response: Optional[ResponseOutput]
    capabilities: RuntimeCapabilities
    resume: Optional[ResumeInput]
    resume_origin: Optional[str]
    resolved_goal: Optional[str]
    trace: list[str]
