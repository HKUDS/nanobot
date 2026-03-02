import asyncio
from nanobot.config import load_config
from nanobot.channels.telegram import TelegramChannel

async def send_test():
    cfg = load_config()
    print("Loaded config")
    tg_cfg = cfg.channels.telegram
    print(f"Telegram enabled: {tg_cfg.enabled}")
    
    channel = TelegramChannel(tg_cfg, None) # None for agent, we just want to send
    
    # We must instantiate the telegram app first to connect
    # To avoid the full polling loops, we can also manually initialize the bot API token to just send
    from telegram import Bot
    bot_token = tg_cfg.token
    bot = Bot(token=bot_token)
    
    await bot.send_message(chat_id="8008838739", text="Hello! This is an autonomous test message from nanobot!")
    print("Message sent.")

if __name__ == "__main__":
    asyncio.run(send_test())
