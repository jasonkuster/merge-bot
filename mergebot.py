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
    l = logging.getLogger('{name}_logger'.format(name=config['name']))
    formatter = logging.Formatter('%(asctime)s : %(message)s')
    file_handler = logging.FileHandler(
        os.path.join('log', '{name}_log.txt'.format(name=config['name'])))
    file_handler.setFormatter(formatter)
    l.addHandler(file_handler)
    l.setLevel(logging.INFO)
    l.info('starting')
    poller = mergebot_poller.create_poller(config)
    l.info('poller created')
    poller.poll()
    l.info('poller is poll')


def main():
    """Reads configs and kicks off pollers.

    main reads the configs and then kicks off pollers per config file
    successfully read in. It then waits for a keyboard interrupt as the
    signal to shut down itself and its children.
    """
    logger = logging.getLogger('mergebot')
    formatter = logging.Formatter('%(asctime)s : %(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(stream_handler)
    logger.info('Mergebot Manager Starting Up')
    configs = []
    logger.info('Parsing Config Files')
    for filename in glob.iglob('config/*.yaml'):
        with open(filename) as cfg:
            try:
                logger.info('Opening {}'.format(filename))
                config = yaml.load(cfg)
                logger.info('{} Successfully Read'.format(filename))
                configs.append(config)
            except yaml.YAMLError as exc:
                logger.error('Error parsing file {}: {}.'.format(filename, exc))
                logger.error('Please fix and try again.')
                return
    # Workaround for multiprocessing SIGINT problems per
    # http://stackoverflow.com/questions/11312525 and the like. Children need to
    # ignore SIGINT; parent should obey and clean up itself.
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    pool = Pool(len(configs))
    signal.signal(signal.SIGINT, original_sigint_handler)

    try:
        logger.info('Starting Poller Pool')
        pool.map_async(poll_scm, configs)
        while True:
            input('Mergebot running; press Ctrl + C to cancel.\n')
    except KeyboardInterrupt:
        logger.info('Exiting.')
        pool.terminate()
    else:
        # Generally this shouldn't happen - pollers should run forever.
        pool.close()
        pool.join()
        # TODO(jasonkuster): We could get into a state where we're only polling
        # one repo and all others have crashed. Once mergebot is functional,
        # work on better poller management.
        logger.error('Mergebot terminated early. All pollers'
                     ' must have crashed.')


if __name__ == '__main__':
    main()
