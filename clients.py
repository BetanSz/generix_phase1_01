"""
Client bootstrap for external services used by the Generix pipeline.

This module centralizes the creation of SDK clients for:
- Azure Document Intelligence (`client_di`)
- Azure Blob Storage (`container`)
- Azure Cosmos DB (document store: `cosmos_digitaliezd`, table-like store: `cosmos_table`)
- Azure OpenAI (`client_oai`)

Configuration
-------------
All connection info and secrets are imported from `keys_generix`:

- Document Intelligence
  - `di_endpoint`, `di_key`

- Azure OpenAI
  - `oai_endpoint`, `oai_key`
  - API version is pinned here to ensure request/response stability.

- Blob Storage
  - `BLOB_CONNECTION_STRING`, `BLOB_CONTAINER`

- Cosmos DB
  - `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE`
  - `COSMOS_CONTAINER_digitalized` (documents extracted from PDFs)
  - `COSMOS_CONTAINER_table` (tabular/row-oriented results)

Exports
-------
- `client_di`: `azure.ai.documentintelligence.DocumentIntelligenceClient`
- `container`: `azure.storage.blob.ContainerClient`
- `cosms_db`:   `azure.cosmos.database.DatabaseProxy` (created if not exists)
- `cosmos_digitaliezd`: `azure.cosmos.container.ContainerProxy`
- `cosmos_table`:       `azure.cosmos.container.ContainerProxy`
- `client_oai`: `openai.AzureOpenAI`

Behavior
--------
- Cosmos database and containers are created if they do not already exist.
- The Blob `ContainerClient` is obtained from the provided connection string and container name.
- All clients are instantiated at import time for convenience and reuse.

Usage
-----
Import this module once and reuse the clients:

    from clients import (
        client_di,
        container,
        cosmos_digitaliezd,
        cosmos_table,
        client_oai,
    )

    blobs = list(container.list_blobs(name_starts_with="M/"))
    result = client_di.begin_analyze_document("prebuilt-layout", pdf_bytes).result()

Notes
-----
- This module performs side effects (network calls for Cosmos “create if not exists”)
  at import time. If you prefer lazy initialization, switch to factory functions or
  a `get_clients()` accessor to defer this work.
- Secrets should ultimately come from environment variables or a secure secret store
  (e.g., Azure Key Vault) rather than a committed Python file.
- If you need custom retry/timeout policies, consider constructing clients with
  explicit `transport`/`retry_total`/`request_timeout` settings.
- Keep API versions pinned (e.g., Azure OpenAI) to avoid breaking changes.
"""

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey

from keys_generix import (
    di_endpoint,
    di_key,
    oai_key,
    oai_endpoint,
    BLOB_CONNECTION_STRING,
    BLOB_CONTAINER,
    COSMOS_ENDPOINT,
    COSMOS_KEY,
    COSMOS_DATABASE,
    COSMOS_CONTAINER_digitalized,
    COSMOS_CONTAINER_table,
)

client_di = DocumentIntelligenceClient(di_endpoint, AzureKeyCredential(di_key))
blob = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
container = blob.get_container_client(BLOB_CONTAINER)
cosmos = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
cosms_db = cosmos.create_database_if_not_exists(id=COSMOS_DATABASE)
cosmos_digitaliezd = cosms_db.create_container_if_not_exists(
    id=COSMOS_CONTAINER_digitalized, partition_key=PartitionKey(path="/id")
)
cosmos_table = cosms_db.create_container_if_not_exists(
    id=COSMOS_CONTAINER_table, partition_key=PartitionKey(path="/id")
)
client_oai = AzureOpenAI(
    api_key=oai_key, api_version="2024-12-01-preview", azure_endpoint=oai_endpoint
)
