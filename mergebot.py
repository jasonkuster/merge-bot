#!/usr/bin/python
"""Mergebot is a program which merges approved SCM changes into a master repo.
"""

from datetime import datetime
import glob
import logging
from multiprocessing import Pipe, Process
import signal
from threading import Thread
from time import sleep

import mergebot_poller
import yaml


def poll_scm(config, pipe):
    """poll_scm handles delegating a single repository's work to an SCM poller.

    Args:
        config: A dictionary of configuration to use for the poller.
        pipe: Communication pipe for passing messages.
    """
    poller = mergebot_poller.create_poller(config, pipe)
    poller.poll()


class MergerInfo(object):
    def __init__(self, process, pipe, last_heartbeat):
        self.process = process
        self.pipe = pipe
        self.last_heartbeat = last_heartbeat


def main():
    _, child_pipe = Pipe()
    mb = MergeBot(child_pipe)
    mb.start()
    mb.join()


def get_logger():
    l = logging.getLogger('mergebot')
    log_fmt = '[%(levelname).1s-%(asctime)s %(filename)s:%(lineno)s] %(message)s'
    date_fmt = '%m/%d %H:%M:%S'
    f = logging.Formatter(log_fmt, date_fmt)
    h = logging.StreamHandler()
    h.setFormatter(f)
    l.setLevel(logging.INFO)
    l.addHandler(h)
    return l


class MergeBot(Thread):

    def __init__(self, message_pipe):
        self.message_pipe = message_pipe
        self.l = get_logger()
        self.l.info('Mergebot Manager Starting Up')
        Thread.__init__(self)

    def run(self):
        """Reads configs and kicks off pollers.

        start_pollers reads the configs and then kicks off pollers per config file
        successfully read in. It then waits for a keyboard interrupt as the signal
        to shut down itself and its children.
        """
        configs = self.parse_configs()
        mergers = self.start_mergers(configs)

        while True:
            if self.message_pipe.poll():
                msg = self.message_pipe.recv()
                if msg == 'terminate':
                    break
            for merger in mergers:
                while merger.pipe.poll():
                    self.message_pipe.send(merger.pipe.recv())
            sleep(1)

        self.l.info('Caught terminate signal; killing children and exiting.')
        for merger in mergers:
            merger.pipe.send('terminate')
        for merger in mergers:
            merger.process.join()
        self.l.info('Children killed, done.')

    def parse_configs(self):
        configs = []
        self.l.info('Parsing Config Files')
        for filename in glob.iglob('config/*.yaml'):
            with open(filename) as cfg:
                try:
                    self.l.info('Opening {}'.format(filename))
                    config = yaml.load(cfg)
                    self.l.info('{} Successfully Read'.format(filename))
                    configs.append(config)
                except yaml.YAMLError as exc:
                    self.l.fatal(
                        'Error parsing file {filename}: {exc}. Please fix and try '
                        'again.'.format(filename=filename, exc=exc))
        return configs

    def start_mergers(self, configs):
        mergers = []
        for config in configs:
            parent_pipe, child_pipe = Pipe()
            p = Process(target=poll_scm, args=(config, child_pipe,))
            mergers.append(MergerInfo(
                process=p,
                pipe=parent_pipe,
                last_heartbeat=datetime.now()))
            self.l.info('Starting poller for {}.'.format(config['name']))
            p.start()
        return mergers

if __name__ == '__main__':
    main()
