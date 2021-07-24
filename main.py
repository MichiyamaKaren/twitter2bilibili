import config
from twitter2bilibili import T2BForwarder

from loguru import logger

logger.add('t2b.log')

forwarder = T2BForwarder(config)
forwarder.run()
