"""merge contains classes which will merge work into SCM systems.
"""
import Queue
from subprocess import call
import sys
import github_helper

APACHE_URL = 'https://git-wip-us.apache.org/repos/asf/{}.git'
GITHUB_REPO_URL = 'https://github.com/{}/{}.git'
TMP_DIR_FMT = '/tmp/{}'


GITHUB_ORG = 'apache'
SOURCE_REMOTE = 'github'
TARGET_BRANCH = 'master'
TARGET_REMOTE = 'apache'


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

    def __init__(self, config, work_queue):
        self.config = config
        if not isinstance(work_queue, Queue.Queue):
            raise AttributeError('Expected work_queue to be of type '
                                 'Queue.Queue.')
        self.work_queue = work_queue

    def merge(self):
        """merge spins forever, merging things off of the work queue.
        """
        raise NotImplementedError('merge is required to be implemented.')


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
            if not isinstance(pr, github_helper.GithubPR.__class__):
                raise AttributeError('Expected items in work_queue to be of '
                                     'type github_helper.GithubPR')
            self.merge_git_pr(pr)

    def merge_git_pr(self, pr):
        """merge_git_pr merges git pull requests.

        Args:
            pr: The GithubPR to merge.
        Returns:
            True if merging was successful.
            False otherwise.
        """
        repo = self.config['repository']
        tmp_dir = TMP_DIR_FMT.format('{}-{}'.format(repo, pr.get_num()))
        if not set_up(tmp_dir):
            pr.post_error('Error setting up - please try again.')
            return False

        # Clone repository and configure.
        _print_flush('Starting merge process for #{}.'.format(pr))
        repo_url = GITHUB_REPO_URL.format(GITHUB_ORG, repo)
        clone_args = ['git', 'clone', '-b', TARGET_BRANCH, repo_url, tmp_dir]
        clone_success = call(clone_args, cwd=tmp_dir)
        if clone_success != 0:
            pr.post_error(
                'Couldn\'t clone from github/{}/{}. Please try again.'.format(
                    GITHUB_ORG, repo))
            return False

        call(['git', 'remote', 'add', TARGET_REMOTE, APACHE_URL.format(repo)],
             cwd=tmp_dir)
        call(['git', 'remote', 'rename', 'origin', SOURCE_REMOTE], cwd=tmp_dir)
        call('git config --local --add remote.' + SOURCE_REMOTE +
             '.fetch "+refs/pull/*/head:refs/remotes/{}/pr/*"'.format(
                 SOURCE_REMOTE), shell=True,
             cwd=tmp_dir)
        call(['git', 'fetch', '--all'], cwd=tmp_dir)
        _print_flush('Initial work complete.')

        # Clean up fetch
        pr_name = 'finish-pr-{}'.format(pr)
        ic_args = ['git', 'checkout', '-b', pr_name, 'github/pr/{}'.format(pr)]
        initial_checkout = call(ic_args, cwd=tmp_dir)
        if initial_checkout != 0:
            pr.post_error("Couldn't checkout code. Please try again.")
            return False
        _print_flush('Checked out.')

        # Rebase PR onto main.
        branch = '{}/{}'.format(TARGET_REMOTE, TARGET_BRANCH)
        rebase_args = ['git', 'rebase', branch]
        rebase_success = call(rebase_args, cwd=tmp_dir)
        if rebase_success != 0:
            _print_flush(rebase_success)
            pr.post_error('Rebase was not successful. Please rebase against '
                          'main and try again.')
            return False
        _print_flush('Rebased')

        # Check out target branch to here
        checkout_success = call(['git', 'checkout', branch], cwd=tmp_dir)
        if checkout_success != 0:
            pr.post_error(
                'Error checking out target branch: master. Please try again.')
            return False
        _print_flush('Checked out Apache master.')

        # Merge
        merge_msg = 'This closes #{}'.format(pr)
        merge_args = ['git', 'merge', '--no-ff', '-m', merge_msg, pr_name]
        merge_success = call(merge_args, cwd=tmp_dir)
        if merge_success != 0:
            pr.post_error(
                'Merge was not successful against target branch: master. '
                'Please try again.')
            return False
        _print_flush('Merged successfully.')

        _print_flush('Running mvn clean verify.')
        # mvn clean verify
        mvn_success = call(['mvn', 'clean', 'verify'], cwd=tmp_dir)
        if mvn_success != 0:
            pr.post_error(
                'verify against HEAD + PR#{} failed. Not merging.'.format(pr))
            return False

        # git push
        push_args = ['git', 'push', 'apache', 'HEAD:master']
        push_success = call(push_args, cwd=tmp_dir)
        if push_success != 0:
            pr.post_error('Git push failed. Please try again.')
            return False
        return True


def _set_up(tmp_dir):
    """set_up creates a temp directory for use.

    Args:
        tmp_dir: Directory to create.
    Returns:
        True if directory was created successfully.
        False otherwise.
    """
    if call(['mkdir', tmp_dir]) != 0:
        return False
    return True


def _clean_up(tmp_dir):
    """_clean_up removes a temp directory after use.

    Args:
        tmp_dir: Directory to remove.
    Returns:
        True if directory was removed successfully.
        False otherwise.
    """
    if call(['rm', '-rf', tmp_dir]) != 0:
        return False
    return True


def _print_flush(msg):
    """_print_flush prints to stdout, then flushes immediately.

    Args:
        msg: the message to print.
    """
    print msg
    sys.stdout.flush()
