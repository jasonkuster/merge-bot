#!/usr/bin/python
"""Mergebot is a program which merges approved SCM changes into a master repo.
"""

import glob
from multiprocessing import Pipe, Process
from time import sleep

import signal
import yaml

from mergebot_backend import mergebot_poller
from mergebot_backend.log_helper import get_logger
from mergebot_frontend import db
from mergebot_frontend.models import Poller, QueuedItem

l = get_logger('mergebot')


def shutdown_mergebot(signum, _):
    """shutdown_mergebot is the handler used to receive the kill signal."""
    print 'Caught {signal}.'.format(signal=signum)
    raise ServerExit


class ServerExit(Exception):
    """ServerExit is a more specific exception for when we terminate."""
    pass


def main():
    """Reads configs and kicks off pollers.

    main reads the configs and then kicks off pollers per config file 
    successfully read in. It then waits for the signal to shut down itself 
    and its children.
    """
    l.info('Mergebot manager starting up.')
    configs = parse_configs()

    l.info('Cleaning up old tables.')
    Poller.query.delete()
    QueuedItem.query.delete()
    db.session.commit()

    # Set signals to ignore while we set up the mergers, then set appropriately.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pollers = start_pollers(configs)
    signal.signal(signal.SIGINT, shutdown_mergebot)
    signal.signal(signal.SIGTERM, shutdown_mergebot)

    try:
        while True:
            sleep(1)
    except ServerExit:
        l.info('Caught terminate signal; killing children and exiting.')

    for poller in pollers:
        poller.pipe.send('terminate')
    for poller in pollers:
        poller.process.join()

    l.info('Children killed, done.')


class MergeBotConfig(object):
    """Defines MergeBot configuration for a project."""
    def __init__(self,
                 name,
                 github_org,
                 repository,
                 merge_branch,
                 verification_branch,
                 scm_type,
                 jenkins_location,
                 verification_job_name):
        self.name = name
        self.github_org = github_org
        self.repository = repository
        self.merge_branch = merge_branch
        self.verification_branch = verification_branch
        self.scm_type = scm_type
        self.jenkins_location = jenkins_location
        self.verification_job_name = verification_job_name


def mergebotconfig_constructor(loader, node):
    """mergebotconfig_constructor is an object constructor for the yaml library.
       It is intended to be used to validate that all configs contain the
       appropriate fields.
    """
    values = loader.construct_mapping(node)
    try:
        name = values['name']
        github_org = values['github_org']
        repository = values['repository']
        merge_branch = values['merge_branch']
        verification_branch = values['verification_branch']
        scm_type = values['scm_type']
        jenkins_location = values['jenkins_location']
        verification_job_name = values['verification_job_name']
    except KeyError as exc:
        raise yaml.YAMLError('problem with key {exc}'.format(exc=exc))
    return MergeBotConfig(name,
                          github_org,
                          repository,
                          merge_branch,
                          verification_branch,
                          scm_type,
                          jenkins_location,
                          verification_job_name)


def parse_configs():
    """Parses config files out of config/ directory.
    
    Returns:
        Array of MergeBotConfig objects.
    """
    configs = []
    yaml.add_constructor(u'!MergeBotConfig', mergebotconfig_constructor)
    l.info('Parsing Config Files')
    for filename in glob.iglob('config/*.yaml'):
        with open(filename) as cfg:
            try:
                l.info('Opening {}'.format(filename))
                config = yaml.load(cfg)
                l.info('{} Successfully Read'.format(filename))
                configs.append(config)
            except yaml.YAMLError as exc:
                l.fatal(
                    'Error parsing file {filename}: {exc}. Please fix and try '
                    'again.'.format(filename=filename, exc=exc))
    return configs


class PollerInfo(object):
    """MergerInfo contains important hooks for the pollers we are running."""
    def __init__(self, process, pipe):
        self.process = process
        self.pipe = pipe


def poll_scm(config, pipe):
    """poll_scm handles delegating a single repository's work to an SCM poller.

    Args:
        config: A dictionary of configuration to use for the poller.
        pipe: Communication pipe for passing messages.
    """
    try:
        poller = mergebot_poller.create_poller(config, pipe)
        poller.poll()
    except BaseException as exc:
        l.error('Poller for {name} crashed with exception {exc}. Please '
                'restart and try again'.format(name=config.name, exc=exc))


def start_pollers(configs):
    """start_pollers starts a set of pollers for specified configurations.
    
    Args:
        configs: Configurations for the pollers.

    Returns:
        Array of poller info (process, comm pipe).
    """
    pollers = []
    for config in configs:
        parent_pipe, child_pipe = Pipe()
        p = Process(target=poll_scm, args=(config, child_pipe,))
        pollers.append(PollerInfo(
            process=p,
            pipe=parent_pipe))
        l.info('Starting poller for {}.'.format(config.name))
        p.start()
    return pollers

if __name__ == '__main__':
    main()
