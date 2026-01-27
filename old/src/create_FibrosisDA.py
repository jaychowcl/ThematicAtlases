'''
create_FibrosisDA.py

Script that uses ThematicAtlases to create a curated fibrosis disease atlas


Workflow:
config) logger

1) Expand search terms to create synonyms

'''
from ThematicAtlases import ThematicAtlas

import logging
### logger ###
logger = logging.getLogger(__name__)
logger_format = (
    "%(asctime)s | %(name)s | %(levelname)s | "
    "%(filename)s:%(lineno)d | %(module)s:%(funcName)s | %(message)s"
)
logging.basicConfig(
    level = logging.DEBUG,
    format = logger_format,
    filename = ".logs/FibrosisDA.log",
    filemode = "a"
)


### Workflow ###
logger.info("[create_FibrosisDA.py] Start!")
thematic_atlas = ThematicAtlas.ThematicAtlas()

# Import config terms
## search_terms.tsv
thematic_atlas.import_search_terms(file = "config/search_terms.tsv")
## filter_groups.tsv
thematic_atlas.import_filter_groups(file = "config/filter_groups.tsv")

#get synonyms from OLS
thematic_atlas.get_synonyms()

# Use search terms and filter groups to search data repositories



#end
logger.info("[create_FibrosisDA.py] End!")