from mergebot_frontend import app
from flask import abort, render_template, send_from_directory
from mergebot_frontend.models import Poller, QueuedItem, WorkItemStatus


@app.route("/")
def index():
    """Root handler for website; serves list of pollers.
    
    Returns:
        Index template with the list of active pollers.
    """
    pollers = Poller.query.order_by(Poller.project_name).all()
    return render_template('index.html', pollers=pollers)


@app.route('/<proj>')
def project(proj):
    """Handler for project page; shows the currently active and pending merges.
    
    Args:
        proj: Name of the project to show.

    Returns:
        Project template with the currently active and pending merges.
    """
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


@app.route('/<proj>/<int:item_id>')
def item(proj, item_id):
    """Item page handler, shows all work item updates for a work item.
    
    Args:
        proj: Project under which this work item lives.
        item_id: Unique identifier for this work item. For a pull request, PR #.

    Returns:
        Item template formatted with poller and item status updates.
    """
    poller = Poller.query.filter_by(
        project_name=proj).first_or_404()
    item_statuses = WorkItemStatus.query.filter_by(
        project_name=proj,
        item_id=item_id,
    ).order_by(WorkItemStatus.timestamp).all()
    if not item_statuses:
        abort(404)
    return render_template('item.html',
                           poller=poller,
                           item_statuses=item_statuses)


# TODO(jasonkuster): How can we serve the actual directory?
@app.route("/log/<path:path>")
def send_log(path):
    """send_log allows for viewing mergebot logs from the frontend.
    
    Args:
        path: name of the log file to send.

    Returns:
        Raw log sent from the directory.
    """
    return send_from_directory('log', path)

