def command(*, name=None, description=None):
    def deco(func):
        func.__app_command__ = {"name": name or func.__name__, "description": description}
        return func
    return deco


def allowed_installs(**kwargs):
    def deco(func):
        return func
    return deco


def describe(**kwargs):
    def deco(func):
        return func
    return deco


class CommandTree:
    def __init__(self, client):
        self.client = client
        self.commands = []

    def add_command(self, cmd):
        self.commands.append(cmd)

    async def sync(self):
        return list(self.commands)
