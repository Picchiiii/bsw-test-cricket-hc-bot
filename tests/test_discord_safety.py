"""Guard against overriding discord.py internals.

discord.py's View/Item classes use private methods such as `_refresh(components)`, `_dispatch_item`,
`_refresh_component`. A subclass that defines a method with one of those names silently replaces
discord.py's and crashes the gateway (this happened with JoinMatchView._refresh). Our UI classes must
therefore never define `_private` methods.
"""
import importlib
import inspect
import os

import discord

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _all_modules():
    for dirpath, _, files in os.walk(os.path.join(ROOT, "core")):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                rel = os.path.relpath(os.path.join(dirpath, f), ROOT)[:-3]
                yield importlib.import_module(rel.replace(os.sep, "."))


def test_ui_classes_do_not_define_private_methods():
    offenders = []
    seen = set()
    for mod in _all_modules():
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls in seen or not cls.__module__.startswith("core"):
                continue
            seen.add(cls)
            if not issubclass(cls, (discord.ui.View, discord.ui.Item)):
                continue
            for attr in vars(cls):
                if attr.startswith("_") and not attr.startswith("__") and callable(vars(cls)[attr]):
                    offenders.append(f"{cls.__module__}.{cls.__name__}.{attr}")
    assert not offenders, f"private methods on discord UI classes (clash risk): {offenders}"
    assert len(seen) > 5
