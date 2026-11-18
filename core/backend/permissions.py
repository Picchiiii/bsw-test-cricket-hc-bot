"""Small permission helpers shared by commands and views."""


def is_host(mi, user) -> bool:
    return user == mi.host


def is_captain(mi, user) -> bool:
    return user == mi.teamA_captain or user == mi.teamB_captain


def can_control(mi, user) -> bool:
    """Host or either captain (used for resume / next day)."""
    return is_host(mi, user) or is_captain(mi, user)
