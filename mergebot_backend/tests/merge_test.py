import unittest
from multiprocessing import Queue

from mock import patch

from mergebot_backend import merge


class MergeTest(unittest.TestCase):

    def setUp(self):
        q = Queue()
        config = {'scm_type': 'github', 'name': 'test', 'merge_branch': 'test',
                  'github_org': 'test', 'repository': 'test',
                  'verification_command': 'go'}
        self.gm = merge.create_merger(config, q)
        self.logger = patch('logging.Logger')

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmds')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_success(self, mock_pr, mock_run, mock_logger):
        self.gm.run_cmds = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertTrue(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmds')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_cmd_failure(self, mock_pr, mock_run, mock_logger):
        mock_run.side_effect = AssertionError
        self.gm.run_cmds = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertTrue(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmds')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_post_failure(self, mock_pr, mock_run, mock_logger):
        mock_run.side_effect = EnvironmentError
        self.gm.run_cmds = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertFalse(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmds')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_unk_exception(self, mock_pr, mock_run, mock_logger):
        mock_run.side_effect = Exception
        self.gm.run_cmds = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertFalse(ret)
        self.assertEqual(mock_run.call_count, 1)
