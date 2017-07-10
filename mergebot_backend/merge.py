"""Contains functions for creating and running mergers for various SCM systems.

The merger interacts with the underlying SCM to patch specific changes, verify
they work, and then submit.
"""
import time

import abc
import shlex
import urlparse

from jenkinsapi.jenkins import Jenkins
from jenkinsapi.custom_exceptions import NotFound
from Queue import Empty
from subprocess import check_call, check_output, STDOUT, CalledProcessError
from threading import Thread

from mergebot_backend import db_publisher
from mergebot_backend import github_helper
from mergebot_backend.log_helper import get_logger

TMP_DIR_FMT = '/tmp/{dir}'
JENKINS_TIMEOUT_ERR = ('Timed out trying to find verification job. Check '
                       'Jenkins ({url}) to ensure job is configured correctly.')
JENKINS_STARTED_MSG = ('Job verification started. Verification job is [here]'
                       '({build_url}) (may still be pending; if page 404s, '
                       'check job status page [here]({job_url})).')
MERGEBOT_ITEM_URL = 'http://mergebot-vm.apache.org/{name}/{number}'


class Terminate(Exception):
    """Terminate is a custom exception for when we want to end."""
    pass


class Command(object):
    """Command defines the attributes necessary to run a merge command."""
    def __init__(self, command, desc, error, shell=False):
        self.command = command
        self.desc = desc
        self.error = error
        self.shell = shell


def create_merger(config, work_queue, pipe):
    """create_merger creates a merger of the type specified in the config.

    Args:
        config: A dictionary containing repository configuration.
        work_queue: A Queue.Queue where new work items will be queued.
        pipe: Pipe to use to communicate termination request.
    Returns:
        Merger of type specified in configuration
    Raises:
        AttributeError: if passed an unsupported SCM type.
    """
    if config.scm_type == 'github':
        return GitMerger(config, work_queue, pipe)
    raise AttributeError(
        'Unsupported SCM type: {type}.'.format(type=config.scm_type))


