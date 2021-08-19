import os

from dotenv import load_dotenv

load_dotenv()

PREFIX = os.environ["BOT_PREFIX"]
GM_ROLE_ID = int(os.environ["GM_ROLE_ID"])
