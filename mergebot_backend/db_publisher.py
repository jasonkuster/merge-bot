"""db_publisher handles talking to the frontend database."""

from datetime import datetime

from mergebot_frontend import db
from mergebot_frontend.models import Poller, QueuedItem, WorkItemStatus


class DBPublisher(object):
    """DBPublisher sets up an instance of a publisher for the backend."""

    def __init__(self, name):
        """Initializes DBPublisher
        
        Args:
            name: Name of the project this component belongs to.
        """
        self.name = name
        db.engine.dispose()
        db.create_scoped_session()

    def publish_poller_status(self, status):
        """publish_poller_status updates the status for a particular poller.
        
        Args:
            status: Status to publish for this poller.
        """
        poller = Poller.query.filter_by(project_name=self.name).first()
        if status == 'STARTED':
            if not poller:
                poller = Poller(self.name, datetime.now())
                db.session.add(poller)
            poller.status = 'STARTED'
            poller.timestamp = datetime.now()
        elif status == 'TERMINATING':
            if not poller:
                raise ValueError(
                    'Cannot set status for nonexistent poller {poller}.'.format(
                        poller=self.name))
            poller.status = 'TERMINATING'
            poller.timestamp = datetime.now()
        elif status == 'SHUTDOWN':
            if not poller:
                raise ValueError(
                    'Cannot set status for nonexistent poller {poller}.'.format(
                        poller=self.name))
            poller.status = 'SHUTDOWN'
            poller.timestamp = datetime.now()
        else:
            raise ValueError(
                'Poller has no such status: {status}.'.format(status=status))

        db.session.commit()

    def publish_merger_status(self, status):
        """publish_merger_status updates the status for a particular merger.
        
        Args:
            status: Status to publish for this merger.
        """
        poller = Poller.query.filter_by(
            project_name=self.name).first()
        poller.timestamp = datetime.now()
        if status == 'STARTED':
            poller.merger_started = True
        elif status == 'SHUTDOWN':
            poller.merger_started = False
        else:
            raise ValueError(
                'Merger has no such status: {status}.'.format(status=status))
        db.session.commit()

    def publish_enqueue(self, item_id):
        """publish_enqueue informs the frontend that an item has been enqueued.
        
        Args:
            item_id: ID of the item.
        """
        item = QueuedItem(
            project_name=self.name,
            item_id=item_id,
            timestamp=datetime.now())
        db.session.add(item)
        db.session.commit()

    def publish_dequeue(self, item_id):
        """publish_enqueue informs the frontend that an item has been dequeued.
        
        Args:
            item_id: ID of the item.
        """
        item = QueuedItem.query.filter_by(
            project_name=self.name,
            item_id=item_id).first()
        db.session.delete(item)
        db.session.commit()

    def publish_poller_heartbeat(self):
        """publish_poller_heartbeat updates the last-seen time of a poller."""
        poller = Poller.query.filter_by(project_name=self.name).first()
        poller.timestamp = datetime.now()
        db.session.commit()

    def publish_item_status(self, item_id, status):
        """publish_item_status handles work item updates.
        
        Args:
            item_id: Unique work item identifier (e.g. PR number).
            status: Item status to update.
        """
        # TODO(jasonkuster): enum of item status?
        item_status = WorkItemStatus(
            project_name=self.name,
            item_id=item_id,
            timestamp=datetime.now(),
            status=status)
        db.session.add(item_status)
        db.session.commit()

    def publish_item_heartbeat(self, item_id):
        """publish_item_heartbeat bumps the timestamp on the JOB_WAIT status.
        
        Args:
            item_id: Unique work item identifier (e.g. PR number).
        Raises:
            KeyError if the corresponding job_wait cannot be found.
        """
        item_status = WorkItemStatus.query.order_by(
            WorkItemStatus.timestamp).filter_by(project_name=self.name,
                                                item_id=item_id,
                                                status='JOB_WAIT').first()
        if not item_status:
            raise KeyError('JOB_WAIT not found.')
        item_status.timestamp = datetime.now()
        db.session.commit()
