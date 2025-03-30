import os
from telegram import Bot
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def clear_webhook():
    """Clear any existing webhooks."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("No token found! Please set TELEGRAM_BOT_TOKEN environment variable.")
        return

    try:
        bot = Bot(token)
        bot.delete_webhook()
        print("Successfully cleared webhook!")
    except Exception as e:
        print(f"Error clearing webhook: {str(e)}")

if __name__ == '__main__':
    clear_webhook() 