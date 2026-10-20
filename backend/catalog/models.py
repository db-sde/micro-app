from sqlalchemy import Column, Integer, BigInteger, String, Text, LargeBinary, Float, UniqueConstraint
from db.database import Base


class CatalogLock(Base):
    __tablename__ = "catalog_lock"
    id = Column(Integer, primary_key=True)
    revision = Column(BigInteger, nullable=False, default=0)
    site = Column(String(2048))
    destination = Column(String(2048))
    sender_token = Column(String(36))
    sender_until = Column(Float, nullable=False, default=0)


class CatalogPost(Base):
    __tablename__ = "catalog_posts"
    id = Column(Integer, primary_key=True)
    site = Column(String(2048), nullable=False)
    page_type = Column(String(50), nullable=False)
    wp_post_id = Column(String(64), nullable=False)
    version = Column(BigInteger, nullable=False, default=0)
    applied_version = Column(BigInteger, nullable=False, default=0)
    entity_slug = Column(String(80))
    catalog_slug = Column(String(80))
    # Pending explicit removals are consumed by one event, never inferred.
    clear_fields = Column(Text, nullable=False, default="[]")
    __table_args__ = (UniqueConstraint("site", "page_type", "wp_post_id"),)


class CatalogPublication(Base):
    """Latest successful WP snapshot per upload, independent of later editor changes/deletion."""
    __tablename__ = "catalog_publications"
    upload_id = Column(Integer, primary_key=True)
    post_id = Column(Integer, nullable=False, index=True)
    operation_id = Column(String(36), nullable=False, unique=True)
    published_at = Column(Float, nullable=False)
    wp_status = Column(String(50), nullable=False)
    reviewed = Column(Integer, nullable=False, default=1)
    source_url = Column(Text)
    university_id = Column(String(64))
    course_id = Column(String(64))
    snapshot = Column(Text, nullable=False)
    error = Column(Text)
    event_id = Column(String(36))


class CatalogEvent(Base):
    __tablename__ = "catalog_outbox"
    event_id = Column(String(36), primary_key=True)
    post_id = Column(Integer, nullable=False, index=True)
    version = Column(BigInteger, nullable=False)
    body = Column(LargeBinary, nullable=False)
    university_id = Column(String(64))
    course_id = Column(String(64))
    status = Column(String(30), nullable=False, default="queued")
    delivered = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt = Column(Float, nullable=False, default=0, index=True)
    lease_token = Column(String(36))
    lease_until = Column(Float, nullable=False, default=0)
    last_error = Column(Text)
    warnings = Column(Text, nullable=False, default="[]")
    __table_args__ = (UniqueConstraint("post_id", "version"),)


class CatalogBackfill(Base):
    __tablename__ = "catalog_backfills"
    id = Column(String(36), primary_key=True)
    created_at = Column(Float, nullable=False)
    # Durable fixed membership: an interrupted sender resumes these same jobs.
    items = Column(Text, nullable=False)
