"""Contains functions for creating and running mergers for various SCM systems.

The merger interacts with the underlying SCM to patch specific changes, verify
they work, and then submit.
"""
import abc
import os
import Queue
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
        if not isinstance(work_queue, Queue.Queue):
            raise AttributeError('Expected work_queue to be of type '
                                 'Queue.Queue.')
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
        sys.stdout = open(os.path.join('log', self.config['name'] +
                                       '_merger_log.txt'), 'w')
        while True:
            pr = self.work_queue.get()
            if not isinstance(pr, github_helper.GithubPR.__class__):
                raise AttributeError('Expected items in work_queue to be of '
                                     'type github_helper.GithubPR')
            _print_flush('Starting merge process for #{}.'.format(pr.get_num()))
            if self.merge_git_pr(pr):
                _print_flush('Merge concluded satisfactorily. Moving on.')
            else:
                _print_flush('Merge did not conclude satisfactorily. Adding '
                             'PR back to queue to be tried again.')
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
        repo = self.config['repository']
        tmp_dir = TMP_DIR_FMT.format(dir='{}-{}'.format(repo, pr.get_num()))
        try:
            _set_up(tmp_dir)
        except AssertionError:
            pr.post_error('Error setting up - trying again.')
            return False
        try:
            self.clone_configure(tmp_dir, pr)
            pr_name = 'finish-pr-{}'.format(pr.get_num())
            self.checkout(pr_name, tmp_dir, pr)
            branch = '{}/{}'.format('apache', self.config['merge_branch'])
            self.rebase(branch, tmp_dir, pr)
            self.target_checkout(branch, tmp_dir, pr)
            self.do_local_merge(pr_name, tmp_dir, pr)
            self.verify(tmp_dir, pr)
            self.push(tmp_dir, pr)
            _clean_up(tmp_dir)
            _print_flush('Merged successfully!')
        except AssertionError as err:
            _print_flush(err)
        except EnvironmentError as err:
            _print_flush(err)
            return False
        return True

    def clone_configure(self, tmp_dir, pr):
        """Clone repository and configure.

        Args:
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Cloning repository and configuring.')
        repo = self.config['repository']
        repo_url = GITHUB_REPO_URL.format(org='apache', repo=repo)
        clone_args = ['git', 'clone', '-b', self.config['merge_branch'],
                      repo_url, tmp_dir]
        try:
            check_call(clone_args, cwd=tmp_dir)
        except:
            pr.post_error(
                'Couldn\'t clone from github/{}/{}. Please try again.'.format(
                    'apache', repo))
            raise AssertionError('Clone Failed.')

        try:
            check_call(['git', 'remote', 'add', 'apache',
                        APACHE_GIT.format(repo=repo)], cwd=tmp_dir)
            check_call(['git', 'remote', 'rename', 'origin', 'github'],
                       cwd=tmp_dir)
            check_call('git config --local --add remote.github.fetch'
                       ' "+refs/pull/*/head:refs/remotes/github/pr/*"',
                       shell=True, cwd=tmp_dir)
            check_call(['git', 'fetch', '--all'], cwd=tmp_dir)
        except:
            pr.post_error('Problem configuring repository. Please try again.')
            raise AssertionError('Failed to set up.')
        _print_flush('Initial configuration complete.')

    def checkout(self, pr_name, tmp_dir, pr):
        """Check out PR from Github.

        Args:
            pr_name: Name of pull request branch.
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Checking out PR.')
        pr_num = pr.get_num()
        ic_args = ['git', 'checkout', '-b', pr_name, 'github/pr/{}'.format(
            pr_num)]
        try:
            check_call(ic_args, cwd=tmp_dir)
        except:
            pr.post_error("Couldn't checkout code. Please try again.")
            raise AssertionError('Failed to check out PR.')
        _print_flush('Checked out.')

    def rebase(self, branch, tmp_dir, pr):
        """Rebase PR onto main.

        Args:
            branch: Path to branch.
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Rebasing onto main.')
        rebase_args = ['git', 'rebase', branch]
        try:
            check_call(rebase_args, cwd=tmp_dir)
        except:
            pr.post_error('Automatic rebase was not successful. Please rebase '
                          'against main and try again.')
            raise AssertionError('Failed to rebase.')
        _print_flush('Rebased successfully.')

    def target_checkout(self, branch, tmp_dir, pr):
        """Check out target branch to here.

        Args:
            branch: Path to branch.
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Checking out target branch.')
        try:
            check_call(['git', 'checkout', branch], cwd=tmp_dir)
        except:
            pr.post_error(
                'Error checking out target branch: master. Please try again.')
            raise AssertionError('Failed to check out target branch.')
        _print_flush('Checked out target branch.')

    def do_local_merge(self, pr_name, tmp_dir, pr):
        """Merge the pull request locally.

        Args:
            pr_name: Name of pull request branch.
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Merging.')
        merge_msg = 'This closes #{}'.format(pr.get_num())
        merge_args = ['git', 'merge', '--no-ff', '-m', merge_msg, pr_name]
        try:
            check_call(merge_args, cwd=tmp_dir)
        except:
            pr.post_error(
                'Merge was not successful against target branch: master. '
                'Please try again.')
            raise AssertionError('Local merge failed.')
        _print_flush('Merged successfully.')

    def verify(self, tmp_dir, pr):
        """Runs the verify step.

        Args:
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Running verify step.')
        try:
            check_call(['mvn', 'clean', 'verify'], cwd=tmp_dir)
        except:
            pr.post_error(
                'verify against HEAD + PR#{} failed. Not merging.'.format(
                    pr.get_num()))
            raise AssertionError('Verify step failed.')
        _print_flush('Verified successfully.')

    def push(self, tmp_dir, pr):
        """Runs the push step.

        Args:
            tmp_dir: Directory in which commands should be run.
            pr: Pull request to merge.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        _print_flush('Pushing pull request.')
        push_args = ['git', 'push', 'apache', 'HEAD:{}'.format(
            self.config['merge_branch'])]
        try:
            check_call(push_args, cwd=tmp_dir)
        except:
            pr.post_error('Git push failed. Please try again.')
            raise AssertionError('Push failed.')
        try:
            pr.post_info('Pull request successfully merged.')
        except EnvironmentError as err:
            _print_flush("Merge was successful but we couldn't update "
                         "Github. Moving on since there's no better option.")
            _print_flush(err)
        _print_flush('Pull request pushed successfully.')


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
