from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import Optional, List
from enum import Enum
from decimal import Decimal


class DubbingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class LanguageCode(str, Enum):
    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"


# Persistent models (stored in database)
class Language(SQLModel, table=True):
    __tablename__ = "languages"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    code: LanguageCode = Field(unique=True)
    name: str = Field(max_length=100)
    is_active: bool = Field(default=True)

    # Relationships
    source_videos: List["Video"] = Relationship(back_populates="source_language")
    target_dubbing_jobs: List["DubbingJob"] = Relationship(back_populates="target_language")


class Video(SQLModel, table=True):
    __tablename__ = "videos"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    file_path: str = Field(max_length=500)
    file_size: int = Field(ge=0)  # Size in bytes
    duration: Optional[Decimal] = Field(default=None, decimal_places=2)  # Duration in seconds
    mime_type: str = Field(max_length=100)
    source_language_id: int = Field(foreign_key="languages.id")
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    source_language: Language = Relationship(back_populates="source_videos")
    dubbing_jobs: List["DubbingJob"] = Relationship(back_populates="source_video")


class DubbingJob(SQLModel, table=True):
    __tablename__ = "dubbing_jobs"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    source_video_id: int = Field(foreign_key="videos.id")
    target_language_id: int = Field(foreign_key="languages.id")
    status: DubbingStatus = Field(default=DubbingStatus.PENDING)
    output_filename: Optional[str] = Field(default=None, max_length=255)
    output_file_path: Optional[str] = Field(default=None, max_length=500)
    output_file_size: Optional[int] = Field(default=None, ge=0)  # Size in bytes
    processing_started_at: Optional[datetime] = Field(default=None)
    processing_completed_at: Optional[datetime] = Field(default=None)
    error_message: Optional[str] = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    source_video: Video = Relationship(back_populates="dubbing_jobs")
    target_language: Language = Relationship(back_populates="target_dubbing_jobs")


# Non-persistent schemas (for validation, forms, API requests/responses)
class VideoUpload(SQLModel, table=False):
    filename: str = Field(max_length=255)
    file_size: int = Field(ge=0)
    mime_type: str = Field(max_length=100)
    source_language_id: int


class VideoResponse(SQLModel, table=False):
    id: int
    filename: str
    original_filename: str
    file_size: int
    duration: Optional[Decimal]
    mime_type: str
    source_language_id: int
    uploaded_at: str  # ISO format string
    source_language_name: str


class DubbingJobCreate(SQLModel, table=False):
    source_video_id: int
    target_language_id: int


class DubbingJobResponse(SQLModel, table=False):
    id: int
    source_video_id: int
    target_language_id: int
    status: DubbingStatus
    output_filename: Optional[str]
    output_file_size: Optional[int]
    processing_started_at: Optional[str]  # ISO format string
    processing_completed_at: Optional[str]  # ISO format string
    error_message: Optional[str]
    created_at: str  # ISO format string
    updated_at: str  # ISO format string
    source_video_filename: str
    target_language_name: str


class DubbingJobUpdate(SQLModel, table=False):
    status: Optional[DubbingStatus] = Field(default=None)
    output_filename: Optional[str] = Field(default=None, max_length=255)
    output_file_path: Optional[str] = Field(default=None, max_length=500)
    output_file_size: Optional[int] = Field(default=None, ge=0)
    processing_started_at: Optional[datetime] = Field(default=None)
    processing_completed_at: Optional[datetime] = Field(default=None)
    error_message: Optional[str] = Field(default=None, max_length=1000)


class LanguageResponse(SQLModel, table=False):
    id: int
    code: LanguageCode
    name: str
    is_active: bool
