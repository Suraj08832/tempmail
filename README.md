# Temporary Email Telegram Bot

A Telegram bot that provides temporary email addresses using the DropMail API.

## Features

- Create temporary email addresses
- View current email address
- Delete email sessions
- View email statistics
- Set up email forwarding
- Real-time email notifications
- Auto-restart and monitoring capabilities

## Commands

- `/start` - Start the bot and see welcome message
- `/help` - Show help information
- `/newmail` - Generate a new temporary email address
- `/current` - Show current email address
- `/delete` - Delete current email session
- `/stats` - Show email statistics
- `/forward` - Set up email forwarding

## Deployment on Render.com

1. Fork this repository to your GitHub account

2. Create a new Web Service on Render.com:
   - Connect your GitHub repository
   - Select Python environment
   - Set the following environment variables:
     ```
     TELEGRAM_BOT_TOKEN=your_bot_token_here
     PORT=10000
     ```

3. Configure the service:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn bot:app --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 120`
   - Health Check Path: `/monitor/status`
   - Health Check Timeout: 180 seconds
   - Health Check Interval: 60 seconds

4. Deploy the service

## Local Development

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/tempmail.git
   cd tempmail
   ```

2. Create and activate virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create `.env` file:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```

5. Run the bot:
   ```bash
   python bot.py
   ```

## Monitoring

The bot includes built-in monitoring and auto-restart capabilities:
- Health check endpoint: `/monitor/status`
- Automatic restart on failure
- Email alerts for critical issues
- Performance monitoring

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 