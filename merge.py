"""Contains functions for creating and running mergers for various SCM systems.

The merger interacts with the underlying SCM to patch specific changes, verify
they work, and then submit.
"""


import abc
import logging
import os
import shlex
from subprocess import check_call, check_output, STDOUT
from threading import Thread


APACHE_GIT = 'https://git-wip-us.apache.org/repos/asf/{repo}.git'
GITHUB_REPO_URL = 'https://github.com/{org}/{repo}.git'
TMP_DIR_FMT = '/tmp/{dir}'


class Command(object):
    def __init__(self, command, desc, error, shell=False):
        self.command = command
        self.desc = desc
        self.error = error
        self.shell = shell


# Commands to merge a Github PR.
# Environment variables will be:
#     'apache_url': URL for the Apache repository to push to.
#     'branch': Branch to push to
#     'branch_path': Full path to the branch
#     'msg': Commit message
#     'remote_name': What to call the remote
#     'repo': Which Github repository to pull from
#     'repo_url': The url of the Github repository
#     'pr_name': Pull request name
#     'pr_num': Pull request number
#     'verification_cmd': Command to run to verify PR should be merged
GIT_CMDS = [
    Command('git clone -b {branch} {repo_url} .', desc='Clone',
            error='Clone failed. Please try again.'),
    Command('git remote add {remote_name} {apache_url}', desc='Add Remote',
            error='Failed to add remote. Please try again.'),
    Command('git remote rename origin github', 'Rename Origin',
            error='Failed to rename origin. Please try again.'),
    Command('git config --local --add remote.github.fetch '
            '"+refs/pull/*/head:refs/remotes/github/pr/*"',
            desc='Configure git fetch.',
            error='Failed to configure git fetch. Please try again.',
            shell=True),
    Command('git fetch --all', desc='Fetch everything.',
            error='Fetch failed. Please try again.'),
    Command('git checkout -b {pr_name} github/pr/{pr_num}', desc='Checkout PR',
            error='Failed to check out PR. Please try again.'),
    Command('git rebase {branch_path}', desc='Rebase against target branch.',
            error='Automatic rebase failed. Please manually rebase against'
            ' {branch_path} and try again.'),
    Command('git checkout {branch_path}', desc='Check out target branch.',
            error='Failed to check out {branch_path}. Please try again.'),
    Command('git merge --no-ff -m "{msg}" {pr_name}', desc='Merge PR',
            error='Merge was not successful. Please try again.'),
    Command('{verification_cmd}', desc='Verifying PR',
            error='Verification failed. Please check the error log and try '
               'again.'),
    # TODO(jasonkuster): Turn this on once we have guidance from Apache Infra.
    # Command('git push {remote_name} HEAD:{branch}',
    #         desc='Push to remote master.',
    #         error='Remote push failed. Please try again.'),
]

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
    raise AttributeError(
        'Unsupported SCM type: {}.'.format(config['scm_type']))


