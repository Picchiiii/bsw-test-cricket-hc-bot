import logging
import tomllib
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    prefix: str


def _load() -> Config:
    with open("config.toml", "rb") as f:
        raw = tomllib.load(f)

    cfg = Config(
        prefix=raw.get("prefix", "$"),)

    return cfg


config: Config = _load()
