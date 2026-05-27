# ChatGPT Pro playlist-option review workflow

This runbook defines a manual ChatGPT review loop for validating whether the
selected playlist option for each Wikipedia music genre is a faithful
representation of that genre.

The review unit is the playlist option, not each track. A partial track list is
provided only as evidence for judging the playlist's overall genre fit.

## Review objective

For every genre, decide whether the selected playlist option should be trusted
as a source playlist for that genre.

A playlist option is acceptable when the playlist as a whole appears to be a
focused, credible representation of the requested genre. It does not need every
sampled track to be perfect, but the sampled tracks, playlist title, owner, and
available metadata should support the same genre definition.

A playlist option should be rejected or flagged when it is:

- an adjacent, parent, child, fusion, regional, or successor style rather than
  the requested genre;
- a broad umbrella playlist for a narrow genre;
- a narrow artist/scene/era playlist for a broad genre, unless the selected
  genre is actually that narrow scene;
- only related by country, language, decade, mood, instrument, dance context, or
  artist association;
- a generic discovery, radio, hits, karaoke, covers, remixes, compilation, or
  algorithmic playlist that is not genre-specific;
- too ambiguous to distinguish from a neighboring genre using the supplied
  Wikipedia summary and sampled tracks.

## Batch sizing

Use small batches for accuracy. One row should represent one genre's selected
playlist option, with a sampled portion of the playlist's tracks embedded in the
row or provided on a companion sheet.

Recommended sequence:

1. Pilot batch: 25 genre playlist options.
2. Normal batch: 75 genre playlist options.
3. Large batch: 125 genre playlist options only after output consistency is
   proven.
4. Escalation batch: single-genre review for ambiguous microgenres, regional
   styles, fusion styles, or any playlist with a low-quality sample.

Do not ask ChatGPT to review thousands of playlist options in one message.
Large batches reduce attention to the genre summary and increase false accepts
for adjacent styles.

## Batch ordering

Review in this order:

1. High-pageview genres with selected playlist options.
2. Newer discovery groups.
3. Older discovery groups.
4. Low-pageview genres.
5. Genres with no selected playlist option should be exported separately as a
   discovery gap, not as a playlist-option faithfulness review.

Within each batch, sort by:

1. `genre_title`
2. `playlist_candidate_rank`
3. `playlist_title`

## Required workbook columns

Every review workbook should contain one row per genre playlist option.

Required genre columns:

- `batch_id`
- `genre_id`
- `wikidata_qid`
- `genre_title`
- `wikipedia_url`
- `wikipedia_summary`
- `monthly_views_p30`

Required playlist-option columns:

- `playlist_option_id`
- `playlist_url`
- `playlist_title`
- `playlist_owner`
- `playlist_description`
- `playlist_total_tracks`
- `playlist_sample_tracks`
- `playlist_discovery_group`
- `playlist_candidate_rank`
- `candidate_source_notes`

`playlist_sample_tracks` should be concise but informative. Prefer a newline,
semicolon, or JSON list with entries like:

```text
1. Artist — Track Title
2. Artist — Track Title
3. Artist — Track Title
```

Sample 15-30 tracks when possible:

- include the first 10 tracks;
- include 5-10 middle tracks;
- include 5-10 later tracks;
- include known high-confidence or suspicious tracks if the discovery pipeline
  surfaced them.

Recommended context columns:

- `genre_aliases`
- `infobox_color`
- `parent_genres`
- `child_genres`
- `stylistic_origins`
- `derivative_genres`
- `fusion_genres`
- `related_genres`
- `playlist_locale`
- `playlist_platform`

Required review output columns:

- `playlist_review_decision`
- `playlist_faithfulness_score`
- `confidence`
- `review_reason`
- `genre_definition_used`
- `sample_supporting_evidence`
- `sample_contradicting_evidence`
- `boundary_risk`
- `replacement_needed`
- `replacement_query`
- `manual_spotcheck_priority`

Allowed `playlist_review_decision` values:

- `accept_playlist`
- `accept_playlist_low_confidence`
- `reject_wrong_genre`
- `reject_too_broad`
- `reject_too_narrow`
- `reject_bad_playlist`
- `needs_human_review`

Allowed `playlist_faithfulness_score` values:

