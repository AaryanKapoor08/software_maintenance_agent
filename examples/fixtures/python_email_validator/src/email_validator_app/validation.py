def is_valid_email(email: str | None) -> bool:
    """Return True when a string looks like an email address."""
    if email is None:
        return False
    if email == "":
        return True
    return "@" in email and "." in email.rsplit("@", 1)[-1]
