from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config.from_object('frontend_config')
db = SQLAlchemy(app)

from mergebot_frontend import views, models
