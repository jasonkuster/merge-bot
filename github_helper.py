"""github_helper provides several methods to help interface with Github.
"""

import urlparse
import dateutil.parser
import requests
from requests.exceptions import HTTPError, Timeout, RequestException

GITHUB_API_ROOT = 'https://api.github.com'
GITHUB_REPO_FMT_URL = GITHUB_API_ROOT + '/repos/{0}/{1}/'
GITHUB_PULLS_ENDPOINT = 'pulls'

BOT_NAME = 'apache-merge-bot'
GITHUB_SECRET = '../../github_auth/mergebot.secret'


class GithubHelper(object):
    """GithubHelper is a lightweight authenticated wrapper for the Github API.
    """

    def __init__(self, org, repo):
        self.repo_url = GITHUB_REPO_FMT_URL.format(org, repo)
        with open(GITHUB_SECRET, 'r') as key_file:
            self.bot_key = key_file.read().strip()

    def fetch_prs(self):
        """Gets the PRs for the configured repository.

        Returns:
            A tuple of (pr_list, error).
            pr_list is an iterable of GithubPRs if successful, otherwise empty.
            error is None if successful, or the error message otherwise.
        """
        try:
            prs = self.get(GITHUB_PULLS_ENDPOINT)
            return [GithubPR(self, pr) for pr in prs], None
        except HTTPError as exc:
            return [], 'Non-200 HTTP Code Received: {}'.format(exc)
        except Timeout as exc:
            return [], 'Request timed out: {}'.format(exc)
        except RequestException as exc:
            return [], 'Catastrophic error in requests: {}'.format(exc)
        return [], 'Unreachable Error'

    def get(self, endpoint):
        """get makes a GET request against a specified endpoint.

        Args:
            endpoint: URL to which to make the GET request. URL is relative
            to https://api.github.com/repos/{self.org}/{self.repo}/
        Returns:
            JSON object retrieved from the endpoint.
        Raises:
            HTTPError: if we get an HTTP error status.
            Timeout: for timeouts.
            RequestException: for other assorted exceptional cases.
        """
        url = urlparse.urljoin(self.repo_url, endpoint)
        resp = requests.get(url, auth=(BOT_NAME, self.bot_key))
        if resp.status_code is 200:
            return resp.json()
        resp.raise_for_status()

    def post(self, content, endpoint):
        """post makes a POST request against a specified endpoint.

        Args:
            content: data to send in POST body.
            endpoint: URL to which to make the POST request. URL is relative
            to https://api.github.com/repos/{self.org}/{self.repo}/
        Returns:
            None if request returned successfully, error otherwise.
        """
        payload = '{{"body": "{}"}}'.format(content)
        url = urlparse.urljoin(self.repo_url, endpoint)
        try:
            resp = requests.post(url, data=payload, auth=(BOT_NAME,
                                                          self.bot_key))
            # Unlike above, any 2XX status code is valid here - comments,
            # for example, return 201 CREATED.
            if resp.status_code // 100 is 2:
                return None
            resp.raise_for_status()
        except HTTPError as exc:
            return 'Non-200 HTTP Code Received:'.format(exc)
        except Timeout as exc:
            return 'Request timed out: {}'.format(exc)
        except RequestException as exc:
            return 'Catastrophic error in requests: {}'.format(exc)
        return 'Unreachable Error'


class GithubPR(object):
    """GithubPR contains helper methods for interacting with pull requests.
    """

    def __init__(self, helper, pr_object):
        self.helper = helper
        self.pr_num = pr_object['number']
        self.head_sha = pr_object['head']['sha']
        self.comments_url = pr_object['comments_url']
        self.updated = dateutil.parser.parse(pr_object['updated_at'])

    def get_num(self):
        """Gets the pull request number.

        Returns:
            pull request number.
        """
        return self.pr_num

    def get_updated(self):
        """Gets datetime of when the pull request was last updated.

        Returns:
            last updated datetime.
        """
        return self.updated

    def fetch_comments(self):
        """Gets the comments for this pull request.

        Returns:
            An iterable containing instances of GithubComment if successful.
            Empty list otherwise.
        """
        comments = self.helper.get(self.comments_url)
        if comments is not None:
            return [GithubComment(cmt) for cmt in comments]
        return []

    def post_error(self, content):
        """Posts an error as a comment to Github.

        Args:
            content: the content to post.
        Raises:
            EnvironmentError: If post to Github failed.
        """
        self.post_pr_comment('Error: {}.'.format(content))

    def post_info(self, content):
        """Posts an info-level message as a comment to Github.

        Args:
            content: the content to post.
        Raises:
            EnvironmentError: If post to Github failed.
        """
        # TODO(jasonkuster) it seems reasonable to catch the error here instead?
        self.post_pr_comment('Info: {}.'.format(content))

    def post_pr_comment(self, content):
        """Posts a PR comment to Github.

        Args:
            content: the content to post.
        Raises:
            EnvironmentError: If post to Github failed.
        """
        err = self.helper.post(content, self.comments_url)
        if err is not None:
            # TODO(jasonkuster): Create a custom error to raise here.
            raise EnvironmentError(
                "Couldn't post to Github: {err}.".format(err=err))


class GithubComment(object):
    """GithubComment contains helper methods for interacting with comments.
    """

    def __init__(self, cmt_object):
        self.user = cmt_object['user']['login']
        self.cmt_body = cmt_object['body'].encode('ascii', 'ignore')

    def get_user(self):
        """Returns the user who posted the comment.

        Returns:
            username.
        """
        return self.user

    def get_body(self):
        """Returns the ascii-encoded body of the comment.

        Returns:
            comment body.
        """
        return self.cmt_body
