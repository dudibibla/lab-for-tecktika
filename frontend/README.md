> **Current status (2026-09-16): implemented, tested and deployed.** The dev
> environment uses Azure Blob Storage behind the API; direct SharePoint/Graph
> integration remains future work. The backend contract is live, and historical
> open questions in [API.md](API.md) are superseded by its current-status note.
# lab-for-tecktika

AI Agent Chat — a React + TypeScript front end for querying a SharePoint PDF
library in natural language and managing the files in it.

## Running it

```bash
npm install
cp .env.example .env      # point VITE_DEV_API_PROXY at your backend
npm run dev               # http://localhost:5173
npm run build             # type-check + production bundle into dist/
npm run lint
npm test                  # vitest
```

The API contract this client is written against is in **[API.md](API.md)** — routes,
the SSE frame protocol, the shapes it tolerates, and the open questions for whoever
owns the server.

In dev, Vite proxies `/api` to `VITE_DEV_API_PROXY`. Sign-in is MSAL.js against
Entra ID directly (no local auth host needed) — set `VITE_AUTH_DEV_BYPASS=true`
to skip the sign-in gate entirely.

## How the requirements are met

**Everything goes through the conversation.** There is no file dashboard. A PDF
is an attachment on a message, not an upload action: picking one starts pushing
the bytes to storage immediately, so the send stays instant, but nothing happens
to the library until the message is sent and the agent has decided what the file
is for. Add, replace, update and delete are all the agent acting on a turn, and
the client never invents an action the agent did not propose.

**Auth (`src/services/auth.ts`, `src/services/apiClient.ts`).** Sign-in is
MSAL.js (`@azure/msal-browser`, public client, PKCE, no secret) against the
Entra ID app registration in `infrastructure/main.bicepparam`
(`entraTenantId`/`entraApiClientId`) — redirect flow, session cached in
`sessionStorage`. The session loads once on boot (a silent token acquisition
against the signed-in account), with concurrent callers de-duplicated.
`authorizedFetch` is the single choke point every API call goes through — it
attaches `Authorization: Bearer <token>`, and on a 401 or 403 retries a fresh
silent token acquisition and replays the request once. If that also fails (or
needs interaction) the user is sent into the MSAL sign-in redirect rather than
shown a status code. The exception is a 403 for someone who *is* signed in:
that is a permissions problem, and redirecting to a provider that will happily
sign them in again would loop, so it surfaces as an error.
>
> The backend must validate the bearer token itself — issuer
> `https://login.microsoftonline.com/<tenant>/v2.0`, audience either the raw
> client ID or `api://<client-id>` (see `frontend/API.md` §2). There is no Easy
> Auth host doing this for you.

**Streaming chat (`src/lib/sse.ts`, `src/services/chat.ts`, `src/hooks/useChat.ts`).**
`EventSource` cannot POST or set headers, so the stream is read from a `fetch`
POST body through a hand-rolled SSE parser that handles split chunks, CRLF,
keep-alive comments, multi-line `data:` and an unterminated tail. History loads
on mount into the React Query cache and streamed tokens patch that same cache, so
both paths converge on one message list. Deltas are buffered and flushed once per
animation frame rather than re-rendering per token. A backend that answers a
stream request with plain JSON still works.

**Two conversation identities, deliberately separate.** `threadId` is minted on
the client, is stable for the life of a conversation, and is the only thing the
React Query key is built from. `conversationId` is assigned by the backend and
travels in request bodies. Keying the cache on the server id meant the key
changed the moment that id arrived, abandoning the cache entry the stream was
writing into. The stream now reports the conversation id on its `start` and
`done` frames. "New conversation" mints a fresh `threadId` and skips the history
load — asking `/api/chat/history` without an id returns the most recent
conversation, which is the one being left behind — so the first message is what
brings the server-side conversation into existence.

**Session history.** Conversations are listed newest first in the composer footer,
each named after its opening message, and reopening one refetches its history. The
list lives in `localStorage` because the API has no conversations endpoint yet; if
one appears, this becomes the rendering layer for it and nothing else moves.

**A reply interrupted by a refresh is not lost.** The in-flight answer is written
to `localStorage` as it streams (at most once a second) and spliced back into the
transcript on the next load, marked as interrupted, if the server does not have
it.

**Non-blocking jobs (`src/providers/JobsProvider.tsx`).** A `jobId` is written to
`localStorage` the moment it appears. Polling lives in a provider mounted above
the app, not in the chat, which is what keeps the composer live throughout. It
backs off from 2s toward 15s, stops on a terminal state, continues while the tab
is in the background, and mirrors across tabs via the `storage` event. Each poll
result is folded back into the persisted record, so a refresh mid-job renders the
last known state immediately and resumes polling.

