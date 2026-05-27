from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CallForPaper(BaseModel):
    id: str
    title: str
    source: str
    journal: str = "No disponible"
    deadline: str = "No disponible"
    description: str = "No disponible"
    url: str = "No disponible"


class ScrapingStatus(BaseModel):
    source_id: Optional[int] = None
    source: str
    success: bool
    count: int
    error: Optional[str] = None


class Source(BaseModel):
    id: int
    name: str
    scraper_type: str
    url: str
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    last_success: Optional[bool] = None
    last_count: int = 0
    last_error: Optional[str] = None


class SourceCreate(BaseModel):
    name: str
    scraper_type: Optional[str] = None
    url: str
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    scraper_type: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None
    settings: Optional[dict[str, Any]] = None


class Search(BaseModel):
    id: int
    name: str
    email: str
    keywords_text: str
    enabled: bool = True
    created_at: datetime
    updated_at: datetime
    last_checked_at: Optional[datetime] = None
    last_notified_at: Optional[datetime] = None
    last_match_count: int = 0
    last_error: Optional[str] = None


class SearchCreate(BaseModel):
    name: str
    email: str
    keywords_text: str
    enabled: bool = True


class SearchUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    keywords_text: Optional[str] = None
    enabled: Optional[bool] = None
