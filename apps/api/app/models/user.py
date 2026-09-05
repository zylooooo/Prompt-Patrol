import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class UserRoleEnum(str, enum.Enum):
    root_admin = "root_admin"
    instructor = "instructor"
    teaching_assistant = "teaching_assistant"


class UserStatusEnum(str, enum.Enum):
    """The single authoritative lifecycle state. Never derive it from a timestamp."""

    active = "active"
    deactivated = "deactivated"
    deleted = "deleted"


class User(Base):
    """
    User data model for user management purposes. The model will keep track of all users and their roles in the system.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Unique among non-deleted users only, via the partial indexes below. A
    # deleted row keeps its real address so attribution stays readable, but stops
    # reserving it - otherwise deleting someone makes them unprovisionable for
    # ever, and a misclick needs manual SQL to undo.
    email: Mapped[str] = mapped_column(String, nullable=False)
    auth0_sub: Mapped[str | None] = mapped_column(String, nullable=True)
    # Display label only, never an identifier: an admin placeholder until first
    # login, then whatever Auth0's `name` claim says. Nothing may look a user up
    # by it, and it carries no uniqueness.
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[UserRoleEnum] = mapped_column(Enum(UserRoleEnum, native_enum=False), nullable=False)
    status: Mapped[UserStatusEnum] = mapped_column(
        Enum(UserStatusEnum, native_enum=False),
        nullable=False,
        default=UserStatusEnum.active,
        server_default=UserStatusEnum.active.value,
    )
    provisioned_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Partial uniqueness, not plain UNIQUE: identifiers are reserved only while a
    # user is still part of the system. Declared on the model so the SQLite test
    # schema matches the Postgres one - both support partial indexes.
    __table_args__ = (
        Index(
            "uq_users_email_live",
            "email",
            unique=True,
            postgresql_where=text("status <> 'deleted'"),
            sqlite_where=text("status <> 'deleted'"),
        ),
        Index(
            "uq_users_auth0_sub_live",
            "auth0_sub",
            unique=True,
            postgresql_where=text("status <> 'deleted'"),
            sqlite_where=text("status <> 'deleted'"),
        ),
    )


class UserStatusEvent(Base):
    """Append-only record of every lifecycle transition. Never updated or deleted."""

    __tablename__ = "user_status_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    from_status: Mapped[UserStatusEnum] = mapped_column(Enum(UserStatusEnum, native_enum=False), nullable=False)
    to_status: Mapped[UserStatusEnum] = mapped_column(Enum(UserStatusEnum, native_enum=False), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
