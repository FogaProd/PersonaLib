import asyncio
import contextlib
import os

from .bot import PersonaLib

if __name__ == "__main__":
    bot = PersonaLib()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(bot.start(os.environ["BOT_TOKEN"]))

        input("press ENTER to exit")
