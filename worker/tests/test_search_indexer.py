from unittest.mock import MagicMock, patch
import pytest

from services.search_indexer import SearchPipelineSetupService


@patch("services.search_indexer.SearchIndexerClient")
@patch("services.search_indexer.SearchIndexClient")
@patch("services.search_indexer.DefaultAzureCredential")
def test_search_pipeline_setup(MockCredential, MockIndexClient, MockIndexerClient):
    """
    Verifies that SearchPipelineSetupService idempotently creates or updates:
    1. Data Source Connection
    2. Index with proper schema (parentDocumentId, fileName, page, sourceUrl, text_vector 1536d)
    3. Skillset with DocumentIntelligenceLayoutSkill (text-chunked) and OpenAIEmbeddingSkill
    4. Indexer with field mappings
    """
    mock_index_client = MockIndexClient.return_value
    mock_indexer_client = MockIndexerClient.return_value

    mock_indexer_client.create_or_update_data_source_connection.return_value = MagicMock(name="pdf-blob-datasource")
    mock_index_client.create_or_update_index.return_value = MagicMock(name="pdf-chunks-index")
    mock_indexer_client.create_or_update_skillset.return_value = MagicMock(name="pdf-chunks-skillset")
    mock_indexer_client.create_or_update_indexer.return_value = MagicMock(name="pdf-chunks-indexer")

    service = SearchPipelineSetupService()
    service.setup_pipeline()

    # Verify DataSource creation
    mock_indexer_client.create_or_update_data_source_connection.assert_called_once()
    ds_arg = mock_indexer_client.create_or_update_data_source_connection.call_args[0][0]
    assert ds_arg.name == service.datasource_name
    assert ds_arg.type == "azureblob"
    assert ds_arg.container.name == service.blob_container_name

    # Verify Index schema
    mock_index_client.create_or_update_index.assert_called_once()
    index_arg = mock_index_client.create_or_update_index.call_args[0][0]
    assert index_arg.name == service.index_name
    field_names = [f.name for f in index_arg.fields]
    assert "id" in field_names
    assert "parentDocumentId" in field_names
    assert "fileName" in field_names
    assert "page" in field_names
    assert "sourceUrl" in field_names
    assert "content" in field_names
    assert "text_vector" in field_names

    # Check vector field dimensions
    vector_field = next(f for f in index_arg.fields if f.name == "text_vector")
    assert vector_field.vector_search_dimensions == 1536
    assert vector_field.vector_search_profile_name == "hnsw-profile"
    assert index_arg.semantic_search.default_configuration_name == "document-content-semantic"
    semantic_config = index_arg.semantic_search.configurations[0]
    assert semantic_config.name == "document-content-semantic"
    assert semantic_config.prioritized_fields.title_field.field_name == "fileName"
    assert semantic_config.prioritized_fields.content_fields[0].field_name == "content"

    # Verify Skillset & IndexProjections
    mock_indexer_client.create_or_update_skillset.assert_called_once()
    skillset_arg = mock_indexer_client.create_or_update_skillset.call_args[0][0]
    assert skillset_arg.name == service.skillset_name
    assert len(skillset_arg.skills) == 2

    layout_skill, embedding_skill = skillset_arg.skills

    # Document Intelligence layout extraction runs first, so reading order
    # (RTL included) comes from the layout-aware skill instead of the
    # default OCR/content cracking.
    #
    # outputMode is always "oneToMany" for this skill - there's no flat
    # single-string output. outputFormat must be "text" (not the default
    # "markdown") to get a chunk object with a real "content" string;
    # markdown mode's output ("markdown_document") has no such field, so a
    # downstream skill reading it as scalar text always gets nothing.
    assert layout_skill.odata_type == "#Microsoft.Skills.Util.DocumentIntelligenceLayoutSkill"
    assert layout_skill.inputs[0].source == "/document/file_data"
    assert layout_skill.output_format == "text"
    assert layout_skill.outputs[0].target_name == "text_sections"
    assert layout_skill.chunking_properties.maximum_length == 2000
    assert layout_skill.chunking_properties.overlap_length == 500

    # The embedding skill must consume the layout skill's per-chunk content,
    # not raw/whole-document content - otherwise the layout extraction is
    # wired in but never actually used.
    assert embedding_skill.context == "/document/text_sections/*"
    assert embedding_skill.inputs[0].source == "/document/text_sections/*/content"

    # Without billing attached, DocumentIntelligenceLayoutSkill silently
    # produces no output past its small free quota - identity-based, not a
    # stored key, matching how every other service in this stack authenticates.
    cognitive_services = skillset_arg.cognitive_services_account
    assert cognitive_services is not None
    assert cognitive_services.odata_type == "#Microsoft.Azure.Search.AIServicesByIdentity"
    assert cognitive_services.subdomain_url == service.document_intelligence_endpoint

    assert embedding_skill.deployment_name == service.embedding_deployment
    proj = getattr(skillset_arg, "index_projection", None) or getattr(skillset_arg, "index_projections", None)
    assert proj is not None
    assert len(proj.selectors) == 1
    selector = proj.selectors[0]
    assert selector.target_index_name == service.index_name
    assert selector.parent_key_field_name == "parentDocumentId"
    assert selector.source_context == "/document/text_sections/*"
    selector_mappings = {m.name: m.source for m in selector.mappings}
    assert selector_mappings["content"] == "/document/text_sections/*/content"
    assert selector_mappings["text_vector"] == "/document/text_sections/*/text_vector"
    assert selector_mappings["page"] == "/document/text_sections/*/locationMetadata/pageNumber"
    assert selector_mappings["fileName"] == "/document/metadata_storage_name"
    assert selector_mappings["sourceUrl"] == "/document/metadata_storage_path"

    # Verify Indexer
    mock_indexer_client.create_or_update_indexer.assert_called_once()
    indexer_arg = mock_indexer_client.create_or_update_indexer.call_args[0][0]
    assert indexer_arg.name == service.indexer_name
    assert indexer_arg.target_index_name == service.index_name
    assert indexer_arg.skillset_name == service.skillset_name
    assert indexer_arg.output_field_mappings == []

    # The key must not come from the implicit default (base64 of the full
    # blob URL) - a long, non-ASCII file name percent-encodes far past
    # Search's 1024-character key limit. metadata_storage_name (the blob
    # name alone, never percent-encoded, unique within the container) keeps
    # this bounded regardless of file name length or script.
    assert len(indexer_arg.field_mappings) == 1
    key_mapping = indexer_arg.field_mappings[0]
    assert key_mapping.source_field_name == "metadata_storage_name"
    assert key_mapping.target_field_name == "id"
    assert key_mapping.mapping_function.name == "base64Encode"
