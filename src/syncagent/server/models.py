"""SQLAlchemy models for SyncAgent server.

This module defines the database schema using SQLAlchemy ORM.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


class Machine(Base):
    """Represents a registered machine/client."""

    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    tokens: Mapped[list[Token]] = relationship(
        "Token", back_populates="machine", cascade="all, delete-orphan"
    )
    files_updated: Mapped[list[FileMetadata]] = relationship(
        "FileMetadata", back_populates="updated_by_machine"
    )


class Token(Base):
    """Represents an authentication token."""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    machine: Mapped[Machine] = relationship("Machine", back_populates="tokens")

    # Indexes
    __table_args__ = (Index("idx_tokens_hash", "token_hash"),)


class FileMetadata(Base):
    """Represents file metadata on the server."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("machines.id"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    updated_by_machine: Mapped[Machine] = relationship("Machine", back_populates="files_updated")
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="file", cascade="all, delete-orphan", order_by="Chunk.chunk_index"
    )

    # Indexes
    __table_args__ = (
        Index("idx_files_path", "path"),
        Index("idx_files_deleted", "deleted_at"),
    )


class Chunk(Base):
    """Represents a chunk associated with a file."""

    __tablename__ = "chunks"

    file_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Relationships
    file: Mapped[FileMetadata] = relationship("FileMetadata", back_populates="chunks")
