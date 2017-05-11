"""mergebot_poller is a utility which polls an SCM and follows commands.

mergebot_poller defines a MergebotPoller class from which other classes can
inherit and a create_poller method which allows creation of SCM pollers.
"""


from datetime import datetime
import logging
from multiprocessing import Pipe, Queue
import os
import time
import github_helper
import merge

# TODO(jasonkuster): Fetch authorized users from somewhere official.
AUTHORIZED_USERS = ['davorbonaci', 'jasonkuster']
BOT_NAME = 'apache-merge-bot'


def create_poller(config, comm_pipe):
    """create_poller creates a poller of the type specified in the config.

    Args:
        config: A dictionary containing repository configuration.
    Returns:
        MergebotPoller of type specified in configuration
    Raises:
        AttributeError: if passed an unsupported SCM type.
    """
    if config['scm_type'] == 'github':
        return GithubPoller(config, comm_pipe)
    raise AttributeError('Unsupported SCM Type: {}.'.format(config['scm_type']))


class MergebotPoller(object):
    """MergebotPoller is a base class for polling SCMs.
    """

    def __init__(self, config, comm_pipe):
        self.config = config
        self.comm_pipe = comm_pipe
        # Instantiate the two variables used for tracking work.
        self.work_queue = Queue()
        self.known_work = {}
        self.merger_pipe, child_pipe = Pipe()
        self.l = self.get_logger()
        self.merger = merge.create_merger(config, self.work_queue, child_pipe)

    def get_logger(self):
        l = logging.getLogger('{name}_logger'.format(name=self.config['name']))
        log_fmt = ('[%(levelname).1s-%(asctime)s %(filename)s:%(lineno)s] '
                   '%(message)s')
        date_fmt = '%m/%d %H:%M:%S'
        f = logging.Formatter(log_fmt, date_fmt)
        h = logging.FileHandler(
            os.path.join('log',
                         '{name}_log.txt'.format(name=self.config['name'])))
        h.setFormatter(f)
        l.addHandler(h)
        l.setLevel(logging.INFO)
        return l

    def publish_message(self, msg_type, content):
        """Publishes messages to the merger message bus.

        Args:
          msg_type: Type of message, should be a string.
          content: Content of message.
        """
        now = datetime.now()
        msg = {
            'name': self.config['name'],
            'module': 'mergebot_poller',
            'type': msg_type,
            'timestamp': now,
            'content': content,
        }
        self.comm_pipe.send(msg)

    def poll(self):
        """Poll should be implemented by subclasses as the main entry point.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError()


class GithubPoller(MergebotPoller):
    """GithubPoller polls Github repositories and merges them.
    """

    def __init__(self, config, comm_pipe):
        super(GithubPoller, self).__init__(config, comm_pipe)
        self.COMMANDS = {'merge': self.merge_git}
        # Set up a github helper for handling network requests, etc.
        self.github_helper = github_helper.GithubHelper(
            self.config['github_org'], self.config['repository'])

    def poll(self):
        """Kicks off polling of Github.
        """
        self.l.info('Starting poller for {}.'.format(self.config['name']))
        self.publish_message('STATUS', 'STARTUP')
        self.poll_github()

    def poll_github(self):
        """Polls Github for PRs, verifies, then searches them for commands.
        """
        self.merger.start()
        # Loop: Forever, every fifteen seconds.
        while True:
            if self.comm_pipe.poll():
                t = self.comm_pipe.recv()
                if t == 'terminate':
                    self.merger_pipe.send('terminate')
                    self.publish_message('STATUS', 'TERMINATING')
                    self.merger.join()
                    self.publish_message('STATUS', 'SHUTDOWN')
                    return
            self.publish_message('HEARTBEAT', '')
            self.l.info('Polling Github for PRs')
            prs, err = self.github_helper.fetch_prs()
            if err is not None:
                self.l.error('Error fetching PRs: {err}.'.format(err=err))
                continue
            for pull in prs:
                self.check_pr(pull)
            time.sleep(15)

    def check_pr(self, pull):
        """Determines if a pull request should be evaluated.

        Args:
            pull: A GithubPR object.
        """
        num = pull.get_num()
        pr_unknown = num not in self.known_work.keys()
        if pr_unknown or pull.get_updated() != self.known_work.get(num):
            self.l.info('<PR #{}>'.format(num))
            if self.search_github_pr(pull):
                self.known_work[num] = pull.get_updated()
            self.l.info('</PR #{}>'.format(num))

    def search_github_pr(self, pull):
        """Searches a PR for mergebot commands, validates, and runs commands.

        Args:
            pull: A GithubPR object.
        Returns:
            True if pull request has been successfully handled.
            False otherwise.
        """
        # Load comments for each pull request
        comments = pull.fetch_comments()
        if not comments:
            self.l.info('No comments. Moving on.')
            return True
        # FUTURE: Loop over comments to make sure PR has been approved by a
        # committer before a committer requests a merge.
        cmt = comments[-1]
        cmt_body = cmt.get_body()
        # Look for committer request comment.
        # FUTURE: Look for @merge-bot reply comments.
        # FUTURE: Use mentions API instead?
        if not cmt_body.startswith('@{}'.format(BOT_NAME)):
            self.l.info('Last comment not a command. Moving on. Comment: ')
            self.l.info(cmt_body)
            return True
        # Check auth.
        user = cmt.get_user()
        if user not in AUTHORIZED_USERS:
            log_error = 'Unauthorized user "{user}" attempted command "{com}".'
            pr_error = 'User {user} not a committer; access denied.'
            self.l.warning(log_error.format(user=user, com=cmt_body))
            pull.post_error(pr_error.format(user=user), self.l)
            return True
        cmd_str = cmt_body.split('@{} '.format(BOT_NAME), 1)[1]
        cmd = cmd_str.split(' ')[0]
        if cmd not in self.COMMANDS.keys():
            self.l.warning('Command was {}, not a valid command.'.format(cmd))
            # Post back to PR
            error = 'Command was {}, not a valid command. Valid commands: {}.'
            pull.post_error(error.format(cmd, self.COMMANDS.keys()), self.l)
            return True
        return self.COMMANDS[cmd](pull)

    def merge_git(self, pull):
        """Adds pull request to the list of work.

        merge_git adds the pull request to the list of work, where it will be
        picked up by the concurrently-running merger.

        Args:
            pull: A GithubPR object.
        Returns:
            True when successfully added. Return value is just to fulfill
            contract with search_github_pr since other commands could fail.
        """
        self.l.info('Command was merge, adding to merge queue.')
        pull.post_info('Adding PR to work queue; current position: '
                       '{pos}.'.format(pos=self.work_queue.qsize() + 1), self.l)
        self.publish_message('ENQUEUE', str(pull.get_num()))
        self.work_queue.put(pull)
        return True
