"""test_github_helper defines a set of unit tests for github_helper."""

import unittest

import requests
from mock import mock_open, patch, PropertyMock

from mergebot_backend import github_helper


class TestGithubHelper(unittest.TestCase):

    def setUp(self):
        m = mock_open()
        with patch('mergebot_backend.github_helper.open', m, create=True):
            self.mocked_helper = github_helper.GithubHelper('none', 'none')

    @patch('mergebot_backend.github_helper.requests.get')
    @patch('mergebot_backend.github_helper.requests')
    def testGetValidResponse(self, mock_req, mock_req_get):
        # Tests that Get returns correctly
        mock_req.get.return_value = mock_req_get
        type(mock_req_get).status_code = PropertyMock(return_value=200)
        mock_req_get.json.return_value = 'return'
        self.assertEqual(self.mocked_helper.get('asdf'), 'return')

    @patch('mergebot_backend.github_helper.GithubHelper.get')
    @patch('mergebot_backend.github_helper.GithubPR')
    def testFetchPRsEmptyResponse(self, mock_pr, mock_get):
        # Tests that an empty response returns correctly.
        mock_get.return_value = []
        self.mocked_helper.get = mock_get
        res, err = self.mocked_helper.fetch_prs()
        self.assertEqual(res, [])
        self.assertIsNone(err)

    @patch('mergebot_backend.github_helper.GithubHelper.get')
    @patch('mergebot_backend.github_helper.GithubPR')
    def testFetchPRsHTTPError(self, mock_pr, mock_get):
        # Tests that HTTPErrors are caught correctly.
        mock_get.side_effect = requests.exceptions.HTTPError
        self.mocked_helper.get = mock_get
        res, err = self.mocked_helper.fetch_prs()
        self.assertEqual(res, [])
        self.assertIsNotNone(err)

    @patch('mergebot_backend.github_helper.GithubHelper.get')
    @patch('mergebot_backend.github_helper.GithubPR')
    def testFetchPRsTimeout(self, mock_pr, mock_get):
        # Tests that timeouts are caught correctly.
        mock_get.side_effect = requests.exceptions.Timeout
        self.mocked_helper.get = mock_get
        res, err = self.mocked_helper.fetch_prs()
        self.assertEqual(res, [])
        self.assertIsNotNone(err)

    @patch('mergebot_backend.github_helper.GithubHelper.get')
    @patch('mergebot_backend.github_helper.GithubPR')
    def testFetchPRsRequestException(self, mock_pr, mock_get):
        # Tests that RequestExceptions are caught correctly.
        mock_get.side_effect = requests.exceptions.RequestException
        self.mocked_helper.get = mock_get
        res, err = self.mocked_helper.fetch_prs()
        self.assertEqual(res, [])
        self.assertIsNotNone(err)

    @patch('mergebot_backend.github_helper.requests.post')
    @patch('mergebot_backend.github_helper.requests')
    def testPostValidResponse(self, mock_req, mock_req_post):
        # Tests that a valid POST works.
        mock_req.post.return_value = mock_req_post
        type(mock_req_post).status_code = PropertyMock(return_value=200)
        self.assertIsNone(self.mocked_helper.post('asdf', 'ghjkl'))

    @patch('mergebot_backend.github_helper.requests.post')
    @patch('mergebot_backend.github_helper.requests')
    def testPostHTTPError(self, mock_req, mock_req_post):
        # Tests that post successfully catches HTTPError.
        mock_req.get.return_value = mock_req_post
        type(mock_req_post).status_code = PropertyMock(return_value=400)
        mock_req.raise_for_status.side_effect = requests.exceptions.HTTPError
        self.assertIsNotNone(self.mocked_helper.post('asdf', 'ghjkl'))

    @patch('mergebot_backend.github_helper.requests.post')
    @patch('mergebot_backend.github_helper.requests')
    def testPostTimeout(self, mock_req, mock_req_post):
        # Tests that post successfully catches Timeout.
        mock_req.get.return_value = mock_req_post
        type(mock_req_post).status_code = PropertyMock(return_value=400)
        mock_req.post.side_effect = requests.exceptions.Timeout
        self.assertIsNotNone(self.mocked_helper.post('asdf', 'ghjkl'))

    @patch('mergebot_backend.github_helper.requests.post')
    @patch('mergebot_backend.github_helper.requests')
    def testPostRequestException(self, mock_req, mock_req_post):
        # Tests that post successfully catches RequestException.
        mock_req.get.return_value = mock_req_post
        type(mock_req_post).status_code = PropertyMock(return_value=400)
        mock_req.post.side_effect = requests.exceptions.RequestException
        self.assertIsNotNone(self.mocked_helper.post('asdf', 'ghjkl'))
