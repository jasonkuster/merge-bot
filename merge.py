"""Contains functions for creating and running mergers for various SCM systems.

The merger interacts with the underlying SCM to patch specific changes, verify
they work, and then submit.
"""
import abc
from multiprocessing import Queue
import os
from subprocess import check_call
import sys
import github_helper

APACHE_GIT = 'https://git-wip-us.apache.org/repos/asf/{repo}.git'
GITHUB_REPO_URL = 'https://github.com/{org}/{repo}.git'
TMP_DIR_FMT = '/tmp/{dir}'


def create_merger(config, work_queue):
    """create_merger creates a merger of the type specified in the config.

    Args:
        config: A dictionary containing repository configuration.
        work_queue: A Queue.Queue where new work items will be queued.
    Returns:
        Merger of type specified in configuration
    Raises:
        AttributeError: if passed an unsupported SCM type.
    """
    if config['scm_type'] == 'github':
        return GitMerger(config, work_queue)
    raise AttributeError('Unsupported SCM type: {}.'.format(config['scm_type']))


class Merger(object):
    """Merger is the base class for all mergers.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, config, work_queue):
        self.config = config
        if not isinstance(work_queue, Queue):
            raise AttributeError('Expected work_queue to be of type '
                                 'multiprocessing.Queue.')
        self.work_queue = work_queue

    @abc.abstractmethod
    def merge(self):
        """merge spins forever, merging things off of the work queue.
        """
        return


class GitMerger(Merger):
    """GitMerger merges Git pull requests.
    """

    def merge(self):
        """merge spins forever, merging things off of the work queue.

        Raises:
            AttributeError: if work items are not of type github_helper.GithubPR
        """
        while True:
            pr = self.work_queue.get()
            output_file = '{name}_pr_{pr_num}_merge_log.txt'.format(
                name=self.config['name'], pr_num=pr.get_num())
            with open(os.path.join('log', output_file), 'w') as log_file:
                sys.stdout = log_file
                if not isinstance(pr, github_helper.GithubPR.__class__):
                    raise AttributeError('Expected items in work_queue to be of'
                                         ' type github_helper.GithubPR')
                _print_flush('Starting merge process for #{}.'.format(
                    pr.get_num()))
                if self.merge_git_pr(pr):
                    _print_flush('Merge concluded satisfactorily. Moving on.')
                else:
                    _print_flush('Merge did not conclude satisfactorily. Adding'
                                 ' PR back to queue to be tried again.')
                    self.work_queue.put(pr)

    def merge_git_pr(self, pr):
        """merge_git_pr merges git pull requests.

        Args:
            pr: The GithubPR to merge.
        Returns:
            True if merge was concluded satisfactorily (merged successfully,
            or failed due to supposed fault of the PR itself).
            False if failure was due to an environmental issue and should be
            retried.
        """
        self.pr = pr
        repo = self.config['repository']
        self.tmp_dir = TMP_DIR_FMT.format(dir='{}-{}'.format(
            repo, pr.get_num()))
        try:
            _set_up(self.tmp_dir)
        except AssertionError:
            pr.post_error('Setup of initial directory failed, try again.')
            return False
        try:
            repo_url = GITHUB_REPO_URL.format(org='apache', repo=repo)
            self.run('git clone -b {branch} {repo}'.format(
                branch=self.config['merge_branch'], repo=repo_url), 'Clone',
                     'Clone failed. Please try again.')
            self.run('git remote add apache {apache_url}'.format(
                apache_url=APACHE_GIT.format(repo=repo)), 'Add Remote',
                     'Failed to add remote. Please try again.')
            self.run('git remote rename origin github', 'Rename Origin',
                     'Failed to rename origin. Please try again.')
            self.run('git config --local --add remote.github.fetch '
                     '"+refs/pull/*/head:refs/remotes/github/pr/*"',
                     'Configure git fetch.', 'Failed to configure git fetch. '
                                             'Please try again.', shell=True)
            self.run('git fetch --all', 'Fetch everything.',
                     'Fetch failed. Please try again.')
            pr_num = pr.get_num()
            pr_name = 'finish-pr-{}'.format(pr.get_num())
            self.run('git checkout -b {pr_name} github/pr/{pr_num}'.format(
                pr_name=pr_name, pr_num=pr_num),
                     'Checkout PR', 'Failed to check out PR. Please try again.')
            branch = '{}/{}'.format('apache', self.config['merge_branch'])
            self.run('git rebase {branch}'.format(branch=branch),
                     'Rebase against target branch.',
                     'Automatic rebase failed. Please manually rebase '
                     'against {branch} and try again.'.format(branch=branch))
            self.run('git checkout {branch}'.format(branch=branch),
                     'Check out target branch.',
                     'Failed to check out '
                     '{branch}. Please try again.'.format(branch=branch))
            merge_msg = 'This closes #{}'.format(pr.get_num())
            self.run('git merge --no-ff -m {msg} {pr_name}'.format(
                msg=merge_msg, pr_name=pr_name), 'Merge PR',
                     'Merge was not successful. Please try again.')
            self.run(self.config['verification_command'], 'Verifying PR',
                     'Verification failed. Please check the error log and try '
                     'again.')
            self.run('git push apache HEAD:{branch}'.format(
                branch=self.config['merge_branch']), 'Push to Apache master.',
                     'Apache push failed. Please try again.')
        except AssertionError as err:
            _print_flush(err)
        except EnvironmentError as err:
            _print_flush(err)
            return False
        try:
            pr.post_info('PR merge succeeded!')
        except EnvironmentError as err:
            _print_flush(err)
            _print_flush('Pull Request success post failed. Moving on.')
        return True

    def run(self, cmd, desc, error, shell=False):
        """Runs command.

        Args:
            cmd: Command to run.
            desc: Description of command.
            error: Error to post to github if command fails.
            shell: Whether to run the command in shell mode.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Starting: {}.'.format(desc))
        _print_flush('Running command: {}.'.format(cmd))
        try:
            check_call(cmd, cwd=self.tmp_dir, shell=shell)
        except:
            self.pr.post_error(error)
            raise AssertionError('Command "{}" failed.'.format(cmd))
        _print_flush('Finished: {}.'.format(desc))


def _set_up(tmp_dir):
    """set_up creates a temp directory for use.

    Args:
        tmp_dir: Directory to create.
    Raises:
        AssertionError: If command was not successful.
    """
    try:
        check_call(['mkdir', tmp_dir])
    except:
        raise AssertionError('Setup failed.')


def _clean_up(tmp_dir):
    """_clean_up removes a temp directory after use.

    Args:
        tmp_dir: Directory to remove.
    Raises:
        AssertionError: If command was not successful.
    """
    try:
        check_call(['rm', '-rf', tmp_dir])
    except:
        raise AssertionError('Cleanup failed.')


def _print_flush(msg):
    """_print_flush prints to stdout, then flushes immediately.

    Args:
        msg: the message to print.
    """
    print msg
    sys.stdout.flush()
