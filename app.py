import time

import mergebot
from multiprocessing import Process, Pipe
from threading import Thread
from flask import Flask, abort, render_template, send_from_directory, request
from flask_sqlalchemy import SQLAlchemy
import signal

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db/mergebot.db'
db = SQLAlchemy(app)


@app.route("/")
def index():
    pollers = Poller.query.order_by(Poller.project_name).all()
    return render_template('index.html', pollers=pollers)


@app.route('/<proj>')
def project(proj):
    poller = Poller.query.filter_by(
        project_name=proj).first_or_404()
    queue = QueuedItem.query.filter_by(
        project_name=proj,
    ).order_by(QueuedItem.timestamp.desc()).all()
    active = None
    last_start = WorkItemStatus.query.filter_by(
        project_name=proj,
        status='START',
    ).order_by(WorkItemStatus.timestamp.desc()).first()
    last_finish = WorkItemStatus.query.filter_by(
        project_name=proj,
        status='FINISH',
    ).order_by(WorkItemStatus.timestamp.desc()).first()
    if last_start and (not last_finish or (last_start.timestamp >
                                           last_finish.timestamp)):
        active = WorkItemStatus.query.filter_by(
            project_name=proj,
            item_id=last_start.item_id,
        ).order_by(WorkItemStatus.timestamp).first()
    return render_template('project.html',
                           poller=poller,
                           queue=queue,
                           active=active)


@app.route('/<proj>/<int:item>')
def item(proj, item):
    poller = Poller.query.filter_by(
        project_name=proj).first_or_404()
    item_statuses = WorkItemStatus.query.filter_by(
        project_name=proj,
        item_id=item,
    ).order_by(WorkItemStatus.timestamp).all()
    if not item_statuses:
        abort(404)
    return render_template('item.html',
                           poller=poller,
                           item_statuses=item_statuses)


@app.route("/css/<path:path>")
def send_css(path):
    return send_from_directory('css', path)


@app.route("/log/<path:path>")
def send_log(path):
    return send_from_directory('log', path)


class WorkItemStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(80))
    item_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)
    status = db.Column(db.String(200))

    def __init__(self, project_name, item_id, timestamp, status):
        self.project_name = project_name
        self.item_id = item_id
        self.timestamp = timestamp
        self.status = status

    def __repr__(self):
        return ('Project: {proj}, Item ID: {item}, Status: {status}, '
                'Timestamp: {timestamp}'.format(
                    proj=self.project_name,
                    item=self.item_id,
                    status=self.status,
                    timestamp=self.timestamp,
                ))


class Poller(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(80), unique=True)
    status = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime)
    merger_started = db.Column(db.Boolean)

    def __init__(self, project_name, timestamp):
        self.project_name = project_name
        self.status = "STARTED"
        self.timestamp = timestamp
        self.merger_started = False

    def __repr__(self):
        return ('Poller for {proj}, Current Status: {status}, Merger Started: '
                '{ms}, Last Updated: {time}'.format(
                     proj=self.project_name,
                     status=self.status,
                     ms=self.merger_started,
                     time=self.timestamp))


class QueuedItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(80))
    item_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)

    def __init__(self, project_name, item_id, timestamp):
        self.project_name = project_name
        self.item_id = item_id
        self.timestamp = timestamp

    def __repr__(self):
        return ('Queued Item: {id}, Project: {proj}, Added: {time}'.format(
            id=self.item_id,
            proj=self.project_name,
            time=self.timestamp))


if __name__ == "__main__":
    app.run(host='0.0.0.0', port='8080')
