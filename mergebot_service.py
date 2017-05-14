from threading import Thread
from app import db, QueuedItem, Poller, WorkItemStatus
import time
import signal
import mergebot
from multiprocessing import Pipe


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


def shutdown_mergebot(signum, _):
    print 'Caught {signal}.'.format(signal=signum)
    raise ServerExit


class ServerExit(Exception):
    pass


def main():
    Poller.query.delete()
    QueuedItem.query.delete()
    db.session.commit()
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    parent_pipe, child_pipe = Pipe()
    mb = mergebot.MergeBot(child_pipe)
    pub = DatabasePublisher(parent_pipe)
    try:
        mb.start()
        pub.start()
        signal.signal(signal.SIGINT, shutdown_mergebot)
        signal.signal(signal.SIGTERM, shutdown_mergebot)
        while True:
            time.sleep(0.5)
    except ServerExit:
        print "Exiting; waiting for MergeBot termination."
        parent_pipe.send('terminate')
        mb.join()
        child_pipe.send('terminate')
        pub.join()
    print "Mergebot terminated."


if __name__ == "__main__":
    main()
