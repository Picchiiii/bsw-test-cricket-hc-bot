"""CPU (computer) players for friendly matches.

A CPU player stands in for a Discord member everywhere the match engine expects one: it has an `id`,
a `name` and a `mention`, compares equal only to itself, and is never sent DMs. The engine asks
`cpu_pick()` for its numbers and lets it make captain decisions instantly.

CPU ids are small numbers (1-99) that can never be real Discord snowflakes, so they are unique inside a
match and are easy to recognise after a restart (`is_cpu_id`). The same id may be used in two different
matches; CPUs are never "busy elsewhere".
"""
import asyncio
import random

from core.config import config

CPU_MAX_ID = 99
CPU_NAMES = ["Robo", "Chip", "Byte", "Pixel", "Bolt", "Turbo", "Gizmo", "Sparky", "Dynamo", "Cog", "Widget"]


class CpuPlayer:
    is_cpu = True
    bot = False          # not a Discord bot account: lobby rules that refuse bots don't apply
    roles = ()
    display_avatar = None
    avatar = None

    def __init__(self, cpu_id: int, name: str | None = None):
        self.id = int(cpu_id)
        self.name = name or f"CPU {self.id}"
        self.display_name = self.name
        self.global_name = self.name
        self.guild = None

    @property
    def mention(self) -> str:
        return f"🤖 **{self.name}**"

    async def send(self, *args, **kwargs):
        return None

    def __eq__(self, other):
        return isinstance(other, CpuPlayer) and other.id == self.id

    def __hash__(self):
        return hash(("cpu", self.id))

    def __repr__(self):
        return f"<CpuPlayer {self.id} {self.name}>"


def is_cpu(player) -> bool:
    return bool(getattr(player, "is_cpu", False))


def is_cpu_id(player_id) -> bool:
    try:
        return 0 < int(player_id) <= CPU_MAX_ID
    except (TypeError, ValueError):
        return False


def has_cpu(mi) -> bool:
    return any(is_cpu(p) for p in mi.players) or any(is_cpu_id(i) for i in getattr(mi, "cpu_names", {}))


def new_cpu(mi) -> CpuPlayer | None:
    """A CPU with the lowest id not used in this match (None if all 99 are taken)."""
    used = {p.id for p in mi.players}
    used.update(int(i) for i in getattr(mi, "cpu_names", {}))
    for cpu_id in range(1, CPU_MAX_ID + 1):
        if cpu_id not in used:
            base = CPU_NAMES[(cpu_id - 1) % len(CPU_NAMES)]
            name = f"{base} 🤖" if cpu_id <= len(CPU_NAMES) else f"{base} {cpu_id} 🤖"
            cpu = CpuPlayer(cpu_id, name)
            mi.cpu_names[str(cpu_id)] = cpu.name
            return cpu
    return None


async def think():
    delay = float(config.game.get("cpu_delay", 1.0) or 0)
    if delay > 0:
        await asyncio.sleep(random.uniform(delay * 0.5, delay))
    else:
        await asyncio.sleep(0)


def cpu_pick(role: str, mi=None) -> int:
    """A number for one ball. Bowlers never bowl a no-ball (0); batters avoid a 5th dot in an over."""
    if role == "bowler":
        return random.randint(1, 6)
    if mi is not None and getattr(mi, "zeros_by_batsman", 0) >= 4:
        return random.randint(1, 6)
    return random.choice([0, 1, 1, 2, 2, 3, 4, 4, 5, 6, 6])


def choose_from(data: dict, kind: str):
    """Captain decision for a CPU: the batter who has scored least is held back; bowlers rotate."""
    ids = [pid for pid in data if isinstance(pid, int)]
    if not ids:
        return None
    if kind == "bowler":
        # fewest balls bowled first, so the attack rotates
        return min(ids, key=lambda pid: (data[pid].get("balls_given", 0), random.random()))
    return random.choice(ids)
