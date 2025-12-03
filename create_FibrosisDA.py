'''
create_FibrosisDA.py

Script that uses ThematicAtlases to create a curated fibrosis disease atlas


Workflow:
config) logger

1) Expand search terms to create synonyms

'''
from src.ThematicAtlases import ThematicAtlases
import logging

### logger ###
logger = logging.getLogger(__name__)
logger_format = (
    "%(asctime)s | %(name)s | %(levelname)s | "
    "%(filename)s:%(lineno)d | %(message)s"
)
logging.basicConfig(
    level = logging.DEBUG,
    format = logger_format,
    filename = ".logs/FibrosisDA.log",
    filemode = "a"
)


### Workflow ###
logger.info("[create_FibrosisDA.py] Start!")
thematic_atlas = ThematicAtlases.ThematicAtlases()

#get synonyms from OLS
import pandas as pd
thematic_atlas.get_synonyms(infile = pd.DataFrame())


#end
logger.info("[create_FibrosisDA.py] End!")