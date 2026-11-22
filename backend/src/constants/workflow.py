from enum import StrEnum


class Role(StrEnum):
    OPERATOR = 'operator'
    REVIEWER = 'reviewer'
    VIEWER = 'viewer'


class Status(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETE = 'complete'
    FAILED = 'failed'


class OrderStatus(StrEnum):
    FULFILLED = 'fulfilled'
    SHORTAGE = 'shortage'
    EMPTY = 'empty'
    CANCELLED = 'cancelled'


class ItemState(StrEnum):
    HELD = 'held'
    SHORTAGE = 'shortage'
    SKIPPED = 'skipped'
    RETURNED = 'returned'
