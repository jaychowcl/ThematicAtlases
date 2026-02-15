'''
Docstring for create_FibrosisDA

Script for using ThematicAtlases to create FibrosisDA, a thematic organisation of fibrosis related transcriptomic data.


 - Initiate ThematicAtlas class 
 - Import queries for publication search from config/queries.tsv
 - Search EuropePMC for publications and publication metadata using queries


'''


from ThematicAtlases import ThematicAtlas

# Initiate ThematicAtlas class
thematic_atlas = ThematicAtlas.ThematicAtlas()

# Import queries for publication search from config/queries.tsv
thematic_atlas.import_queries(filepath="config/queries.txt")

# Search EuropePMC for publications, publication metadata and datalinks using queries 
thematic_atlas.search_for_publications()

# Use datalink accessions to get metadata for each datalink
thematic_atlas.get_datalink_metadata()


