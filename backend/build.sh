#!/usr/bin/env bash
# Render (and generic) build procedure: deps → static → migrations.
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
