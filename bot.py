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
import multiprocessing
import sys
import atexit
import tempfile
import re
import signal
import socket
import errno
import threading
import queue
import psutil
import json
import subprocess
import platform
import os.path

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
lock_file = None
lock_fd = None
health_check_queue = queue.Queue()
shutdown_event = threading.Event()
process_manager = None

# Spam keywords (can be expanded)
SPAM_KEYWORDS = [
    'lottery', 'winner', 'inheritance', 'urgent', 'million',
    'bank transfer', 'account suspended', 'verify account'
]

# Add these global variables after other globals
MONITORING_INTERVAL = 60  # seconds
MAX_RESTART_ATTEMPTS = 3
RESTART_DELAY = 30  # seconds
last_restart_attempt = None
restart_count = 0
MAX_SHUTDOWN_ATTEMPTS = 3
SHUTDOWN_DELAY = 5
is_restarting = False
last_shutdown_attempt = None
shutdown_count = 0
WELCOME_INTERVAL = 600  # 10 minutes in seconds
last_welcome_time = {}

def is_process_running(pid):
    """Check if a process is still running."""
    try:
        process = psutil.Process(pid)
        return process.is_running()
    except psutil.NoSuchProcess:
        return False

def acquire_lock():
    """Acquire a lock to prevent multiple instances using a simple file-based approach."""
    global lock_file, lock_fd
    try:
        lock_path = os.path.join(tempfile.gettempdir(), 'tempmail_bot.lock')
        
        # First, try to clean up any stale lock files
        if os.path.exists(lock_path):
            try:
                with open(lock_path, 'r') as f:
                    pid = int(f.read().strip())
                if not is_process_running(pid):
                    # Process is not running, remove stale lock
                    os.remove(lock_path)
                else:
                    logger.error("Another instance is already running")
                    return False
            except (ValueError, ProcessLookupError, OSError):
                # Lock file is invalid or can't be read, remove it
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
        
        # Create new lock file
        try:
            lock_fd = open(lock_path, 'w')
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
            lock_file = lock_path
            return True
        except Exception as e:
            logger.error(f"Error creating lock file: {str(e)}")
            return False
    except Exception as e:
        logger.error(f"Error acquiring lock: {str(e)}")
        return False

def release_lock():
    """Release the lock file."""
    global lock_file, lock_fd
    try:
        if lock_fd:
            try:
                lock_fd.close()
            except Exception as e:
                logger.error(f"Error closing lock file: {str(e)}")
        
        if lock_file and os.path.exists(lock_file):
            try:
                # Only remove if it's our lock file
                with open(lock_file, 'r') as f:
                    pid = int(f.read().strip())
                if pid == os.getpid():
                    os.remove(lock_file)
            except Exception as e:
                logger.error(f"Error removing lock file: {str(e)}")
    except Exception as e:
        logger.error(f"Error in release_lock: {str(e)}")

def cleanup_processes():
    """Clean up all child processes."""
    global process_manager
    try:
        # Get all child processes
        current_process = psutil.Process()
        children = current_process.children(recursive=True)
        
        # Terminate each child process
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        
        # Wait for processes to terminate
        psutil.wait_procs(children, timeout=3)
        
        # Force kill any remaining processes
        for child in children:
            try:
                if child.is_running():
                    child.kill()
            except psutil.NoSuchProcess:
                pass
            
        # Clean up any remaining lock files
        lock_path = os.path.join(tempfile.gettempdir(), 'tempmail_bot.lock')
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass
    except Exception as e:
        logger.error(f"Error cleaning up processes: {str(e)}")

