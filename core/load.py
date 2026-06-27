from .commands.players import players
from .commands.host import host
from .commands.match import match
from .commands.error import error_handler

def load(bot):
    players(bot)
    host(bot)
    match(bot)
    # error_handler(bot)