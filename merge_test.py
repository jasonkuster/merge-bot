import unittest
import github_helper
import merge
from mock import patch
from multiprocessing import Queue

class MergeTest(unittest.TestCase):

    def setUp(self):
        q = Queue()
        config = {'scm_type':'github'}
        self.gm = merge.create_merger(config, q)

    @patch('merge.GitMerger.run')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_success(self, mock_pr, mock_run):
        self.gm.run = mock_run
        ret = self.gm.merge_git_pr(mock_pr)
        self.assertTrue(ret)
        self.assertEqual(mock_run.call_count, 11)

    @patch('merge.GitMerger.run')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_cmd_failure(self, mock_pr, mock_run):
        mock_run.side_effect = AssertionError
        self.gm.run = mock_run
        ret = self.gm.merge_git_pr(mock_pr)
        self.assertTrue(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('merge.GitMerger.run')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_post_failure(self, mock_pr, mock_run):
        mock_run.side_effect = EnvironmentError
        self.gm.run = mock_run
        ret = self.gm.merge_git_pr(mock_pr)
        self.assertFalse(ret)
        self.assertEqual(mock_run.call_count, 1)

    @patch('merge.GitMerger.run')
    @patch('github_helper.GithubPR')
    def test_merge_git_pr_unk_exception(self, mock_pr, mock_run):
        mock_run.side_effect = Exception
        self.gm.run = mock_run
        ret = self.gm.merge_git_pr(mock_pr)
        self.assertFalse(ret)
        self.assertEqual(mock_run.call_count, 1)
