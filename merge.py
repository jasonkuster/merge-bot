"""Contains functions for creating and running mergers for various SCM systems.

The merger interacts with the underlying SCM to patch specific changes, verify
they work, and then submit.
"""
import time

import abc
import logging
import os
import shlex
from jenkinsapi.jenkins import Jenkins
from jenkinsapi.custom_exceptions import NotFound
from subprocess import check_call, check_output, STDOUT, CalledProcessError
from threading import Thread


TMP_DIR_FMT = '/tmp/{dir}'


class Command(object):
    def __init__(self, command, desc, error, shell=False):
        self.command = command
        self.desc = desc
        self.error = error
        self.shell = shell


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
        'Unsupported SCM type: {type}.'.format(type=config['scm_type']))


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

    # Commands to merge a Github PR.
    # Environment variables will be:
    #     'apache_url': URL for the Apache repository to push to.
    #     'branch': Branch to push to
    #     'verification_branch': Branch to use for verification.
    #     'branch_path': Full path to the branch
    #     'msg': Commit message
    #     'remote_name': What to call the remote
    #     'repo': Which Github repository to pull from
    #     'repo_url': The url of the Github repository
    #     'pr_name': Pull request name
    #     'pr_num': Pull request number
    PREPARE_CMDS = [
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
        Command('git checkout -b {pr_name} github/pr/{pr_num}',
                desc='Checkout PR',
                error='Failed to check out PR. Please try again.'),
        Command('git rebase {branch_path}',
                desc='Rebase against target branch.',
                error='Automatic rebase failed. Please rebase branch against'
                ' {branch_path} and try again.'),
        Command('git checkout {branch_path}', desc='Check out target branch.',
                error='Failed to check out {branch_path}. Please try again.'),
        Command('git merge --no-ff -m "{msg}" {pr_name}', desc='Merge PR',
                error='Merge was not successful. Please try again.'),
    ]

    VERIFICATION_CMDS = [
        Command('git push -f {remote_name} HEAD:{verification_branch}',
                desc='Force push to verification branch.',
                error='Couldn\'t complete force push to verification branch. '
                      'Please try again.')
    ]

    FINAL_CMDS = [
        Command('git push {remote_name} HEAD:{branch}',
                desc='Push to remote master.',
                error='Remote push failed. Please try again.'),
    ]

    APACHE_GIT = 'https://git-wip-us.apache.org/repos/asf/{repo}.git'
    GITHUB_REPO_URL = 'git:{org}/{repo}.git'

    JOB_START_TIMEOUT = 300
    WAIT_INTERVAL = 10

    def __init(self, config, work_queue):
        super.__init__(self, config, work_queue)
        branch = self.config['merge_branch']
        verification_branch = self.config['verification_branch']
        org = self.config['github_org']
        remote_name = 'apache'
        repo = self.config['repository']
        self.common_vars = {
            'apache_url': self.APACHE_GIT.format(repo=repo),
            'branch': branch,
            'branch_path': '{remote}/{branch}'.format(
                remote=remote_name, branch=branch),
            'remote_name': remote_name,
            'repo': repo,
            'repo_url': self.GITHUB_REPO_URL.format(org=org, repo=repo),
            'verification_branch': verification_branch,
        }

    def run(self):
        """run spins forever, merging things off of the work queue.

        Raises:
            AttributeError: if work items are not of type github_helper.GithubPR
        """
        while True:
            # TODO(jasonkuster) How do we confirm to the parent that this thread
            # is still alive? What happens if an exception tanks us?
            pr = self.work_queue.get()
            pr_num = pr.get_num()
            self.merge_logger.info(
                'Starting work on PR#{pr_num}.'.format(pr_num=pr_num))
            self.merge_logger.info('{remaining} work items remaining.'.format(
                remaining=self.work_queue.qsize()))
            pr.post_info(
                'MergeBot starting work on PR#{pr_num}.'.format(pr_num=pr_num),
                self.merge_logger)

            # Note on loggers: merge_logger is for merge-level events:
            # started work, finished work, etc. pr_logger is for pr-merging
            # lifecycle events: clone, merge, push, etc.
            pr_logger = self.get_logger(pr_num)
            pr_logger.info('Starting merge process for #{pr_num}.'.format(
                pr_num=pr_num))

            tmp_dir = TMP_DIR_FMT.format(dir='{repo}-{pr_num}'.format(
                repo=self.config['repository'],
                pr_num=pr_num))
            try:
                _set_up(tmp_dir)
                self.merge_git_pr(pr, tmp_dir, pr_logger)
                pr_logger.info('Merge concluded satisfactorily. Moving on.')
                self.merge_logger.info(
                    'PR#{num} processing done.'.format(num=pr_num))
            except AssertionError as exc:
                pr.post_error(exc, pr_logger)
            finally:
                _clean_up(tmp_dir)

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

    def merge_git_pr(self, pr, tmp_dir, pr_logger):
        """merge_git_pr merges git pull requests.

        Args:
            pr: The GithubPR to merge.
            tmp_dir: Directory in which to work.
            pr_logger: pr logger
        Raises:
            AssertionError if there was a problem with merging the PR.
        """
        pr_vars = self.common_vars.copy()
        pr_vars.update({
            'msg': 'This closes #{pr_num}'.format(pr_num=pr.get_num()),
            'pr_name': 'finish-pr-{pr_num}'.format(pr_num=pr.get_num()),
            'pr_num': pr.get_num(),
        })

        pr_logger.info('Beginning pre-verification phase.')
        self.run_cmds(self.PREPARE_CMDS, pr_vars, tmp_dir, pr, pr_logger)
        pr_logger.info("Successfully finished pre-verification phase.")

        pr_logger.info("Starting verification phase.")
        jenkins = Jenkins(self.config['jenkins_location'])
        job = jenkins[self.config['verification_job_name']]
        buildnum = job.get_next_build_number()
        self.run_cmds(self.VERIFICATION_CMDS, pr_vars, tmp_dir, pr, pr_logger)

        # We've pushed to the verification branch; Jenkins should pick up the
        # job soon.
        if not self.verify_pr_via_jenkins(job, buildnum, pr, pr_logger):
            pr_logger.info('Job verification failed, moving on.')
            raise AssertionError(
                'PR failed in verification; check the Jenkins job for more '
                'information.')
        pr_logger.info('Job verification succeeded.')

        pr_logger.info('Starting final push.')
        self.run_cmds(self.FINAL_CMDS, pr_vars, tmp_dir, pr, pr_logger)
        pr.post_info('PR merge succeeded!', pr_logger)
        pr_logger.info('Merge for {pr_num} completed successfully.'.format(
            pr_num=pr.get_num()))

    def verify_pr_via_jenkins(self, job, buildnum, pr, pr_logger):
        """Checks against the configured Jenkins job for verification.

        Args:
            job: jenkinsapi.job.Job this project uses for verification.
            buildnum: Build number of verification build.
            pr: github_helper.GithubPR corresponding to this pull request.
            pr_logger: Logger for this pull request.
        Raises:
            AssertionError if the job cannot be found.
        Returns:
            True if PR verification succeeded; false otherwise.
        """
        wait_secs = 0
        build = None
        while wait_secs < self.JOB_START_TIMEOUT:
            try:
                build = job.get_build(buildnum)
                break
            except NotFound:
                pr_logger.info("Waiting on job start, {wait} secs.".format(
                    wait=wait_secs))
            time.sleep(self.WAIT_INTERVAL)
            wait_secs += self.WAIT_INTERVAL

        # TODO(jasonkuster) Use some sort of url joiner for this?
        job_url = '{jenkins_loc}/job/{job_name}'.format(
            jenkins_loc=self.config['jenkins_location'],
            job_name=self.config['verification_job_name'])
        if not build:
            pr_logger.error('Timed out trying to find the verification job.')
            raise AssertionError(
                'Timed out trying to find verification job. Check Jenkins '
                '({url}) to ensure job is configured correctly.'.format(
                    url=job_url))

        pr_logger.info("Build #{build_num} found.".format(build_num=buildnum))
        build_url = '{job_url}/{build_num}'.format(
            job_url=job_url,
            build_num=buildnum)
        if build._get_git_rev() != pr.get_head_sha():
            error = ('Build at {build_url} did not match HEAD SHA we were '
                     'expecting. Expected: {expected}, actual {actual}.'.format(
                build_url=build_url,
                expected=pr.get_head_sha(),
                actual=build._get_git_rev()))
            pr_logger.error(error)
            raise AssertionError(error)

        text = ('Job verification started. Verification job is '
                '[here]({job_url}) (may still be pending; if page 404s, '
                'check job status page [here]({build_url})).'.format(
            job_url=job_url,
            build_url=build_url))
        pr.post_info(text, pr_logger)

        build.block_until_complete()

        # For some reason, the build does not have a status upon completion and
        # we have to fetch it again. A fairly extensive live debug failed to
        # find job status anywhere on the object.
        build = job.get_build(buildnum)
        if build.get_status() == "SUCCESS":
            return True
        return False

    def run_cmds(self, cmds, fmt_dict, tmp_dir, pr, pr_logger):
        """Runs a set of commands.

        Args:
            cmds: Iterable of Commands to run.
            fmt_dict: Dictionary of parameters with which to format the
                command and other strings.
            tmp_dir: Directory in which to run commands.
            pr: Pull request being merged.
            pr_logger: pr logger.
        Raises:
            AssertionError: If command was not successful.
        """
        for cmd in cmds:
            cmd_full = cmd.command.format(**fmt_dict)
            cmd_formatted = cmd_full if cmd.shell else shlex.split(cmd_full)
            pr_logger.info('Starting: {cmd_desc}.'.format(
                cmd_desc=cmd.desc.format(**fmt_dict)))
            pr_logger.info('Running command: {cmd}.'.format(cmd=cmd_formatted))
            try:
                out = check_output(cmd_formatted, cwd=tmp_dir,
                                   shell=cmd.shell, stderr=STDOUT)
                for line in out.split('\n'):
                    pr_logger.info(line)
            except CalledProcessError as exc:
                pr_logger.error(
                    'Command "{cmd}" failed: {err}.'.format(
                    cmd=cmd_formatted,
                    err=exc))
                for line in exc.output.split('\n'):
                    pr_logger.error(line)
                raise AssertionError(cmd.error.format(**fmt_dict))

            pr_logger.info('Finished: {cmd_desc}.'.format(
                cmd_desc=cmd.desc.format(**fmt_dict)))


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
        raise AssertionError('Creation of temporary directory failed.')


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