def health_check_worker():
    """Background worker to perform health checks."""
    while not shutdown_event.is_set():
        try:
            # Check bot status
            if bot_instance:
                try:
                    bot_instance.bot.get_me()
                    health_check_queue.put(True)
                except Exception as e:
                    logger.error(f"Health check failed: {str(e)}")
                    health_check_queue.put(False)
            
            # Sleep for 30 seconds
            time.sleep(30)
        except Exception as e:
            logger.error(f"Error in health check worker: {str(e)}")
            time.sleep(5)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global is_shutting_down
    logger.info("Received shutdown signal. Cleaning up...")
    is_shutting_down = True
    shutdown_event.set()
    
    # Stop the bot first
    if bot_instance:
        try:
            logger.info("Stopping bot...")
            # Stop the updater first
            bot_instance.stop()
            # Wait for any pending updates to be processed
            time.sleep(2)
            # Stop the dispatcher
            bot_instance.dispatcher.stop()
            # Stop the job queue if it exists
            if hasattr(bot_instance, 'job_queue'):
                bot_instance.job_queue.stop()
        except Exception as e:
            logger.error(f"Error stopping bot: {str(e)}")
    
    # Clean up processes
    cleanup_processes()
    
    # Release the lock
    release_lock()
    
    # Give time for cleanup
    time.sleep(2)
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
    
    try:
        # Check if bot has responded in the last 3 minutes
        time_since_last_response = (datetime.now() - last_response_time).total_seconds()
        is_healthy = time_since_last_response < 180  # 3 minutes = 180 seconds
        
        # Check health check queue
        try:
            recent_health = health_check_queue.get_nowait()
            is_healthy = is_healthy and recent_health
        except queue.Empty:
            pass
        
        if not is_healthy:
            logger.warning(f"Health check failed: No response for {time_since_last_response} seconds")
        
        return jsonify({
            "status": "healthy" if is_healthy else "unhealthy",
            "last_response": last_response_time.isoformat(),
            "time_since_last_response": time_since_last_response,
            "bot_running": bot_instance is not None and not is_shutting_down,
            "health_check_queue_size": health_check_queue.qsize()
        })
    except Exception as e:
        logger.error(f"Error in health check: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

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

@app.route('/monitor/status')
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Check if bot is running
        if not bot_instance or not bot_instance.is_running:
            return jsonify({
                'status': 'unhealthy',
                'message': 'Bot is not running',
                'timestamp': datetime.now().isoformat()
            }), 503
        
        # Check if bot is responding to commands
        try:
            # Get bot info to verify connection
            bot_info = bot_instance.bot.get_me()
            if not bot_info:
                return jsonify({
                    'status': 'unhealthy',
                    'message': 'Bot is not responding to API calls',
                    'timestamp': datetime.now().isoformat()
                }), 503
        except Exception as e:
            logger.error(f"Error checking bot API: {str(e)}")
            return jsonify({
                'status': 'unhealthy',
                'message': f'Bot API error: {str(e)}',
                'timestamp': datetime.now().isoformat()
            }), 503
        
        # Check if dispatcher is running
        if not bot_instance.dispatcher or not bot_instance.dispatcher.is_running:
            return jsonify({
                'status': 'unhealthy',
                'message': 'Bot dispatcher is not running',
                'timestamp': datetime.now().isoformat()
            }), 503
        
        # Check if job queue is running
        if hasattr(bot_instance, 'job_queue') and not bot_instance.job_queue.is_running:
            return jsonify({
                'status': 'unhealthy',
                'message': 'Bot job queue is not running',
                'timestamp': datetime.now().isoformat()
            }), 503
        
        # If all checks pass, return healthy status
        return jsonify({
            'status': 'healthy',
            'message': 'Bot is running normally',
            'timestamp': datetime.now().isoformat(),
            'bot_info': {
                'username': bot_info.username,
                'id': bot_info.id,
                'is_bot': bot_info.is_bot
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error in health check: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'message': f'Health check error: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 503

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
        logger.warning("Conflict detected - cleaning up and restarting bot")
        if bot_instance:
            try:
                # Stop the updater first
                bot_instance.stop()
                # Wait for any pending updates to be processed
                time.sleep(2)
                # Stop the dispatcher
                bot_instance.dispatcher.stop()
                # Stop the job queue if it exists
                if hasattr(bot_instance, 'job_queue'):
                    bot_instance.job_queue.stop()
            except Exception as e:
                logger.error(f"Error during bot cleanup: {str(e)}")
        time.sleep(5)  # Wait before restarting
        sys.exit(1)  # Exit to allow the process manager to restart
    elif isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Network error occurred - will retry automatically")
        if bot_instance:
            try:
                bot_instance.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        time.sleep(5)
    else:
        logger.error(f"Unexpected error: {context.error}")
        logger.exception("Full traceback for unexpected error:")
        if bot_instance:
            try:
                bot_instance.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        time.sleep(5)

def run_web_server():
    """Run the Flask web server in a separate process using Gunicorn."""
    port = int(os.getenv("PORT", 10000))
    logger.info(f"Starting web server on port {port}")
    
    # Use Gunicorn for production
    from gunicorn.app.wsgiapp import WSGIApplication
    
    class StandaloneApplication(WSGIApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                self.cfg.set(key, value)

        def load(self):
            return self.application

    options = {
        'bind': f'0.0.0.0:{port}',
        'workers': 1,  # Single worker to prevent conflicts
        'threads': 1,  # Single thread to prevent conflicts
        'timeout': 120,
        'worker_class': 'sync',
        'accesslog': '-',
        'errorlog': '-',
        'loglevel': 'info',
        'graceful_timeout': 30,  # Give workers time to finish
        'keepalive': 5,  # Keep connections alive
        'max_requests': 1000,  # Restart workers after this many requests
        'max_requests_jitter': 50,  # Add jitter to prevent all workers restarting at once
        'worker_tmp_dir': '/dev/shm',  # Use shared memory for better performance
        'preload_app': True,  # Preload the application
        'worker_connections': 1000,  # Maximum number of simultaneous connections
        'backlog': 2048,  # Maximum number of pending connections
        'reload': False,  # Disable auto-reload in production
        'daemon': False,  # Don't daemonize the process
        'pidfile': None,  # Don't use a PID file
        'umask': 0,  # Set umask to 0
        'user': None,  # Don't change user
        'group': None,  # Don't change group
        'tmp_upload_dir': None,  # Use system default
        'forwarded_allow_ips': '*',  # Allow all forwarded IPs
        'secure_scheme_headers': {
            'X-FORWARDED-PROTOCOL': 'ssl',
            'X-FORWARDED-PROTO': 'https',
            'X-FORWARDED-SSL': 'on'
        }
    }
    
    try:
        StandaloneApplication(app, options).run()
    except Exception as e:
        logger.error(f"Error in web server: {str(e)}")
        logger.exception("Full traceback:")
        sys.exit(1)

def restart_bot():
    """Restart the bot process."""
    global is_restarting, last_shutdown_attempt, shutdown_count
    
    try:
        logger.info("Attempting to restart bot...")
        is_restarting = True
        
        # Clean up before restart
        cleanup_processes()
        release_lock()
        
        # Get the current script path
        script_path = os.path.abspath(__file__)
        
        # Stop the current process
        if bot_instance:
            try:
                bot_instance.stop()
                time.sleep(2)
                bot_instance.dispatcher.stop()
                if hasattr(bot_instance, 'job_queue'):
                    bot_instance.job_queue.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        
        # Wait a bit before starting new process
        time.sleep(2)
        
        # Start a new process
        if platform.system() == 'Windows':
            subprocess.Popen(['python', script_path], 
                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                           env=os.environ.copy())
        else:
            subprocess.Popen(['python3', script_path],
                           env=os.environ.copy())
            
        logger.info("Bot restart initiated")
        time.sleep(5)  # Give time for the new process to start
        
    except Exception as e:
        logger.error(f"Error restarting bot: {str(e)}")
        is_restarting = False

def handle_shutdown(signum, frame):
    """Handle shutdown signals with retry mechanism."""
    global last_shutdown_attempt, shutdown_count, is_shutting_down
    
    if is_shutting_down:
        return

    current_time = datetime.now()
    
    # Check if this is a recent shutdown attempt
    if last_shutdown_attempt and (current_time - last_shutdown_attempt).total_seconds() < SHUTDOWN_DELAY:
        shutdown_count += 1
        if shutdown_count >= MAX_SHUTDOWN_ATTEMPTS:
            logger.warning("Multiple shutdown attempts detected, initiating restart...")
            restart_bot()
            return
    else:
        shutdown_count = 0
        
    last_shutdown_attempt = current_time
    logger.info("Received shutdown signal. Attempting graceful shutdown...")
    
    try:
        is_shutting_down = True
        shutdown_event.set()
        
        if bot_instance:
            try:
                bot_instance.stop()
                time.sleep(2)
                bot_instance.dispatcher.stop()
                if hasattr(bot_instance, 'job_queue'):
                    bot_instance.job_queue.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        
        # Clean up processes
        cleanup_processes()
        
        # Release the lock
        release_lock()
        
        # Give time for cleanup
        time.sleep(2)
        
        # If we got here without hitting max attempts, exit
        if shutdown_count < MAX_SHUTDOWN_ATTEMPTS:
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")
        if shutdown_count < MAX_SHUTDOWN_ATTEMPTS:
            time.sleep(5)
        else:
            restart_bot()

# Modify the signal handlers
signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

def monitor_bot():
    """Background thread to monitor bot health and auto-restart if needed."""
    global last_restart_attempt, restart_count
    
    while not shutdown_event.is_set():
        try:
            # Wait for web server to start
            time.sleep(5)
            
            # Check bot health
            try:
                response = requests.get('http://localhost:10000/monitor/status', timeout=5)
                status_data = response.json()
                
                if status_data.get('status') == 'unhealthy':
                    logger.warning("Bot health check failed, attempting restart...")
                    
                    # Check if we've exceeded max restart attempts
                    if restart_count >= MAX_RESTART_ATTEMPTS:
                        logger.error("Max restart attempts reached. Manual intervention required.")
                        time.sleep(MONITORING_INTERVAL)
                        continue
                    
                    # Check if we're already in the process of restarting
                    if is_restarting:
                        logger.info("Bot is already restarting, skipping this attempt")
                        time.sleep(MONITORING_INTERVAL)
                        continue
                    
                    # Attempt restart
                    last_restart_attempt = datetime.now()
                    restart_count += 1
                    
                    # Stop the current bot instance gracefully
                    if bot_instance:
                        try:
                            logger.info("Stopping current bot instance...")
                            bot_instance.stop()
                            time.sleep(2)
                            bot_instance.dispatcher.stop()
                            if hasattr(bot_instance, 'job_queue'):
                                bot_instance.job_queue.stop()
                            logger.info("Current bot instance stopped successfully")
                        except Exception as e:
                            logger.error(f"Error stopping bot: {str(e)}")
                    
                    # Wait before restarting
                    time.sleep(RESTART_DELAY)
                    
                    # Start a new bot instance
                    try:
                        logger.info("Starting new bot instance...")
                        run_bot()
                        logger.info("New bot instance started successfully")
                        restart_count = 0  # Reset restart count on successful start
                    except Exception as e:
                        logger.error(f"Error starting new bot instance: {str(e)}")
                        time.sleep(RESTART_DELAY)
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Error checking bot health: {str(e)}")
                time.sleep(5)
                
            time.sleep(MONITORING_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in monitor_bot: {str(e)}")
            time.sleep(MONITORING_INTERVAL)

def send_welcome_message(context: CallbackContext):
    """Send welcome message to users every 10 minutes."""
    global last_welcome_time
    current_time = datetime.now()
    
    try:
        # Get all active users from user_sessions
        for user_id in user_sessions.keys():
            # Check if we should send welcome message to this user
            if user_id not in last_welcome_time or \
               (current_time - last_welcome_time[user_id]).total_seconds() >= WELCOME_INTERVAL:
                
                welcome_message = (
                    "👋 Welcome back to Temporary Telegram Bot!\n\n"
                    "Here's a quick reminder of what you can do:\n"
                    "• Use /newmail to get a new temporary email\n"
                    "• Use /current to see your current email\n"
                    "• Use /delete to remove your email session\n"
                    "• Use /stats to see email statistics\n"
                    "• Use /forward to set up email forwarding\n"
                    "• Use /extend to extend email lifetime\n"
                    "• Use /privacy to get privacy tips\n"
                    "• Use /help for more information\n\n"
                    "Need help? Just type /help anytime! 😊"
                )
                
                try:
                    context.bot.send_message(chat_id=user_id, text=welcome_message)
                    last_welcome_time[user_id] = current_time
                    logger.info(f"Sent welcome message to user {user_id}")
                except Exception as e:
                    logger.error(f"Error sending welcome message to user {user_id}: {str(e)}")
                    
    except Exception as e:
        logger.error(f"Error in send_welcome_message: {str(e)}")

def run_bot():
    """Initialize and run the Telegram bot."""
    global bot_instance, is_restarting
    
    try:
        # Get the bot token from environment variables
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")
            
        # Initialize the bot
        bot_instance = Updater(token, use_context=True)
        
        # Get the dispatcher to register handlers
        dispatcher = bot_instance.dispatcher
        
        # Register command handlers
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("newmail", newmail))
        dispatcher.add_handler(CommandHandler("current", current))
        dispatcher.add_handler(CommandHandler("delete", delete_session))
        dispatcher.add_handler(CommandHandler("stats", stats))
        dispatcher.add_handler(CommandHandler("forward", forward))
        dispatcher.add_handler(CommandHandler("extend", extend_lifetime))
        dispatcher.add_handler(CommandHandler("privacy", privacy_tips))
        
        # Register callback query handler
        dispatcher.add_handler(CallbackQueryHandler(button_callback))
        
        # Register error handler
        dispatcher.add_error_handler(error_handler)
        
        # Start the bot
        logger.info("Starting bot...")
        bot_instance.start_polling()
        
        # Add welcome message job
        job_queue = bot_instance.job_queue
        job_queue.run_repeating(send_welcome_message, interval=WELCOME_INTERVAL, first=WELCOME_INTERVAL)
        
        logger.info("Bot started successfully")
        
        # Reset restart count on successful start
        global restart_count
        restart_count = 0
        
        # Instead of using idle(), we'll use a loop with shutdown_event
        while not shutdown_event.is_set():
            time.sleep(1)
            
        # Cleanup when shutdown is requested
        bot_instance.stop()
        time.sleep(2)
        bot_instance.dispatcher.stop()
        if hasattr(bot_instance, 'job_queue'):
            bot_instance.job_queue.stop()
            
    except Exception as e:
        logger.error(f"Error in run_bot: {str(e)}")
        logger.exception("Full traceback:")
        if bot_instance:
            try:
                bot_instance.stop()
            except Exception as stop_error:
                logger.error(f"Error stopping bot: {str(stop_error)}")
        raise
    finally:
        is_restarting = False  # Reset restarting flag when done

if __name__ == '__main__':
    logger.info("Starting application...")
    
    # Clean up any existing processes and lock files
    cleanup_processes()
    
    # Try to acquire lock
    if not acquire_lock():
        logger.error("Another instance is already running. Exiting...")
        sys.exit(1)
    
    try:
        # Start the web server in a separate process
        web_process = multiprocessing.Process(target=run_web_server)
        web_process.daemon = True
        web_process.start()
        logger.info("Web server process started")
        
        # Start monitoring thread
        monitor_thread = threading.Thread(target=monitor_bot)
        monitor_thread.daemon = True
        monitor_thread.start()
        logger.info("Monitoring thread started")
        
        # Run the bot in the main thread
        while not shutdown_event.is_set():
            try:
                run_bot()
            except Exception as e:
                logger.error(f"Error in main loop: {str(e)}")
                if not is_restarting:
                    time.sleep(RESTART_DELAY)
                    continue
                else:
                    break
                    
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        shutdown_event.set()
        if bot_instance:
            try:
                bot_instance.stop()
                time.sleep(2)
                bot_instance.dispatcher.stop()
                if hasattr(bot_instance, 'job_queue'):
                    bot_instance.job_queue.stop()
            except Exception as e:
                logger.error(f"Error stopping bot: {str(e)}")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error in main: {str(e)}")
        logger.exception("Full traceback:")
        if not is_restarting:
            restart_bot()
    finally:
        if not is_restarting:
            cleanup_processes()
            release_lock() 