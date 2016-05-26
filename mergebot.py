#!/usr/bin/python
"""
Mergebot is a program to handle merging approved SCM changes into a master
repository.
"""

import glob
import mergebot_poller
import multiprocessing
import os
import signal
import sys
import yaml


def poll_scm(config):
    """
    poll_scm handles delegating a single repository's work to an SCM poller

    :param config: A dictionary of configuration to use for the poller.
    :return: returns nothing
    """
    sys.stdout = open(os.path.join('log', config['name'] + '_log.txt'), 'w')
    poller = mergebot_poller.MergebotPoller(config)
    poller.poll()


def main():
    """
    main reads the configs and then kicks off pollers per config file
    successfully read in.

    :return: returns nothing
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
                print 'Continuing with others.'

    # Workaround for multiprocessing SIGINT problems per
    # http://stackoverflow.com/questions/11312525 and the like. Children need to
    # ignore SIGINT; parent should obey and clean up itself.
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    pool = multiprocessing.Pool(len(configs))
    signal.signal(signal.SIGINT, original_sigint_handler)

    try:
        print 'Starting Poller Pool'
        pool.map_async(poll_scm, configs)
        while True:
            input('Mergebot running; press Ctrl + C to cancel.\n')
    except KeyboardInterrupt:
        print "\nExiting."
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
