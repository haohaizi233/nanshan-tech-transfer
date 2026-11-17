import pytest

from modules.achievement.service import _parse_cooperation_capacity as achievement_parse
from modules.demand.service import _parse_cooperation_capacity as demand_parse


@pytest.mark.parametrize("parse", [demand_parse, achievement_parse])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize(
    "value", [10000, 2147483648, "9" * 5000, 1e100], ids=["over-limit", "int-overflow", "long-string", "large-float"]
)
def test_oversized_capacity_is_unlimited(parse, partial, value):
    fields = {}
    parse({"cooperationCapacity": value}, fields, partial=partial)
    assert fields["cooperation_capacity"] is None
    assert fields.get("cooperation_remaining") is None


@pytest.mark.parametrize("parse", [demand_parse, achievement_parse])
@pytest.mark.parametrize("value", [1, 9999, "9999", None, ""])
def test_capacity_boundary(parse, value):
    fields = {}
    parse({"cooperationCapacity": value}, fields)
    expected = None if value in (None, "") else int(value)
    assert fields["cooperation_capacity"] == expected
    assert fields["cooperation_remaining"] == expected
