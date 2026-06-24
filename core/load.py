from .commands.players import players
from .commands.host import host

def load(bot):
    players(bot)
    host(bot)