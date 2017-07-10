"""github_helper provides several methods to help interface with Github.
"""

import urlparse
import dateutil.parser
import requests
from requests.exceptions import HTTPError, Timeout, RequestException

GITHUB_API_ROOT = 'https://api.github.com'
GITHUB_REPO_FMT_URL = GITHUB_API_ROOT + '/repos/{0}/{1}/'
GITHUB_PULLS_ENDPOINT = 'pulls'

BOT_NAME = 'asfgit'
GITHUB_SECRET = 'mergebot.secret'

COMMENT_PAYLOAD = '{{"body": "{body}"}}'
COMMIT_STATUS_PAYLOAD = """
{{
  "state": "{state}",
  "target_url": "{url}",
  "description": "{description}",
  "context": "{context}"
}}
"""
COMMIT_STATE_PENDING = 'pending'
COMMIT_STATE_SUCCESS = 'success'
COMMIT_STATE_ERROR = 'error'
COMMIT_STATE_FAILURE = 'failure'


class GithubHelper(object):
    """GithubHelper is a lightweight authenticated wrapper for the Github API.
    """

    def __init__(self, org, repo):
        self.repo_url = GITHUB_REPO_FMT_URL.format(org, repo)
        with open(GITHUB_SECRET) as key_file:
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

    def post(self, payload, endpoint):
        """post makes a POST request against a specified endpoint.

        Args:
            payload: data to send in POST body.
            endpoint: URL to which to make the POST request. URL is relative
            to https://api.github.com/repos/{self.org}/{self.repo}/
        Returns:
            None if request returned successfully, error otherwise.
        """
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
        self.statuses_url = pr_object['statuses_url']
        self.comments_url = pr_object['comments_url']
        self.updated = dateutil.parser.parse(pr_object['updated_at'])
        self.metadata = {}

    def get_num(self):
        """Gets the pull request number.

        Returns:
            pull request number.
        """
        return self.pr_num

    def get_head_sha(self):
        """Gets the SHA corresponding to the commit at HEAD.

        Returns:
            HEAD SHA
        """
        return self.head_sha

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

    def post_error(self, content, logger):
        """Posts an error as a comment to Github.

        Args:
            content: the content to post.
            logger: logger to send error to if post fails.
        """
        self.post_pr_comment('Error: {}'.format(content), logger)

    def post_info(self, content, logger):
        """Posts an info-level message as a comment to Github.

        Args:
            content: the content to post.
            logger: logger to send error to if post fails.
        """
        self.post_pr_comment('Info: {}'.format(content), logger)

    def post_commit_status(self, state, url, description, context, logger):
        """ Posts a commit status update to this PR.

        Args:
            state: State for status; can be 'pending', 'success', 'error', or
              'failure'.
            url: URL at which more information can be found.
            description: Description to show on commit status.
            context: Unique name for this particular status line.
            logger: Logger to use for reporting failure.
        """
        payload = COMMIT_STATUS_PAYLOAD.format(
            state=state,
            url=url,
            description=description,
            context=context
        )
        err = self.helper.post(payload, self.statuses_url)
        if err:
            logger.error(
                "Couldn't set commit status for pr {pr_num}: {err}. Context: "
                "{context}, State: {state}, Description: {description}, URL: "
                "{url}. Falling back to posting a comment.".format(
                    pr_num=self.pr_num, err=err, context=context, state=state,
                    description=description, url=url))
            self.post_pr_comment(
                '{context}: PR {pr_num} in state {state} with description '
                '{description}. URL: {url}.'.format(
                    context=context, pr_num=self.pr_num, state=state,
                    description=description, url=url), logger)

    def post_pr_comment(self, content, logger):
        """Posts a PR comment to Github.

        Args:
            content: the content to post.
            logger: logger to send error to if post fails.
        """
        payload = COMMENT_PAYLOAD.format(body=content)
        err = self.helper.post(payload, self.comments_url)
        if err is not None:
            logger.error(
                "Couldn't post comment '{cmt}' to Github: {err}.".format(
                    cmt=content, err=err))


class GithubComment(object):
    """GithubComment contains helper methods for interacting with comments.
    """

    def __init__(self, cmt_object):
        self.user = cmt_object['user']['login']
        self.cmt_body = cmt_object['body'].encode('ascii', 'ignore')
        self.created = cmt_object['created_at']

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

    def get_created(self):
        """Returns the time the comment was created.
        
        Returns:
            string of comment creation time.
        """
        return self.created
