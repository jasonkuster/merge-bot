import unittest
import mergebot_poller
from mock import patch


class GithubPollerTest(unittest.TestCase):

    def setUp(self):
        self.args = {'repository': 'asdf', 'scm_type': 'github'}

    @patch('mergebot_poller.GithubPoller')
    def testCreatePollerSuccess(self, mock_poller):
        # Tests creating a poller with a valid SCM type.
        mergebot_poller.create_poller(self.args)
        self.assertEqual(mock_poller.call_count, 1)

    def testCreatePollerFailure(self):
        # Tests creating a poller with an invalid SCM type.
        self.assertRaises(AttributeError, mergebot_poller.create_poller,
                          {'scm_type': 'unicorn'})

    @patch('github_helper.GithubPR')
    def testCheckValidPR(self, mock_pr):
        # Tests that a valid PR (unknown) is successfully searched and added
        # to the list of known work.
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 100
        gp = mergebot_poller.GithubPoller(self.args)
        gp.search_github_pr = lambda pr: True
        gp.check_pr(mock_pr)
        self.assertDictContainsSubset(gp.known_work, (1, 100))
        self.assertEqual(gp.known_work.get(1), 100)

    @patch('github_helper.GithubPR')
    def testCheckValidPRUpdated(self, mock_pr):
        # Tests that a valid PR (updated) is successfully searched and added
        # to the list of known work.
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 150
        gp = mergebot_poller.GithubPoller(self.args)
        gp.known_work[1] = 100
        gp.search_github_pr = lambda pr: True
        gp.check_pr(mock_pr)
        self.assertEqual(gp.known_work.get(1), 150)

    @patch('github_helper.GithubPR')
    def testCheckValidPRUnsuccessful(self, mock_pr):
        # Tests that a valid PR (updated) is successfully searched but not added
        # to the list of known work if search_github_pr fails.
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 200
        gp = mergebot_poller.GithubPoller(self.args)
        gp.known_work[1] = 150
        gp.search_github_pr = lambda pr: False
        gp.check_pr(mock_pr)
        self.assertEqual(gp.known_work.get(1), 150)

    @patch('github_helper.GithubPR')
    @patch('mergebot_poller.GithubPoller.search_github_pr')
    def testCheckInvalidPR(self, mock_search_pr, mock_pr):
        # Tests that invalid PRs (known and stale) are not added to the list of
        #  known work.
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 100
        gp = mergebot_poller.GithubPoller(self.args)
        gp.search_github_pr = mock_search_pr
        gp.known_work[1] = 100
        gp.check_pr(mock_pr)
        self.assertEqual(mock_search_pr.call_count, 0)

    @patch('github_helper.GithubPR')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchNoCommentsPR(self, mock_merge_git, mock_pr):
        # Tests that a PR with no comments is caught successfully.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_pr.fetch_comments.return_value = []
        search = gp.search_github_pr(mock_pr)
        self.assertTrue(search)
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchNoCommandPR(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that a PR with no commands is caught successfully.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = 'not a command'
        mock_pr.fetch_comments.return_value = [mock_comment]
        search = gp.search_github_pr(mock_pr)
        self.assertTrue(search)
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchUnauthorizedUser(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that a command by an unauthorized user is caught successfully.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot command'
        mock_comment.get_user.return_value = 'unauthorized'
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = True
        search = gp.search_github_pr(mock_pr)
        self.assertTrue(search)
        mock_pr.post_error.assert_called_with("User unauthorized not a "
                                              "committer; access denied.")
        self.assertEqual(mock_merge_git.call_count, 0)


    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchUnauthorizedUserPostFail(self, mock_merge_git, mock_comment,
                                    mock_pr):
        # Tests that a command by an unauthorized user is caught successfully,
        #  but if the post fails we still return false.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot command'
        mock_comment.get_user.return_value = 'unauthorized'
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = False
        search = gp.search_github_pr(mock_pr)
        self.assertFalse(search)
        mock_pr.post_error.assert_called_with("User unauthorized not a "
                                              "committer; access denied.")
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchInvalidCommand(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that an invalid comment on a valid PR is caught successfully.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot command'
        mock_comment.get_user.return_value = 'authorized'
        mergebot_poller.AUTHORIZED_USERS = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = True
        search = gp.search_github_pr(mock_pr)
        self.assertTrue(search)
        mock_pr.post_error.assert_called_with("Command was command, not a valid"
                                              " command. Valid commands:"
                                              " ['merge'].")
        self.assertEqual(mock_merge_git.call_count, 0)


    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchInvalidCommandPostFail(self, mock_merge_git, mock_comment,
                                    mock_pr):
        # Tests that an invalid comment on a valid PR is caught successfully,
        #  but if the post fails we still return false.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot command'
        mock_comment.get_user.return_value = 'authorized'
        mergebot_poller.AUTHORIZED_USERS = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = False
        search = gp.search_github_pr(mock_pr)
        self.assertFalse(search)
        mock_pr.post_error.assert_called_with("Command was command, not a valid"
                                              " command. Valid commands:"
                                              " ['merge'].")
        self.assertEqual(mock_merge_git.call_count, 0)

    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchValidCommand(self, mock_merge_git, mock_comment, mock_pr):
        # Tests that valid commands are successfully piped through.
        gp = mergebot_poller.GithubPoller(self.args)
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot merge'
        mock_comment.get_user.return_value = 'authorized'
        mergebot_poller.AUTHORIZED_USERS = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        search = gp.search_github_pr(mock_pr)
        self.assertTrue(search)
        self.assertEqual(mock_merge_git.call_count, 1)
