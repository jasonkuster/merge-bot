"""
github_helper provides several methods to help interface with Github
"""

import requests

GITHUB_ORG = 'apache'
SECRET_FILE = '../../github_auth/apache-beam.secret'
SOURCE_REMOTE = 'github'
TARGET_BRANCH = 'master'
TARGET_REMOTE = 'apache'

GITHUB_API_ROOT = 'https://api.github.com'
GITHUB_REPO_FMT_URL = GITHUB_API_ROOT + '/repos/{0}/{1}'

BOT_NAME = 'merge-bot'
GITHUB_SECRET = '../../github_auth/mergebot.secret'


class GithubHelper(object):
    """
    GithubHelper provides a lightweight authenticated wrapper for the Github
    API.
    """

    def __init__(self, org, repo):
        self.org = org
        self.repo = repo
        with open(GITHUB_SECRET, 'r') as key_file:
            self.bot_key = key_file.read().strip()
        print('Loaded key file.')

    def fetch_prs(self):
        """
        Gets the PRs for the configured repository

        :return: returns a JSON object containing the pull request if
                         successful, else None.
        """
        p_url = pulls_url(self.org, self.repo)
        print('Loading pull requests from Github at {}.'.format(p_url))
        req = requests.get(p_url, auth=(BOT_NAME, self.bot_key))
        if req.status_code != 200:
            print('Oops, that didn\'t work. Error below,' +
                        'waiting then trying again.')
            print(req.text)
            return None
        print('Loaded.')
        return req.json()

    def fetch_comments(self, pr_num):
        """
        Gets the comments for a specified pull request

        :return: returns a JSON object containing the comments if successful,
                 else None.
        """
        cmt_url = comment_url(self.org, self.repo, pr_num)
        print('Loading comments from Github at {}.'.format(cmt_url))
        req = requests.get(cmt_url, auth=(BOT_NAME, self.bot_key))
        if req.status_code != 200:
            print('Oops, that didn\'t work. Error below, moving on.')
            print(req.text)
            return None
        return req.json()

    def post_error(self, content, pr_num):
        """
        Posts an error as a comment to Github

        :return: returns nothing
        """
        self.post_pr_comment("Error: {}, #{}.".format(content, pr_num), pr_num)

    def post_info(self, content, pr_num):
        """
        Posts an info-level message as a comment to Github

        :return: returns nothing
        """
        self.post_pr_comment("Info: {}, #{}.".format(content, pr_num), pr_num)

    def post_pr_comment(self, content, pr_num):
        """
        Posts a PR comment to Github

        :return: returns nothing
        """
        print(content)
        self.post(content, comment_url(self.org, self.repo, pr_num))

    def post(self, content, endpoint):
        """
        Posts a comment to a specified endpoint.

        :return: returns nothing
        """
        payload = {"body": content}
        requests.post(endpoint, data=payload, auth=(BOT_NAME, self.bot_key))


def repo_url(org, repo):
    """
    Formats the appropriate API url for the requested repository.

    :return: returns a formatted Github repository URL
    """
    return GITHUB_REPO_FMT_URL.format(org, repo)


def issues_url(org, repo):
    """
    Gets the issues URL for the specified repository.

    :return: returns a formatted Github issues URL
    """
    return repo_url(org, repo) + '/issues'


def comment_url(org, repo, pr_num):
    """
    Gets the comments URL for the specified pull request.

    :return: returns a formatted Github comment URL
    """
    cmt = '/{pr_num}/comments'.format(pr_num=pr_num)
    return repo_url(org, repo) + cmt


def pulls_url(org, repo):
    """
    Gets the pull request URL for the specified repository.

    :return: returns a formatted Github pulls URL
    """
    return repo_url(org, repo) + '/pulls/'

