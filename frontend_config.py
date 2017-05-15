import os
basedir = os.path.abspath(os.path.dirname(__file__))

SQLALCHEMY_DATABASE_URI = 'sqlite:///{db_uri}'.format(
    db_uri=os.path.join(basedir, 'db', 'mergebot.db'))

# TODO(jasonkuster): Configure migration.
# SQLALCHEMY_MIGRATE_REPO = os.path.join(basedir, 'db_repository')
