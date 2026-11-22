"""Rehearsal-week lending orders and their persistent score holds.

An order picks one catalog batch (a business case) and an inclusive score-number
range, then holds one copy of every registered score in that range.  The
decision rules live in :mod:`src.services.lending_rules`; this module adds the
transactional storage, row locking and idempotency around them.

Concurrency rules
-----------------
* Each matched inventory row is taken with a conditional ``UPDATE`` that
  re-checks availability in the same statement, so two overlapping orders can
  never oversell a score.  The predicates use the unique ``(case_id, number)``
  key, taking record locks only, so disjoint ranges never block each other.
* All takes run in one savepoint: if any score is short the savepoint rolls
  back, the order records nothing, and the whole order is marked shortage.
* A caller-supplied request key makes retries idempotent: the existing order is
  returned untouched instead of holding a second time.
* Cancelling releases exactly the copies this order held.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError

from src.config.settings import engine
from src.models.tables import audit, cases, inventory_scores, lending_order_items, lending_orders
from src.services import lending_rules as rules
from src.utils.time import utc_time

PENDING = 'pending'
ORDER_VIEW_KEYS = ('id', 'case_id', 'start_number', 'end_number', 'request_key', 'status',
                   'author', 'created_at', 'decided_at', 'note')


def _inventory_insert(conn, rows):
    """Insert inventory rows without touching batches that already have them."""
    if not rows:
        return
    dialect = conn.dialect.name
    if dialect == 'mysql':
        statement = mysql_insert(inventory_scores).values(rows).prefix_with('IGNORE')
    elif dialect == 'postgresql':
        statement = postgres_insert(inventory_scores).values(rows).on_conflict_do_nothing(
            index_elements=['case_id', 'number'])
    else:
        statement = insert(inventory_scores).values(rows)
    conn.execute(statement)


def ensure_inventory(conn, case_id, scores):
    """Create inventory rows for a catalog batch, preserving earlier holds."""
    known = {row for row in conn.execute(
        select(inventory_scores.c.number).where(inventory_scores.c.case_id == case_id)).scalars()}
    rows = [{'case_id': case_id, 'number': score['number'], 'title': score['title'],
             'total_copies': score['available_copies'], 'held_copies': 0}
            for score in scores if score['number'] not in known]
    _inventory_insert(conn, rows)


def _case_title(conn, case_id):
    title = conn.execute(select(cases.c.title).where(cases.c.id == case_id)).scalar_one_or_none()
    if title is None:
        raise HTTPException(404, '找不到对应的曲目索引批')
    return title


def _items(conn, order_ids):
    grouped = {order_id: [] for order_id in order_ids}
    if not order_ids:
        return grouped
    rows = conn.execute(
        select(lending_order_items)
        .where(lending_order_items.c.order_id.in_(order_ids))
        .order_by(lending_order_items.c.order_id, lending_order_items.c.number)
    ).mappings()
    for row in rows:
        grouped[row['order_id']].append({
            'number': row['number'], 'title': row['title'],
            'state': row['state'], 'copies': row['copies'],
        })
    return grouped


def _serialize(order, title, items):
    data = {key: order[key] for key in ORDER_VIEW_KEYS}
    data['case_title'] = title
    data['items'] = items
    data['held_numbers'] = [item['number'] for item in items if item['state'] == rules.HELD]
    data['shortage_numbers'] = [item['number'] for item in items if item['state'] == rules.SHORTAGE]
    data['held_total'] = sum(item['copies'] for item in items if item['state'] == rules.HELD)
    return data


def _view(conn, order):
    items = _items(conn, [order['id']])[order['id']]
    return _serialize(order, _case_title(conn, order['case_id']), items)


def _by_request_key(request_key):
    with engine.connect() as conn:
        row = conn.execute(select(lending_orders)
                           .where(lending_orders.c.request_key == request_key)).mappings().first()
        return _view(conn, row) if row else None


def _same_request(existing, case_id, first, last):
    return (existing['case_id'], existing['start_number'], existing['end_number']) == (case_id, first, last)


class _TakeFailed(Exception):
    """Raised inside the attempt transaction so every partial take rolls back."""


def _range_rows(conn, case_id, first, last):
    return conn.execute(
        select(inventory_scores.c.number, inventory_scores.c.title,
               inventory_scores.c.total_copies, inventory_scores.c.held_copies)
        .where(inventory_scores.c.case_id == case_id,
               inventory_scores.c.number.between(first, last))
        .order_by(inventory_scores.c.number)
    ).mappings().all()


def _try_hold(conn, case_id, rows):
    """Take one copy of every matched score or abort the whole attempt.

    Each conditional UPDATE re-checks availability in the same statement, so a
    concurrent order can never oversell.  Equality predicates on the unique
    ``(case_id, number)`` index take record locks only, letting disjoint ranges
    proceed independently instead of waiting on each other's gaps.
    """
    items = []
    for row in rows:
        taken = conn.execute(
            update(inventory_scores)
            .where(inventory_scores.c.case_id == case_id,
                   inventory_scores.c.number == row['number'],
                   inventory_scores.c.total_copies - inventory_scores.c.held_copies >= rules.COPIES_PER_SCORE)
            .values(held_copies=inventory_scores.c.held_copies + rules.COPIES_PER_SCORE)
            .execution_options(synchronize_session=False)
        ).rowcount
        if taken != 1:
            raise _TakeFailed
        items.append({'number': row['number'], 'title': row['title'],
                      'state': rules.HELD, 'copies': rules.COPIES_PER_SCORE})
    return items


def _insert_items(conn, order_id, items):
    if items:
        conn.execute(lending_order_items.insert(), [
            {'order_id': order_id, 'number': item['number'], 'title': item['title'],
             'state': item['state'], 'copies': item['copies']}
            for item in items
        ])


def _insert_order(conn, case_id, first, last, key, actor, status, note):
    order_id = conn.execute(lending_orders.insert().values(
        case_id=case_id, start_number=first, end_number=last,
        request_key=key or f'anon-{uuid.uuid4().hex}',
        status=status, author=actor, created_at=utc_time(), decided_at=utc_time(), note=note,
    )).inserted_primary_key[0]
    log_order(conn, actor, 'create_order', order_id)
    return order_id


def create_order(case_id, start_number, end_number, request_key=None, actor='operator'):
    """Place one all-or-nothing hold order and return its stored result."""
    try:
        first, last = rules.normalize_range(start_number, end_number)
        key = rules.normalize_request_key(request_key)
    except rules.RuleError as exc:
        raise HTTPException(422, str(exc)) from None
    if not isinstance(case_id, int) or case_id <= 0:
        raise HTTPException(422, '曲目索引批编号无效')

    try:
        with engine.begin() as conn:
            payload = conn.execute(select(cases.c.payload).where(cases.c.id == case_id)).scalar_one_or_none()
            if payload is None:
                raise HTTPException(404, '找不到对应的曲目索引批')
            ensure_inventory(conn, case_id, payload.get('scores') or [])
            rows = _range_rows(conn, case_id, first, last)

            if not rows:
                note = rules.summary(rules.EMPTY, [], first, last)
                order_id = _insert_order(conn, case_id, first, last, key, actor, rules.EMPTY, note)
                order = conn.execute(select(lending_orders)
                                     .where(lending_orders.c.id == order_id)).mappings().one()
                return _serialize(order, _case_title(conn, case_id), [])

            order_id = _insert_order(conn, case_id, first, last, key, actor, PENDING, '')
            items = None
            # A short take rolls back all its conditional updates; a fresh read
            # then tells us whether the range is genuinely short or stock was
            # released mid-flight (in which case one bounded retry is enough).
            for _ in range(3):
                try:
                    with conn.begin_nested():
                        items = _try_hold(conn, case_id, rows)
                except _TakeFailed:
                    rows = _range_rows(conn, case_id, first, last)
                    status, items = rules.plan(rows)
                    if status == rules.FULFILLED:
                        continue
                    break
                status = rules.FULFILLED
                break
            if items is None:  # pragma: no cover - guarded by the retry bound above
                status, items = rules.SHORTAGE, [
                    {'number': row['number'], 'title': row['title'],
                     'state': rules.SKIPPED, 'copies': 0} for row in rows]
            note = rules.summary(status, items, first, last)
            _insert_items(conn, order_id, items)
            conn.execute(lending_orders.update().where(lending_orders.c.id == order_id)
                         .values(status=status, note=note))
            order = conn.execute(select(lending_orders)
                                 .where(lending_orders.c.id == order_id)).mappings().one()
            return _serialize(order, _case_title(conn, case_id), items)
    except IntegrityError:
        # A concurrent retry with the same request key won the unique insert.
        existing = _by_request_key(key) if key else None
        if existing is None:
            raise HTTPException(409, '借阅单提交冲突，请重试') from None
        if not _same_request(existing, case_id, first, last):
            raise HTTPException(409, '该请求键已被其他编号段的借阅单使用') from None
        return existing


def cancel_order(order_id, actor='operator'):
    """Release the copies held by this order; retries and empty orders are safe."""
    with engine.begin() as conn:
        order = conn.execute(select(lending_orders).where(lending_orders.c.id == order_id)
                             .with_for_update()).mappings().first()
        if order is None:
            raise HTTPException(404, '找不到该借阅单')
        if order['status'] == rules.CANCELLED:
            return _view(conn, order)

        held = conn.execute(
            select(lending_order_items)
            .where(lending_order_items.c.order_id == order_id,
                   lending_order_items.c.state == rules.HELD)
            .order_by(lending_order_items.c.number)
        ).mappings().all()
        if held:
            numbers = [row['number'] for row in held]
            # Equality locks on the unique index: record locks, never gap locks,
            # so releasing one range cannot block a disjoint order.
            for number in numbers:
                conn.execute(select(inventory_scores.c.id)
                             .where(inventory_scores.c.case_id == order['case_id'],
                                    inventory_scores.c.number == number)
                             .with_for_update())
            for row in held:
                conn.execute(update(inventory_scores)
                             .where(inventory_scores.c.case_id == order['case_id'],
                                    inventory_scores.c.number == row['number'])
                             .values(held_copies=inventory_scores.c.held_copies - row['copies']))
                conn.execute(update(lending_order_items)
                             .where(lending_order_items.c.id == row['id'])
                             .values(state=rules.RETURNED, copies=0))
        conn.execute(lending_orders.update().where(lending_orders.c.id == order_id)
                     .values(status=rules.CANCELLED, decided_at=utc_time(),
                             note='借阅单已撤销，本单留谱份数已归还。'))
        log_order(conn, actor, 'cancel_order', order_id)
        order = conn.execute(select(lending_orders)
                             .where(lending_orders.c.id == order_id)).mappings().one()
        return _view(conn, order)


def list_orders():
    with engine.connect() as conn:
        rows = conn.execute(
            select(lending_orders, cases.c.title)
            .join(cases, cases.c.id == lending_orders.c.case_id)
            .order_by(lending_orders.c.id.desc()).limit(100)
        ).mappings().all()
        grouped = _items(conn, [row['id'] for row in rows])
        return [_serialize(row, row['title'], grouped[row['id']]) for row in rows]


def get_order(order_id):
    with engine.connect() as conn:
        row = conn.execute(select(lending_orders, cases.c.title)
                           .join(cases, cases.c.id == lending_orders.c.case_id)
                           .where(lending_orders.c.id == order_id)).mappings().first()
        if row is None:
            raise HTTPException(404, '找不到该借阅单')
        return _serialize(row, row['title'], _items(conn, [order_id])[order_id])


def held_by_case(case_id):
    """Map score number to copies currently held for one catalog batch."""
    with engine.connect() as conn:
        rows = conn.execute(select(inventory_scores.c.number, inventory_scores.c.held_copies)
                            .where(inventory_scores.c.case_id == case_id,
                                   inventory_scores.c.held_copies > 0)).all()
    return {row.number: row.held_copies for row in rows}


def inventory(case_id):
    """Current availability for a batch: total minus copies already held."""
    with engine.connect() as conn:
        _case_title(conn, case_id)
        rows = conn.execute(
            select(inventory_scores)
            .where(inventory_scores.c.case_id == case_id)
            .order_by(inventory_scores.c.number)
        ).mappings().all()
    return [{
        'number': row['number'], 'title': row['title'], 'total_copies': row['total_copies'],
        'held_copies': row['held_copies'], 'available_copies': row['total_copies'] - row['held_copies'],
    } for row in rows]


def log_order(conn, actor, action, order_id):
    conn.execute(audit.insert().values(actor=actor, action=action, reference=str(order_id),
                                       created_at=utc_time()))
