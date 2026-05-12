from email_validator_app import is_valid_email


def test_valid_email_is_accepted() -> None:
    assert is_valid_email("reader@example.com") is True


def test_none_is_invalid() -> None:
    assert is_valid_email(None) is False


def test_missing_domain_dot_is_invalid() -> None:
    assert is_valid_email("reader@example") is False


def test_empty_email_is_invalid() -> None:
    assert is_valid_email("") is False


def test_blank_email_is_invalid() -> None:
    assert is_valid_email("   ") is False
