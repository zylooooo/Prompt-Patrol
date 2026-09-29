import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text, Uuid, and_, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
    # Display label only, chosen by the person after first sign-in.
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[UserRoleEnum] = mapped_column(Enum(UserRoleEnum, native_enum=False), nullable=False)
    status: Mapped[UserStatusEnum] = mapped_column(
        Enum(UserStatusEnum, native_enum=False),
        nullable=False,
        default=UserStatusEnum.active,
        server_default=UserStatusEnum.active.value,
    )
    # Who sent the invite. Populated once and never changed. Supervision relationship tracking in supervision
    provisioned_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Stamped once by the first successful sign-in and never changed. Null means
    # the invite is still pending. Reset to null when a deleted email is
    # re-provisioned.
    first_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Instructors currently supervising this user: active `supervisions` links
    supervisors: Mapped[list["User"]] = relationship(
        "User",
        secondary=lambda: Supervision.__table__,
        primaryjoin=lambda: and_(User.id == Supervision.ta_id, Supervision.ended_at.is_(None)),
        secondaryjoin=lambda: and_(User.id == Supervision.instructor_id, User.status == UserStatusEnum.active),
        viewonly=True,
        lazy="selectin",
        join_depth=1,
    )

    @property
    def supervisor_ids(self) -> list[uuid.UUID]:
        return [instructor.id for instructor in self.supervisors]

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


class UserRoleEvent(Base):
    """Append-only record of every role reassignment. Sole purpose is for auditing trial. Never updated or deleted."""

    __tablename__ = "user_role_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    from_role: Mapped[UserRoleEnum] = mapped_column(Enum(UserRoleEnum, native_enum=False), nullable=False)
    to_role: Mapped[UserRoleEnum] = mapped_column(Enum(UserRoleEnum, native_enum=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Supervision(Base):
    """
    Table to represent the supervision relationship between teaching assistants and instructors.

    Replaces `users.provisioned_by` as the supervision edge, so a TA can have
    any number of supervisors. Ended, never deleted: the table is its own
    history, the same per-domain approach as the event tables above. At most
    one active link per pair.
    """

    __tablename__ = "supervisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ta_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    instructor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Null only on rows backfilled from provisioned_by by migration 0013.
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index(
            "uq_supervisions_active_pair",
            "ta_id",
            "instructor_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )
