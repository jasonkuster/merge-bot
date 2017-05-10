#!/usr/bin/python
"""Mergebot is a program which merges approved SCM changes into a master repo.
"""

from datetime import datetime
import glob
import logging
from multiprocessing import Pipe, Process
import signal
import mergebot_poller
import yaml


def poll_scm(config, pipe):
    """poll_scm handles delegating a single repository's work to an SCM poller.

    Args:
        config: A dictionary of configuration to use for the poller.
    """
    poller = mergebot_poller.create_poller(config, pipe)
    poller.poll()


class MergerInfo(object):
  def __init__(self, process, pipe, last_heartbeat):
    self.process = process
    self.pipe = pipe
    self.last_heartbeat = last_heartbeat


def main():
    """Reads configs and kicks off pollers.

    main reads the configs and then kicks off pollers per config file
    successfully read in. It then waits for a keyboard interrupt as the
    signal to shut down itself and its children.
    """
    l = logging.getLogger('mergebot')
    log_fmt = '[%(levelname).1s-%(asctime)s %(filename)s:%(lineno)s] %(message)s'
    date_fmt = '%m/%d %H:%M:%S'
    f = logging.Formatter(log_fmt, date_fmt)
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

    # Start up processes for each merger for which we have a config.
    mergers = []
    # Workaround for multiprocessing SIGINT problems per
    # http://stackoverflow.com/questions/11312525 and the like. Children need to
    # ignore SIGINT; parent should obey and clean up itself.
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    for config in configs:
        parent_pipe, child_pipe = Pipe()
        p = Process(target=poll_scm, args=(config, child_pipe,))
        mergers.append(MergerInfo(
            process=p,
            pipe=parent_pipe,
            last_heartbeat=datetime.now()))
        l.info('Starting poller for {}.'.format(config['name']))
        p.start()
    signal.signal(signal.SIGINT, original_sigint_handler)

    # Watch heartbeats of mergers
    try:
        while True:
            for merger in mergers:
                msgs = []
                while merger.pipe.poll():
                    msgs.append(merger.pipe.recv())
                for msg in msgs:
                    # Check heartbeat, update last heard from, etc.
                    # msgs will be FIFO, so update last_heartbeat as we go.
                    if msg.startswith('hb: '):
                        merger.last_heartbeat = datetime.strptime(
                            msg[len('hb: '):],
                            "%H:%M:%S-%Y-%m-%d")
                    ts = (datetime.now() -
                          merger.last_heartbeat).total_seconds()
                    if ts > 60:
                        # TODO(jasonkuster): Restart the process.
                        # TODO(jasonkuster): How do we preserve queue?
                        l.warn('houston we have a problem')
                        # do something
    except KeyboardInterrupt:
        l.info('Caught KeyboardInterrupt; killing children and ending.')

    for merger in mergers:
        merger.pipe.send('terminate')

    for merger in mergers:
        merger.process.join()

    l.info('Children killed, done.')

    # Workaround for multiprocessing SIGINT problems per
    # http://stackoverflow.com/questions/11312525 and the like. Children need to
    # ignore SIGINT; parent should obey and clean up itself.
    # original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    # pool = Pool(len(configs))
    # signal.signal(signal.SIGINT, original_sigint_handler)

    # try:
        # l.info('Starting Poller Pool')
        # pool.map_async(poll_scm, configs)
        # while True:
        #     input('Mergebot running; press Ctrl + C to cancel.\n')
    # except KeyboardInterrupt:
        # l.info('Exiting.')
        # pool.terminate()
    # else:
        # Generally this shouldn't happen - pollers should run forever.
        # pool.close()
        # pool.join()
        # TODO(jasonkuster): We could get into a state where we're only polling
        # one repo and all others have crashed. Once mergebot is functional,
        # work on better poller management.
        # l.error('Mergebot terminated early. All pollers must have crashed.')


if __name__ == '__main__':
    main()
