from sqlalchemy import (JSON, Column, ForeignKey, Integer, MetaData, String,
                        Table, Text, UniqueConstraint)

schema = MetaData()
users = Table('accounts', schema,
    Column('id', Integer, primary_key=True),
    Column('username', String(40), nullable=False, unique=True),
    Column('password_hash', String(200), nullable=False),
    Column('role', String(20), nullable=False))
cases = Table('business_cases', schema,
    Column('id', Integer, primary_key=True),
    Column('slug', String(64), nullable=False, unique=True),
    Column('title', String(120), nullable=False),
    Column('payload', JSON, nullable=False),
    Column('author', String(40), nullable=False),
    Column('created_at', String(32), nullable=False))
runs = Table('business_runs', schema,
    Column('id', Integer, primary_key=True),
    Column('case_id', ForeignKey('business_cases.id'), nullable=False, index=True),
    Column('status', String(20), nullable=False, index=True),
    Column('owner', String(40), nullable=False),
    Column('attempt_token', String(36)),
    Column('started_at', String(32)),
    Column('finished_at', String(32)),
    Column('created_at', String(32), nullable=False),
    Column('error', Text))
evidence = Table('business_evidence', schema,
    Column('id', Integer, primary_key=True),
    Column('run_id', ForeignKey('business_runs.id'), nullable=False, unique=True),
    Column('report', JSON, nullable=False),
    Column('digest', String(64), nullable=False),
    Column('reviewer', String(40)),
    Column('review_note', String(500)),
    Column('reviewed_at', String(32)))
audit = Table('audit_events', schema,
    Column('id', Integer, primary_key=True),
    Column('actor', String(40), nullable=False),
    Column('action', String(32), nullable=False),
    Column('reference', String(50), nullable=False),
    Column('created_at', String(32), nullable=False))
# One row per catalogued score in a batch (a batch is a submitted catalog case).
# total_copies is the shelf count; held_copies counts active rehearsal-week holds.
inventory_scores = Table('inventory_scores', schema,
    Column('id', Integer, primary_key=True),
    Column('case_id', ForeignKey('business_cases.id'), nullable=False, index=True),
    Column('number', Integer, nullable=False),
    Column('title', String(120), nullable=False),
    Column('total_copies', Integer, nullable=False),
    Column('held_copies', Integer, nullable=False, default=0, server_default='0'),
    UniqueConstraint('case_id', 'number', name='uq_inventory_case_number'))
lending_orders = Table('lending_orders', schema,
    Column('id', Integer, primary_key=True),
    Column('case_id', ForeignKey('business_cases.id'), nullable=False, index=True),
    Column('start_number', Integer, nullable=False),
    Column('end_number', Integer, nullable=False),
    Column('request_key', String(64), nullable=False, unique=True),
    Column('status', String(20), nullable=False, index=True),
    Column('author', String(40), nullable=False),
    Column('created_at', String(32), nullable=False),
    Column('decided_at', String(32)),
    Column('note', String(500)))
lending_order_items = Table('lending_order_items', schema,
    Column('id', Integer, primary_key=True),
    Column('order_id', ForeignKey('lending_orders.id'), nullable=False, index=True),
    Column('number', Integer, nullable=False),
    Column('title', String(120), nullable=False),
    Column('state', String(20), nullable=False),
    Column('copies', Integer, nullable=False, default=0, server_default='0'),
    UniqueConstraint('order_id', 'number', name='uq_lending_item_order_number'))
