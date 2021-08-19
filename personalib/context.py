from typing import Optional

from discord.ext import commands


class Context(commands.Context):
    @property
    def prefix(self) -> str:
        return self._prefix  # type: ignore

    @prefix.setter
    def prefix(self, value: Optional[str]) -> None:
        # because custom get_prefix can leave spaces
        self._prefix = None if value is None else value.rstrip()
