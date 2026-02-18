'''
Docstring for ThematicAtlases.wrappers.wrappers

Module for parent level wrappers to interact with external APIs for ThematicAtlases.
'''

from ThematicAtlases.wrappers.epmc_wrapper import EPMCWrapper
from ThematicAtlases.wrappers.geo_wrapper import GEOWrapper

class Wrappers(EPMCWrapper, GEOWrapper):
    def __init__(self):
        super().__init__()