#!/usr/bin/env bash
# Render (and generic) build procedure: deps → static → migrations.
set -o errexit

# Render builds must validate, migrate and collect static assets with the same
# hardened settings the web and Celery processes will use. This overrides stale
# dashboard values such as config.settings.development.
if [[ -n "${RENDER:-}" ]]; then
  export DJANGO_SETTINGS_MODULE=config.settings.production
fi

pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
