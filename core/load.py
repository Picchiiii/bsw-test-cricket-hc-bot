from .commands.players import players
from .commands.host import host
from .commands.match import match
from .commands.error import error_handler
from .commands.owner import owner

def load(bot):
    players(bot)
    host(bot)
    match(bot)
    owner(bot)
    # error_handler(bot)