#!/usr/bin/python
"""Mergebot is a program which merges approved SCM changes into a master repo.
"""

import glob
import logging
from multiprocessing import Pool
import os
import signal
import mergebot_poller
import yaml


def poll_scm(config):
    """poll_scm handles delegating a single repository's work to an SCM poller.

    Args:
        config: A dictionary of configuration to use for the poller.
    """
    poller = mergebot_poller.create_poller(config)
    poller.poll()


def main():
    """Reads configs and kicks off pollers.

    main reads the configs and then kicks off pollers per config file
    successfully read in. It then waits for a keyboard interrupt as the
    signal to shut down itself and its children.
    """
    l = logging.getLogger('mergebot')
    f = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    h = logging.StreamHandler()
    h.setFormatter(f)
    l.setLevel(logging.INFO)
    l.addHandler(h)
    l.info('Mergebot Manager Starting Up')
    configs = []
    l.info('Parsing Config Files')
    for filename in glob.iglob('config/*.yaml'):
        with open(filename) as cfg:
            try:
                l.info('Opening {}'.format(filename))
                config = yaml.load(cfg)
                l.info('{} Successfully Read'.format(filename))
                configs.append(config)
            except yaml.YAMLError as exc:
                l.error('Error parsing file {}: {}.'.format(filename, exc))
                l.error('Please fix and try again.')
                return
    # Workaround for multiprocessing SIGINT problems per
    # http://stackoverflow.com/questions/11312525 and the like. Children need to
    # ignore SIGINT; parent should obey and clean up itself.
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    pool = Pool(len(configs))
    signal.signal(signal.SIGINT, original_sigint_handler)

    try:
        l.info('Starting Poller Pool')
        pool.map_async(poll_scm, configs)
        while True:
            input('Mergebot running; press Ctrl + C to cancel.\n')
    except KeyboardInterrupt:
        l.info('Exiting.')
        pool.terminate()
    else:
        # Generally this shouldn't happen - pollers should run forever.
        pool.close()
        pool.join()
        # TODO(jasonkuster): We could get into a state where we're only polling
        # one repo and all others have crashed. Once mergebot is functional,
        # work on better poller management.
        l.error('Mergebot terminated early. All pollers'
                ' must have crashed.')


if __name__ == '__main__':
    main()
