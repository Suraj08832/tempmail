import os
import logging
import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from datetime import datetime, timedelta
import pytz
from flask import Flask
import threading
import sys
import atexit
import signal
import email
from email import policy
import json
import time
import psutil
import requests
from aiosmtpd.controller import Controller
import asyncio
import socket

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Lock file path
LOCK_FILE = '/tmp/telegram_bot.lock'

# Email server settings
EMAIL_HOST = '0.0.0.0'
EMAIL_PORT = 25
DOMAINS = ['10mail.xyz', 'emlhub.com', 'tempmail.plus', 'tempmail.space']

# Store emails and user sessions
emails = {}
user_emails = {}
user_stats = {}
message_tracking = {}  # Track bot messages for editing/deleting

class CustomHandler:
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if not address.endswith(tuple(DOMAINS)):
            return '550 not relaying to that domain'
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session, envelope):
        try:
            # Parse email
            msg = email.message_from_bytes(envelope.content, policy=policy.default)
            subject = msg.get('subject', 'No Subject')
            from_addr = envelope.mail_from
            to_addr = envelope.rcpt_tos[0]
            date = msg.get('date', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            
            # Extract body
            body = ''
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_content()
                        break
            else:
                body = msg.get_content()

            # Store email
            if to_addr not in emails:
                emails[to_addr] = []
            emails[to_addr].append({
                'subject': subject,
                'from': from_addr,
                'date': date,
                'body': body
            })

            # Find user by email and send notification
            for user_id, email_addr in user_emails.items():
                if email_addr == to_addr:
                    try:
                        # Get bot instance from the application context
                        bot = Updater.bot
                        if bot:
                            # Create notification message
                            notification = (
                                f"📧 New email received!\n\n"
                                f"From: {from_addr}\n"
                                f"Subject: {subject}\n"
                                f"Date: {date}\n"
                                f"Body: {body[:200]}..."  # First 200 chars
                            )
                            # Send notification to user
                            sent_msg = bot.send_message(
                                chat_id=user_id,
                                text=notification,
                                parse_mode='HTML'
                            )
                            # Track the message
                            message_tracking[sent_msg.message_id] = {
                                'chat_id': user_id,
                                'type': 'email_notification',
                                'email': to_addr
                            }
                    except Exception as e:
                        logger.error(f"Error sending notification to user {user_id}: {str(e)}")

            logger.info(f"Received email for {to_addr} from {from_addr}")
            return '250 Message accepted for delivery'
        except Exception as e:
            logger.error(f"Error processing email: {str(e)}")
            return f'500 Error processing email: {str(e)}'

async def run_email_server():
    """Run SMTP server in a separate thread."""
    try:
        # Create a socket to check if port is available
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((EMAIL_HOST, EMAIL_PORT))
        sock.close()
        
        controller = Controller(CustomHandler(), hostname=EMAIL_HOST, port=EMAIL_PORT)
        controller.start()
        logger.info(f"Starting SMTP server on {EMAIL_HOST}:{EMAIL_PORT}")
        
        # Keep the server running
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error running SMTP server: {str(e)}")
        sys.exit(1)

def is_process_running(pid):
    """Check if a process is running."""
    try:
        process = psutil.Process(pid)
        return process.is_running()
    except psutil.NoSuchProcess:
        return False

def cleanup():
    """Cleanup function to remove lock file on exit."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock file removed")
    except Exception as e:
        logger.error(f"Error removing lock file: {str(e)}")

def create_lock():
    """Create a lock file to ensure only one instance runs."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
                if is_process_running(pid):
                    logger.error(f"Another instance is already running with PID {pid}")
                    return False
                else:
                    # Process is not running, we can create a new lock
                    os.remove(LOCK_FILE)
        
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        logger.error(f"Error creating lock file: {str(e)}")
        return False

def error_handler(update: Update, context: CallbackContext):
    """Handle errors in the bot."""
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.effective_message:
        update.effective_message.reply_text(
            "Sorry, something went wrong. Please try again later."
        )

@app.route('/')
def home():
    return "Bot is running!"

def generate_email():
    """Generate a random temporary email address."""
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = random.choice(DOMAINS)
    return f"{username}@{domain}"

def newmail(update: Update, context: CallbackContext):
    """Generate a new temporary email address."""
    user_id = update.effective_user.id
    email = generate_email()
    user_emails[user_id] = email
    user_stats[user_id] = {'created': datetime.now(), 'emails_received': 0}
    
    # Create refresh button
    keyboard = [[InlineKeyboardButton("🔄 Refresh Email", callback_data='refresh_email')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    sent_msg = update.message.reply_text(
        f"📧 Your new temporary email address:\n\n"
        f"`{email}`\n\n"
        f"This email will be valid for 24 hours.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    # Track the message
    message_tracking[sent_msg.message_id] = {
        'chat_id': update.effective_chat.id,
        'type': 'email_generation',
        'email': email
    }

def tempmaill(update: Update, context: CallbackContext):
    """Generate a new temporary email address and show inbox."""
    user_id = update.effective_user.id
    email = generate_email()
    user_emails[user_id] = email
    
    # Create refresh and new email buttons
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Messages", callback_data='refresh_messages')],
        [InlineKeyboardButton("📧 New Email", callback_data='new_email')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Show inbox
    inbox_text = show_inbox(email)
    
    sent_msg = update.message.reply_text(
        f"📧 Your temporary email address:\n\n"
        f"`{email}`\n\n"
        f"{inbox_text}",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    # Track the message
    message_tracking[sent_msg.message_id] = {
        'chat_id': update.effective_chat.id,
        'type': 'inbox_view',
        'email': email
    }

def show_inbox(email):
    """Show inbox contents for an email address."""
    if email not in emails or not emails[email]:
        return "📥 Inbox is empty"
    
    inbox_text = "📥 Inbox:\n\n"
    for i, msg in enumerate(emails[email], 1):
        inbox_text += f"{i}. From: {msg['from']}\n"
        inbox_text += f"   Subject: {msg['subject']}\n"
        inbox_text += f"   Date: {msg['date']}\n"
        inbox_text += f"   Body: {msg['body'][:200]}...\n\n"  # Show first 200 chars of body
    
    return inbox_text

def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == 'refresh_messages':
        if user_id in user_emails:
            email = user_emails[user_id]
            inbox_text = show_inbox(email)
            
            # Create refresh and new email buttons
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Messages", callback_data='refresh_messages')],
                [InlineKeyboardButton("📧 New Email", callback_data='new_email')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            query.edit_message_text(
                f"📧 Your temporary email address:\n\n"
                f"`{email}`\n\n"
                f"{inbox_text}",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            query.answer("Messages refreshed!")
    
    elif query.data == 'new_email':
        email = generate_email()
        user_emails[user_id] = email
        
        # Create refresh and new email buttons
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Messages", callback_data='refresh_messages')],
            [InlineKeyboardButton("📧 New Email", callback_data='new_email')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(
            f"📧 Your new temporary email address:\n\n"
            f"`{email}`\n\n"
            f"📥 Inbox is empty",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        query.answer("New email address generated!")

def handle_edited_message(update: Update, context: CallbackContext):
    """Handle edited messages in groups."""
    try:
        if update.edited_message and update.edited_message.chat.type in ['group', 'supergroup']:
            edited_msg = update.edited_message
            user = edited_msg.from_user
            
            # Get the original message if available
            original_text = edited_msg.reply_to_message.text if edited_msg.reply_to_message else "Original message not available"
            
            # Create notification message
            notification = (
                f"📝 Message edited by @{user.username or user.first_name}\n\n"
                f"Original: {original_text}\n"
                f"New: {edited_msg.text}"
            )
            
            # Send notification and store the message object
            sent_msg = context.bot.send_message(
                chat_id=edited_msg.chat_id,
                text=notification,
                parse_mode='HTML'
            )
            
            # Track the message
            message_tracking[sent_msg.message_id] = {
                'chat_id': edited_msg.chat_id,
                'type': 'edit_notification',
                'original_message_id': edited_msg.message_id
            }
            
            # Schedule deletion after 1 minute
            context.job_queue.run_once(
                lambda context: context.bot.delete_message(
                    chat_id=edited_msg.chat_id,
                    message_id=sent_msg.message_id
                ),
                when=60  # 60 seconds = 1 minute
            )
    except Exception as e:
        logger.error(f"Error handling edited message: {str(e)}")

def handle_deleted_message(update: Update, context: CallbackContext):
    """Handle deleted messages in groups."""
    try:
        if update.message and update.message.chat.type in ['group', 'supergroup']:
            deleted_msg = update.message
            user = deleted_msg.from_user
            
            # Create notification message
            notification = (
                f"🗑️ Message deleted by @{user.username or user.first_name}\n\n"
                f"Content: {deleted_msg.text}"
            )
            
            # Send notification and store the message object
            sent_msg = context.bot.send_message(
                chat_id=deleted_msg.chat_id,
                text=notification,
                parse_mode='HTML'
            )
            
            # Track the message
            message_tracking[sent_msg.message_id] = {
                'chat_id': deleted_msg.chat_id,
                'type': 'delete_notification',
                'original_message_id': deleted_msg.message_id
            }
    except Exception as e:
        logger.error(f"Error handling deleted message: {str(e)}")

def current_email(update: Update, context: CallbackContext):
    """Show current email address."""
    user_id = update.effective_user.id
    if user_id in user_emails:
        sent_msg = update.message.reply_text(
            f"📧 Your current temporary email address:\n\n"
            f"`{user_emails[user_id]}`",
            parse_mode='Markdown'
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'current_email',
            'email': user_emails[user_id]
        }
    else:
        sent_msg = update.message.reply_text(
            "❌ You don't have an active temporary email address.\n"
            "Use /newmail to create one."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'no_email'
        }

def delete_email(update: Update, context: CallbackContext):
    """Delete current email session."""
    user_id = update.effective_user.id
    if user_id in user_emails:
        email = user_emails.pop(user_id)
        user_stats.pop(user_id, None)
        sent_msg = update.message.reply_text(
            f"🗑️ Your temporary email address has been deleted:\n\n"
            f"`{email}`"
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'email_deletion',
            'email': email
        }
    else:
        sent_msg = update.message.reply_text(
            "❌ You don't have an active temporary email address."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'no_email'
        }

def show_stats(update: Update, context: CallbackContext):
    """Show email statistics."""
    user_id = update.effective_user.id
    if user_id in user_stats:
        stats = user_stats[user_id]
        created_time = stats['created'].strftime('%Y-%m-%d %H:%M:%S')
        sent_msg = update.message.reply_text(
            f"📊 Email Statistics:\n\n"
            f"Created: {created_time}\n"
            f"Emails received: {stats['emails_received']}\n"
            f"Current address: `{user_emails[user_id]}`",
            parse_mode='Markdown'
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'stats',
            'email': user_emails[user_id]
        }
    else:
        sent_msg = update.message.reply_text(
            "❌ No statistics available.\n"
            "Use /newmail to create a temporary email address."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'no_stats'
        }

def forward_email(update: Update, context: CallbackContext):
    """Set email forwarding."""
    user_id = update.effective_user.id
    if user_id in user_emails:
        sent_msg = update.message.reply_text(
            "📧 Email forwarding is enabled by default.\n"
            "All emails sent to your temporary address will be forwarded to you."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'forwarding_info',
            'email': user_emails[user_id]
        }
    else:
        sent_msg = update.message.reply_text(
            "❌ You don't have an active temporary email address.\n"
            "Use /newmail to create one."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'no_email'
        }

def extend_email(update: Update, context: CallbackContext):
    """Extend email lifetime."""
    user_id = update.effective_user.id
    if user_id in user_stats:
        user_stats[user_id]['created'] = datetime.now()
        sent_msg = update.message.reply_text(
            "⏰ Your temporary email address lifetime has been extended by 24 hours."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'extension',
            'email': user_emails[user_id]
        }
    else:
        sent_msg = update.message.reply_text(
            "❌ You don't have an active temporary email address.\n"
            "Use /newmail to create one."
        )
        
        # Track the message
        message_tracking[sent_msg.message_id] = {
            'chat_id': update.effective_chat.id,
            'type': 'no_email'
        }

def privacy_tips(update: Update, context: CallbackContext):
    """Get privacy tips."""
    tips = (
        "🔒 Privacy Tips for Using Temporary Emails:\n\n"
        "1. Never use temporary emails for sensitive accounts\n"
        "2. Change your email address regularly\n"
        "3. Don't share your temporary email with others\n"
        "4. Use strong passwords for your accounts\n"
        "5. Enable 2FA when possible\n"
        "6. Monitor your email activity regularly\n"
        "7. Delete your temporary email when done"
    )
    sent_msg = update.message.reply_text(tips)
    
    # Track the message
    message_tracking[sent_msg.message_id] = {
        'chat_id': update.effective_chat.id,
        'type': 'privacy_tips'
    }

def help_command(update: Update, context: CallbackContext):
    """Send a message when the command /help is issued."""
    help_text = (
        "👋 Welcome to the Bot!\n\n"
        "Temporary Email Commands:\n"
        "/newmail - Generate a new temporary email address\n"
        "/tempmaill - Generate a new temporary email address and show inbox\n"
        "/current - Show current email address\n"
        "/delete - Delete current email session\n"
        "/stats - Show email statistics\n"
        "/forward - Set email forwarding\n"
        "/extend - Extend email lifetime\n"
        "/privacy - Get privacy tips\n\n"
        "Group Features:\n"
        "- Tracks edited messages\n"
        "- Tracks deleted messages"
    )
    sent_msg = update.message.reply_text(help_text)
    
    # Track the message
    message_tracking[sent_msg.message_id] = {
        'chat_id': update.effective_chat.id,
        'type': 'help'
    }

def run_flask():
    """Run Flask server in a separate thread."""
    try:
        port = int(os.getenv('PORT', 10000))
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error running Flask server: {str(e)}")
        sys.exit(1)

def main():
    """Start the bot."""
    try:
        # Create lock file
        if not create_lock():
            logger.error("Failed to create lock file. Another instance might be running.")
            sys.exit(1)

        # Register cleanup function
        atexit.register(cleanup)

        # Get the bot token
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
            cleanup()
            return

        # Create the Updater with specific settings
        updater = Updater(
            token=token,
            use_context=True,
            workers=1,  # Limit workers to 1
            request_kwargs={'read_timeout': 30, 'connect_timeout': 30}  # Increase timeouts
        )

        # Get the dispatcher to register handlers
        dp = updater.dispatcher

        # Add error handler
        dp.add_error_handler(error_handler)

        # Add command handlers
        dp.add_handler(CommandHandler("start", help_command))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("newmail", newmail))
        dp.add_handler(CommandHandler("tempmaill", tempmaill))
        dp.add_handler(CommandHandler("current", current_email))
        dp.add_handler(CommandHandler("delete", delete_email))
        dp.add_handler(CommandHandler("stats", show_stats))
        dp.add_handler(CommandHandler("forward", forward_email))
        dp.add_handler(CommandHandler("extend", extend_email))
        dp.add_handler(CommandHandler("privacy", privacy_tips))
        
        # Add message handlers
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_edited_message))
        dp.add_handler(MessageHandler(Filters.status_update, handle_deleted_message))
        
        # Add callback query handler
        dp.add_handler(CallbackQueryHandler(button_callback))

        # Start the bot
        logger.info("Starting bot...")
        updater.start_polling(
            allowed_updates=['message', 'edited_message', 'callback_query'],
            drop_pending_updates=True  # Drop any pending updates
        )

        # Start Flask in a separate thread
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()

        # Start email server in a separate thread
        email_thread = threading.Thread(target=lambda: asyncio.run(run_email_server()))
        email_thread.daemon = True
        email_thread.start()

        # Handle shutdown signals
        def signal_handler(signum, frame):
            logger.info("Received shutdown signal")
            updater.stop()
            cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Run the bot until you press Ctrl-C
        updater.idle()

    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        cleanup()
        sys.exit(1)

if __name__ == '__main__':
    main() 