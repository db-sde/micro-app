"""
SQLAlchemy ORM models for DegreeBaba Content Publisher.

Tables:
  - uploads: tracks each uploaded .docx file and its processing state
  - field_mappings: per-field extraction results for an upload
  - bulk_jobs: tracks batch/zip upload jobs
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    page_type = Column(String(50), nullable=True, comment="university / course / specialization")
    status = Column(String(50), default="draft", nullable=False)
    score = Column(Float, nullable=True)
    payload = Column(Text, nullable=True, comment="Full ACF JSON payload")
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    field_mappings = relationship(
        "FieldMapping",
        back_populates="upload",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Upload id={self.id} filename={self.filename!r} status={self.status}>"


class FieldMapping(Base):
    __tablename__ = "field_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(
        Integer,
        ForeignKey("uploads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_key = Column(String(100), nullable=False)
    heading_in_doc = Column(String(500), nullable=True)
    value = Column(Text, nullable=True)
    confidence = Column(Float, default=0.0, nullable=False)
    status = Column(
        String(50),
        default="missing",
        nullable=False,
        comment="mapped / thin / missing",
    )
    source = Column(
        String(50),
        default="none",
        nullable=False,
        comment="embedding / ai / manual / none",
    )
    is_confirmed = Column(Boolean, default=False, nullable=False)

    upload = relationship("Upload", back_populates="field_mappings")

    def __repr__(self) -> str:
        return (
            f"<FieldMapping id={self.id} field_key={self.field_key!r} "
            f"status={self.status} confidence={self.confidence:.2f}>"
        )


class BulkJob(Base):
    __tablename__ = "bulk_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(50), default="pending", nullable=False)
    total_files = Column(Integer, default=0, nullable=False)
    processed_files = Column(Integer, default=0, nullable=False)
    page_type = Column(String(50), nullable=True)
    dry_run = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    results = Column(Text, nullable=True, comment="JSON string of per-file results")

    def __repr__(self) -> str:
        return (
            f"<BulkJob id={self.id} status={self.status} "
            f"processed={self.processed_files}/{self.total_files}>"
        )