class Merger(Thread):
    """Merger is the base class for all mergers.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, config, work_queue):
        self.config = config
        l = logging.getLogger('{name}_merge_logger'.format(
            name=self.config['name']))
        log_fmt = '[%(levelname).1s-%(asctime)s %(filename)s:%(lineno)s] %(message)s'
        date_fmt = '%m/%d %H:%M:%S'
        f = logging.Formatter(log_fmt, date_fmt)
        filename = '{name}_merger_log.txt'.format(name=config['name'])
        h = logging.FileHandler(os.path.join('log', filename), mode='w')
        h.setFormatter(f)
        l.addHandler(h)
        l.setLevel(logging.INFO)
        self.merge_logger = l
        self.work_queue = work_queue
        Thread.__init__(self)

    @abc.abstractmethod
    def run(self):
        """run spins forever, merging things off of the work queue.
        """
        return


class GitMerger(Merger):
    """GitMerger merges Git pull requests.
    """

    def run(self):
        """run spins forever, merging things off of the work queue.

        Raises:
            AttributeError: if work items are not of type github_helper.GithubPR
        """
        while True:
            pr = self.work_queue.get()
            pr_num = pr.get_num()
            self.merge_logger.info(
                'Starting work on PR#{pr_num}.'.format(pr_num=pr_num))
            self.merge_logger.info('{remaining} work items remaining.'.format(
                remaining=self.work_queue.qsize()))

            # Note on loggers: merge_logger is for merge-level events:
            # started work, finished work, etc. pr_logger is for pr-merging
            # lifecycle events: clone, merge, push, etc.
            pr_logger = self.get_logger(pr_num)
            pr_logger.info('Starting merge process for #{}.'.format(pr_num))

            if self.merge_git_pr(pr, pr_logger):
                pr_logger.info('Merge concluded satisfactorily. Moving on.')
                self.merge_logger.info(
                    'PR#{num} processing done.'.format(num=pr_num))
            else:
                pr_logger.info('Merge did not conclude satisfactorily ('
                               'reporting to github failed). Adding PR back to'
                               ' queue to be tried again.')
                self.merge_logger.info(
                    'PR#{num} processing failed.'.format(num=pr_num))
                self.work_queue.put(pr)

    def get_logger(self, pr_num):
        """get_logger returns a logger for a particular PR.

        Args:
            pr_num: The pull request number.
        Returns:
            logger configured to output to an appropriate file.
        """
        # TODO(jasonkuster): In a future iteration refactor into its own class.
        output_file = '{name}_pr_{pr_num}_merge_log.txt'.format(
            name=self.config['name'], pr_num=pr_num)
        pr_logger = logging.getLogger('{name}_{num}_merge_logger'.format(
            name=self.config['name'], num=pr_num))
        if not pr_logger.handlers:
            log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            f = logging.Formatter(log_fmt)
            h = logging.FileHandler(os.path.join('log', output_file))
            h.setFormatter(f)
            pr_logger.addHandler(h)
            pr_logger.setLevel(logging.INFO)
        return pr_logger

    def merge_git_pr(self, pr, pr_logger):
        """merge_git_pr merges git pull requests.

        Args:
            pr: The GithubPR to merge.
            pr_logger: pr logger
        Returns:
            True if merge was concluded satisfactorily (merged successfully,
            or failed due to supposed fault of the PR itself).
            False if failure was due to an environmental issue and should be
            retried.
        """
        branch = self.config['merge_branch']
        org = self.config['github_org']
        remote_name = 'apache'
        repo = self.config['repository']
        pr_vars = {
            'apache_url': APACHE_GIT.format(repo=repo),
            'branch': branch,
            'branch_path': '{}/{}'.format(remote_name, branch),
            'msg': 'This closes #{}'.format(pr.get_num()),
            'remote_name': remote_name,
            'repo': repo,
            'repo_url': GITHUB_REPO_URL.format(org=org, repo=repo),
            'pr_name': 'finish-pr-{}'.format(pr.get_num()),
            'pr_num': pr.get_num(),
            'verification_cmd': self.config['verification_command']
        }
        try:
            self.run_cmds(GIT_CMDS, pr_vars, pr, pr_logger)
        except AssertionError as err:
            pr_logger.error(err)
            return True
        except EnvironmentError as err:
            pr_logger.error("Couldn't post comment to github. Leaving this PR "
                            "on the queue to try again.")
            pr_logger.error(err)
            return False
        except Exception as err:
            pr_logger.error(err)
            return False
        try:
            pr.post_info('PR merge succeeded!')
            pr_logger.info('Merge for {pr_num} completed successfully.'.format(
                pr_num=pr.get_num()))
        except EnvironmentError as err:
            info = 'Pull Request success post failed. Moving on. {}'.format(err)
            pr_logger.info(info)
        return True

    def run_cmds(self, cmds, fmt_dict, pr, pr_logger):
        """Runs command.

        Args:
            cmds: Iterable of Commands to run.
            fmt_dict: Dictionary of parameters with which to format the
            command and other strings.
            pr: Pull request being merged.
            pr_logger: pr logger.
        Raises:
            AssertionError: If command was not successful.
            EnvironmentError: If PR comment couldn't be posted to Github.
        """
        tmp_dir = TMP_DIR_FMT.format(dir='{}-{}'.format(
            self.config['repository'], pr.get_num()))
        try:
            _set_up(tmp_dir)
        except AssertionError:
            pr.post_error('Setup of temp directory failed, try again.')
            raise
        for cmd in cmds:
            cmd_full = cmd.command.format(**fmt_dict)
            cmd_formatted = cmd_full if cmd.shell else shlex.split(cmd_full)
            pr_logger.info('Starting: {}.'.format(cmd.desc.format(**fmt_dict)))
            pr_logger.info('Running command: {}.'.format(cmd_formatted))
            try:
                out = check_output(cmd_formatted, cwd=tmp_dir,
                                   shell=cmd.shell, stderr=STDOUT)
                for line in out.split('\n'):
                    pr_logger.info(line)
            except Exception as exc:
                pr_logger.error(exc)
                pr.post_error(cmd.error.format(**fmt_dict))
                _clean_up(tmp_dir)
                raise AssertionError('Command "{}" failed.'.format(
                    cmd_formatted))
            pr_logger.info('Finished: {}.'.format(cmd.desc.format(**fmt_dict)))
        _clean_up(tmp_dir)


def _set_up(tmp_dir):
    """set_up creates a temp directory for use.

    Args:
        tmp_dir: Directory to create.
    Raises:
        AssertionError: If command was not successful.
    """
    try:
        _clean_up(tmp_dir)
        check_call(['mkdir', tmp_dir])
    except:
        raise AssertionError('Setup failed.')


def _clean_up(tmp_dir):
    """_clean_up removes a temp directory after use.

    Args:
        tmp_dir: Directory to remove.
    Returns:
        error if cleanup fails, None otherwise.
    """
    try:
        check_call(['rm', '-rf', tmp_dir])
        return None
    except:
        return 'Cleanup failed.'
