# Corpus datasheet — ITR Slice 1

Task 17 · owner: Sutej · recorded the day the dimension was chosen.

## What is in the corpus

Canonical `itr360.message` rows only — Gmail is the single source in Slice 1.
Nothing raw is indexed: chunking reads `message.body_redacted`, which has
already been through `scout.governance.pii.redact()` on the way into canonical
(Task 12/13). KB articles and runbooks ride the same pipeline later.

## Chunking strategy — parent/child

| | Unit | Rough target | Purpose |
|---|---|---|---|
| **Parent** | paragraph block (blank-line separated); the whole body when the message has no blank lines | up to `PARENT_MAX_TOKENS` (~1000 tok) before it is cut at a sentence boundary | context that is **displayed** with a hit, never embedded |
| **Child** | sentence-aligned sliding window inside a parent | `CHILD_TARGET_TOKENS` ≈ 300 tok, `CHILD_OVERLAP_TOKENS` ≈ 50 tok | the unit that is **embedded and retrieved** |

Constants live in `scout.context.chunk` and are overridable per call. They are
chunking *geometry*, not pinned model config — changing them makes an existing
index inconsistent, not wrong.

Splitting is stdlib `re` only. No tokeniser or NLP dependency was added for
Task 17; token targets are converted to characters at `CHARS_PER_TOKEN = 4`.
A "sentence" longer than 1.5× the child window falls back to a fixed-width
split so a wall-of-text email still produces usable children.

### Offsets and citation

Every `Chunk` carries `start_offset` / `end_offset` into the original
`body_redacted`, with the exactness guarantee

```
body_redacted[chunk.start_offset:chunk.end_offset] == chunk.child_text
```

This is what lets Task 18 cite a specific sentence in a specific message
rather than a whole email, and what Task 19a's `evidence_spans` are expressed
in. It is also why drafting at Task 19b can refuse to make an uncitable claim.

### ACL tags

Each chunk carries `acl_tags` (`["tenant:<uuid>", "org:<uuid>"]`) plus
`case_id`, `person_id` and `tenant_id`. These exist so the Task 18 trust filter
can filter **at query time** as an index-side payload filter. Filtering after
retrieval is how restricted content ends up in an LLM prompt.

## Embedding model and dimension

Both are read from config; neither is written as a literal in code, in tests,
or in this document:

- model — `scout.config.settings.embed_model`
- dimension — `scout.config.settings.embed_dims`
- batch size — `scout.config.settings.embed_batch`
- endpoint — `scout.config.settings.embed_base_url`

Embeddings go **direct to OpenAI**, not through OpenRouter: OpenRouter routes
chat/completions and has no `/embeddings` endpoint. That is why `.env.local`
carries two keys (`OPENAI_API_KEY` and `OPENROUTER_API_KEY`) rather than one.
See `docs/decisions/ADR-002-embedding-model.md`.

Only `child_text` is embedded. Text is passed through `pii.redact()` once more
immediately before dispatch — defence in depth, and the reason `EmbeddedChunk`
records `embedded_text` alongside the vector.

## EMBED_DIMS is pinned and irreversible

`settings.embed_dims` is fixed for the life of the corpus. It is written into
the vector collection's schema at creation, so once real vectors exist:

- changing it invalidates **every** stored vector — a query embedded at the new
  dimension cannot be compared with a corpus embedded at the old one;
- recovering means dropping the collection and **re-embedding the entire
  corpus** from `itr360.message`, at full API cost and full wall-clock;
- the same applies to changing `settings.embed_model`, even at the same
  dimension — different models produce incomparable vector spaces.

Changing either value is a migration, not a config tweak. It needs a new ADR
and a planned re-embed, not a `.env.local` edit.

## Known limits (Slice 1)

- Retrieval is vector-only. No BM25 leg, no graph leg, no reranker — those are
  meaningless against one source and arrive in Slice 3.
- The "input must already be redacted" contract is enforced by a heuristic
  (`chunk.looks_unredacted` catches bare email addresses and unmasked long
  digit runs). It cannot detect an unredacted personal name. The real
  guarantee is that callers pass `body_redacted`, and that redaction fails
  closed upstream.
- A batch that fails twice at the embeddings endpoint is skipped and logged,
  not retried forever — those chunks are simply absent from the index until
  the message is reprocessed.
