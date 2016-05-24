"""TODO(jasonkuster): DO NOT SUBMIT without one-line documentation for mergebot_poller.

TODO(jasonkuster): DO NOT SUBMIT without a detailed description of mergebot_poller.
"""

import mergebot
import Queue

GITHUB_SECRET = '../../github_auth/apache-beam.secret'

class MergebotPoller:
  scm_type = ""
  repository = ""
  branch = ""
  scm_pollers = { "github": poll_github }
  scm_mergers = { "github": mergebot.merge_git }
  work_queue = Queue.Queue()


  def poll(self, config):
    print('Starting merge poller for {}.'.format(config['name']))
    self.scm_type = config['scm_type']
    self.repository = config['repository']
    self.branch = config['default_branch']
    scm_pollers[scm_type](config)


  def poll_github(self, config):
    # Loop: Forever, once per minute.
    while True:
      print('Loading pull requests from Github at {}.'.format(PULLS_URL))
      # Load list of pull requests from Github
      r = requests.get(PULLS_URL, auth=(BOT_NAME, bot_key))
      if r.status_code != 200:
        print('Oops, that didn\'t work. Error below, waiting then trying again.')
        print(r.text)
        return

      print('Loaded.')
      pr_json = r.json()
      # Loop: Each pull request
      for pr in pr_json:
        search_pr(pr)

      time.sleep(15)


