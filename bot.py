import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from telegram.error import Conflict, TimedOut, NetworkError
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time
from flask import Flask, jsonify, request
import threading
import sys
import atexit
import tempfile
import re
import signal

# Load environment variables
load_dotenv()

# Configure logging with more detailed format
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# DropMail API endpoint
DROPMAIL_API = "https://dropmail.me/api/graphql/web-test"

# Initialize Flask app
app = Flask(__name__)

# Global variables
bot_instance = None
user_sessions = {}
is_shutting_down = False
last_response_time = datetime.now()
last_health_check = datetime.now()

# Spam keywords (can be expanded)
SPAM_KEYWORDS = [
    'lottery', 'winner', 'inheritance', 'urgent', 'million',
    'bank transfer', 'account suspended', 'verify account'
]

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global is_shutting_down
    logger.info("Received shutdown signal. Cleaning up...")
    is_shutting_down = True
    if bot_instance:
        try:
            bot_instance.stop()
        except Exception as e:
            logger.error(f"Error stopping bot: {str(e)}")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def is_spam(text):
    """Check if text contains spam keywords."""
    text = text.lower()
    return any(keyword in text for keyword in SPAM_KEYWORDS)

def update_last_response():
    """Update the last response time."""
    global last_response_time
    last_response_time = datetime.now()

@app.route('/')
def home():
    return "Temporary Telegram Bot API is running! 🚀"

@app.route('/health')
def health_check():
    """Health check endpoint."""
    global last_response_time, last_health_check
    last_health_check = datetime.now()
    
    # Check if bot has responded in the last 3 minutes
    time_since_last_response = (datetime.now() - last_response_time).total_seconds()
    is_healthy = time_since_last_response < 180  # 3 minutes = 180 seconds
    
    if not is_healthy:
        logger.warning(f"Health check failed: No response for {time_since_last_response} seconds")
    
    return jsonify({
        "status": "healthy" if is_healthy else "unhealthy",
        "last_response": last_response_time.isoformat(),
        "time_since_last_response": time_since_last_response
    })

