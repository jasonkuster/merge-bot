import unittest
from mock import patch
import mergebot_poller

class MergebotPollerTest(unittest.TestCase):
    @patch('mergebot_poller.GithubPoller')
    def testCreatePollerSuccess(self, mockPoller):
        mergebot_poller.create_poller({'scm_type': 'github'})
        assert mockPoller.call_count == 1

    def testCreatePollerFailure(self):
        self.assertRaises(AttributeError, mergebot_poller.create_poller,
                          {'scm_type': 'unicorn'})

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    def testCheckValidPR(self, mock_pr, mock_helper):
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 100
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.search_github_pr = lambda pr: True
        gp.check_pr(mock_pr)
        assert 1 in gp.known_work.keys()
        assert gp.known_work.get(1) == 100
        mock_pr.get_updated.return_value = 150
        gp.check_pr(mock_pr)
        assert gp.known_work.get(1) == 150
        mock_pr.get_updated.return_value = 200
        gp.search_github_pr = lambda pr: False
        gp.check_pr(mock_pr)
        assert gp.known_work.get(1) == 150

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    @patch('mergebot_poller.GithubPoller.search_github_pr')
    def testCheckInvalidPR(self, mock_search_pr, mock_pr, mock_helper):
        mock_pr.get_num.return_value = 1
        mock_pr.get_updated.return_value = 100
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.search_github_pr = mock_search_pr
        gp.known_work[1] = 100
        gp.check_pr(mock_pr)
        assert mock_search_pr.call_count == 0

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchNoCommentsPR(self, mock_merge_git, mock_pr, mock_helper):
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.merge_git = mock_merge_git
        mock_pr.fetch_comments.return_value = []
        assert gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 0

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchNoCommandPR(self, mock_merge_git, mock_comment, mock_pr,
                                                           mock_helper):
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = 'not a command'
        mock_pr.fetch_comments.return_value = [mock_comment]
        assert gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 0

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchUnauthorizedUser(self, mock_merge_git, mock_comment, mock_pr,
                                                           mock_helper):
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot command'
        mock_comment.get_user.return_value = 'unauthorized'
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = True
        assert gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 0
        mock_pr.post_error.return_value = False
        assert not gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 0

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchInvalidCommand(self, mock_merge_git, mock_comment, mock_pr,
                                                           mock_helper):
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot command'
        mock_comment.get_user.return_value = 'authorized'
        mergebot_poller.AUTHORIZED_USERS = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        mock_pr.post_error.return_value = True
        assert gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 0
        mock_pr.post_error.return_value = False
        assert not gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 0

    @patch('github_helper.GithubHelper')
    @patch('github_helper.GithubPR')
    @patch('github_helper.GithubComment')
    @patch('mergebot_poller.GithubPoller.merge_git')
    def testSearchValidCommand(self, mock_merge_git, mock_comment, mock_pr,
                                                           mock_helper):
        gp = mergebot_poller.GithubPoller({'repository': 'asdf'})
        gp.merge_git = mock_merge_git
        mock_comment.get_body.return_value = '@merge-bot merge'
        mock_comment.get_user.return_value = 'authorized'
        mergebot_poller.AUTHORIZED_USERS = ['authorized']
        mock_pr.fetch_comments.return_value = [mock_comment]
        assert gp.search_github_pr(mock_pr)
        assert mock_merge_git.call_count == 1
