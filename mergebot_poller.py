"""mergebot_poller is a utility which polls an SCM and follows commands.

mergebot_poller defines a MergebotPoller class from which other classes can
inherit and a create_poller method which allows creation of SCM pollers.
"""


import logging
from multiprocessing import Process, Queue
import sys
import time
import github_helper
import merge

# TODO(jasonkuster): Fetch authorized users from somewhere official.
AUTHORIZED_USERS = ['davorbonaci', 'jasonkuster']
BOT_NAME = 'beam-testing'


def create_poller(config):
    """create_poller creates a poller of the type specified in the config.

    Args:
        config: A dictionary containing repository configuration.
    Returns:
        MergebotPoller of type specified in configuration
    Raises:
        AttributeError: if passed an unsupported SCM type.
    """
    if config['scm_type'] == 'github':
        return GithubPoller(config)
    raise AttributeError('Unsupported SCM Type: {}.'.format(config['scm_type']))


class MergebotPoller(object):
    """MergebotPoller is a base class for polling SCMs.
    """

    def __init__(self, config):
        self.config = config
        # Instantiate the two variables used for tracking work.
        # Thread-safe because of the GIL.
        self.work_queue = Queue()
        self.known_work = {}
        l = logging.getLogger('{name}_logger'.format(name=self.config['name']))
        self.l = l
        self.l.info('creating merger')
        self.merger = merge.create_merger(config, self.work_queue)
        self.l.info('merger created')

    def poll(self):
        """Poll should be implemented by subclasses as the main entry point.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError()


class GithubPoller(MergebotPoller):
    """GithubPoller polls Github repositories and merges them.
    """

    def __init__(self, config):
        super(GithubPoller, self).__init__(config)
        self.COMMANDS = {'merge': self.merge_git}
        self.l.info('in ghp init')
        # Set up a github helper for handling network requests, etc.
        self.github_helper = github_helper.GithubHelper(
            self.config['github_org'], self.config['repository'])
        self.l.info('starting githubpoller')

    def poll(self):
        """Kicks off polling of Github.
        """
        self.l.info('Starting poller for {}.'.format(self.config['name']))
        self.poll_github()

    def poll_github(self):
        """Polls Github for PRs, verifies, then searches them for commands.
        """
        # Kick off an SCM merger
        self.l.info('starting merge process')
        merge_process = Process(target=self.merger.merge)
        self.l.info('created')
        merge_process.start()
        self.l.info('started')
        # Loop: Forever, every fifteen seconds.
        while True:
            prs, err = self.github_helper.fetch_prs()
            if err is not None:
                self.l.error(
                    'Error fetching pull requests: {err}.'.format(err=err))
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
        if num not in self.known_work.keys() or pull.get_updated() != \
                self.known_work.get(num):
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
            self.l.info('Last comment not a command. Moving on.')
            return True
        # Check auth.
        user = cmt.get_user()
        if user not in AUTHORIZED_USERS:
            error = 'User {} not a committer; access denied.'.format(user)
            self.l.warning('Unauthorized user "{}"'.format(user) +
                           ' attempted command "{}".'.format(cmt_body))
            if not pull.post_error(error):
                self.l.error('Error posting PR comment.')
                return False
            return True
        cmd_str = cmt_body.split('@{} '.format(BOT_NAME), 1)[1]
        cmd = cmd_str.split(' ')[0]
        if cmd not in self.COMMANDS.keys():
            self.l.warning('Command was {}, not a valid command.'.format(cmd))
            # Post back to PR
            err = 'Command was {}, not a valid command. Valid commands: {}.'
            if not pull.post_error(err.format(cmd, self.COMMANDS.keys())):
                self.l.error('Error posting PR comment.')
                return False
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
        self.work_queue.put(pull)
        return True
