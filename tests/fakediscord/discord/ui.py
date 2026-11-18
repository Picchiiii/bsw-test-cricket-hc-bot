import asyncio


class Item:
    def __init__(self, row=None):
        self.view = None
        self.row = row
        self.disabled = False

    async def callback(self, interaction):
        pass


class Button(Item):
    def __init__(self, *, label=None, style=2, emoji=None, url=None, custom_id=None, disabled=False, row=None):
        super().__init__(row)
        if label is not None and len(str(label)) > 80:
            raise ValueError("button label > 80")
        self.label = label
        self.style = style
        self.emoji = emoji
        self.url = url
        self.custom_id = custom_id
        self.disabled = disabled


class Select(Item):
    def __init__(self, *, placeholder=None, min_values=1, max_values=1, options=None, row=None, disabled=False):
        super().__init__(row)
        options = list(options or [])
        if not 1 <= len(options) <= 25:
            raise ValueError(f"Select must have 1-25 options, got {len(options)}")
        if placeholder and len(placeholder) > 150:
            raise ValueError("placeholder > 150")
        self.placeholder = placeholder
        self.min_values = min_values
        self.max_values = max_values
        self.options = options
        self.values = []
        self.disabled = disabled


def button(*, label=None, style=2, emoji=None, row=None, disabled=False, custom_id=None):
    def deco(func):
        func.__discord_ui_button__ = dict(label=label, style=style, emoji=emoji, row=row, disabled=disabled)
        return func
    return deco


class View:
    def __init__(self, *, timeout=180):
        self.timeout = timeout
        self.children = []
        self._stopped = asyncio.get_event_loop().create_future()
        self._timer = None
        self._timed_out = False
        self.messages = []
        for name in dir(type(self)):
            func = getattr(type(self), name, None)
            spec = getattr(func, "__discord_ui_button__", None)
            if spec is None:
                continue
            btn = Button(**spec)

            def make_cb(f, b):
                async def cb(interaction):
                    return await f(self, interaction, b)
                return cb
            btn.callback = make_cb(func, btn)
            btn.name = name
            setattr(self, name, btn)
            self.add_item(btn)

    def add_item(self, item):
        if len(self.children) >= 25:
            raise ValueError("view has 25 items")
        item.view = self
        self.children.append(item)
        rows = {}
        for c in self.children:
            weight = 5 if isinstance(c, Select) else 1
            r = c.row if c.row is not None else 0
            rows[r] = rows.get(r, 0) + weight
        auto = sum(rows.values())
        if any(c.row is not None for c in self.children):
            if any(v > 5 for v in rows.values()):
                raise ValueError("a view row has more than 5 components")
        elif auto > 25:
            raise ValueError("too many components")
        return self

    def remove_item(self, item):
        self.children.remove(item)
        return self

    def clear_items(self):
        self.children.clear()
        return self

    def _attach(self, message):
        self.messages.append(message)
        if self.timeout is not None and self._timer is None and not self._stopped.done():
            self._timer = asyncio.ensure_future(self._run_timeout())

    async def _run_timeout(self):
        try:
            await asyncio.sleep(self.timeout)
        except asyncio.CancelledError:
            return
        if self._stopped.done():
            return
        self._timed_out = True
        self._stopped.set_result(True)
        asyncio.ensure_future(self.on_timeout())

    def stop(self):
        if not self._stopped.done():
            self._stopped.set_result(False)
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()

    def is_finished(self):
        return self._stopped.done()

    async def wait(self):
        return await asyncio.shield(self._stopped)

    async def on_timeout(self):
        pass

    def find(self, cls=None, label=None):
        for c in self.children:
            if cls is not None and not isinstance(c, cls):
                continue
            if label is not None and (getattr(c, "label", None) or "").split(" ")[0] != label and getattr(c, "label", None) != label:
                continue
            return c
        return None