**Explicit confirmations (`ConfirmationCard.tsx`, `ConfirmationDialog.tsx`).**
Non-destructive asks resolve inline; anything destructive opens a modal. Both
list every affected file by name — never "this file" or a count — and every
destructive action requires typing a file name before the button unlocks, bulk
operations included. An action whose type the client does not recognise is
treated as destructive. Requests queue into a single modal slot, so two
`aria-modal` dialogs can never stack and fight over the focus trap. Decisions are
persisted against the backend's `confirmationId`, so a refresh cannot re-offer an
action the user has already answered, and a confirmation past its `expiresAt` locks
itself rather than staying clickable.

None of that is enforcement — it is an interlock for a human. The server issues the
`confirmationId`, binds it to an action and a file set, and must refuse to act
without one; the client never synthesises one. See [API.md §6.1](API.md).

**Large uploads (`src/services/blobUpload.ts`, `src/hooks/useFileUpload.ts`).**
Two steps: ask the API for a SAS URL, then PUT the bytes straight to storage, so
50MB+ files never pass through the API. Files over 32MB are staged as 8MB blocks
uploaded three at a time with per-block retry and committed with a block list — a
drop at 48/50MB retries one block, not the file. Progress comes from XHR upload
events. No `Authorization` header is ever sent to storage; the SAS token is the
credential.

**Citations (`CitationList.tsx`).** Numbered chips under the answer, expanding to
the matched snippet and a SharePoint deep link. Relevance is shown relative to
the best source in that answer: `@search.score` is an unbounded relevance score
rather than a probability, so rendering it as `score * 100` turned a score of
12.4 into "1240% match".

**Markdown.** Assistant replies render through `react-markdown` with GFM,
memoised so a stream frame re-parses only the message that is growing. Raw HTML
is off — `rehype-raw` is deliberately not installed, so markup inside a retrieved
document is text, not markup — and an element allowlist backs that up.

## Layout

```
src/
  services/      auth, apiClient (bearer interceptor), chat (SSE), files, jobs, blobUpload
  hooks/         useAuth, useChat, useFileUpload, useConfirmationQueue
  providers/     JobsProvider — persisted job registry + polling
  lib/           sse parser, localStorage helpers, queryClient, formatters
  components/    ChatWindow, MessageList/Bubble/Content, CitationList, Composer,
                 ConfirmationCard/Dialog, JobTray, AppHeader, ErrorBoundary
  types.ts       shared contracts
```

## Backend contract

Where the brief left the shape open, the service layer normalises tolerantly
rather than assuming one:

- **SSE frames** are accepted as typed events (`event: start|delta|citations|
  confirmation|job|error|done`) or untyped `data:` JSON carrying a `type` field;
  `[DONE]` ends the stream. Token deltas are read from `delta`, `text` or
  `content`. `start` and `done` may carry `conversationId`.
- **Job status** accepts `state` or `status`, and maps the usual vocabularies
  (`completed`/`success`/`done` → `succeeded`, `in_progress`/`processing` →
  `running`, …). `progress` may be 0-1 or 0-100.
- **Citations** accept `fileName`/`filename`/`name`, `url`/`webUrl`/`link`,
  `snippet`/`excerpt`/`content`.

Two things to confirm against the real API:

1. `POST /api/chat/message` accepts an `attachments` array of
   `{ fileId, fileName, size, blobPath }` for files already staged in storage,
   and `GET /api/chat/history` echoes them back on the message.
2. Something has to tell the backend the bytes have landed so it can index the
   PDF. This client assumes the agent does it, having been handed the `fileId` on
   the message. If the backend would rather have an explicit call, add a
   `finalize` step in `src/hooks/useFileUpload.ts`; nothing else moves.
   `POST /api/files/confirm-action` is never sent a synthesised
   `confirmationId` — only one the backend issued on a `confirmation` frame.

## Verification

`npm run build`, `npm run lint` and `npm test` all pass clean — 45 tests in four
files:

- `src/lib/sse.test.ts` — the SSE parser against chunk splits mid-field, CRLF
  framing, `:` keep-alives, multi-line `data:`, an unterminated tail, the
  single-leading-space rule, and abort.
- `src/services/normalise.test.ts` — the tolerated backend shapes, which are the
  client's half of [API.md](API.md): job state vocabularies, fractional vs
  percentage progress, citation aliases, and that an unrecognised confirmation
  action fails safe to destructive.
- `src/lib/confirmations.test.ts` — an answered confirmation is not re-offered
  after a reload, and expiry boundaries.
- `src/components/render.test.tsx` — the tree through `react-dom/server`: markdown
  renders rather than leaking its source, every file name appears on a bulk delete,
  a typed name is demanded, an expired confirmation refuses, and an unbounded
  relevance score never reaches the DOM as a percentage.

**The UI has not been exercised against a live backend.** Every backend-facing
assumption is listed in [API.md §7](API.md).
