# Timeline Map Plan

## Goal

Add a timeline-based map that shows genre evolution chronologically instead of
as a spatial drill-down graph. The view should start from earlier
year-supported genres and trace lineage downward through descendants, making it
possible to read how a selected genre family developed over time.

The core challenge is not animation or physics. The core challenge is building
a reliable year-hint pass and a deterministic layout that places items on a
timeline while minimizing connection overlap.

## Non-Goals

- No force simulation.
- No force-like post-processing.
- No live physics settling.
- No browser-only inference pass.
- No raw "first year mentioned anywhere" extraction.
- No attempt to editorially rewrite Wikipedia's graph.

This needs to be a calculated chart: data in, scored positions and routed
connections out.

## Data Enrichment: Relevant Year Hints

The timeline needs a backend pass that extracts candidate years, scores them,
and stores the best usable temporal hint per genre. The important distinction
is that a relevant year for a genre is usually an origin, emergence, formation,
first-use, or peak-era clue. A random mentioned year in the article is not
enough.

Candidate sources:

- Infobox temporal origin fields.
- Infobox cultural origin strings with decade or year text.
- Lead paragraph sentences that say a genre originated, emerged, developed,
  began, appeared, was created, was pioneered, or rose in a specific period.
- Article body sections named `Origins`, `History`, `Development`, `Early
  history`, or close variants.
- Wikipedia categories with decade or century labels.
- Wikidata inception/start-time style statements where available.
- Title hints for pages like `1980s...`, `1990s...`, or `... in the 1970s`,
  but only as low-confidence support.

Scoring should be string-pattern based at first, with explicit reasons:

- High confidence:
  - infobox temporal origin has a parseable year or decade
  - sentence pattern says the genre "originated in", "emerged in", "developed
    in", or "began in" a year/decade/period
  - Wikidata gives a direct inception/start-time-like value
- Medium confidence:
  - origin/history section has a nearby year with origin verbs
  - lead paragraph has a decade near genre-identifying language
  - cultural origin string gives a place plus a parseable decade
- Low confidence:
  - category or title implies a decade/century
  - article mentions a genre-defining scene in a broad period without a direct
    origin verb

Each accepted hint should keep evidence:

- `genre_id`
- `year_start`
- `year_end`
- `year_kind` such as `origin`, `emergence`, `formation`, `first_use`, or
  `period`
- `confidence`
- `source_type`
- `source_field` or section title
- short evidence text
- parser reason code

The UI should be able to hide low-confidence items or show them as uncertain
bands rather than precise points.

## Timeline Graph Scope

The initial chart should be scoped from a selected genre or top-level domain:

- descendants from a selected ancestor
- ancestors and descendants around a selected genre
- a full top-level family such as Hip-hop, Electronic, Rock, or Pop

Edges should use the same approved relationship vocabulary as the explorer:

- `subgenre`
- `derivative`
- directional `fusion`
- valid related-genre evidence
- region-backed genre relationships where they represent real lineage

The chart should not display every known relationship at once. It should prefer
high-confidence lineage edges first, then reveal weaker or cross-family edges on
interaction.

## Deterministic Layout Model

The timeline is not a force graph. It should be calculated in fixed stages.

1. Build the visible subgraph.
2. Assign each node an x-position from its scored year:
   - exact year maps to a point
   - decade maps to the decade midpoint
   - broad period maps to a band midpoint with lower confidence styling
   - unknown year inherits a provisional slot from connected parents/children
     and is marked as undated
3. Create lineage layers from earliest roots toward later descendants.
4. Assign y-lanes with a crossing-minimization pass.
5. Route edges through deterministic corridors.
6. Render nodes and links directly from the calculated layout.

No node should move because another node is "pushing" it. If layout quality is
bad, the chart should recompute better lanes or edge routes.

## Lane Assignment

Use lanes to reduce visual crossings:

- Start with roots ordered by year, pageviews, and selected-lineage priority.
- Keep direct descendants near their strongest parent lane.
- Penalize lane changes that cross existing edges.
- Keep sibling groups adjacent when they share the same parent and similar
  dates.
- Let large families reserve more vertical space, but compress sparse years.
- Prefer stable lane IDs so a small filter change does not reshuffle the whole
  chart.

Suggested deterministic pass:

1. Topologically sort the visible graph by year, then lineage depth.
2. For each node, compute ideal lane from weighted parent lanes.
3. Place the node in the nearest available lane slot for its time bucket.
4. Run a limited barycentric reorder by year bucket to reduce crossings.
5. Freeze final lanes and generate edge routes.

