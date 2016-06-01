# Mergebot is a program to handle merging approved SCM changes into a master repository.

import glob
import mergebot_poller
import multiprocessing
import os
import signal
import sys
import yaml

# poll_scm handles delegating a single repository's work to an SCM poller
def poll_scm(config):
  sys.stdout = open(os.path.join('log', config['name'] + '_log.txt'), 'w')
  poller = mergebot_poller.MergebotPoller()
  poller.poll(config)

# main reads the configs and then kicks off pollers per config file successfully
# read in.
def main():
  print('Mergebot Manager Starting Up')

  configs = []
  print('Parsing Config Files')
  for fn in glob.iglob('config/*.yaml'):
    with open(fn) as cfg:
      try:
        print('Opening {}'.format(fn))
        config = yaml.load(cfg)
        print('{} Successfully Read'.format(fn))
        configs.append(config)
      except YAMLError as exc:
        print("Error parsing file {}: {}. Continuing with others.".format(fn, exc))

  # Workaround for multiprocessing SIGINT problems per
  # http://stackoverflow.com/questions/11312525 and the like. Children need to
  # ignore SIGINT; parent should obey and clean up itself.
  original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
  pool = multiprocessing.Pool(len(configs))
  signal.signal(signal.SIGINT, original_sigint_handler)

  try:
    print('Starting Poller Pool')
    pool.map_async(poll_scm, configs)
    while True:
      input("Mergebot running; press Ctrl + C to cancel.\n")
  except KeyboardInterrupt:
    print("\nExiting.")
    pool.terminate()
  else:
    # Generally this shouldn't happen - pollers should run forever.
    pool.close()
    pool.join()
    # TODO: We could get into a state where we're only polling one repo and all
    # others have crashed. Once mergebot is functional, work on better poller
    # management.
    print('Mergebot terminated early - all pollers must have crashed.')

if __name__ == '__main__':
  main()