- `5`: strongly genre-specific and likely high-quality;
- `4`: good representation with minor uncertainty;
- `3`: plausible but needs sampling or later audit;
- `2`: weak, adjacent, too broad, or too narrow;
- `1`: wrong genre or unusable playlist.

Allowed `confidence` values:

- `high`
- `medium`
- `low`

Allowed `manual_spotcheck_priority` values:

- `none`
- `normal`
- `high`

## Output contract

ChatGPT should produce two downloadable files:

1. `playlist_option_review_decisions_<batch_id>.csv`
   - includes all input rows plus required review output columns.
2. `playlist_options_accepted_<batch_id>.csv`
   - includes only accepted playlist options for the downstream playlist
     expansion/import step.

The accepted playlist-options CSV must use these columns:

```csv
genre_id,playlist_option_id,playlist_url,playlist_title,playlist_owner,playlist_discovery_group,playlist_review_decision,playlist_faithfulness_score,confidence,review_reason
```

Use a new group label for reviewed output, for example:

```text
reviewed_gpt55_pro_playlist_option_faithfulness_20260526
```

Do not output a per-track import CSV from this review. Track-level import should
happen later from the accepted playlist option after local expansion,
deduplication, URL validation, and preflight checks.

## ChatGPT prompt

Paste this prompt into a new ChatGPT conversation with GPT-5.5 Pro selected.
Attach exactly one review workbook.

```text
You are reviewing selected playlist options for a public Wikipedia music-genre
graph.

Your task is to decide whether each selected playlist option is a faithful
playlist-level representation of the specified music genre. Be strict. The goal
is not to approve playlists that are merely pleasant, popular, adjacent, or
broadly related. Approve only playlist options that credibly represent the exact
genre named in the row.

Input file:
- One row per genre playlist option.
- The row represents the selected playlist option for that genre.
- The `wikipedia_summary` column is required evidence. Use it as the primary
  definition of the genre.
- The `playlist_sample_tracks` column is evidence only. Do not produce
  per-track decisions.
- Relationship columns such as parent/child/origin/derivative/fusion genres are
  context, not permission to accept adjacent styles.

Important constraints:
- Review the playlist as a whole, not individual tracks.
- Do not reject an otherwise accurate playlist because one sampled track is
  imperfect.
- Do not accept a playlist if the sample suggests the playlist mostly belongs
  to an adjacent, parent, child, regional, era-based, language-based, or
  mood-based category rather than the requested genre.
- Do not assume a playlist fits the genre merely because one artist or one track
  in the sample is genre-relevant.
- If the genre is a regional, ethnic, scene, dance, production, or fusion style,
  require the playlist sample and metadata to match that narrower meaning.
- If the playlist appears to be generic hits, radio, karaoke, covers, remixes,
  an artist-only playlist, a label catalog, or a broad mood/activity playlist,
  reject it unless the requested genre itself is that exact concept.
- If the playlist is plausible but the supplied evidence is too thin, mark it
  `accept_playlist_low_confidence` or `needs_human_review`; do not over-accept.
- Do not invent replacement playlist URLs. If replacement is needed, provide a
  search query only.

Review method:
1. Load the workbook with Python.
2. Validate that required columns exist.
3. For each row, write a compact genre definition from `genre_title` and
   `wikipedia_summary`.
4. Compare the playlist title, owner, description, and sampled tracks to that
   genre definition.
5. Assign:
   - `playlist_review_decision`
   - `playlist_faithfulness_score` from 1 to 5
   - `confidence` as high, medium, or low
   - `review_reason`, one concise sentence
   - `genre_definition_used`, one concise phrase or sentence
   - `sample_supporting_evidence`, short examples from sampled tracks/metadata
   - `sample_contradicting_evidence`, short examples or blank
   - `boundary_risk`, the nearest likely confusion genre/category or blank
   - `replacement_needed`, true or false
   - `replacement_query` if replacement is needed
   - `manual_spotcheck_priority` as none, normal, or high
6. Create a full decisions CSV and an accepted playlist-options CSV.

Decision labels:
- `accept_playlist`: playlist is a good source for this genre.
- `accept_playlist_low_confidence`: playlist is plausible but should be sampled
  later.
- `reject_wrong_genre`: playlist mainly represents a different genre.
- `reject_too_broad`: playlist represents a parent/umbrella/category broader
  than the requested genre.
- `reject_too_narrow`: playlist represents one artist, scene, country, era, or
  substyle too narrow for the requested genre.
- `reject_bad_playlist`: playlist is generic, low-signal, mismatched,
  compilation-like, karaoke/cover/remix-heavy, or otherwise not usable.
- `needs_human_review`: evidence is insufficient or the genre boundary is too
  subtle for confident model review.

Scoring rubric:
- 5 = strongly genre-specific and likely high-quality.
- 4 = good representation with minor uncertainty.
- 3 = plausible but needs sampling or later audit.
- 2 = weak, adjacent, too broad, or too narrow.
- 1 = wrong genre or unusable playlist.

Acceptance rule:
- Include `accept_playlist` and `accept_playlist_low_confidence` in the accepted
  playlist-options CSV.
- Exclude all other decisions.
- Keep `accept_playlist_low_confidence` rows in the full decisions CSV so they
  can be sampled later.
- Accepted playlist-options CSV must have this exact schema:
  `genre_id,playlist_option_id,playlist_url,playlist_title,playlist_owner,playlist_discovery_group,playlist_review_decision,playlist_faithfulness_score,confidence,review_reason`
- Set `playlist_discovery_group` to:
  `reviewed_gpt55_pro_playlist_option_faithfulness_YYYYMMDD`
- Do not create a per-track import CSV.

Quality checks before final answer:
- Report row counts by `playlist_review_decision`.
- Report accepted playlist-option count.
- Report rejected count by rejection reason.
- Report rows with missing required output fields.
- Report any duplicated accepted `genre_id` values.
- Report the 10 highest-risk accepted playlist options for manual spot check.
- Confirm that the accepted playlist-options CSV has only the exact accepted
  schema.

Return:
1. A concise summary of findings.
2. The two downloadable CSV files:
   - `playlist_option_review_decisions_<batch_id>.csv`
   - `playlist_options_accepted_<batch_id>.csv`
3. A short list of the 10 highest-risk accepted playlist options for later
   manual spot check.
```

