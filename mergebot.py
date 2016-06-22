#!/usr/bin/python
"""Mergebot is a program which merges approved SCM changes into a master repo.
"""

import glob
from multiprocessing import Pool
import os
import signal
import sys
import mergebot_poller
import yaml


def poll_scm(config):
    """poll_scm handles delegating a single repository's work to an SCM poller.

    Args:
        config: A dictionary of configuration to use for the poller.
    """
    sys.stdout = open(os.path.join('log', config['name'] + '_log.txt'), 'w')
    print('starting')
    sys.stdout.flush()
    poller = mergebot_poller.create_poller(config)
    print('starting 2')
    sys.stdout.flush()
    poller.poll()
    print('starting 3')
    sys.stdout.flush()


def main():
    """Reads configs and kicks off pollers.

    main reads the configs and then kicks off pollers per config file
    successfully read in. It then waits for a keyboard interrupt as the
    signal to shut down itself and its children.
    """
    print 'Mergebot Manager Starting Up'
    configs = []
    print 'Parsing Config Files'
    for filename in glob.iglob('config/*.yaml'):
        with open(filename) as cfg:
            try:
                print 'Opening {}'.format(filename)
                config = yaml.load(cfg)
                print '{} Successfully Read'.format(filename)
                configs.append(config)
            except yaml.YAMLError as exc:
                print 'Error parsing file {}: {}.'.format(filename, exc)
                print 'Please fix and try again.'
                return
    # Workaround for multiprocessing SIGINT problems per
    # http://stackoverflow.com/questions/11312525 and the like. Children need to
    # ignore SIGINT; parent should obey and clean up itself.
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    pool = Pool(len(configs))
    signal.signal(signal.SIGINT, original_sigint_handler)

    try:
        print 'Starting Poller Pool'
        pool.map_async(poll_scm, configs)
        while True:
            input('Mergebot running; press Ctrl + C to cancel.\n')
    except KeyboardInterrupt:
        print '\nExiting.'
        pool.terminate()
    else:
        # Generally this shouldn't happen - pollers should run forever.
        pool.close()
        pool.join()
        # TODO(jasonkuster): We could get into a state where we're only polling
        # one repo and all others have crashed. Once mergebot is functional,
        # work on better poller management.
        print 'Mergebot terminated early - all pollers must have crashed.'


if __name__ == '__main__':
    main()
