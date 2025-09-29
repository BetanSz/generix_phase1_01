import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
import os

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey

#from keys_cellenza import (di_endpoint, di_key, oai_key, oai_endpoint, BLOB_CONNECTION_STRING,
#                   BLOB_CONTAINER, COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE,COSMOS_CONTAINER)

from keys_generix import (di_endpoint, di_key, oai_key, oai_endpoint, BLOB_CONNECTION_STRING,
                   BLOB_CONTAINER, COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_CONTAINER_digitalized,
                   COSMOS_CONTAINER_table)


client_di = DocumentIntelligenceClient(di_endpoint, AzureKeyCredential(di_key))
blob = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
container = blob.get_container_client(BLOB_CONTAINER)
cosmos = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
cosms_db = cosmos.create_database_if_not_exists(id=COSMOS_DATABASE)
#TODO: you need to unifrmize the structre or id at the cosmos db as to known all the fiels related to a single affair.
cosmos_digitaliezd = cosms_db.create_container_if_not_exists(
    id=COSMOS_CONTAINER_digitalized,
    partition_key=PartitionKey(path="/id")
)
print("db:", cosms_db.id, "container:", cosmos_digitaliezd.id)
cosmos_table = cosms_db.create_container_if_not_exists(
    id=COSMOS_CONTAINER_table,
    partition_key=PartitionKey(path="/id")
)
print("db:", cosms_db.id, "container:", cosmos_digitaliezd.id)

client_oai = AzureOpenAI(api_key=oai_key, api_version="2024-12-01-preview", azure_endpoint=oai_endpoint)
#client_oai = AzureOpenAI(
#    api_version="2024-12-01-preview",
#    azure_endpoint="https://generix-01.openai.azure.com/",
#    api_key=oai_key,
#)
