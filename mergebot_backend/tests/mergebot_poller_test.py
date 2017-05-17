"""mergebot_poller_test contains unit tests for the mergebot_poller module."""

import unittest

from mock import MagicMock, call, patch

from mergebot_backend import mergebot_poller
from mergebot import MergeBotConfig


class GithubPollerTest(unittest.TestCase):

    def setUp(self):
        self.config = MergeBotConfig(
            name='test', github_org='test', repository='test',
            merge_branch='test', verification_branch='test', scm_type='github',
            jenkins_location='http://test.test', verification_job_name='test')

    @patch('mergebot_backend.github_helper.GithubHelper')
    @patch(
        'mergebot_backend.mergebot_poller.MergebotPoller.get_authorized_users')
    @patch('mergebot_backend.merge.create_merger')
    @patch('mergebot_backend.mergebot_poller.Pipe')
    @patch('mergebot_backend.mergebot_poller.Queue')
    @patch('mergebot_backend.mergebot_poller.get_logger')
    def create_poller_for_testing(self, mock_logger, mock_queue, mock_pipe,
                                  mock_create, mock_authorized, mock_helper):
        pipe = MagicMock()
        mock_pipe.return_value = (MagicMock(), MagicMock())
        mock_authorized.return_value = ['authorized']
        return mergebot_poller.GithubPoller(config=self.config, comm_pipe=pipe)

    @patch('mergebot_backend.mergebot_poller.GithubPoller')
    def testCreatePollerSuccess(self, mock_poller):
        # Tests creating a poller with a valid SCM type.
        mergebot_poller.create_poller(self.config, MagicMock())
        self.assertEqual(mock_poller.call_count, 1)

    @patch('mergebot.MergeBotConfig')
    def testCreatePollerFailure(self, mock_config):
        # Tests creating a poller with an invalid SCM type.
        with self.assertRaises(AttributeError) as context:
            mock_config.scm_type = 'unicorn'
            mergebot_poller.create_poller(mock_config, MagicMock())
        self.assertEqual('Unsupported SCM Type: unicorn.',
                         context.exception.message)

    @patch('mergebot_backend.db_publisher.publish_poller_heartbeat')
    @patch('mergebot_backend.db_publisher.publish_poller_status')
    def test_terminate(self, mock_status, mock_heartbeat):
        ghp = self.create_poller_for_testing()
        pipe = MagicMock()
        pipe.poll.side_effect = [False, True]
        ghp.comm_pipe = pipe
        ghp.github_helper.fetch_prs.return_value = ([MagicMock()], None)
        ghp.check_pr = lambda prs: None
        ghp.POLL_WAIT = 0.1
        ghp.comm_pipe.recv.return_value = 'terminate'
        ghp.poll()
        calls = [call('test', 'STARTED'), call('test', 'TERMINATING'),
                 call('test', 'SHUTDOWN')]
        mock_status.assert_has_calls(calls)
        self.assertEqual(mock_heartbeat.call_count, 1)

    @patch('mergebot_backend.github_helper.GithubPR')
    def testCheckValidPR(self, mock_pr):
        # Tests that a valid PR (unknown) is successfully searched and added
        # to the list of known work.
        ghp = self.create_poller_for_testing()
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 100
        ghp.search_github_pr = lambda pr: True
        ghp.check_pr(mock_pr)
        self.assertDictContainsSubset(ghp.known_work, (1, 100))
        self.assertEqual(ghp.known_work.get(1), 100)

    @patch('mergebot_backend.github_helper.GithubPR')
    def testCheckValidPRUpdated(self, mock_pr):
        # Tests that a valid PR (updated) is successfully searched and added
        # to the list of known work.
        ghp = self.create_poller_for_testing()
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 150
        ghp.known_work[1] = 100
        ghp.search_github_pr = lambda pr: True
        ghp.check_pr(mock_pr)
        self.assertEqual(ghp.known_work.get(1), 150)

    @patch('mergebot_backend.github_helper.GithubPR')
    def testCheckValidPRUnsuccessful(self, mock_pr):
        # Tests that a valid PR (updated) is successfully searched but not added
        # to the list of known work if search_github_pr fails.
        ghp = self.create_poller_for_testing()
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 200
        ghp.known_work[1] = 150
        ghp.search_github_pr = lambda pr: False
        ghp.check_pr(mock_pr)
        self.assertEqual(ghp.known_work.get(1), 150)

    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('mergebot_backend.mergebot_poller.GithubPoller.search_github_pr')
    def testCheckInvalidPR(self, mock_search_pr, mock_pr):
        # Tests that invalid PRs (known and stale) are not added to the list of
        #  known work.
        ghp = self.create_poller_for_testing()
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 100
        ghp.search_github_pr = mock_search_pr
        ghp.known_work[1] = 100
        ghp.check_pr(mock_pr)
        self.assertEqual(mock_search_pr.call_count, 0)

    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('mergebot_backend.mergebot_poller.GithubPoller.merge_git')
    def testSearchNoCommentsPR(self, mock_merge_git, mock_pr):
        # Tests that a PR with no comments is caught successfully.
        ghp = self.create_poller_for_testing()
        ghp.merge_git = mock_merge_git
        mock_pr.fetch_comments.return_value = []
        search = ghp.search_github_pr(mock_pr)
        self.assertTrue(search)
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('mergebot_backend.github_helper.GithubComment')
    @patch('mergebot_backend.mergebot_poller.GithubPoller.merge_git')
    def testSearchNoCommandPR(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that a PR with no commands is caught successfully.
        ghp = self.create_poller_for_testing()
        ghp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = 'not a command'
        mock_pr.fetch_comments.return_value = [mock_comment]
        search = ghp.search_github_pr(mock_pr)
        self.assertTrue(search)
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('mergebot_backend.github_helper.GithubComment')
    @patch('mergebot_backend.mergebot_poller.GithubPoller.merge_git')
    def testSearchUnauthorizedUser(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that a command by an unauthorized user is caught successfully.
        ghp = self.create_poller_for_testing()
        ghp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@apache-merge-bot command'
        mock_comment.get_user.return_value = 'unauthorized'
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = True
        search = ghp.search_github_pr(mock_pr)
        self.assertTrue(search)
        mock_pr.post_error.assert_called_with(content="User unauthorized not a "
                                              "committer; access denied.",
                                              logger=ghp.l)
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('mergebot_backend.github_helper.GithubComment')
    @patch('mergebot_backend.mergebot_poller.GithubPoller.merge_git')
    def testSearchInvalidCommand(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that an invalid comment on a valid PR is caught successfully.
        ghp = self.create_poller_for_testing()
        ghp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@apache-merge-bot command'
        mock_comment.get_user.return_value = 'authorized'
        mergebot_poller.AUTHORIZED_USERS = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = None
        search = ghp.search_github_pr(mock_pr)
        self.assertTrue(search)
        mock_pr.post_error.assert_called_with(content="Command was command, "
                                              "not a valid command. Valid "
                                              "commands: ['merge'].",
                                              logger=ghp.l)
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('mergebot_backend.github_helper.GithubPR')
    @patch('mergebot_backend.github_helper.GithubComment')
    @patch('mergebot_backend.mergebot_poller.GithubPoller.merge_git')
    def testSearchValidCommand(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that valid commands are successfully piped through.
        ghp = self.create_poller_for_testing()
        ghp.COMMANDS['merge'] = mock_merge_git
        mock_comment.get_body.return_value = '@apache-merge-bot merge'
        mock_comment.get_user.return_value = 'authorized'
        ghp.authorized_users = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        search = ghp.search_github_pr(mock_pr)
        self.assertTrue(search)
        self.assertEqual(mock_merge_git.call_count, 1)
