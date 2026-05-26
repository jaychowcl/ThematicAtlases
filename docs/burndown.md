# BurnDown

# meta_standards_converter
[] validate meta_standards_converter
[]  ArrayExpress to JSON  
[]  JSON to GSK SCHR .h5ad  

# ThematicAtlases
## big
[] Major refactor of existing codebase.
[] Get gse list from any geo accession level
[] meta_standards_converter gse to json

## small

# agentic_curator
[] vertex ai ADC auth
[] unified interface for llm models
[] collect publication texts 
[] agent prompts

[] list of ontologies
[] ols websearch for ontology term


























































BurnDown

# meta_standards_converter
## Big fixes
[]  refactor ncbi, sra and pubmed lookup to work on json, then converter will pick up from json instead of calling during conversion stage  
[]  change link from ncbi to ena  
[]  remove greedy geo sdrf appending and just place known columns in  
[]  only 4 platform considerations: microarray, bulk, single droplet, single plate  
    []  only microarrays have extract / labeled extract + array data files + deried array data files  
    []  single cell both reads on same row if droplet, if plat single or bulkd, each row each read, removed derrived file from single and bulk  
    []  fields missing from single cell: eaexpected clusters, eaexperiment, Typeae, additional attributes, eabatcheffect, Comment[AEExperimentType], Comment[EACurator], Comment[EAExpectedClusters], Comment[EAExperimentType], Comment[EAAdditionalAttributes], Comment[EABatchEffect]  
[]  sdrf protocol refs point to protocol name in idf  
[]  qc, rep, norm in idf  


## Small fixes
[]  public release date as geo release date  
[]  comment[arrayexpresssubmissiondate] as current date  
[]  set date format to yyyy-mm-dd  
[]  add columns to sdrf even if empty: Characteristics[organism part], sequence data uri  
[]  must have sample collection protocol even if empty & nucleic acid sequencing protocol in idf  
[]  fix publication status + source ref (probably missing keys in efo mapper?)
[]  strip all quotes from all values  
[]  address should append everything in address incl affiliation  
[]  fallback for first and last if none, maybe affiliation?  

## Additional Features
[]  ArrayExpress to JSON  
[]  JSON to GSK SCHR .h5ad  


# ThematicAtlases
## Fixes
[] refactor for extensibility
## Additional Features
[] Build gse list from any geo accession level
[] use meta_standards_converter to convert gse to jsons

# theme_verifier
[] llm unified interface
[] publication text gathering for each pub, a class to handle
[] agent prompts

# agentic_curator

