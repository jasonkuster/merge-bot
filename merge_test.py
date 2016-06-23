import unittest
import github_helper
import merge
from mock import patch
from multiprocessing import Queue


class MergeTest(unittest.TestCase):

    def setUp(self):
        q = Queue()
        config = {'scm_type': 'github', 'name': 'test', 'merge_branch': 'test',
                  'github_org': 'test', 'repository': 'test',
                  'verification_command': 'go'}
        self.gm = merge.create_merger(config, q)
        self.logger = patch('logging.Logger')

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmd')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_success(self, mock_pr, mock_run, mock_logger):
        self.gm.run_cmd = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertTrue(ret)
        self.assertEqual(mock_run.call_count, 10)

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmd')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_cmd_failure(self, mock_pr, mock_run, mock_logger):
        mock_run.side_effect = AssertionError
        self.gm.run_cmd = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertTrue(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmd')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_post_failure(self, mock_pr, mock_run, mock_logger):
        mock_run.side_effect = EnvironmentError
        self.gm.run_cmd = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertFalse(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('logging.Logger')
    @patch('merge.GitMerger.run_cmd')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_unk_exception(self, mock_pr, mock_run, mock_logger):
        mock_run.side_effect = Exception
        self.gm.run_cmd = mock_run
        ret = self.gm.merge_git_pr(mock_pr, '/tmp', mock_logger)
        self.assertFalse(ret)
        self.assertEqual(mock_run.call_count, 1)
