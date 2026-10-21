"""Gunicorn reads this file automatically from the project folder.

The Railway start command keeps working unchanged
(gunicorn 'web:create_app()' --bind 0.0.0.0:$PORT --workers 2 --timeout 45 ...).
Values given on that command line still win; this file only adds threads.

Before: 2 sync workers = 2 requests at a time for the whole site.
Now: 2 workers x 8 threads = 16 requests at a time. Requests mostly wait on
MongoDB and Telegram, so threads are the right tool here.
"""
import os

worker_class = "gthread"
threads = int(os.getenv("WEB_THREADS", "8"))
graceful_timeout = 30
keepalive = 5
