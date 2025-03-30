import multiprocessing
from bot import create_app, run_bot
import threading

# Create the Flask application
app = create_app()

# Start the bot thread only once
bot_thread = threading.Thread(target=run_bot)
bot_thread.daemon = True
bot_thread.start()

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes - use only 1 worker for the bot
workers = 1
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 2

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Process naming
proc_name = 'tempmail-bot'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None 