def plural(num):
    """Return s for plurals."""
    if num > 1 or num < 1:
        return "s"
    else:
        return ""
