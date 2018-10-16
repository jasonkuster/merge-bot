# merge-bot

MergeBot is a bot for automatically merging pull requests with a mainline
repository. It was written for the Apache Infrastructure team by Jason Kuster.

## Usage

Authorized committers can comment on a pull request `@asfgit merge`. MergeBot
polls repositories every fifteen seconds and upon seeing a request to merge will
queue it and begin the merge process.

## Implementation Info

MergeBot is written in Python and implemented in two parts: a frontend and a
backend. These two pieces share information via a SQLite database; the backend
writes info, and the frontend formats the information for viewing by users.

### Frontend

The frontend is written using the Flask Python web framework. It is laid out as
follows
*   `/`: Top-level view listing all of the currently-active mergebot pollers.
*   `/{poller-name}/`: Shows the active PR plus any queued PRs ready for merge.
*   `/{poller-name}/{item-id}/`: Shows MergeBot status updates for the work item
    in question.

The database is laid out as follows:

#### `Poller`

*   `project_name`: Project for which this poller is configured.
*   `status`: Status of this poller.
*   `timestamp`: Time at which we received the last poller heartbeat.
*   `merger_started`: Shows whether the merger is active.

#### `QueuedItem`

*   `project_name`: Project to which this item belongs.
*   `item_id`: Unique identifier for this work item.
*   `timestamp`: Time at which this item was added to the queue.

#### `WorkItemStatus`

*   `project_name`: Name of project which owns this work item.
*   `item_id`: Unique identifier for the work item in this project.
*   `timestamp`: Time at which this event occurred.
*   `status`: Status of the work item for this update.
*   `info`: String with more information about the status update.

### Backend

The backend is implemented via three complementary components.

#### `mergebot.py`

`mergebot.py` owns the overall mergebot process -- it is responsible for reading
in configs and spinning up subprocesses for each of the projects for which
MergeBot is configured.

#### `mergebot_poller.py`

`mergebot_poller.py` is in charge of polling an SCM for changes. Currently
GitHub is the only SCM available, but MergeBot has been designed to allow for
triggering from other SCM systems.

Currently the GitHub poller reads from GitHub every 15 seconds, looking for
either new PRs, or PRs which have been updated since the last time it checked.
When it notices a PR, it checks the PR for any of the commands available
(currently only `merge`) and that the comments have been made by an authorized
user. Once this is validated, it takes the appropriate step -- in the case of
`merge`, adding the PR to the merge queue.

#### `merge.py`

`merge.py` owns the process of actually merging a pull request. It reads the
merge queue from `mergebot_poller.py` and performs the merges in the order in
which they were received. Merges proceed in a few phases.

*   `SETUP`: The setup phase runs the appropriate Git commands to check out the
    PR and get it ready for verification.
*   `VERIFY`: The verify step pushes the changes under test to the `mergebot`
    branch on the project, at which point they are picked up by some CI system
    (currently Jenkins) for test. `merge.py` polls the CI system for the test
    results until results are available.
*   `PREPARE`: `merge.py` runs any commands necessary to prepare the PR for
    being merged with the mainline repository. For example, `beam-site`
    previously had MergeBot
    [generate the appropriate HTML from the markdown pages](https://github.com/jasonkuster/merge-bot/blob/90c0f45a09afb72d88e0a580ab3f071a7017d9b3/config/beam-site.yaml#L10)
    checked in as part of the PR.
*   `MERGE`: MergeBot pushes the changes to the upstream repository.

All of these phases are communicated via `WorkItemStatus` updates.
