from .commands.players import players
from .commands.host import host
from .commands.match import match
from .commands.error import error_handler
from .commands.owner import owner
from .commands.economy import economy
from .commands.help import help_command
from .commands.tournament import tournament
from .commands.squad import squad


def load(bot):
    players(bot)
    host(bot)
    match(bot)
    owner(bot)
    economy(bot)
    tournament(bot)
    squad(bot)
    help_command(bot)
    error_handler(bot)
