import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class EnrichmentTaskTypeEnum(str, Enum):
    CLAIM_EXTRACTION = "CLAIM_EXTRACTION"
    CONCEPT_EXTRACTION = "CONCEPT_EXTRACTION"
    RELATION_EXTRACTION = "RELATION_EXTRACTION"
    SUMMARY = "SUMMARY"

class EnrichmentStatusEnum(str, Enum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    worker_id: str = Field(default="local_worker_01")
    model: str = Field(default="qwen2.5-coder:7b")
    model_quantization: str = Field(default="Q4")
    prompt_version: str = Field(default="v1.0")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class QueueTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: f"tsk_{uuid.uuid4().hex[:12]}")
    job_id: str = Field(description="ID del trabajo de enriquecimiento")
    chunk_id: str = Field(description="FK al fragmento en catalog.db")
    task_type: EnrichmentTaskTypeEnum
    priority: int = Field(default=1)
    status: EnrichmentStatusEnum = Field(default=EnrichmentStatusEnum.PENDING)
    worker_id: Optional[str] = Field(default=None)
    lease_until: Optional[str] = Field(default=None)
    heartbeat_at: Optional[str] = Field(default=None)
    attempts: int = Field(default=0)
    model_name: Optional[str] = Field(default="qwen2.5-coder:7b")
    prompt_version: str = Field(default="v1.0")
    error_message: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = Field(default=None)

class KaggleJobManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    input_manifest_sha256: str
    schema_version: str = Field(default="2.1")
    worker_version: str = Field(default="1.0.0")
    model_used: str = Field(default="qwen2.5-coder:7b")
    model_quantization: str = Field(default="Q4")
    chunks_processed: int = Field(default=0)
    claims_generated: int = Field(default=0)
    claims_verified: int = Field(default=0)
    relations_generated: int = Field(default=0)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
