import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from telegram.error import Conflict, TimedOut, NetworkError
import requests
from dotenv import load_dotenv
from datetime import datetime
import time
from flask import Flask
import threading
import sys
import fcntl
import atexit
import tempfile

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# DropMail API endpoint
DROPMAIL_API = "https://dropmail.me/api/graphql/web-test"

# Initialize Flask app
app = Flask(__name__)

# Global variables
bot_instance = None
lock_file = None

def acquire_lock():
    """Acquire a lock file to ensure only one instance runs."""
    global lock_file
    try:
        # Use tempfile to get a system-appropriate temporary directory
        lock_path = os.path.join(tempfile.gettempdir(), 'bot.lock')
        lock_file = open(lock_path, 'w')
        fcntl.lockf(lock_file, fcntl.F_EXLCK)
        return True
    except (IOError, AttributeError) as e:
        logger.warning(f"Could not acquire lock: {str(e)}")
        return False

def release_lock():
    """Release the lock file."""
    global lock_file
    if lock_file:
        try:
            fcntl.lockf(lock_file, fcntl.F_UNLCK)
            lock_file.close()
            try:
                os.remove(os.path.join(tempfile.gettempdir(), 'bot.lock'))
            except:
                pass
        except Exception as e:
            logger.warning(f"Error releasing lock: {str(e)}")

def cleanup():
    """Cleanup function to be called on exit."""
    release_lock()
    if bot_instance:
        try:
            bot_instance.stop()
        except:
            pass

# Register cleanup function
atexit.register(cleanup)

@app.route('/')
def home():
    return "DropMail Bot is running! 🚀"

@app.route('/health')
def health_check():
    return "OK", 200

def start(update: Update, context: CallbackContext):
    """Send a message when the command /start is issued."""
    welcome_message = (
        "👋 Welcome to DropMail Bot!\n\n"
        "This bot helps you create temporary email addresses.\n\n"
        "Commands:\n"
        "/newmail - Generate a new temporary email address\n"
        "/current - Show current email address\n"
        "/delete - Delete current email session\n"
        "/stats - Show email statistics\n"
        "/forward - Set email forwarding\n"
        "/help - Show this help message"
    )
    update.message.reply_text(welcome_message)

def help_command(update: Update, context: CallbackContext):
    """Send a message when the command /help is issued."""
    help_message = (
        "📧 DropMail Bot Help\n\n"
        "Commands:\n"
        "/newmail - Generate a new temporary email address\n"
        "/current - Show current email address\n"
        "/delete - Delete current email session\n"
        "/stats - Show email statistics\n"
        "/forward - Set email forwarding\n"
        "/help - Show this help message\n\n"
        "How to use:\n"
        "1. Use /newmail to get a temporary email address\n"
        "2. Share this email address with anyone\n"
        "3. Emails sent to this address will be shown in the chat\n"
        "4. The email address is temporary and will expire after some time\n"
        "5. Use /current to see your current email address\n"
        "6. Use /delete to remove the current email session\n"
        "7. Use /stats to see email statistics\n"
        "8. Use /forward to set up email forwarding"
    )
    update.message.reply_text(help_message)

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
                message = (
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
    
    if isinstance(context.error, Conflict):
        logger.warning("Conflict detected - another bot instance might be running")
        # Stop the current instance and wait for restart
        if bot_instance:
            try:
                bot_instance.stop()
            except:
                pass
        time.sleep(5)
    elif isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Network error occurred - will retry automatically")
    else:
        logger.error(f"Unexpected error: {context.error}")

def run_bot():
    """Run the Telegram bot."""
    global bot_instance
    
    # Get the token from environment variable
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("No token found! Please set TELEGRAM_BOT_TOKEN environment variable.")
        return

    # Try to acquire lock
    if not acquire_lock():
        logger.error("Another instance is already running")
        return

    try:
        # Create the Updater and pass it your bot's token
        updater = Updater(token, use_context=True)
        bot_instance = updater

        # Get the dispatcher to register handlers
        dispatcher = updater.dispatcher

        # Add command handlers
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("newmail", newmail))
        dispatcher.add_handler(CommandHandler("current", current))
        dispatcher.add_handler(CommandHandler("delete", delete_session))
        dispatcher.add_handler(CommandHandler("stats", stats))
        dispatcher.add_handler(CommandHandler("forward", forward))
        dispatcher.add_handler(CallbackQueryHandler(button_callback))
        
        # Add error handler
        dispatcher.add_error_handler(error_handler)

        # Start the Bot with a longer timeout
        updater.start_polling(drop_pending_updates=True, read_timeout=30, write_timeout=30)
        logger.info("Bot started successfully!")
        
        # Keep the bot running
        while True:
            try:
                # Test bot connection every 30 seconds
                updater.bot.get_me()
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in bot loop: {str(e)}")
                break
                
    except Exception as e:
        logger.error(f"Critical error in bot: {str(e)}")
    finally:
        cleanup()

def run_web_server():
    """Run the Flask web server."""
    port = int(os.getenv("PORT", 8000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Start the web server in a separate thread
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    # Run the bot in the main thread
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        cleanup()
        sys.exit(0) 