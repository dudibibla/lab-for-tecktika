# Pipeline & Data Engineering Plan (`plan.md`)

* **Goal**: Implement the event-driven ingestion, indexing, and routing worker responsible for processing PDFs, managing job states, ensuring idempotency, triggering Azure AI Search Integrated Vectorization, and executing surgical deletions.

---

## Task Breakdown & Implementation Steps

### Phase 1: Local Emulation & Setup
* [ ] **1.1 Azurite Environment**: Configure `docker-compose.local.yml` to run Azurite locally for Blob, Queue, and Table storage emulation.
* [ ] **1.2 Worker Scaffolding**: Initialize the Python Azure Functions v2 project structure (`worker/`) with `host.json` and `local.settings.json` targeting `UseDevelopmentStorage=true`.
* [ ] **1.3 Data Models**: Define Pydantic models for queue messages (ingestion/deletion events) and Table Storage job entities (`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`).

### Phase 2: Core Ingestion & State Machine
* [ ] **2.1 Queue Trigger Function**: Implement the base `function_app.py` queue-triggered function to consume messages from the storage queue.
* [ ] **2.2 State Machine Transitions**: Implement logic to update Table Storage job status from `QUEUED` $\to$ `RUNNING` upon pickup.
* [ ] **2.3 ETag Idempotency (No-op)**: Integrate Blob client checks to extract the file's ETag. Skip reprocessing if the stored ETag matches the previously indexed state, preventing redundant workloads.

### Phase 3: Search Integration & Surgical Cleanups
* [ ] **3.1 Integrated Vectorization Orchestration**: Document chunking strategy (size and overlap) in `LIMITATIONS.md` and trigger the managed Azure AI Search Indexer run (`SearchIndexerClient.run_indexer()`) on new/updated content.
* [ ] **3.2 Surgical Deletion**: Implement OData filter deletion queries to wipe all child chunks matching `ParentDocumentID eq '{document_id}'` from Azure AI Search when a delete event is processed.

### Phase 4: Resilience, Reporting, and Backfill
* [ ] **4.1 Dead Letter Queue (DLQ)**: Add robust error handling to route unrecoverable or poison messages to the Dead Letter Queue (`{queue}-poison`) after max dequeue retries, updating job status to `FAILED`.
* [ ] **4.2 Run Reporting**: Generate structured execution logs and summary reports at the end of each worker batch (recording counts for indexed, skipped, and failed files).
* [ ] **4.3 Reconciliation & Backfill**: Write a scheduled/on-demand utility function to perform a full library backfill and reconcile discrepancies between Blob Storage and the search index.
> **מסמך היסטורי.** זו תכנית העבודה המקורית ואינה משקפת את מצב המימוש. הרכיבים המפורטים כאן הושלמו או השתנו. למצב הנוכחי ראו [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md) ו-[SUMMARY.md](SUMMARY.md).
