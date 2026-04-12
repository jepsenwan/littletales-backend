release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn littletales.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120
worker: celery -A littletales worker -l info --concurrency=2