@app.route('/api/newmail', methods=['POST'])
def api_newmail():
    """API endpoint to generate a new email address."""
    try:
        query = """
        mutation {
            introduceSession {
                id
                expiresAt
                addresses {
                    address
                }
            }
        }
        """
        response = requests.post(DROPMAIL_API, json={"query": query})
        data = response.json()
        
        if "errors" in data:
            return jsonify({"error": "Failed to generate email"}), 500
            
        email_data = data["data"]["introduceSession"]
        return jsonify({
            "email": email_data["addresses"][0]["address"],
            "session_id": email_data["id"],
            "expires_at": email_data["expiresAt"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check_inbox/<session_id>', methods=['GET'])
def api_check_inbox(session_id):
    """API endpoint to check inbox."""
    try:
        query = """
        query ($sessionId: ID!) {
            session(id: $sessionId) {
                mails {
                    rawSize
                    fromAddr
                    toAddr
                    downloadUrl
                    text
                }
            }
        }
        """
        response = requests.post(
            DROPMAIL_API,
            json={
                "query": query,
                "variables": {"sessionId": session_id}
            }
        )
        data = response.json()
        
        if "errors" in data:
            return jsonify({"error": "Failed to fetch emails"}), 500
            
        return jsonify({"emails": data["data"]["session"]["mails"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def start(update: Update, context: CallbackContext):
    """Send a message when the command /start is issued."""
    update_last_response()
    welcome_message = (
        "👋 Welcome to Temporary Telegram Bot!\n\n"
        "This bot helps you create and manage temporary email addresses.\n\n"
        "Commands:\n"
        "/newmail - Generate a new temporary email address\n"
        "/current - Show current email address\n"
        "/delete - Delete current email session\n"
        "/stats - Show email statistics\n"
        "/forward - Set email forwarding\n"
        "/extend - Extend email lifetime\n"
        "/privacy - Get privacy tips\n"
        "/help - Show this help message"
    )
    update.message.reply_text(welcome_message)

def help_command(update: Update, context: CallbackContext):
    """Send a message when the command /help is issued."""
    update_last_response()
    help_message = (
        "📧 Temporary Telegram Bot Help\n\n"
        "Commands:\n"
        "/newmail - Generate a new temporary email address\n"
        "/current - Show current email address\n"
        "/delete - Delete current email session\n"
        "/stats - Show email statistics\n"
        "/forward - Set email forwarding\n"
        "/extend - Extend email lifetime\n"
        "/privacy - Get privacy tips\n"
        "/help - Show this help message\n\n"
        "How to use:\n"
        "1. Use /newmail to get a temporary email address\n"
        "2. Share this email address with anyone\n"
        "3. Emails sent to this address will be shown in the chat\n"
        "4. The email address is temporary and will expire after some time\n"
        "5. Use /current to see your current email address\n"
        "6. Use /delete to remove the current email session\n"
        "7. Use /stats to see email statistics\n"
        "8. Use /forward to set up email forwarding\n"
        "9. Use /extend to extend the email lifetime\n"
        "10. Use /privacy to get privacy tips"
    )
    update.message.reply_text(help_message)

def privacy_tips(update: Update, context: CallbackContext):
    """Send privacy tips to the user."""
    tips = (
        "🔒 Privacy Tips for Using Temporary Emails:\n\n"
        "1. Never use temporary emails for:\n"
        "   • Banking or financial services\n"
        "   • Important account verifications\n"
        "   • Personal or sensitive information\n\n"
        "2. Best practices:\n"
        "   • Use for one-time registrations\n"
        "   • Avoid sharing personal details\n"
        "   • Delete the email after use\n"
        "   • Don't use for long-term services\n\n"
        "3. Security reminders:\n"
        "   • Emails are not encrypted\n"
        "   • Anyone with the address can read emails\n"
        "   • Emails expire after a set time\n"
        "   • Don't use for sensitive communications"
    )
    update.message.reply_text(tips)

def extend_lifetime(update: Update, context: CallbackContext):
    """Extend the lifetime of the temporary email."""
    if "session_id" not in context.user_data:
        update.message.reply_text("❌ No active email session. Use /newmail to generate a new address.")
        return
        
    try:
        # GraphQL mutation to extend session lifetime
        query = """
        mutation ($sessionId: ID!) {
            extendSession(id: $sessionId) {
                id
                expiresAt
            }
        }
        """
        
        response = requests.post(
            DROPMAIL_API,
            json={
                "query": query,
                "variables": {"sessionId": context.user_data["session_id"]}
            }
        )
        data = response.json()
        
        if "errors" in data:
            update.message.reply_text("❌ Error extending session. Please try again later.")
            return
            
        session_data = data["data"]["extendSession"]
        expires_at = datetime.fromisoformat(session_data["expiresAt"].replace("Z", "+00:00"))
        
        update.message.reply_text(
            f"✅ Email lifetime extended!\n"
            f"New expiration: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        
    except Exception as e:
        logger.error(f"Error in extend_lifetime: {str(e)}")
        update.message.reply_text("❌ An error occurred. Please try again later.")

def current(update: Update, context: CallbackContext):
    """Show the current email address."""
    if "session_id" not in context.user_data:
        update.message.reply_text("❌ No active email session. Use /newmail to generate a new address.")
        return
        
    try:
        # GraphQL query to get current session info
        query = """
        query ($sessionId: ID!) {
            session(id: $sessionId) {
                addresses {
                    address
                }
                expiresAt
            }
        }
        """
        
        response = requests.post(
            DROPMAIL_API,
            json={
                "query": query,
                "variables": {"sessionId": context.user_data["session_id"]}
            }
        )
        data = response.json()
        
        if "errors" in data:
            update.message.reply_text("❌ Error fetching current email. Please try again later.")
            return
            
        session_data = data["data"]["session"]
        email_address = session_data["addresses"][0]["address"]
        expires_at = datetime.fromisoformat(session_data["expiresAt"].replace("Z", "+00:00"))
        
        message = (
            f"📧 Current Email Address:\n\n"
            f"`{email_address}`\n\n"
            f"Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        
        update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in current: {str(e)}")
        update.message.reply_text("❌ An error occurred. Please try again later.")

def delete_session(update: Update, context: CallbackContext):
    """Delete the current email session."""
    if "session_id" not in context.user_data:
        update.message.reply_text("❌ No active email session to delete.")
        return
        
    try:
        # GraphQL mutation to delete session
        query = """
        mutation ($sessionId: ID!) {
            deleteSession(id: $sessionId) {
                id
            }
        }
        """
        
        response = requests.post(
            DROPMAIL_API,
            json={
                "query": query,
                "variables": {"sessionId": context.user_data["session_id"]}
            }
        )
        data = response.json()
        
        if "errors" in data:
            update.message.reply_text("❌ Error deleting session. Please try again later.")
            return
            
        # Clear the session ID from user_data
        del context.user_data["session_id"]
        update.message.reply_text("✅ Email session deleted successfully.")
        
    except Exception as e:
        logger.error(f"Error in delete_session: {str(e)}")
        update.message.reply_text("❌ An error occurred. Please try again later.")

def stats(update: Update, context: CallbackContext):
    """Show email statistics."""
    if "session_id" not in context.user_data:
        update.message.reply_text("❌ No active email session. Use /newmail to generate a new address.")
        return
        
    try:
        # GraphQL query to get email statistics
        query = """
        query ($sessionId: ID!) {
            session(id: $sessionId) {
                mails {
                    rawSize
                    fromAddr
                    toAddr
                    downloadUrl
                    text
                }
                expiresAt
            }
        }
        """
        
        response = requests.post(
            DROPMAIL_API,
            json={
                "query": query,
                "variables": {"sessionId": context.user_data["session_id"]}
            }
        )
        data = response.json()
        
        if "errors" in data:
            update.message.reply_text("❌ Error fetching statistics. Please try again later.")
            return
            
        session_data = data["data"]["session"]
        mails = session_data["mails"]
        expires_at = datetime.fromisoformat(session_data["expiresAt"].replace("Z", "+00:00"))
        
        total_emails = len(mails)
        total_size = sum(mail["rawSize"] for mail in mails)
        unique_senders = len(set(mail["fromAddr"] for mail in mails))
        
        message = (
            f"📊 Email Statistics:\n\n"
            f"Total Emails: {total_emails}\n"
            f"Total Size: {total_size / 1024:.2f} KB\n"
            f"Unique Senders: {unique_senders}\n"
            f"Session Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        
        update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Error in stats: {str(e)}")
        update.message.reply_text("❌ An error occurred. Please try again later.")

def forward(update: Update, context: CallbackContext):
    """Set up email forwarding."""
    if "session_id" not in context.user_data:
        update.message.reply_text("❌ No active email session. Use /newmail to generate a new address.")
        return
        
    try:
        # Get the forwarding email from the command arguments
        args = context.args
        if not args:
            update.message.reply_text("❌ Please provide an email address to forward to.\nUsage: /forward your@email.com")
            return
            
        forward_email = args[0]
        
        # GraphQL mutation to set forwarding
        query = """
        mutation ($sessionId: ID!, $forwardTo: String!) {
            setForwarding(sessionId: $sessionId, forwardTo: $forwardTo) {
                id
                forwardTo
            }
        }
        """
        
        response = requests.post(
            DROPMAIL_API,
            json={
                "query": query,
                "variables": {
                    "sessionId": context.user_data["session_id"],
                    "forwardTo": forward_email
                }
            }
        )
        data = response.json()
        
        if "errors" in data:
            update.message.reply_text("❌ Error setting up forwarding. Please try again later.")
            return
            
        update.message.reply_text(f"✅ Emails will now be forwarded to {forward_email}")
        
    except Exception as e:
        logger.error(f"Error in forward: {str(e)}")
        update.message.reply_text("❌ An error occurred. Please try again later.")

def newmail(update: Update, context: CallbackContext):
    """Generate a new temporary email address."""
    try:
        # GraphQL query to get a new email address
        query = """
        mutation {
            introduceSession {
                id
                expiresAt
                addresses {
                    address
                }
            }
        }
        """
        
        response = requests.post(DROPMAIL_API, json={"query": query})
        data = response.json()
        
        if "errors" in data:
            update.message.reply_text("❌ Error generating email address. Please try again later.")
            return
            
        email_data = data["data"]["introduceSession"]
        email_address = email_data["addresses"][0]["address"]
        session_id = email_data["id"]
        expires_at = datetime.fromisoformat(email_data["expiresAt"].replace("Z", "+00:00"))
        
        # Store the session ID in user_data
        context.user_data["session_id"] = session_id
        
        # Create inline keyboard with refresh button
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"📧 Your temporary email address:\n\n"
            f"`{email_address}`\n\n"
            f"Use this address to receive emails.\n"
            f"Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"Click the refresh button to check for new emails."
        )
        
        update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in newmail: {str(e)}")
        update.message.reply_text("❌ An error occurred. Please try again later.")

def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks."""
    callback_query = update.callback_query
    callback_query.answer()
    
    if callback_query.data == "refresh":
        if "session_id" not in context.user_data:
            callback_query.message.reply_text("❌ No active email session. Use /newmail to generate a new address.")
            return
            
        try:
            # GraphQL query to get emails
            graphql_query = """
            query ($sessionId: ID!) {
                session(id: $sessionId) {
                    mails {
                        rawSize
                        fromAddr
                        toAddr
                        downloadUrl
                        text
                    }
                }
            }
            """
            
            response = requests.post(
                DROPMAIL_API,
                json={
                    "query": graphql_query,
                    "variables": {"sessionId": context.user_data["session_id"]}
                }
            )
            data = response.json()
            
            if "errors" in data:
                callback_query.message.reply_text("❌ Error fetching emails. Please try again later.")
                return
                
            mails = data["data"]["session"]["mails"]
            
            if not mails:
                callback_query.message.reply_text("📭 No new emails received yet.")
                return
                
            for mail in mails:
                # Check for spam
                spam_warning = "⚠️ This email might be spam!\n\n" if is_spam(mail['text']) else ""
                
                message = (
                    f"{spam_warning}"
                    f"📨 New Email Received!\n\n"
                    f"From: {mail['fromAddr']}\n"
                    f"To: {mail['toAddr']}\n"
                    f"Size: {mail['rawSize']} bytes\n\n"
                    f"Content:\n{mail['text']}"
                )
                callback_query.message.reply_text(message)
                
        except Exception as e:
            logger.error(f"Error in button_callback: {str(e)}")
            callback_query.message.reply_text("❌ An error occurred while fetching emails.")

def error_handler(update: Update, context: CallbackContext) -> None:
    """Handle errors in the telegram bot."""
    logger.error(f"Update {update} caused error: {context.error}")
    update_last_response()  # Update last response time even on errors
    
    if isinstance(context.error, Conflict):
        logger.warning("Conflict detected - continuing operation...")
        # Don't stop the bot on conflict, just continue
        time.sleep(5)  # Reduced sleep time on conflict
    elif isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Network error occurred - will retry automatically")
        if bot_instance:
            try:
                bot_instance.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        time.sleep(5)  # Reduced sleep time on network errors
    else:
        logger.error(f"Unexpected error: {context.error}")
        logger.exception("Full traceback for unexpected error:")
        if bot_instance:
            try:
                bot_instance.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        time.sleep(5)

def run_bot():
    """Run the Telegram bot."""
    global bot_instance, is_shutting_down
    
    # Get the token from environment variable
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("No token found! Please set TELEGRAM_BOT_TOKEN environment variable.")
        return

    retry_count = 0
    max_retries = 5
    retry_delay = 10

    while not is_shutting_down:
        try:
            logger.info("Creating Updater with token...")
            # Create the Updater and pass it your bot's token
            updater = Updater(token=token, use_context=True)
            bot_instance = updater

            # Get the dispatcher to register handlers
            dispatcher = updater.dispatcher

            # Add command handlers
            logger.info("Registering command handlers...")
            dispatcher.add_handler(CommandHandler("start", start))
            dispatcher.add_handler(CommandHandler("help", help_command))
            dispatcher.add_handler(CommandHandler("newmail", newmail))
            dispatcher.add_handler(CommandHandler("current", current))
            dispatcher.add_handler(CommandHandler("delete", delete_session))
            dispatcher.add_handler(CommandHandler("stats", stats))
            dispatcher.add_handler(CommandHandler("forward", forward))
            dispatcher.add_handler(CommandHandler("extend", extend_lifetime))
            dispatcher.add_handler(CommandHandler("privacy", privacy_tips))
            dispatcher.add_handler(CallbackQueryHandler(button_callback))
            
            # Add error handler
            dispatcher.add_error_handler(error_handler)

            # Start the Bot with proper configuration
            logger.info("Starting polling...")
            # Configure the bot's request timeout
            updater.bot.request.read_timeout = 30
            updater.bot.request.write_timeout = 30
            updater.bot.request.connect_timeout = 30
            updater.bot.request.pool_timeout = 30
            
            # Start polling with proper parameters
            updater.start_polling(drop_pending_updates=True)
            logger.info("Bot started successfully!")
            
            # Reset retry count on successful start
            retry_count = 0
            
            # Keep the bot running
            while not is_shutting_down:
                try:
                    # Test bot connection every 30 seconds
                    bot_info = updater.bot.get_me()
                    logger.info(f"Bot is running: @{bot_info.username}")
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"Error in bot loop: {str(e)}")
                    if not is_shutting_down:
                        retry_count += 1
                        if retry_count >= max_retries:
                            logger.error(f"Max retries ({max_retries}) reached. Restarting bot...")
                            break
                        logger.info(f"Waiting {retry_delay} seconds before retrying... (Attempt {retry_count}/{max_retries})")
                        time.sleep(retry_delay)
                    continue
                    
        except Exception as e:
            logger.error(f"Critical error in bot: {str(e)}")
            logger.exception("Full traceback:")
            if not is_shutting_down:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"Max retries ({max_retries}) reached. Exiting...")
                    break
                logger.info(f"Attempting to restart bot in {retry_delay} seconds... (Attempt {retry_count}/{max_retries})")
                time.sleep(retry_delay)
            continue
        finally:
            if bot_instance:
                try:
                    logger.info("Stopping bot...")
                    bot_instance.stop()
                except Exception as e:
                    logger.error(f"Error stopping bot: {str(e)}")

def run_web_server():
    """Run the Flask web server."""
    port = int(os.getenv("PORT", 10000))
    logger.info(f"Starting web server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    logger.info("Starting application...")
    # Start the web server in a separate thread
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    logger.info("Web server thread started")
    
    # Run the bot in the main thread
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        if bot_instance:
            try:
                bot_instance.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error in main: {str(e)}")
        logger.exception("Full traceback:")
        sys.exit(1) 