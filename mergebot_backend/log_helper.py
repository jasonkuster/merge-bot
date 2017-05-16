"""log_helper provides a common method for retrieving loggers."""

import logging
import os

LOG_FORMAT = '[%(levelname).1s-%(asctime)s %(filename)s:%(lineno)s] %(message)s'
DATE_FORMAT = '%m/%d %H:%M:%S'


def get_logger(name, redirect_to_file=False):
    """get_logger is a helper which enables mergebot components to publish logs.
    
    Args:
        name: Name to use to acquire this logger.
        redirect_to_file: If true, prints log.

    Returns:
        A logging.Logger for the specified arguments.
    """
    logger_name = '{name}_logger'.format(name=name)
    l = logging.getLogger(logger_name)
    if l.handlers:
        # This logger already exists and has been configured.
        return l
    if redirect_to_file:
        file_name = '{name}_log.txt'.format(name=name)
        h = logging.FileHandler(
            os.path.join('log', '{name}_log.txt'.format(name=file_name)))
    else:
        h = logging.StreamHandler()
    f = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    h.setFormatter(f)
    l.setLevel(logging.INFO)
    l.addHandler(h)
    return l
