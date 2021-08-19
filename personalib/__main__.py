import os

from .bot import PersonaLib

if __name__ == "__main__":
    bot = PersonaLib()

    bot.run(os.environ["BOT_TOKEN"])
