# Replacing built-in document cracking with Document Intelligence

Status: **implemented and deployed.** The migration was proposed on 2026-09-09 and
then completed. The worker now provisions and uses Document Intelligence Layout
through the Azure AI Search skillset. Follow-up fixes corrected the skill output
mapping to `content`, connected the billing resource, and made item-level indexer
failures fail the job with their real details.

The sections below preserve the original investigation and design reasoning.
References to "proposed", "today", or an unmodified built-in cracking pipeline
describe the state before the migration.

## The problem, with evidence

Azure AI Search's built-in document cracking returns a PDF's text blocks in the
order they appear in the file, which is not the order a person reads them. On
right-to-left documents this is severe.

A study certificate was indexed and the agent was asked who it belongs to. It
answered with the head of the registrar's office — the person who *signed* the
document — and quoted the college's registration number as if it were her ID.

The chunk it read explains why. This is the indexed `content`, in order:

```
בברכה, ענבר לוי, ראש מינהל רישום וקבלת סטודנטים…   ← signature block, first
לכבוד: 207402850 דוד אליקים ביבלה                  ← the addressee
הרינו לאשר כי מר דוד אליקים ביבלה, זיהוי 207402850… ← the body, in the middle
Inbar Levy # Jerusalem Multidisciplinary College 580278851   ← signature trailer
```

Three things went wrong at once, and all of them come from extraction:

1. **Reading order is inverted.** The signature block precedes the addressee and
   the body. A model reading top-down meets the signatory first.
2. **The digital-signature trailer is indistinguishable from body text.** The
   Latin `Inbar Levy # … 580278851` reads like a labelled identity.
3. **Digits fuse with adjacent words** — `בשנה207402850הרינו` — so numbers stop
   being separable tokens for both search and the model.

None of this is the model being weak. The input genuinely says what it answered.

## What is configured today

`worker/services/search_indexer.py` builds the pipeline as:

| Component | Setting |
| --- | --- |
| Data source | `azureblob` over `pdf-library`, managed identity |
| Indexer parameters | `dataToExtract: contentAndMetadata`, **`parsingMode: default`** |
| Skillset | `SplitSkill` (pages, with overlap) → `AzureOpenAIEmbeddingSkill` (text-embedding-3-small, 1536d) |
| Projection | `IndexProjections`, one index document per chunk |

`parsingMode: default` is the built-in cracker. It is the single line responsible
for the text above, and it is free — it is included in the AI Search tier.

## What already shipped instead

The system prompt now tells the model what extracted text looks like and that a
name beside a signature, job title or issuing authority is the *issuer*, not the
subject; it must quote the sentence it relied on, and say when the text does not
answer rather than reaching for the nearest name.

That is a mitigation, not a fix. It makes the model defensive about a specific
failure shape. It does nothing for retrieval: the chunk still contains fused
digits, so a search for an ID number still will not match it well.

## Options

### A. `DocumentIntelligenceLayoutSkill` inside the existing skillset

Insert the skill ahead of `SplitSkill`. It returns layout-aware text — reading
order resolved, tables preserved, structure marked — which then flows into the
existing split and embedding steps unchanged.

- **For:** smallest change to the shape of the pipeline. The data source,
  projections and index schema all stay as they are.
- **Against:** the skill is preview, so it pins the setup script to a preview
  API version. Preview surfaces move.

### B. Extract in the Worker, index the result

When the Worker copies a file into `pdf-library`, it also calls Document
Intelligence `prebuilt-layout` directly and writes the extracted text alongside
the PDF. The indexer then reads that instead of cracking the PDF.

- **For:** no preview dependency, full control over the output, and the
  extraction becomes testable in isolation — which the current pipeline is not.
- **Against:** more moving parts. A second artefact per document to keep in step
  with the PDF, and the Worker grows a new failure mode that has to reach the
  job status.

### C. Do nothing further

The prompt mitigation stands. Answers stay vulnerable on RTL documents, and
retrieval on identifiers stays weak.

## Recommendation

**Option A**, unless the preview dependency is unacceptable to the team — in
which case B.

The reasoning is scope. A is a change to one skillset definition and a re-run of
`setup_search_pipeline.py`; everything downstream is untouched, and if it does
not help it is reverted by putting the old skillset back. B is the better
long-term design but introduces a second artefact and a new Worker failure path
for a benefit that A already delivers.

## Implementation sketch (Option A)

1. Add the layout skill to `create_or_update_skillset()` ahead of `SplitSkill`,
   feeding its text output into the split step's input.
2. Grant the Search service's managed identity access to the Document
   Intelligence resource, and add that resource to `infrastructure/`. It does not
   exist yet — this is new infrastructure, not a config change.
3. Pin the setup script to the API version the skill requires.
4. Re-run `worker/scripts/setup_search_pipeline.py`.
5. **Reset the indexer** before re-running it. Without a reset, unchanged blobs
   are skipped and the existing bad chunks stay in the index.

## Cost

This is the part that needs a decision, not just an implementation.

Built-in cracking is free. Document Intelligence `prebuilt-layout` is billed per
page, in the order of a few dollars per thousand pages — **check current pricing
before committing, it changes.** At the brief's own benchmark of 5,000 PDFs
(§3.5), assume a handful of pages each and the one-off backfill lands in the low
hundreds of dollars, with ongoing cost proportional to new documents only.

That figure belongs in the §3.5 cost answer either way, because it changes what
"indexing 1,000 PDFs" costs.

## How to verify it worked

Do not trust the indexer reporting success — that has misled us before.

1. Re-index the certificate and read the chunk back:
   `POST /indexes/pdf-chunks-index/docs/search` with `search=*` and
   `select=content`. **Do this from a script, not the shell** — Git Bash cannot
   render Hebrew and will make correct text look like mojibake.
2. Confirm the body sentence now precedes the signature block, and that
   `207402850` stands as its own token rather than fused into a word.
3. Ask the original question. The right answer names דוד אליקים ביבלה and cites
   the `הרינו לאשר כי` sentence.
