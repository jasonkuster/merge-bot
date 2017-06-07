from mergebot_frontend import db


class WorkItemStatus(db.Model):
    """WorkItemStatus has necessary information about updates to work items."""
    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(80))
    item_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime)
    status = db.Column(db.String(200))
    info = db.Column(db.String(200))

    def __init__(self, project_name, item_id, timestamp, status, info):
        self.project_name = project_name
        self.item_id = item_id
        self.timestamp = timestamp
        self.status = status
        self.info = info

    def __repr__(self):
        return ('Project: {proj}, Item ID: {item}, Status: {status}, '
                'Timestamp: {timestamp}. Info: {info}'.format(
                    proj=self.project_name,
                    item=self.item_id,
                    status=self.status,
                    timestamp=self.timestamp,
                    info=self.info))


class Poller(db.Model):
    """Poller describes the attributes of a mergebot poller for a project."""
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
    """QueuedItem stores info about a work item currently in the queue."""
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
