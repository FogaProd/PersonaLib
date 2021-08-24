from __future__ import annotations

import json
import pathlib
import asyncio
import logging
import contextlib

from typing import Optional, Any

from collections import OrderedDict

import discord

from fuzzywuzzy import process
from discord.ext import commands

from personalib.constants import GM_ROLE_ID

MIN_NAME_LEN = 2
MAX_NAME_LEN = 32

REQUIRED_PERMS = discord.Permissions(
    send_messages=True, manage_messages=True, manage_webhooks=True
)


log = logging.getLogger(__name__)


class LRU(OrderedDict[Any, Any]):
    # https://docs.python.org/3/library/collections.html#ordereddict-examples-and-recipes

    def __init__(self, maxsize: int = 128, /, *args: Any, **kwds: Any):
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key: Any, value: Any) -> None:
        if key in self:
            self.move_to_end(key)

        super().__setitem__(key, value)

        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]


class Persona:
    @classmethod
    async def convert(cls, ctx, argument: str):
        personas_cog = ctx.bot.get_cog("Personas")

        try:
            id_arg = int(argument)
        except ValueError:
            pass
        else:
            if persona := personas_cog.available_personas.get(id_arg):
                return persona

        persona, confidence, _ = process.extractOne(
            argument, personas_cog.available_personas
        )

        if confidence < 50:
            raise commands.BadArgument(
                f"Too uncertain about result: {confidence / 100}"
            )

        return persona


