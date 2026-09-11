from core.contact_validation import (
    is_valid_contact_way,
    is_valid_email,
    is_valid_phone,
    validate_contact_way,
    validate_email,
    validate_phone,
)
from core.errors import BizError


def main():
    assert is_valid_phone("13800138000")
    assert is_valid_phone("12345678902")
    assert not is_valid_phone("1380013800")
    assert not is_valid_phone("138001380000")
    assert not is_valid_phone("13800138a00")
    assert validate_phone("", required=False) is None
    try:
        validate_phone("13800", required=True)
        raise AssertionError("expected invalid phone")
    except BizError as exc:
        assert "11位" in exc.message

    assert is_valid_email("user@example.com")
    assert is_valid_email("a.b+c@mail.co")
    assert not is_valid_email("wqe")
    assert not is_valid_email("user@")
    assert not is_valid_email("user@domain")
    assert validate_email("", required=False) is None
    try:
        validate_email("wqe", required=True)
        raise AssertionError("expected invalid email")
    except BizError as exc:
        assert "格式" in exc.message

    assert is_valid_contact_way("13800138000")
    assert is_valid_contact_way("88015909")
    assert is_valid_contact_way("0755-88015909")
    assert not is_valid_contact_way("abc")
    assert validate_contact_way("", required=False) == ""
    try:
        validate_contact_way("nope", required=True)
        raise AssertionError("expected invalid contact way")
    except BizError as exc:
        assert "格式" in exc.message
    print("PASS: contact validation")


if __name__ == "__main__":
    main()
