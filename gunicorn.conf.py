"""Production server settings:  gunicorn -c gunicorn.conf.py config.wsgi"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '3000')}"
# One worker process with threads: login lock-outs and chat rate limits live in the in-process cache.
# (To run several workers, switch CACHES in config/settings.py to Redis or the database cache.)
workers = 1
threads = int(os.environ.get("THREADS", "8"))
worker_class = "gthread"
timeout = 90            # the AI chat provider may take up to AI_TIMEOUT_MS (30 s)
graceful_timeout = 20
accesslog = "-" if os.environ.get("ACCESS_LOG") == "1" else None
errorlog = "-"
loglevel = "info"
control_socket_disable = True
