# DropMail Telegram Bot

A Telegram bot that provides temporary email addresses using the DropMail API. This bot allows users to generate temporary email addresses and receive emails through them directly in Telegram.

## Features

- Generate temporary email addresses
- Receive emails directly in Telegram
- Refresh button to check for new emails
- Show current email address
- Delete email session
- View email statistics
- Set up email forwarding
- Simple and user-friendly interface

## Local Setup

1. Clone this repository
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root and add your Telegram Bot Token:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```
   To get a bot token, talk to [@BotFather](https://t.me/botfather) on Telegram.

4. Run the bot:
   ```bash
   python bot.py
   ```

## Deployment on Render

1. Fork this repository to your GitHub account
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click "New +" and select "Web Service"
4. Connect your GitHub repository
5. Configure the service:
   - Name: tempmail-bot
   - Environment: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
6. Add your environment variable:
   - Key: `TELEGRAM_BOT_TOKEN`
   - Value: Your Telegram bot token
7. Click "Create Web Service"

## Commands

- `/start` - Start the bot and see welcome message
- `/help` - Show help message with all commands
- `/newmail` - Generate a new temporary email address
- `/current` - Show current email address
- `/delete` - Delete current email session
- `/stats` - Show email statistics
- `/forward` - Set up email forwarding

## Note

- Temporary email addresses expire after some time
- Each user gets their own unique email address
- Emails are displayed directly in the Telegram chat 