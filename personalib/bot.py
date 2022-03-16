from __future__ import annotations

import logging
import re
import traceback
from typing import Any, List, Sequence, Union

import discord
from discord.ext import commands

from .constants import PREFIX

log = logging.getLogger(__name__)

initial_extensions = (
    "personalib.cogs.personas",
    "personalib.cogs.meta",
)


def mention_or_prefix_regex(user_id: int, prefixes: Sequence[str]) -> re.Pattern[str]:
    choices = [
        *[re.escape(prefix) for prefix in prefixes],
        rf"<@!?{user_id}>",
    ]

    return re.compile(rf"(?:{'|'.join(choices)})\s*", re.I)


class PersonaLib(commands.Bot):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            command_prefix=PREFIX,
            case_insensitive=True,
            allowed_mentions=discord.AllowedMentions(
                roles=False, everyone=False, users=True
            ),
            intents=discord.Intents(
                guilds=True,
                members=True,
                messages=True,
                reactions=True,
            ),
            **kwargs,
        )

    async def get_prefix(self, message: discord.Message) -> Union[List[str], str]:
        if match := self._prefix_re.match(message.content):
            return match[0]

        if message.guild:
            return []

        # allow empty match in DMs
        return ""

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}!")
        print(f"Prefix: {PREFIX}")

    async def setup_hook(self) -> None:
        self._prefix_re = mention_or_prefix_regex(self.user.id, [PREFIX])

        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
            except Exception as e:
                log.error(f"Error loading {extension}: {type(e).__name__} - {e}")
                traceback.print_exc()
            else:
                print(f"loaded {extension}")

    async def on_command_error(self, ctx, e):
        await super().on_command_error(ctx, e)

        await ctx.reply(f"Error: {e}")
