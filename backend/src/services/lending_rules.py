"""Pure rules for rehearsal-week score holds.

The operational rules are kept free of database imports so that the
all-or-nothing decision can be exercised without a running database.
"""

MAX_NUMBER = 999_999_999
MAX_REQUEST_KEY = 64

# A lending order holds one copy of every registered score in its number range.
COPIES_PER_SCORE = 1

FULFILLED = 'fulfilled'
SHORTAGE = 'shortage'
EMPTY = 'empty'
CANCELLED = 'cancelled'

HELD = 'held'
SKIPPED = 'skipped'
RETURNED = 'returned'


class RuleError(ValueError):
    """A rejected input, reported to the caller as field-level feedback."""


def _number(value, label):
    if type(value) is not int or not 1 <= value <= MAX_NUMBER:
        raise RuleError(f'{label}必须为 1 至 999,999,999 之间的整数')
    return value


def normalize_range(start, end):
    """Validate and return the inclusive score-number range."""
    first = _number(start, '起始曲谱编号')
    last = _number(end, '结束曲谱编号')
    if first > last:
        raise RuleError('起始曲谱编号须小于或等于结束曲谱编号')
    return first, last


def normalize_request_key(value):
    """A caller-supplied idempotency key; blank means "not idempotent"."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuleError('请求键须为字符串')
    key = value.strip()
    if not key:
        return None
    if len(key) > MAX_REQUEST_KEY:
        raise RuleError(f'请求键最多 {MAX_REQUEST_KEY} 个字符')
    return key


def plan(rows):
    """Decide what one order should hold.

    ``rows`` are mappings with ``number``, ``title``, ``total_copies`` and
    ``held_copies`` for every registered score inside the requested range.

    Returns ``(status, items)``.  Every item carries ``number``, ``title``,
    ``state`` and ``copies``.  If any matched score has no free copy the whole
    order holds nothing (``shortage``); an empty range is returned untouched
    (``empty``).
    """
    ordered = sorted(rows, key=lambda row: row['number'])
    if not ordered:
        return EMPTY, []

    items = []
    shortage = False
    for row in ordered:
        free = int(row['total_copies']) - int(row['held_copies'])
        if free < COPIES_PER_SCORE:
            shortage = True
            items.append({'number': row['number'], 'title': row['title'],
                          'state': SHORTAGE, 'copies': 0})
        else:
            items.append({'number': row['number'], 'title': row['title'],
                          'state': HELD, 'copies': COPIES_PER_SCORE})

    if shortage:
        # All-or-nothing: a single out-of-stock score cancels every hold.
        for item in items:
            if item['state'] == HELD:
                item['state'] = SKIPPED
                item['copies'] = 0
        return SHORTAGE, items
    return FULFILLED, items


def summary(status, items, start, end):
    """Human-readable note stored with the order."""
    if status == EMPTY:
        return f'编号 {start} 至 {end} 内没有已登记曲谱，空单退回。'
    if status == SHORTAGE:
        missing = '、'.join(str(item['number']) for item in items if item['state'] == SHORTAGE)
        return f'编号 {start} 至 {end} 内缺货曲谱 {missing}，整单未留。'
    copies = sum(item['copies'] for item in items)
    return f'编号 {start} 至 {end} 内留 {len(items)} 种共 {copies} 份，各自 1 份。'
