"""merge_test contains unit tests for the merge module."""

import unittest

from mock import MagicMock, patch
import jenkinsapi
import Queue

from mergebot_backend import merge
from mergebot import MergeBotConfig


class MergeTest(unittest.TestCase):

    def setUp(self):
        self.config = MergeBotConfig(
            name='test', proj_name='test', github_org='test', repository='test',
            merge_branch='test', verification_branch='test', scm_type='github',
            jenkins_location='http://test.test', prepare_command='test',
            verification_job_name='test')

    @patch('mergebot_backend.db_publisher.DBPublisher')
    @patch('mergebot_backend.merge.get_logger')
    def get_gitmerger_for_testing(self, mock_logger, mock_publisher):
        q = MagicMock()
        pipe = MagicMock()
        gm = merge.create_merger(config=self.config, work_queue=q, pipe=pipe)
        gm.WAIT_INTERVAL = 0.1
        gm.JOB_START_TIMEOUT = 0.1
        return gm

    @patch('mergebot_backend.github_helper.GithubPR')
    def test_fetch_terminate(self, mock_pr):
        gm = self.get_gitmerger_for_testing()
        gm.pipe.poll.return_value = True
        gm.pipe.recv.return_value = 'terminate'
        gm.work_queue.get_nowait.side_effect = [mock_pr, Queue.Empty]
        with self.assertRaises(merge.Terminate):
            gm.fetch_from_queue()
        self.assertEqual(gm.publisher.publish_merger_status.call_count, 1)
        self.assertEqual(gm.publisher.publish_dequeue.call_count, 1)

    @patch('mergebot_backend.github_helper.GithubPR')
    def test_fetch(self, mock_pr):
        gm = self.get_gitmerger_for_testing()
        gm.pipe.poll.return_value = False
        gm.work_queue.get.side_effect = Queue.Empty
        self.assertIsNone(gm.fetch_from_queue())
        self.assertEqual(gm.publisher.publish_dequeue.call_count, 0)
        q = MagicMock()
        q.get.return_value = mock_pr
        gm.work_queue = q
        self.assertEqual(gm.fetch_from_queue(), mock_pr)
        self.assertEqual(gm.publisher.publish_dequeue.call_count, 1)

    @patch('mergebot_backend.merge.GitMerger.execute_merge_lifecycle')
    @patch('mergebot_backend.merge._clean_up')
    @patch('mergebot_backend.merge._set_up')
    @patch('mergebot_backend.merge.get_logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    def test_merge_base_exception(self, mock_pr, mock_logger, mock_setup,
                                  mock_cleanup, mock_eml):
        gm = self.get_gitmerger_for_testing()
        mock_eml.side_effect = BaseException('Oh no')
        with self.assertRaises(BaseException) as context:
            gm.merge_git_pr(mock_pr)
        self.assertIn('Oh no', context.exception.message)
        self.assertEqual(mock_logger.call_count, 1)
        self.assertEqual(mock_setup.call_count, 1)
        self.assertEqual(mock_pr.post_error.call_count, 0)
        self.assertEqual(gm.publisher.publish_item_status.call_count, 0)
        self.assertEqual(mock_cleanup.call_count, 1)

    @patch('mergebot_backend.merge.GitMerger.execute_merge_lifecycle')
    @patch('mergebot_backend.merge._clean_up')
    @patch('mergebot_backend.merge._set_up')
    @patch('mergebot_backend.merge.get_logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    def test_merge_assertion_error(self, mock_pr, mock_logger, mock_setup,
                                   mock_cleanup, mock_eml):
        gm = self.get_gitmerger_for_testing()
        mock_eml.side_effect = AssertionError
        gm.merge_git_pr(mock_pr)
        self.assertEqual(mock_logger.call_count, 1)
        self.assertEqual(mock_setup.call_count, 1)
        self.assertEqual(mock_pr.post_error.call_count, 1)
        self.assertEqual(gm.publisher.publish_item_status.call_count, 1)
        self.assertEqual(mock_cleanup.call_count, 1)

    @patch('mergebot_backend.merge.GitMerger.execute_merge_lifecycle')
    @patch('mergebot_backend.merge._clean_up')
    @patch('mergebot_backend.merge._set_up')
    @patch('mergebot_backend.merge.get_logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    def test_merge_success(self, mock_pr, mock_logger, mock_setup,
                           mock_cleanup, mock_eml):
        gm = self.get_gitmerger_for_testing()
        gm.merge_git_pr(mock_pr)
        self.assertEqual(mock_eml.call_count, 1)
        self.assertEqual(mock_logger.call_count, 1)
        self.assertEqual(mock_setup.call_count, 1)
        self.assertEqual(mock_pr.post_error.call_count, 0)
        self.assertEqual(gm.publisher.publish_item_status.call_count, 0)
        self.assertEqual(mock_cleanup.call_count, 1)

    @patch('mergebot_backend.merge.GitMerger.verify_pr_via_jenkins')
    @patch('jenkinsapi.job.Job')
    @patch('mergebot_backend.merge.Jenkins')
    @patch('mergebot_backend.merge.run_cmds')
    @patch('logging.Logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    def test_execute_merge_lifecycle_validation_failed(
            self, mock_pr, mock_logger, mock_run_cmds, mock_jenkins,
            mock_job, mock_verify):
        gm = self.get_gitmerger_for_testing()
        mock_job.get_next_build_number.return_value = 5
        mock_jenkins.return_value = {'test': mock_job}
        mock_verify.return_value = False
        with self.assertRaises(AssertionError) as context:
            gm.execute_merge_lifecycle(mock_pr, '/tmp', mock_logger)
        self.assertIn('PR failed in verification', context.exception.message)
        self.assertEqual(gm.publisher.publish_item_status.call_count, 2)
        self.assertEqual(mock_run_cmds.call_count, 2)

    @patch('mergebot_backend.merge.GitMerger.verify_pr_via_jenkins')
    @patch('jenkinsapi.job.Job')
    @patch('mergebot_backend.merge.Jenkins')
    @patch('mergebot_backend.merge.run_cmds')
    @patch('logging.Logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    def test_execute_merge_lifecycle_validation_success(
            self, mock_pr, mock_logger, mock_run_cmds, mock_jenkins,
            mock_job, mock_verify):
        gm = self.get_gitmerger_for_testing()
        mock_job.get_next_build_number.return_value = 5
        mock_jenkins.return_value = {'test': mock_job}
        mock_verify.return_value = True
        gm.execute_merge_lifecycle(mock_pr, '/tmp', mock_logger)
        self.assertEqual(gm.publisher.publish_item_status.call_count, 4)
        self.assertEqual(mock_run_cmds.call_count, 4)

    @patch('logging.Logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('jenkinsapi.job.Job')
    def test_verify_jenkins_no_build(self, mock_job, mock_pr, mock_logger):
        gm = self.get_gitmerger_for_testing()
        mock_job.get_build.side_effect = jenkinsapi.custom_exceptions.NotFound
        with self.assertRaises(AssertionError) as context:
            gm.verify_pr_via_jenkins(mock_job, 0, mock_pr, mock_logger)
        self.assertIn('Timed out trying to find verification job.',
                      context.exception.message)
        self.assertEqual(gm.publisher.publish_item_status.call_count, 1)

    @patch('jenkinsapi.build.Build')
    @patch('logging.Logger')
    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('jenkinsapi.job.Job')
    def test_verify_jenkins_failure_success(
            self, mock_job, mock_pr, mock_logger, mock_build):
        gm = self.get_gitmerger_for_testing()
        mock_build.get_status.return_value = "FAILURE"
        mock_build.is_running.side_effect = [True, True, False]
        mock_job.get_build.return_value = mock_build
        self.assertFalse(gm.verify_pr_via_jenkins(mock_job, 0, mock_pr,
                                                  mock_logger))
        self.assertEqual(gm.publisher.publish_item_status.call_count, 3)
        self.assertEqual(gm.publisher.publish_item_heartbeat.call_count, 2)
        mock_build.get_status.return_value = "SUCCESS"
        mock_build.is_running.side_effect = [True, True, False]
        mock_job.get_build.return_value = mock_build
        self.assertTrue(gm.verify_pr_via_jenkins(mock_job, 0, mock_pr,
                                                 mock_logger))
        self.assertEqual(gm.publisher.publish_item_status.call_count, 6)
        self.assertEqual(gm.publisher.publish_item_heartbeat.call_count, 4)