Cycles should be broken for layout only, using the strongest chronological
direction. The underlying relationships remain unchanged.

## Edge Routing

Connections should read as chronological evolution lines, not a web of straight
segments.

Routing rules:

- Edges flow left-to-right from earlier to later years.
- Same-family edges get smooth direct routes.
- Cross-family edges route through shared vertical corridors.
- Dense bundles should share a corridor briefly, then split before endpoints.
- Edges should reserve lanes separately from node lanes so labels remain
  readable.
- Edge crossings are allowed only when routing around them would create a less
  readable chart.

The router should score candidate paths:

- fewer crossings
- shorter total path length
- fewer node-label intersections
- less overlap with unrelated edges
- lower bend count
- stable route relative to the previous chart state

This can be implemented without physics by testing several corridor choices
and picking the lowest-cost route.

## Node Placement Details

Node x-position should come from date, but labels need space:

- Use time buckets to prevent same-year pileups.
- Expand dense decades horizontally if the viewport has room.
- Allow a node to occupy a label-width-aware bounding box.
- Offset multiple same-year siblings vertically within their lane group.
- Render uncertain dates as bands or soft spans behind the node.
- Keep the selected lineage visually dominant without hiding context.

Pageviews can influence ordering within a year bucket, but should not override
chronology.

## UI Behavior

The timeline view should feel like a second map mode, not a replacement for the
current explorer.

Controls:

- selected genre / family title
- confidence filter
- relationship-type toggles
- date range control
- "selected lineage only" toggle
- show/hide uncertain dates
- hover detail with year evidence

Interaction:

- clicking a node selects it and updates the detail card
- hovering an edge shows relationship type and evidence
- low-confidence date badges expose the parsing reason
- clicking an uncertain date can open source evidence
- search opens the selected genre's timeline scope

The initial viewport should show the earliest visible genres on the left and
the selected or latest descendants toward the right. If the selected genre has
no confident year, it should still appear in a clearly marked inferred position.

## API Shape

Add a timeline endpoint after the enrichment pass exists:

```http
GET /v1/timeline?genre_id=wg-q8341&scope=descendants&min_confidence=medium
```

Response shape:

```json
{
  "root_id": "wg-q8341",
  "nodes": [
    {
      "id": "wg-q8341",
      "title": "Hip-hop",
      "year_start": 1973,
      "year_end": 1979,
      "year_confidence": "medium",
      "year_kind": "emergence",
      "year_evidence": "emerged in the Bronx during the 1970s",
      "x": 420,
      "y": 180,
      "lane": 4
    }
  ],
  "edges": [
    {
      "from": "wg-q11401",
      "to": "wg-q8341",
      "relation": "derivative",
      "confidence": "high",
      "route": [[120, 180], [260, 180], [420, 180]]
    }
  ]
}
```

The server can return layout coordinates so the browser remains a renderer.
That keeps the chart reproducible and testable.

## Implementation Phases

### Phase 1: Year Hint Extractor

- Add staging table for year candidates.
- Parse infobox temporal and cultural origin strings.
- Parse lead/history/origin sections with origin-verb scoring.
- Store all candidates with reasons and evidence text.
- Pick a best candidate per genre without deleting alternates.

### Phase 2: Timeline Query

- Build a visible subgraph from selected roots.
- Filter by relation type and year confidence.
- Include enough ancestor context to explain lineage.
- Return unresolved or undated nodes with explicit status.

### Phase 3: Layout Engine

- Assign date x-positions.
- Assign deterministic y-lanes.
- Route edges through scored corridors.
- Emit node and edge layout data from the API.
- Add debug output for crossing count, label collisions, and route cost.

### Phase 4: UI Mode

- Add timeline mode switch.
- Render nodes, bands, and routed edges without force simulation.
- Add confidence controls and evidence hover states.
- Keep detail card behavior consistent with the current explorer.

### Phase 5: Review Workflow

- Export low-confidence or conflicting year hints for manual/GPT review.
- Let reviewed hints override parser guesses.
- Track parser version so old scores can be recomputed.

## Open Questions

- Should decade-level genres render at the decade midpoint or as a full decade
  band by default?
- How aggressively should low-confidence undated nodes be included in the first
  view?
- Should region-specific genres use local scene dates, parent genre dates, or
  both?
- How should the timeline handle genres whose article describes a revival
  period more clearly than an origin period?
- Should layout coordinates be generated at query time, cached by scope, or
  precomputed for common top-level families?
