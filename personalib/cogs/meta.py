from discord.ext import commands


class Meta(commands.Cog):
    """Bot related utility commands"""

    def __init__(self, bot):
        super().__init__()

        self.old_help_command = bot.help_command

        bot.help_command = commands.DefaultHelpCommand()
        bot.help_command.cog = self

    def cog_unload(self) -> None:
        self.bot.help_command = self.old_help_command

    @commands.command()
    async def ping(self, ctx) -> None:
        """Check if bot is online"""

        await ctx.send("Pong")


def setup(bot):
    bot.add_cog(Meta(bot))
