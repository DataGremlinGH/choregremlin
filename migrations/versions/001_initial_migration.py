from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'chore',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('description', sa.String),
        sa.Column('amount', sa.Float),
        sa.Column('currency', sa.String),
        sa.Column('date', sa.DateTime)
    )
    op.execute("PRAGMA journal_mode=WAL;")

def downgrade():
    op.drop_table('chore')
