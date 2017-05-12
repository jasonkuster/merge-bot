import time

import mergebot
from multiprocessing import Pipe
from threading import Thread
from flask import Flask, abort, render_template, send_from_directory, request
from flask_sqlalchemy import SQLAlchemy
import thread
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


class DatabasePublisher(Thread):
    def __init__(self, pipe):
        self.pipe = pipe
        Thread.__init__(self)

    def run(self):
        while True:
            while self.pipe.poll():
                msg = self.pipe.recv()
                if msg == 'terminate':
                    return
                handle_message(msg)
            time.sleep(1)


def handle_message(msg):
    if msg['type'] == 'WORK_ITEM_STATUS':
        insert_work_item(msg)
    elif msg['type'] == 'ENQUEUE':
        item = QueuedItem(msg['name'], msg['content'], msg['timestamp'])
        db.session.add(item)
        db.session.commit()
    elif msg['type'] == 'DEQUEUE':
        item = QueuedItem.query.filter_by(
            project_name=msg['name'], item_id=msg['content']).first()
        db.session.delete(item)
        db.session.commit()
    elif msg['type'] == 'STATUS':
        if msg['module'] == 'mergebot_poller':
            if msg['content'] == 'STARTUP':
                poller = Poller(msg['name'], msg['timestamp'])
                db.session.add(poller)
                db.session.commit()
            elif msg['content'] == 'TERMINATING':
                poller = Poller.query.filter_by(
                    project_name=msg['name']).first()
                poller.status = 'TERMINATING'
                poller.timestamp = msg['timestamp']
                db.session.commit()
            elif msg['content'] == 'SHUTDOWN':
                poller = Poller.query.filter_by(
                    project_name=msg['name']).first()
                db.session.delete(poller)
                db.session.commit()
            else:
                print "Invalid Status: {status}".format(status=msg['content'])
        elif msg['module'] == 'merge':
            if msg['content'] == 'STARTUP':
                poller = Poller.query.filter_by(
                    project_name=msg['name']).first()
                poller.merger_started = True
                poller.timestamp = msg['timestamp']
                db.session.commit()
            elif msg['content'] == 'SHUTDOWN':
                poller = Poller.query.filter_by(
                    project_name=msg['name']).first()
                poller.merger_started = False
                poller.timestamp = msg['timestamp']
                db.session.commit()
            else:
                print "Invalid Status: {status}".format(status=msg['content'])
        else:
            print "Invalid Module: {module}".format(module=msg['module'])
    elif msg['type'] == 'HEARTBEAT':
        poller = Poller.query.filter_by(
            project_name=msg['name']).first()
        poller.timestamp = msg['timestamp']
        db.session.commit()
    else:
        print "Invalid Type: {type}".format(type=msg['type'])


def insert_work_item(msg):
    if msg['content']['status'] == 'JOB_WAIT_HEARTBEAT':
        item_status = WorkItemStatus.query.filter_by(
            project_name=msg['name'],
            item_id=msg['content']['id'],
            status='JOB_WAIT').first()
        item_status.timestamp = msg['timestamp']
        db.session.commit()
        return

    item_status = WorkItemStatus(
        msg['name'],
        msg['content']['id'],
        msg['timestamp'],
        msg['content']['status'])
    db.session.add(item_status)
    db.session.commit()


def start_server():
    app.run()


def stop_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if not func:
        raise RuntimeError('Not running with werkzeug server.')
    func()


def shutdown_mergebot(signum, frame):
    print 'Caught {signal}.'.format(signum)
    raise ServerExit


class ServerExit(Exception):
    pass


def main():
    Poller.query.delete()
    QueuedItem.query.delete()
    db.session.commit()
    parent_pipe, child_pipe = Pipe()
    mb = mergebot.MergeBot(child_pipe)
    pub = DatabasePublisher(parent_pipe)
    signal.signal(signal.SIGTERM, shutdown_mergebot)
    signal.signal(signal.SIGINT, shutdown_mergebot)
    try:
        mb.start()
        pub.start()
        # TODO(jasonkuster): standardize?
        thread.start_new_thread(start_server, ())
        while True:
            time.sleep(0.5)
    except ServerExit:
        print "Exiting; waiting for MergeBot termination."
        parent_pipe.send('terminate')
        mb.join()
        child_pipe.send('terminate')
        pub.join()
        print "MergeBot terminated; killing server."
        stop_server()
    print "Server terminated; ending."


if __name__ == "__main__":
    main()
