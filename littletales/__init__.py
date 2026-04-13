import pymysql

# Present PyMySQL as MySQLdb so Django's mysql backend uses it.
# Avoids the mysqlclient C-extension build on Nix-based images (Railway).
pymysql.install_as_MySQLdb()

from .celery import app as celery_app

__all__ = ('celery_app',)
