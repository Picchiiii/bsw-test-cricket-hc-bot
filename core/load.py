from .commands.players import players
from .commands.host import host
from .commands.match import match

def load(bot):
    players(bot)
    host(bot)
    match(bot)