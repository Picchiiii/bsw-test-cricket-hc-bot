import logging
import tomllib
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    prefix: str


def _load() -> Config:
    with open("config.toml", "rb") as f:
        raw = tomllib.load(f)

    return Config(prefix=raw.get("prefix", "$"))


config = _load()   # ✅ global instance
