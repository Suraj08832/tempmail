# DropMail Telegram Bot

A Telegram bot that provides temporary email addresses using the DropMail API. This bot allows users to create disposable email addresses, receive emails, and manage their email sessions directly through Telegram.

## Features

- Create temporary email addresses
- View current email address
- Delete email sessions
- View email statistics
- Set up email forwarding
- Real-time email notifications
- Refresh button to check for new emails

## Commands

- `/start` - Start the bot and see welcome message
- `/help` - Show help information
- `/newmail` - Generate a new temporary email address
- `/current` - Show current email address
- `/delete` - Delete current email session
- `/stats` - Show email statistics
- `/forward` - Set up email forwarding

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/dropmail-bot.git
cd dropmail-bot
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file with your Telegram bot token:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

5. Run the bot:
```bash
python bot.py
```

## Deployment

This bot is designed to be deployed on Render.com. To deploy:

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Set the following environment variables:
   - `TELEGRAM_BOT_TOKEN`
4. Set the start command to: `python bot.py`
5. Set the health check path to: `/health`

## Requirements

- Python 3.11+
- python-telegram-bot==13.7
- flask==2.0.1
- requests==2.26.0
- python-dotenv==0.19.0

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 