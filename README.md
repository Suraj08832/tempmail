# Telegram Bot with Message Monitoring

A Telegram bot that monitors edited messages in groups and provides temporary email functionality.

## Features

- Monitors edited messages in groups
- Sends notifications for edited messages
- Auto-deletes notifications after 1 minute
- Temporary email generation with refresh button
- Email statistics tracking

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your environment variables:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token from BotFather

## Running Locally

```bash
python bot.py
```

## Deploying on Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Set the following:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
4. Add your `TELEGRAM_BOT_TOKEN` as an environment variable
5. Deploy!

## Commands

- `/start` - Start the bot
- `/help` - Show help message
- `/newmail` - Generate new temporary email
- `/current` - Show current email
- `/delete` - Delete current email
- `/stats` - Show email statistics
- `/forward` - Set email forwarding
- `/extend` - Extend email lifetime
- `/privacy` - Get privacy tips

## Group Features

- Tracks edited messages
- Sends notifications for edited messages
- Auto-deletes notifications after 1 minute

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 