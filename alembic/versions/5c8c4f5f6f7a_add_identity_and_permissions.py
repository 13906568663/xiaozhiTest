"""add identity and permissions

Revision ID: 5c8c4f5f6f7a
Revises: bfc358b0322e
Create Date: 2026-03-21 11:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5c8c4f5f6f7a"
down_revision: Union[str, Sequence[str], None] = "bfc358b0322e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "permission",
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_permission_action"), "permission", ["action"], unique=False)
    op.create_index(op.f("ix_permission_code"), "permission", ["code"], unique=True)
    op.create_index(op.f("ix_permission_resource"), "permission", ["resource"], unique=False)

    op.create_table(
        "role",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DISABLED", name="rolestatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_role_code"), "role", ["code"], unique=True)

    op.create_table(
        "user_account",
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DISABLED", name="userstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_account_username"), "user_account", ["username"], unique=True)

    op.create_table(
        "role_permission_binding",
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_binding"),
    )
    op.create_index(
        op.f("ix_role_permission_binding_permission_id"),
        "role_permission_binding",
        ["permission_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_role_permission_binding_role_id"),
        "role_permission_binding",
        ["role_id"],
        unique=False,
    )

    op.create_table(
        "user_role_binding",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role_binding"),
    )
    op.create_index(op.f("ix_user_role_binding_role_id"), "user_role_binding", ["role_id"], unique=False)
    op.create_index(op.f("ix_user_role_binding_user_id"), "user_role_binding", ["user_id"], unique=False)

    op.create_table(
        "user_permission_grant",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.Column(
            "effect",
            sa.Enum("ALLOW", "DENY", name="permissioneffect", native_enum=False),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "permission_id", name="uq_user_permission_grant"),
    )
    op.create_index(
        op.f("ix_user_permission_grant_permission_id"),
        "user_permission_grant",
        ["permission_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_permission_grant_user_id"),
        "user_permission_grant",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_permission_grant_user_id"), table_name="user_permission_grant")
    op.drop_index(op.f("ix_user_permission_grant_permission_id"), table_name="user_permission_grant")
    op.drop_table("user_permission_grant")

    op.drop_index(op.f("ix_user_role_binding_user_id"), table_name="user_role_binding")
    op.drop_index(op.f("ix_user_role_binding_role_id"), table_name="user_role_binding")
    op.drop_table("user_role_binding")

    op.drop_index(op.f("ix_role_permission_binding_role_id"), table_name="role_permission_binding")
    op.drop_index(op.f("ix_role_permission_binding_permission_id"), table_name="role_permission_binding")
    op.drop_table("role_permission_binding")

    op.drop_index(op.f("ix_user_account_username"), table_name="user_account")
    op.drop_table("user_account")

    op.drop_index(op.f("ix_role_code"), table_name="role")
    op.drop_table("role")

    op.drop_index(op.f("ix_permission_resource"), table_name="permission")
    op.drop_index(op.f("ix_permission_code"), table_name="permission")
    op.drop_index(op.f("ix_permission_action"), table_name="permission")
    op.drop_table("permission")