class Personas(commands.Cog):
    """Commands for managing personas."""

    def __init__(self, bot):
        super().__init__()

        self.bot = bot

        self.setup()

    def setup(self):
        self.accent_wh_name = f"{self.bot.user.name} bot personas webhook"

        # channel_id -> Webhook
        self._webhooks = LRU(50)

        self._personas_file = pathlib.Path("personas.json")

        if not self._personas_file.exists():
            log.warning(f"Creating new {self._personas_file}")

            data = dict(id=0, available_personas={}, personas={})

            with open(self._personas_file, "w") as f:
                f.write(json.dumps(data, indent=2))
        else:
            with open(self._personas_file) as f:
                data = json.loads(f.read())

        # int
        # unique id for personas, never goes back
        self.id = data["id"]

        # id -> persona
        # personas created by game masters
        # json only supports string dict keys, convert back
        self.available_personas = {
            int(k): v for k, v in data["available_personas"].items()
        }

        # user_id -> id
        # personas, applied to users
        # json only supports string dict keys, convert back
        self.personas = {int(k): v for k, v in data["personas"].items()}

        self.dm_mode = False

    def dump_data(self):
        data = dict(
            id=self.id,
            available_personas=self.available_personas,
            personas=self.personas,
        )

        with open(self._personas_file, "w") as f:
            f.write(json.dumps(data, indent=2))

    @commands.command()
    @commands.has_role(GM_ROLE_ID)
    async def dm(self, ctx, mode: str):
        if mode == "0":
            self.dm_mode = False
            await ctx.send("Switched to chat mode")
        elif mode == "1":
            self.dm_mode = True
            await ctx.send("Switched to DM mode")
        else:
            await ctx.reply("Invalid mode. Expected 0 (chat) or 1 (DM)")

    @commands.group(invoke_without_command=True, ignore_extra=False, aliases=["p"])
    @commands.guild_only()
    async def persona(self, ctx) -> None:
        """Persona management"""

        await ctx.send_help(ctx.command)

    @persona.command(aliases=["ls"])
    @commands.guild_only()
    async def list(self, ctx):
        """Get all available personas"""

        paginator = commands.Paginator(prefix="Personas:```")

        for id, p in self.available_personas.items():
            paginator.add_line(f"{id}: {p['name']}")

        for page in paginator.pages:
            await ctx.send(page)

        if (persona_id := self.personas.get(ctx.author.id)) is not None:
            persona = self.available_personas[persona_id]
            await ctx.send(f"Currently applied persona: **{persona['name']}**")

    async def persona_prompt(self, ctx, edit=False):
        timeout = 15

        done = False

        def check(m):
            return m.channel == ctx.channel and m.author == ctx.author

        async def loop_body():
            nonlocal done

            if edit:
                await ctx.send("Correct persona? y/n")
                correct_persona_msg = await self.bot.wait_for(
                    "message", check=check, timeout=timeout
                )
                if correct_persona_msg.content.lower() != "y":
                    done = True

                    return

            await ctx.send("Name:")
            name_msg = await self.bot.wait_for("message", check=check, timeout=timeout)

            name = name_msg.content

            if not (MIN_NAME_LEN <= len(name) <= MAX_NAME_LEN):
                return await name_msg.reply(
                    f"Name len must be between {MIN_NAME_LEN} and {MAX_NAME_LEN} (Discord limitation)"
                )

            await ctx.send("Avatar:")
            avatar_msg = await self.bot.wait_for(
                "message", check=check, timeout=timeout
            )

            if avatar_msg.attachments:
                avatar_url = avatar_msg.attachments[0].url
            else:
                avatar_url = avatar_msg.content

            if not avatar_url.startswith(("http://", "https://")):
                return await avatar_msg.reply("Avatar URL must be a valid URL")

            persona = dict(name=name, avatar_url=avatar_url)

            try:
                await self._send_new_message(ctx, persona, "good? y/n", ctx.message)
            except discord.errors.HTTPException as e:
                return await ctx.reply(f"HTTP error (probably bad avatar URL): {e}")

            done_msg = await self.bot.wait_for("message", check=check, timeout=timeout)

            if done_msg.content.lower() == "y":
                done = True

                return persona

        while not done:
            try:
                created = await loop_body()
            except asyncio.TimeoutError:
                await ctx.reply("Took to long to respond")

        return created

    @persona.command(aliases=["c"])
    @commands.has_role(GM_ROLE_ID)
    @commands.bot_has_permissions(manage_webhooks=True)
    async def create(self, ctx):
        """Create persona"""

        if (created := await self.persona_prompt(ctx)) is None:
            return

        created["id"] = self.id

        self.id += 1
        self.available_personas[created["id"]] = created

        self.dump_data()

        await ctx.send(f"Created persona **{created['name']}**")

    @persona.command()
    @commands.has_role(GM_ROLE_ID)
    async def delete(self, ctx, persona: Persona) -> None:
        """Delete persona"""

        persona_id = persona["id"]

        del self.available_personas[persona_id]

        self.personas = {id: p for id, p in self.personas.items() if p != persona_id}

        self.dump_data()

        await ctx.send(
            f"Deleted persona **{persona['name']}** and removed it from users"
        )

    @persona.command(aliases=["e"])
    @commands.has_role(GM_ROLE_ID)
    async def edit(self, ctx, persona: Persona) -> None:
        """Edit persona"""

        persona_id = persona["id"]

        await ctx.send(
            f"Editing persona **{persona['name']}** `{persona_id} {persona['avatar_url']}`"
        )

        if (created := await self.persona_prompt(ctx, edit=True)) is None:
            return

        created["id"] = persona_id

        self.available_personas[persona_id] = created

        self.dump_data()

        await ctx.send(f"Edited persona **{created['name']}**")

    @persona.command(name="use", aliases=["u"])
    @commands.bot_has_permissions(manage_messages=True, manage_webhooks=True)
    async def add_persona(self, ctx, persona: Persona) -> None:
        """Use persona or switch to another one"""

        self.personas[ctx.author.id] = persona["id"]

        self.dump_data()

        target = ctx.author if self.dm_mode else ctx

        await target.send(f"Applied persona **{persona['name']}**")

    @persona.command(name="disable", aliases=["d", "off"])
    @commands.guild_only()
    async def disable_persona(self, ctx) -> None:
        """Remove personal persona"""

        if ctx.author.id in self.personas:
            del self.personas[ctx.author.id]

            self.dump_data()

        await ctx.send("Removed persona")

    async def _replace_message(self, message) -> None:
        if message.author.bot:
            return

        if message.guild is None:
            return

        if not message.content:
            return

        # there is no easy and reliable way to preserve attachments
        if message.attachments:
            return

        # webhooks do not support references
        if message.reference is not None:
            return

        # TODO: some other way to prevent accent trigger that is not a missing feature?

        if (persona_id := self.personas.get(message.author.id)) is None:
            return

        persona = self.available_personas[persona_id]

        if not message.channel.permissions_for(message.guild.me).is_superset(
            REQUIRED_PERMS
        ):
            # NOTE: the decision has been made for this to fail silently.
            # this adds some overhead, but makes bot setup much simplier.
            #
            # TODO: find the other way to tell this to users so that they don't think
            # bot is broken. maybe help text?
            return

        if (ctx := await self.bot.get_context(message)).valid:
            return

        try:
            await self._send_new_message(ctx, persona, message.content, message)
        except (discord.NotFound, discord.InvalidArgument):
            # InvalidArgument appears in some rare cases when webhooks is deleted or is
            # owned by other bot
            #
            # cached webhook is missing, should invalidate cache
            del self._webhooks[message.channel.id]

            try:
                await self._send_new_message(ctx, persona_id, message.content, message)
            except Exception as e:
                await ctx.reply(
                    f"Persona error: unable to deliver message after invalidating cache: **{e}**.\n"
                    f"Try deleting webhook **{self.accent_wh_name}** manually."
                )

                # NOTE: is it really needed? what else could trigger this?
                # return
                raise

        with contextlib.suppress(discord.NotFound):
            await message.delete()

    async def _get_cached_webhook(
        self,
        channel: discord.TextChannel,
        create: bool = True,
    ) -> Optional[discord.Webhook]:
        if (wh := self._webhooks.get(channel.id)) is None:
            for wh in await channel.webhooks():
                if wh.name == self.accent_wh_name:
                    break
            else:
                if not create:
                    return None

                wh = await channel.create_webhook(name=self.accent_wh_name)

            self._webhooks[channel.id] = wh

        return wh

    def _copy_embed(self, original: discord.Embed) -> discord.Embed:
        e = original.copy()

        # this results in full sized, but still static image
        #
        # if e.thumbnail:
        #     e.set_image(url=e.thumbnail.url)
        #     e.set_thumbnail(url=e.Empty)

        return e

    async def _send_new_message(self, ctx, persona, content, original):
        wh = await self._get_cached_webhook(original.channel)

        await wh.send(
            content,
            allowed_mentions=discord.AllowedMentions(
                everyone=original.author.guild_permissions.mention_everyone,
                users=True,
                roles=True,
            ),
            # webhook data
            username=persona["name"],
            avatar_url=persona["avatar_url"],
            embeds=list(map(self._copy_embed, original.embeds)),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._replace_message(message)

    # needed in case people use command and edit their message
    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message):
        await self._replace_message(new)


def setup(bot) -> None:
    bot.add_cog(Personas(bot))
