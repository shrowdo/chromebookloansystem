"""Add ChromebookHistory table

Revision ID: 6291f2315cf8
Revises: 76b74ca2d183
Create Date: 2023-09-22 18:41:56.529660

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6291f2315cf8'
down_revision = '76b74ca2d183'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('chromebook_history', schema=None) as batch_op:
        batch_op.drop_constraint('chromebook_history_chromebook_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(None, 'chromebook', ['chromebook_id'], ['id'], ondelete='CASCADE')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('chromebook_history', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('chromebook_history_chromebook_id_fkey', 'chromebook', ['chromebook_id'], ['id'])

    # ### end Alembic commands ###
