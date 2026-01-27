'''
Docstring for create_FibrosisDA

Script for using ThematicAtlases to create FibrosisDA, a thematic organisation of fibrosis related transcriptomic data.


 - Initiate ThematicAtlas class and import search terms for publication search

'''


from ThematicAtlases import ThematicAtlas

thematic_atlas = ThematicAtlas.ThematicAtlas()
thematic_atlas.import_search_terms(filepath="config/search_terms.tsv")