class Merger(Thread):
    """Merger is the base class for all mergers.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, config, work_queue, pipe):
        self.config = config
        self.merge_logger = get_logger(
            '{name}_merge'.format(name=self.config.name), redirect_to_file=True)
        self.work_queue = work_queue
        self.pipe = pipe
        self.publisher = db_publisher.DBPublisher(name=self.config.name)
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
    SETUP_CMDS = [
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

    PREPARE_CMDS = []

    FINAL_CMDS = [
        Command('git push {remote_name} HEAD:{branch}',
                desc='Push to remote master.',
                error='Final push failed, but verification succeeded. This may '
                      'have occurred because of a manual merge into the repo. '
                      'Please check logs and try again.'),
    ]

    APACHE_GIT = 'https://gitbox.apache.org/repos/asf/{repo}.git'
    GITHUB_REPO_URL = 'https://github.com/{org}/{repo}.git'

    JOB_START_TIMEOUT = 300
    WAIT_INTERVAL = 10

    def __init__(self, config, work_queue, pipe):
        super(GitMerger, self).__init__(config, work_queue, pipe)
        remote_name = 'apache'
        if self.config.prepare_command:
            self.PREPARE_CMDS.append(
                Command(self.config.prepare_command,
                        desc='Custom preparation command: %s'.format(
                            self.config.prepare_command),
                        error='Custom preparation command failed. Check logs '
                              'for more information.'))
            self.PREPARE_CMDS.append(
                Command('git diff --quiet && git diff --staged --quiet || '
                        'git commit -am "Prepare repository for deployment."',
                        desc='Add files created by repository preparation.',
                        error='Adding files from repository preparation failed.'
                              ' Please try again.',
                        shell=True))
        self.common_vars = {
            'apache_url': self.APACHE_GIT.format(repo=self.config.repository),
            'branch': self.config.merge_branch,
            'branch_path': '{remote}/{branch}'.format(
                remote=remote_name, branch=self.config.merge_branch),
            'remote_name': remote_name,
            'repo': self.config.repository,
            'repo_url': self.GITHUB_REPO_URL.format(
                org=self.config.github_org, repo=self.config.repository),
            'verification_branch': self.config.verification_branch,
        }

    def run(self):
        """run spins forever, merging things off of the work queue.

        Raises:
            AttributeError: if work items are not of type github_helper.GithubPR
        """
        self.publisher.publish_merger_status(status='STARTED')
        while True:
            pr = None
            while not pr:
                try:
                    pr = self.fetch_from_queue()
                except Terminate:
                    return
                time.sleep(1)

            if not isinstance(pr, github_helper.GithubPR):
                raise AttributeError

            pr_num = pr.get_num()
            self.merge_logger.info(
                'Starting work on PR#{pr_num}.'.format(pr_num=pr_num))
            self.merge_logger.info('{remaining} work items remaining.'.format(
                remaining=self.work_queue.qsize()))
            self.publisher.publish_item_status(
                item_id=pr_num, status='START',
                info="Requested by {user} at {time}.".format(
                    user=pr.metadata['asf_id'], time=pr.metadata['created']))
            try:
                pr.post_commit_status(
                    state=github_helper.COMMIT_STATE_PENDING,
                    url=MERGEBOT_ITEM_URL.format(
                        name=self.config.name, number=pr_num),
                    description='Started Work',
                    context='MergeBot: Merge',
                    logger=self.merge_logger)
                self.merge_git_pr(pr)
            except BaseException as exc:
                pr.post_commit_status(
                    state=github_helper.COMMIT_STATE_ERROR,
                    url=MERGEBOT_ITEM_URL.format(
                        name=self.config.name, number=pr_num),
                    description='Unexpected Error: {exc}.'.format(exc=exc),
                    context='MergeBot: Merge',
                    logger=self.merge_logger)
                # In the case of failure, we still post back to the pull request
                # because otherwise if mergebot is stopped and restarted we will
                # try this pull request again. If mergebot is modified to work
                # with webhooks this can be removed.
                pr.post_error(
                    'MergeBot encountered an unexpected error while processing '
                    'this PR: {exc}.'.format(exc=exc), self.merge_logger)
                self.publisher.publish_item_status(
                    item_id=pr_num, status='ERROR',
                    info='Exception: {exc}'.format(exc=exc))
                self.merge_logger.error('Unexpected exception while merging '
                                        'PR: {exc}.'.format(exc=exc))
            finally:
                self.merge_logger.info(
                    'PR#{num} processing done.'.format(num=pr_num))
                self.publisher.publish_item_status(item_id=pr_num,
                                                   status='FINISH')

    def fetch_from_queue(self):
        """fetch_from_queue tries to pull a PR off of the queue.
        
        Raises:
            merge.Terminate if we receive the termination signal.
        Returns:
            github_helper.GithubPR off the queue, or None if there were none.
        """
        terminate = False
        if self.pipe.poll():
            msg = self.pipe.recv()
            if msg == 'terminate':
                terminate = True
                self.merge_logger.info('Caught termination signal.')
        try:
            if terminate:
                while True:
                    self.flush_queue()
            else:
                pr = self.work_queue.get(timeout=5)
                self.publisher.publish_dequeue(item_id=pr.get_num())
                return pr
        except Empty:
            self.merge_logger.info('Queue was empty.')
        except BaseException as exc:
            self.merge_logger.error(
                "Unhandled exception: {exc}".format(exc=exc))
        if terminate:
            self.publisher.publish_merger_status(status='SHUTDOWN')
            raise Terminate
        return None

    def flush_queue(self):
        """flush_queue posts a shutdown message to a PR in the queue.
        
        Raises:
            Queue.Empty if there is nothing in the queue.
        """
        pr = self.work_queue.get_nowait()
        self.publisher.publish_dequeue(item_id=pr.get_num())
        pr.post_commit_status(
            state=github_helper.COMMIT_STATE_ERROR,
            url=MERGEBOT_ITEM_URL.format(
                name=self.config.name, number=pr.get_num()),
            description='MergeBot shutdown; resubmit when mergebot is back up.',
            context='MergeBot: Merge',
            logger=self.merge_logger)
        # In the case of shutdown, we still post back to the pull request
        # because otherwise if mergebot is stopped and restarted we will try
        # this pull request again. If mergebot is modified to work with webhooks
        #  this can be removed.
        pr.post_info('MergeBot shutting down; please resubmit when MergeBot is '
                     'back up.', self.merge_logger)

    def merge_git_pr(self, pr):
        """merge_git_pr takes care of the overall merge process for a PR.

        Args:
            pr: An instance of github_helper.GithubPR to merge.
        """
        # Note on loggers: merge_logger is for merge-level events:
        # started work, finished work, etc. pr_logger is for pr-merging
        # lifecycle events: clone, merge, push, etc.
        pr_num = pr.get_num()
        name = self.config.name
        pr_logger = get_logger(
            name='{name}_pr_{pr_num}_merge'.format(name=name, pr_num=pr_num),
            redirect_to_file=True)
        pr_logger.info(
            'Starting merge process for #{pr_num}.'.format(pr_num=pr_num))

        tmp_dir = None
        try:
            tmp_dir = TMP_DIR_FMT.format(
                dir='{repo}-{pr_num}'.format(
                    repo=self.config.repository,
                    pr_num=pr_num))
            _set_up(tmp_dir)
            self.execute_merge_lifecycle(pr, tmp_dir, pr_logger)
        except AssertionError as exc:
            pr.post_commit_status(
                state=github_helper.COMMIT_STATE_FAILURE,
                url=MERGEBOT_ITEM_URL.format(
                    name=self.config.name, number=pr.get_num()),
                description=exc.message,
                context='MergeBot: Merge',
                logger=self.merge_logger)
            # In the case of failure, we still post back to the pull request
            # because otherwise if mergebot is stopped and restarted we will
            # try this pull request again. If mergebot is modified to work with
            # webhooks this can be removed.
            pr.post_error(exc, pr_logger)
            self.publisher.publish_item_status(
                item_id=pr_num, status='ERROR',
                info='Exception: {exc}'.format(exc=exc))
        finally:
            _clean_up(tmp_dir)

    def execute_merge_lifecycle(self, pr, tmp_dir, pr_logger):
        """execute_merge_lifecycle merges git pull requests.

        Args:
            pr: The GithubPR to merge.
            tmp_dir: Directory in which to work.
            pr_logger: pr logger
        Raises:
            AssertionError if there was a problem with merging the PR.
        """
        pr_num = pr.get_num()
        pr_vars = self.common_vars.copy()
        pr_vars.update({
            'msg': 'This closes #{pr_num}'.format(pr_num=pr_num),
            'pr_name': 'finish-pr-{pr_num}'.format(pr_num=pr_num),
            'pr_num': pr_num,
        })

        pr_logger.info('Beginning pre-verification phase.')
        self.publisher.publish_item_status(item_id=pr_num, status='SETUP')
        run_cmds(self.SETUP_CMDS, pr_vars, tmp_dir, pr_logger)
        pr_logger.info("Successfully finished pre-verification phase.")

        pr_logger.info("Starting verification phase.")
        self.publisher.publish_item_status(item_id=pr_num, status='VERIFY')
        jenkins = Jenkins(self.config.jenkins_location)
        job = jenkins[self.config.verification_job_name]
        build_num = job.get_next_build_number()
        run_cmds(self.VERIFICATION_CMDS, pr_vars, tmp_dir, pr_logger)

        # We've pushed to the verification branch; Jenkins should pick up the
        # job soon.
        if not self.verify_pr_via_jenkins(job, build_num, pr, pr_logger):
            pr_logger.info('Job verification failed, moving on.')
            raise AssertionError(
                'PR failed in verification; check the Jenkins job for more '
                'information.')
        pr_logger.info('Job verification succeeded.')

        pr_logger.info('Starting final commands.')
        if self.PREPARE_CMDS:
            self.publisher.publish_item_status(item_id=pr_num, status='PREPARE')
            run_cmds(self.PREPARE_CMDS, pr_vars, tmp_dir, pr_logger)
        self.publisher.publish_item_status(item_id=pr_num, status='MERGE')
        # Success commit status needs to be posted before actual success because
        # we lose the ability to update a commit status after the PR is closed.
        # If FINAL_CMDS are not successful, we'll update the commit status with
        # an error as part of the exception handling process, so the user won't
        # see success turn into failure.
        pr.post_commit_status(
            state=github_helper.COMMIT_STATE_SUCCESS,
            url=MERGEBOT_ITEM_URL.format(
                name=self.config.name, number=pr_num),
            description='Merge Succeeded!',
            context='MergeBot: Merge',
            logger=self.merge_logger)
        run_cmds(self.FINAL_CMDS, pr_vars, tmp_dir, pr_logger)
        pr_logger.info(
            'Merge for {pr_num} completed successfully.'.format(pr_num=pr_num))

    def verify_pr_via_jenkins(self, job, build_num, pr, pr_logger):
        """Checks against the configured Jenkins job for verification.

        Args:
            job: jenkinsapi.job.Job this project uses for verification.
            build_num: Build number of verification build.
            pr: github_helper.GithubPR corresponding to this pull request.
            pr_logger: Logger for this pull request.
        Raises:
            AssertionError if the job cannot be found.
        Returns:
            True if PR verification succeeded; false otherwise.
        """
        wait_secs = 0
        build = None
        pr_num = pr.get_num()
        self.publisher.publish_item_status(item_id=pr_num,
                                           status='WAIT_ON_JOB_START')
        job_url = urlparse.urljoin(
            self.config.jenkins_location, '/job/{job_name}/'.format(
                job_name=self.config.verification_job_name))
        pr.post_commit_status(
            state=github_helper.COMMIT_STATE_PENDING,
            url=job_url,
            description='Starting verification job.',
            context='MergeBot: Verification Job',
            logger=self.merge_logger)
        while not build and wait_secs < self.JOB_START_TIMEOUT:
            try:
                build = job.get_build(build_num)
            except NotFound:
                pr_logger.info(
                    "Waiting on job start, {wait} secs.".format(wait=wait_secs))
                time.sleep(self.WAIT_INTERVAL)
                wait_secs += self.WAIT_INTERVAL

        if not build:
            pr_logger.error('Timed out trying to find the verification job.')
            pr.post_commit_status(
                state=github_helper.COMMIT_STATE_ERROR,
                url=job_url,
                description='Timed out waiting for job start.',
                context='MergeBot: Verification Job',
                logger=self.merge_logger)
            raise AssertionError(JENKINS_TIMEOUT_ERR.format(url=job_url))

        pr_logger.info("Build #{build_num} found.".format(build_num=build_num))
        build_url = urlparse.urljoin(job_url, str(build_num))

        pr.post_commit_status(
            state=github_helper.COMMIT_STATE_PENDING,
            url=build_url,
            description='Verification job running.',
            context='MergeBot: Verification Job',
            logger=self.merge_logger)
        self.publisher.publish_item_status(
            item_id=pr_num, status='JOB_FOUND',
            info='Build URL: {build_url}'.format(build_url=build_url))
        self.publisher.publish_item_status(item_id=pr_num, status='JOB_WAIT')

        while build.is_running():
            try:
                self.publisher.publish_item_heartbeat(item_id=pr_num)
            except KeyError:
                pr_logger.error("Couldn't find JOB_WAIT to update -- ending.")
                raise AssertionError("Internal Error: Couldn't find JOB_WAIT "
                                     "to update.")
            time.sleep(self.WAIT_INTERVAL)

        # For some reason, the build does not have a status upon completion and
        # we have to fetch it again. A fairly extensive live debug failed to
        # find job status anywhere on the object.
        build = job.get_build(build_num)
        if build.get_status() == "SUCCESS":
            pr.post_commit_status(
                state=github_helper.COMMIT_STATE_SUCCESS,
                url=build_url,
                description='Verification job succeeded!',
                context='MergeBot: Verification Job',
                logger=self.merge_logger)
            return True
        pr.post_commit_status(
            state=github_helper.COMMIT_STATE_FAILURE,
            url=build_url,
            description='Verification job failed.',
            context='MergeBot: Verification Job',
            logger=self.merge_logger)
        return False


def run_cmds(cmds, fmt_dict, tmp_dir, logger):
    """Runs a set of commands.

    Args:
        cmds: Iterable of Commands to run.
        fmt_dict: Dictionary of parameters with which to format the
            command and other strings.
        tmp_dir: Directory in which to run commands.
        logger: pr logger.
    Raises:
        AssertionError: If command was not successful.
    """
    for cmd in cmds:
        cmd_full = cmd.command.format(**fmt_dict)
        cmd_formatted = cmd_full if cmd.shell else shlex.split(cmd_full)
        logger.info('Starting: {cmd_desc}.'.format(
            cmd_desc=cmd.desc.format(**fmt_dict)))
        logger.info('Running command: {cmd}.'.format(cmd=cmd_formatted))
        try:
            out = check_output(cmd_formatted, cwd=tmp_dir,
                               shell=cmd.shell, stderr=STDOUT)
            for line in out.split('\n'):
                logger.info(line)
        except CalledProcessError as exc:
            logger.error(
                'Command "{cmd}" failed: {err}.'.format(
                    cmd=cmd_formatted,
                    err=exc))
            for line in exc.output.split('\n'):
                logger.error(line)
            raise AssertionError(cmd.error.format(**fmt_dict))

        logger.info('Finished: {cmd_desc}.'.format(
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
    except BaseException as exc:
        return 'Cleanup failed: {exc}.'.format(exc=exc)
