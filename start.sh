#!/usr/bin/env sh
# Start Syntaxo: create/update the database tables, then run the Python web server (gunicorn).
set -e
cd "$(dirname "$0")"
python3 manage.py migrate --noinput -v 0
exec gunicorn -c gunicorn.conf.py config.wsgi:application
