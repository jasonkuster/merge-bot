"""Mergebot is a script which talks to GitHub and submits all ready pull requests.

Mergebot talks to a specified GitHub project and watches for @mentions for its account.
Acceptable commands are:
  @<mergebot-name> merge
"""
from subprocess import call
import glob
import requests
import sys
import time

AUTHORIZED_USERS = ["davor"]
BOT_NAME = 'beam-testing'
GITHUB_ORG = 'apache'
REPOSITORY = 'incubator-beam'
SECRET_FILE = '../../github_auth/apache-beam.secret'
SOURCE_REMOTE = 'github'
TARGET_BRANCH = 'master'
TARGET_REMOTE = 'apache'

GITHUB_API_ROOT = 'https://api.github.com'
GITHUB_REPO_FMT_URL = GITHUB_API_ROOT + '/repos/{0}/{1}'
GITHUB_REPO_URL = GITHUB_REPO_FMT_URL.format(GITHUB_ORG, REPOSITORY)
CMDS = ['merge']
ISSUES_URL = GITHUB_REPO_URL + '/issues'
COMMENT_FMT_URL = ISSUES_URL + '/{pr_num}/comments'
PULLS_URL = GITHUB_REPO_URL + '/pulls'

def merge_git(pr):
  if not set_up():
    post_error('Error setting up - please try again.', pr)
    return False
  # Make temp directory and cd into.
  # Clone repository and configure.
  print("Starting merge process for #{}.".format(pr))
  clone_success = call(['git', 'clone', '-b', TARGET_BRANCH, 'https://github.com/{}/{}.git'.format(GITHUB_ORG, REPOSITORY), '/usr/local/google/home/jasonkuster/tmp/'], cwd='/usr/local/google/home/jasonkuster/tmp/')
  if not clone_success == 0:
    post_error('Couldn\'t clone from github/{}/{}. Please try again.'.format(GITHUB_ORG, REPOSITORY), pr)
    return False
  call(['git', 'remote', 'add', TARGET_REMOTE, 'https://git-wip-us.apache.org/repos/asf/{}.git'.format(REPOSITORY)], cwd='/usr/local/google/home/jasonkuster/tmp/')
  call(['git', 'remote', 'rename', 'origin', SOURCE_REMOTE], cwd='/usr/local/google/home/jasonkuster/tmp/')
  call('git config --local --add remote.' + SOURCE_REMOTE  + '.fetch "+refs/pull/*/head:refs/remotes/{}/pr/*"'.format(SOURCE_REMOTE), shell=True, cwd='/usr/local/google/home/jasonkuster/tmp/')
  call(['git', 'fetch', '--all'], cwd='/usr/local/google/home/jasonkuster/tmp/')
  print("Initial work complete.")
  # Clean up fetch
  initial_checkout = call(['git', 'checkout', '-b', 'finish-pr-{}'.format(pr), 'github/pr/{}'.format(pr)], cwd='/usr/local/google/home/jasonkuster/tmp/')
  if not initial_checkout == 0:
    post_error("Couldn't checkout code. Please try again.", pr)
    return False
  print("Checked out.")
  # Rebase PR onto main.
  rebase_success = call(['git', 'rebase', '{}/{}'.format(TARGET_REMOTE, TARGET_BRANCH)], cwd='/usr/local/google/home/jasonkuster/tmp/')
  if not rebase_success == 0:
    print(rebase_success)
    post_error('Rebase was not successful. Please rebase against main and try again.', pr)
    return False
  print("Rebased")

  # Check out target branch to here
  checkout_success = call(['git', 'checkout', '{}/{}'.format(TARGET_REMOTE, TARGET_BRANCH)], cwd='/usr/local/google/home/jasonkuster/tmp/')
  if not checkout_success == 0:
    post_error('Error checking out target branch: master. Please try again.', pr)
    return False
  print("Checked out Apache master.")

  # Merge
  merge_success = call(['git', 'merge', '--no-ff', '-m', 'This closes #{}'.format(pr), 'finish-pr-{}'.format(pr)], cwd='/usr/local/google/home/jasonkuster/tmp/')
  if not merge_success == 0:
    post_error('Merge was not successful against target branch: master. Please try again.', pr)
    return False
  print("Merged successfully.")

  print("Running mvn clean verify.")
  # mvn clean verify
  mvn_success = call(['mvn', 'clean', 'verify'], cwd='/usr/local/google/home/jasonkuster/tmp/')
  if not mvn_success == 0:
    post_error('mvn clean verify against HEAD + PR#{} failed. Not merging.'.format(pr), pr)
    return False

  # git push (COMMENTED UNTIL MERGEBOT HAS PERMISSIONS)
  #push_success = call(['git', 'push', 'apache', 'HEAD:master'], cwd='/usr/local/google/home/jasonkuster/tmp/')
  #if not push_success == 0:
  #  post_error('Git push failed. Please try again.', pr)
  #  return False
  return True

def set_up():
  if not call(['mkdir', '/usr/local/google/home/jasonkuster/tmp']) == 0:
    return False
  return True


def clean_up():
  if not call(['rm', '-rf', '/usr/local/google/home/jasonkuster/tmp']) == 0:
    return False
  return True

