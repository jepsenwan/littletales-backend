import pymysql

# Present PyMySQL as MySQLdb so Django's mysql backend uses it.
# Avoids the mysqlclient C-extension build on Nix-based images (Railway).
pymysql.install_as_MySQLdb()

# Django 6 checks mysqlclient >= 2.2.1. PyMySQL reports "1.4.6" which
# the backend rejects. The API is compatible, so spoof the version.
import sys
_mysqldb = sys.modules.get('MySQLdb')
if _mysqldb is not None:
    _mysqldb.version_info = (2, 2, 1, 'final', 0)
    _mysqldb.__version__ = '2.2.1'

from .celery import app as celery_app

__all__ = ('celery_app',)
