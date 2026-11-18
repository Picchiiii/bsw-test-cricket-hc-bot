import datetime
import re


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def escape_markdown(text, **kwargs):
    return re.sub(r"([*_`~|>])", r"\\\1", text)


def escape_mentions(text):
    return re.sub(r"@(everyone|here|[!&]?[0-9]{17,20})", "@​\\1", text)


def format_dt(dt, style=None):
    return f"<t:{int(dt.timestamp())}:{style or 'f'}>"
