"""github_helper provides several methods to help interface with Github.
"""

import sys
import urlparse
import dateutil.parser
import requests
from requests.exceptions import HTTPError, Timeout, RequestException

GITHUB_API_ROOT = 'https://api.github.com'
GITHUB_REPO_FMT_URL = GITHUB_API_ROOT + '/repos/{0}/{1}/'
GITHUB_PULLS_ENDPOINT = 'pulls'

BOT_NAME = 'merge-bot'
GITHUB_SECRET = '../../github_auth/mergebot.secret'


class GithubHelper(object):
    """GithubHelper is a lightweight authenticated wrapper for the Github API.
    """

    def __init__(self, org, repo):
        self.repo_url = GITHUB_REPO_FMT_URL.format(org, repo)
        with open(GITHUB_SECRET, 'r') as key_file:
            self.bot_key = key_file.read().strip()
        _print_flush('Loaded key file.')

    def fetch_prs(self):
        """Gets the PRs for the configured repository.

        Returns:
            An iterable containing instances of GithubPR if successful.
            Empty list otherwise.
        """
        try:
            prs = self.get(GITHUB_PULLS_ENDPOINT)
            return [GithubPR(self, pr) for pr in prs]
        except HTTPError as exc:
            _print_flush('Non-200 HTTP Code Received:')
            _print_flush(exc)
        except Timeout as exc:
            _print_flush('Request timed out:')
            _print_flush(exc)
        except RequestException as exc:
            _print_flush('Catastrophic error in requests:')
            _print_flush(exc)
        _print_flush('Retrieving pull requests failed.')
        return []


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
        _print_flush('Loading from Github at {}.'.format(url))
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
            True if request completed successfully.
            False otherwise.
        """
        payload = '{{"body": "{}"}}'.format(content)
        url = urlparse.urljoin(self.repo_url, endpoint)
        try:
            resp = requests.post(url, data=payload, auth=(BOT_NAME,
                                                          self.bot_key))
            # Unlike above, any 2XX status code is valid here - comments,
            # for example, return 201 CREATED.
            if resp.status_code // 100 is 2:
                return True
            resp.raise_for_status()
        except HTTPError as exc:
            _print_flush('Non-200 HTTP Code Received:')
            _print_flush(exc)
        except Timeout as exc:
            _print_flush('Request timed out:')
            _print_flush(exc)
        except RequestException as exc:
            _print_flush('Catastrophic error in requests:')
            _print_flush(exc)
        return False


class GithubPR(object):
    """GithubPR contains helper methods for interacting with pull requests.
    """

    def __init__(self, helper, pr_object):
        self.helper = helper
        self.pr_num = pr_object['number']
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
        Returns:
            True if request completed successfully.
            False otherwise.
        """
        return self.post_pr_comment('Error: {}.'.format(content))

    def post_info(self, content):
        """Posts an info-level message as a comment to Github.

        Args:
            content: the content to post.
        Returns:
            True if request completed successfully.
            False otherwise.
        """
        return self.post_pr_comment('Info: {}.'.format(content))

    def post_pr_comment(self, content):
        """Posts a PR comment to Github.

        Args:
            content: the content to post.
        Returns:
            True if request completed successfully.
            False otherwise.
        """
        return self.helper.post(content, self.comments_url)


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


def _print_flush(msg):
    """print_flush ensures stdout is flushed immediately upon printing.

    Args:
        msg: The message to print.
    """
    print msg
    sys.stdout.flush()
