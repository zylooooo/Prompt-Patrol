import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class UserRoleEnum(str, enum.Enum):
    root_admin = "root_admin"
    instructor = "instructor"
    teaching_assistant = "teaching_assistant"


class User(Base):
    """
    User data model for user management purposes. The model will keep track of all users and their roles in the system.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    entra_oid: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    role: Mapped[UserRoleEnum] = mapped_column(Enum(UserRoleEnum, native_enum=False), nullable=False)
    provisioned_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
