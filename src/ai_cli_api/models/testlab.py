from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import ProviderName


class TestVerifyItem(BaseModel):
    """A single model's test results to verify against expected keywords."""

    provider: ProviderName = Field(description="Provider that was tested.")
    model: str = Field(description="Model that was tested.")
    new_exit_code: int = Field(description="Exit code from the NEW chat step.")
    resume_text: str = Field(description="Full response text from the RESUME chat step.")
    resume_exit_code: int = Field(description="Exit code from the RESUME chat step.")
    keywords: list[str] = Field(description="Keywords expected in the resume response text.")


class TestVerifyRequest(BaseModel):
    """Request body for verifying test results across multiple models."""

    items: list[TestVerifyItem] = Field(description="List of per-model test results to verify.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "provider": "claude",
                            "model": "sonnet",
                            "new_exit_code": 0,
                            "resume_text": "Your responsibilities include PF, ATM, and Transit.",
                            "resume_exit_code": 0,
                            "keywords": ["PF", "ATM", "Transit"],
                        }
                    ]
                }
            ]
        }
    )


class TestVerifyResultItem(BaseModel):
    """Verification result for a single model run."""

    provider: ProviderName = Field(description="Provider that was tested.")
    model: str = Field(description="Model that was tested.")
    new_status: str = Field(description="'OK' if new chat succeeded, otherwise 'FAIL'.")
    resume_status: str = Field(description="'OK' if resume chat succeeded, otherwise 'FAIL'.")
    keyword_results: dict[str, bool] = Field(description="Map of keyword to presence in resume text.")
    grade: str = Field(description="'PASS' when both steps are OK and all keywords are found.")


class TestVerifyResponse(BaseModel):
    """Response containing verification results for all tested models."""

    results: list[TestVerifyResultItem] = Field(description="Per-model verification results.")


class TestGenerateRequest(BaseModel):
    """Request body for AI-generated scenario content."""

    field: str = Field(description="'story', 'questions', 'expected', or 'all'.")
    workspace_path: str = Field(
        min_length=1,
        description="Absolute path to the workspace directory passed to the CLI.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"field": "all", "workspace_path": "C:\\Github\\ai-cli-api"}]
        }
    )


class TestQAPair(BaseModel):
    """A single question + expected keywords pair for Test Lab."""

    question: str = Field(description="Follow-up question to send as a RESUME prompt.")
    expected: str = Field(description="Comma-separated keywords expected in the response.")


class TestGenerateResponse(BaseModel):
    """Response containing AI-generated scenario content."""

    story: str | None = Field(default=None, description="Generated story for the NEW prompt.")
    questions: str | None = Field(default=None, description="Deprecated. Use qa_pairs instead.")
    expected: str | None = Field(default=None, description="Deprecated. Use qa_pairs instead.")
    qa_pairs: list[TestQAPair] = Field(default_factory=list, description="List of question/expected pairs.")
