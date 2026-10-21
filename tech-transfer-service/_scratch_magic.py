"""Scratch check: how MagicMock behaves as a context manager."""
from unittest.mock import MagicMock

cur = MagicMock()
cur.__enter__ = MagicMock(return_value=cur)
with cur as c:
    print("instance __enter__ works:", c is cur)

cur2 = MagicMock()
cur2.__enter__.return_value = cur2
with cur2 as c2:
    print("child return_value works:", c2 is cur2)

cur3 = MagicMock()
with cur3 as c3:
    print("default behavior, inner is outer:", c3 is cur3)
