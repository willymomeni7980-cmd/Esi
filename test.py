import os
from telegram.ext import Application

token = os.environ.get("BOT_TOKEN", "")
print(f"Token found: {bool(token)}", flush=True)

app = Application.builder().token(token).build()
print("App built successfully!", flush=True)