## Follow-up prompt for stricter second pass

Use this only after ChatGPT produces the first decisions file. Attach the first
decisions CSV and paste:

```text
Perform a stricter second-pass audit of this playlist-option review decision
file.

Focus only on rows currently marked `accept_playlist` or
`accept_playlist_low_confidence`.

Downgrade any playlist option where the sampled tracks, playlist title, owner,
or description suggest the playlist is merely adjacent to the genre, too broad,
too narrow, regionally mismatched, era-mismatched, language/mood/activity-based,
artist-only, generic hits/radio, cover/remix/karaoke-heavy, or unsupported by
the supplied Wikipedia summary.

Do not make per-track decisions. Use sampled tracks only as evidence for the
playlist-level decision.

For every downgraded playlist option, update `playlist_review_decision`,
`playlist_faithfulness_score`, `confidence`, `review_reason`,
`sample_contradicting_evidence`, `boundary_risk`, and
`manual_spotcheck_priority`.

Then regenerate:
1. the full revised decisions CSV;
2. the accepted playlist-options CSV;
3. a summary of downgraded playlist options by reason.
```

## Local validation before expansion/import

Before expanding accepted playlist options into track rows:

1. Confirm accepted playlist-options columns are exact.
2. Confirm every `genre_id` is active in `wg_genres`.
3. Confirm every accepted row has one selected playlist URL.
4. Confirm there is at most one accepted playlist option per `genre_id` unless a
   deliberate multi-playlist policy is being tested.
5. Save rejected and low-confidence rows for later audit; do not discard them.
6. Expand tracks locally only from accepted playlist options.
7. Deduplicate expanded tracks per genre.
8. Convert expanded tracks into the project import schema:
   `genre_id,song_title,artist,youtube_url,ordinal,playlist_discovery_group`.
9. Run `playlist-preflight` after expansion/import to find blocked or broken
   videos.

## Accuracy policy

Prefer false negatives over false positives. It is better to reject a plausible
playlist option than to attach an adjacent-style playlist to the wrong genre.

For broad umbrella genres, accept broad playlists only when the playlist is
actually about that umbrella genre, not merely one descendant style.

For narrow microgenres and regional genres, reject parent-genre playlists unless
the playlist metadata and sampled tracks clearly match the narrow style.
