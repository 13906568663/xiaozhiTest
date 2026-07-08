"""add_menu_item_table

Revision ID: db33d08376b5
Revises: 2b3c4d5e6f7a
Create Date: 2026-04-07 13:48:29.932030

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db33d08376b5'
down_revision: Union[str, Sequence[str], None] = '2b3c4d5e6f7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'menu_item',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('parent_id', sa.String(length=36), nullable=True),
        sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('label', sa.String(length=128), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('href', sa.String(length=255), nullable=True),
        sa.Column('permission', sa.String(length=128), nullable=True),
        sa.Column('menu_type', sa.Enum('GROUP', 'ITEM', name='menuitemtype', native_enum=False, create_constraint=True), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_visible', sa.Boolean(), nullable=False),
        sa.Column('default_expanded', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['menu_item.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_menu_item_code'), 'menu_item', ['code'], unique=True)
    op.create_index(op.f('ix_menu_item_parent_id'), 'menu_item', ['parent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_menu_item_parent_id'), table_name='menu_item')
    op.drop_index(op.f('ix_menu_item_code'), table_name='menu_item')
    op.drop_table('menu_item')
