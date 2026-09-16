from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    app_name: str = "Backend Agent API"
    environment: str = "production"
    allow_local_auth_bypass: bool = False
    cors_allowed_origins: str = "http://localhost:5173"

    # Azure AI Search
    azure_search_endpoint: str = "https://srch-ragpoc-dev-qelri355piqlq.search.windows.net"
    azure_search_index_name: str = "pdf-chunks-index"
    azure_search_semantic_configuration_name: str = "document-content-semantic"

    # Azure AI Search schema fields
    # The index's key field is `id` - see the SearchField definitions in
    # worker/services/search_indexer.py, which is what creates the index.
    # "chunkId" made every search 400 on $select: "Could not find a
    # property named 'chunkId' on type 'search.document'".
    aas_field_chunk_id: str = "id"
    aas_field_parent_document_id: str = "parentDocumentId"
    aas_field_file_name: str = "fileName"
    aas_field_content: str = "content"
    aas_field_page: str = "page"
    aas_field_source_url: str = "sourceUrl"
    aas_field_vector: str = "text_vector"

    # Azure OpenAI
    azure_openai_endpoint: str = "https://aoai-ragpoc-dev-qelri355piqlq.openai.azure.com/"
    # 2024-10-21 predates the gpt-5 family: a streamed request to it comes
    # back with zero tool_call frames, so the agent silently loses its
    # tools mid-stream. Verified directly against the deployment - the same
    # request on 2025-04-01-preview streams tool calls correctly.
    azure_openai_api_version: str = "2025-04-01-preview"
    openai_chat_deployment: str = "gpt-5-mini"
    openai_embedding_deployment: str = "text-embedding-3-small"
    # Retries the OpenAI SDK performs on a 429 before giving up.
    openai_max_retries: int = 5

    # Azure Storage
    azure_storage_account_name: str = "stragpocdevqelri355piqlq"

    # Blob Storage (aligned with infra handoff & worker)
    blob_container_name: str = "pdf-library"
    staging_container_name: str = "staging"

    # Queue Storage
    storage_queue_name: str = "index-jobs"

    # Table Storage
    job_status_table_name: str = "jobstatus"
    conversation_history_table_name: str | None = None

    @property
    def azure_blob_container_documents(self) -> str:
        return self.blob_container_name

    @property
    def azure_blob_container_staging(self) -> str:
        return self.staging_container_name

    @property
    def azure_queue_name(self) -> str:
        return self.storage_queue_name

    @property
    def azure_table_name(self) -> str:
        return self.job_status_table_name

    # Job statuses
    job_status_queued: str = "QUEUED"
    job_status_running: str = "RUNNING"
    job_status_succeeded: str = "SUCCEEDED"
    job_status_failed: str = "FAILED"

    # App authorization & Entra ID
    auth_default_role: str = ""
    azure_tenant_id: str = "6fc8a795-8bcb-4e52-8b36-41c1971e6816"
    azure_client_id_api: str = "7267f8e7-50eb-4247-88b7-da2cc3adf6f6"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
