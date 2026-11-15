"""
main.py
-------
Universal entry point for bot-hosting platforms (bot-hosting.net, Pterodactyl, Railway, etc.)
Launches Moonlit Quest Bot v2.
"""
import os
import sys

# Ensure current directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot

if __name__ == "__main__":
    bot._acquire_instance_lock()
    if not bot.BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set in .env! Please set BOT_TOKEN in your environment or .env file.", flush=True)
        sys.exit(1)
    else:
        print(f"Starting {bot.BOT_NAME} on bot-hosting...", flush=True)
        bot.bot.run(bot.BOT_TOKEN)
