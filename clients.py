import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchableField, SearchFieldDataType,
    SearchField, VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile
)
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchableField, SearchFieldDataType,
    SearchField, VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile,
    SemanticSearch, SemanticConfiguration, SemanticPrioritizedFields, SemanticField
)
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey

from keys import (di_endpoint, di_key, oai_key, oai_endpoint, BLOB_CONNECTION_STRING,
                   BLOB_CONTAINER, COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE,COSMOS_CONTAINER)


client_di = DocumentAnalysisClient(di_endpoint, AzureKeyCredential(di_key))
client_oai = AzureOpenAI(api_key=oai_key, api_version="2024-06-01", azure_endpoint=oai_endpoint)
blob = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
container = blob.get_container_client(BLOB_CONTAINER)
cosmos = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
db = cosmos.create_database_if_not_exists(id=COSMOS_DATABASE)
cosmos_container = db.create_container_if_not_exists(
    id=COSMOS_CONTAINER,
    partition_key=PartitionKey(path="/id")
)

print("db:", db.id, "container:", cosmos_container.id)

