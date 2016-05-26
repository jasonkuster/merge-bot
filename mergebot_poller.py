"""
mergebot_poller is a utility which polls an SCM and follows commands.
"""

from github_helper import GithubHelper
import merge
import Queue
from threading import Thread
import time

# TODO(jasonkuster): Fetch authorized users from somewhere official.
AUTHORIZED_USERS = ["davorbonaci"]
BOT_NAME = 'merge-bot'
ORG = 'apache'


class MergebotPoller(object):
    """
    MergebotPoller is a class which handles the polling of a configured SCM.
    """

    SCM_POLLERS = {'github': poll_github}
    SCM_MERGERS = {'github': merge.merge_git}
    CMD_MERGE = {'github': merge_git}
    CMDS = {'merge': CMD_MERGE}

    def __init__(self, config):
        self.config = config
        # Instantiate the two variables used for tracking work.
        # Thread-safe because of the GIL.
        self.work_queue = Queue.Queue()
        self.known_work = set()
        # Set up a github helper for handling network requests, etc.
        self.github_helper = GithubHelper(ORG, self.config['repository'])

    def poll(self):
        """
        Kicks off polling of the SCM. Reads SCM type from config and starts the
        appropriate poller.

        :return: returns nothing
        """
        print('Starting merge poller for {}.'.format(self.config['name']))
        self.SCM_POLLERS[self.config['scm_type']]()

    def poll_github(self):
        """
        Polls Github for PRs, verifies they haven't already been worked on, and
        then searches them for merge-bot commands.

        :return: returns nothing
        """
        # Kick off an SCM merger
        merger_args = (self.work_queue, self.known_work, self.github_helper, )
        merger = Thread(target=self.SCM_MERGERS['github'], args=merger_args)
        merger.start()
        # Loop: Forever, every fifteen seconds.
        while True:
            # Load list of pull requests from Github
            prs = self.github_helper.fetch_prs()
            if prs is not None:
                # Loop: Each pull request
                for pull in prs:
                    if pull['number'] not in self.known_work:
                        self.search_github_pr(pull)
            else:
                print('Error fetching pull requests.')
            time.sleep(15)

    def search_github_pr(self, pull):
        """
        Searches a provided github PR for mergebot commands, validates, and runs
        said commands.

        :param pull: The pull request to validate
        :return: returns nothing
        """
        pr_num = pull['number']
        print('Looking at PR #{}.'.format(pr_num))
        # Load comments for each pull request
        cmts = self.github_helper.fetch_comments(pr_num)
        if len(cmts) < 1:
            print('No comments on PR #{}. Moving on.'.format(pr_num))
            return
        # FUTURE: Loop over comments to make sure PR has been approved by a
        # committer.
        cmt = cmts[-1]
        cmt_body = cmt['body'].encode('ascii', 'ignore')
        # Check auth.
        user = cmt['user']['login']
        if user not in AUTHORIZED_USERS:
            error = 'User {} not a committer; access denied.'.format(user)
            self.github_helper.post_error(error, pr_num)
            print('Unauthorized user {}'.format(user) +
                  ' attempted command {}, #{}.'.format(cmt_body, pr_num))
            return
        # Look for committer request comment.
        # FUTURE: Look for @merge-bot reply comments.
        # FUTURE: Use mentions API instead?
        if not cmt_body.startswith('@{}'.format(BOT_NAME)):
            print(
                'Last comment: {}, not a command. Moving on.'.format(cmt_body))
            return
        cmd_str = cmt_body.split('@{} '.format(BOT_NAME), 1)[1]
        cmd = cmd_str.split(' ')[0]
        if cmd not in self.CMDS.keys():
            # Post back to PR
            self.github_helper.post_error(
                'Command was {}, not a valid command.' +
                ' Valid commands: {}.'.format(cmd, self.CMDS.keys()), pr_num)
            print('Command was {}, not a valid command.'.format(cmd))
            return

        if 'github' not in self.CMDS[cmd]:
            error = 'Command was {}, not available for github.'.format(cmd)
            self.github_helper.post_error(error, pr_num)
            print(error)
            return

        self.CMDS[cmd]['github'](pull)

    def merge_git(self, pull):
        """
        Adds the pull request in question to the list of work, to be picked up
        by the concurrently-running merger.

        :param pull: The PR to merge
        :return: returns nothing
        """
        print('Command was merge, adding to merge queue.')
        self.work_queue.put(pull)
        self.known_work.add(pull['number'])

