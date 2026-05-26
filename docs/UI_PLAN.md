# wiki-genres UI: drill-down graph explorer

**Status:** implemented static explorer, API-backed radial drill UI.
**Owner:** koopakondra
**Last revised:** 2026-05-22

---

## 1. Goals & non-goals

### Goals
- **Drill into the genre graph** starting from a root ("Music") and clicking one genre at a time to reveal its children.
- **Stay lightweight.** No build step. No SPA framework. Single static page served by the FastAPI app.
- **Be self-explanatory.** Anyone with the URL should understand the interaction in under five seconds.
- **Dogfood the API.** Every data fetch goes through `/v1/*` — if the UI feels slow or awkward, that's a signal about the API.

### Non-goals (v1)
- No force-directed network visualisation (d3-force, cytoscape). The graph has cycles and millions of paths — a force layout would be a hairball.
- No multi-select, no compare view, no edit/admin actions.
- Mobile and tablet should keep the same graph interaction with adjusted panel placement.
- No URL state persistence beyond `?path=…` (no full SPA routing).

---

## 2. Navigation model

The graph in our DB is a DAG-with-cycles (a genre can be a subgenre of multiple parents). For navigation we project it onto a **drill-down tree**:

- At any moment the user has selected exactly one genre. Call this `current`.
- `current`'s **children** are computed from outbound edges:
  - `relation = 'subgenre'` ← first-class child
  - `relation = 'derivative'` ← first-class child (same weight, same look, same physics)
  - `relation = 'fusion_genre'` ← first-class child
  - other outbound relations (`stylistic_origin`, `influenced_by`, …) are listed in the detail card but are *not* children — they point backward in time, not forward.
- Clicking a child makes *it* the new `current`. Previous context remains visible in the graph itself.
- There are no visible breadcrumbs. URL path state exists only for restoration/sharing.

### The root

"Music" isn't a row in our DB (it's a Wikidata Q-ID for a concept, not a genre). We define the synthetic root client-side as a fixed list of curated top-level genres — rock, pop, hip hop, electronic, jazz, classical, R&B, country, folk, blues, metal, reggae, world, soundtrack, experimental. Resolved on first load via `/v1/resolve?title=Hip+hop` etc. — 15 round-trips cached.

**Why curated:** the data has no clean "top-level" signal. Wikidata `subclass_of` chains end at abstract concepts like "music" (Q638), not at human-meaningful roots. A hand-picked list is faster to ship and gives a better first impression.

### Cycles

Cycles are normal in this graph. We let users walk them; the internal URL path may contain `Electronic → House → Electronic` and that's fine. No de-duplication, no warning.

---

## 3. Layout

One SVG canvas, two visually distinct zones plus an HTML detail card. **Inspired by Gnoosic** — children orbit the current node with continuous spring motion, and the path back to the root reads as a linked chain.

```
┌─────────────────────────────────────────────────────────────────────────┐
│   ●───────●──────●───────●                              ┌──────────┐    │
│ Music  Electr.  House   Deep ◄ current                  │ DETAIL   │    │
│   ◄─── trail (linked chain, anchored to top) ───        │ CARD     │    │
│                       │                                  │  title   │    │
│                       ▼                                  │  q-id    │    │
│                                                          │  color   │    │
│              ┌─●─●─●─●─●─┐  ← children jiggle around    │  summary │    │
│              │   ●━━●    │     the current node          │  aliases │    │
│              │ ●  ◆  ●   │     (◆ = current)             │  origins │    │
│              │    ●●●    │                                │  ↗ wiki  │    │
│              └───────────┘                                └──────────┘    │
│                                                                           │
│  (footer: child counts, "this leaf has no children" empty state)          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Zones

| Zone | Implementation | Behaviour |
|---|---|---|
| **Prior context** | Existing graph nodes and spine edges remain visible in the same SVG | Static feel; previous context fades without becoming visible breadcrumb navigation. |
| **Cluster** | SVG group, force simulation with `forceManyBody` (repulsion) + `forceLink` to the current node + `forceCollide` + low `velocityDecay` | Continuously alive — `alpha` floor keeps the simulation simmering. Drag a node and it springs back. |
| **Detail card** | Plain HTML, top-right, 320 px wide | Title, QID badge, color swatch, summary, aliases, origins, "Open on Wikipedia ↗" |
| **Footer** | HTML below the SVG | "12 children · 4 subgenres · 6 derivatives · 2 fusion" counts |

The two simulations share an SVG `<svg>` but run as separate `d3.forceSimulation()` instances so the trail doesn't pull the cluster around.

### Empty / edge states

- **No children.** The current node sits alone in the cluster zone with a softly pulsing halo. A small line of text under it: "Deep house has no subgenres or derivatives in our data."
- **Unresolved edge.** The child still appears in the cluster (visible label, dimmer fill, no link arrow). Clicking it shows a tooltip "Not yet in the graph" instead of drilling. Surfacing them is honest about coverage gaps.
- **Loading.** New children fade in at low alpha and the simulation re-energises to `alpha = 0.8` for the dive-in animation.

---

## 4. Stack & deployment

| Layer | Choice | Why |
|---|---|---|
| **Framework** | None. Vanilla HTML + JS + CSS modules. | Zero SPA framework. ESM imports for d3-force. |
| **Physics** | **d3-force** (just the force module, ~15 KB minified+gzipped) | Smallest battle-tested force simulation. Gives the "jiggly Gnoosic" feel with three knobs: `forceManyBody`, `forceLink`, `velocityDecay`. We render to SVG ourselves — no rendering coupling. |
| **Rendering** | Plain SVG via DOM. No d3-selection. | SVG nodes are real DOM, so they get free CSS styling, accessibility (`<button>`/`<a>` for nodes), and we avoid d3's whole-suite weight. |
| **Styling** | Plain CSS, custom properties for theming. No Tailwind. | ~200 lines incl. node hover states. |
| **Bundling** | None. d3-force loaded from `esm.sh` CDN; our files served as-is. | Whole UI weighs < 50 KB. |
| **Hosting** | Mounted at `/explorer` by FastAPI via `StaticFiles`. | One container, one origin, no CORS. |

**File layout:**

```
src/wiki_genres/api/static/
  index.html      # ~120 lines: shell + svg container + detail card slot
  app.js          # ~400 lines: state, fetch, two force sims, render
  styles.css      # ~200 lines: layout, node skins, theme tokens
```

Mounted in `api/main.py`:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/explorer", StaticFiles(directory="src/wiki_genres/api/static", html=True), name="explorer")
```

(Mount after API routers so it doesn't shadow `/v1/*` or `/healthz`.)

### Why not `force-graph` or cytoscape?

- `force-graph` (vasturiano) is a higher-level wrapper that owns the whole viewport. It's tempting (~5 lines to render a graph), but it doesn't compose cleanly with our trail + detail-card layout — we'd be fighting its single-canvas assumption. Worth a second look if we ever go fullscreen.
- cytoscape.js is built for graph *analysis*, not bouncy UIs. Its default layouts (cose, grid) feel stiff. Wrong vibe.
- springy.js gives the right feel but is unmaintained.
- matter.js would be more fun (bouncing-off-walls physics) but it's ~80 KB and we'd reinvent half of d3-force on top.

---

## 5. Data flow

Every navigation step is two API calls, both already shipped in M2:

```
user clicks "Deep house" card
        │
        ▼
fetch GET /v1/genres/{id}/edges?direction=out&relation=subgenre
   ── then ──
fetch GET /v1/genres/{id}/edges?direction=out&relation=derivative
        │  (parallel)
        ▼
render child grid
        │
        ▼
fetch GET /v1/genres/{id}            ◄── for the detail card
        │
        ▼
render detail card
```

Two-phase render so the grid appears instantly while the card hydrates. ~80 ms p50 against the local API.

### Caching

Client-side caches keyed by genre id. They live for the page session so revisiting a previously loaded branch does not refetch.

### The synthetic root

`/v1/resolve?title=…` for each of the 15 curated names. Done once on first load; cached in `sessionStorage` for the next page load. If `resolve` returns 404 for any (the bootstrap missed one), it's silently dropped from the root grid.

---

## 6. State & URL

Application state is just two pieces:

```javascript
{
  path: ["wg-q188451", "wg-q188450", "wg-q12345"],   // ids, root first
  cache: Map(...)
}
```

URL reflects the internal path: `?path=wg-q188451,wg-q188450,wg-q12345`. On load, parse the path and walk it through the cache.

This gives shareable links (`https://wiki-genres.example.com/?path=…`) without a router.

---

## 7. Physics & motion

### Two simulations, same SVG

```javascript
// Trail: anchored chain of small nodes at the top.
const trailSim = d3.forceSimulation(trailNodes)
  .force("y",   d3.forceY(60).strength(1.0))      // pin to y = 60
  .force("x",   d3.forceX((d, i) => 80 + i * 120).strength(0.8))
  .force("link", d3.forceLink(trailLinks).distance(120).strength(0.6))
  .force("collide", d3.forceCollide(24))
  .alpha(0.3).alphaDecay(0.05);                   // settles quickly

// Cluster: children orbiting `current`, never quite at rest.
const clusterSim = d3.forceSimulation(clusterNodes)
  .force("link",    d3.forceLink(clusterLinks).distance(140).strength(0.5))
  .force("charge",  d3.forceManyBody().strength(-380))   // siblings repel
  .force("center",  d3.forceCenter(cx, cy).strength(0.05))
  .force("collide", d3.forceCollide(d => d.r + 8))
  .velocityDecay(0.22)                            // motion lingers (default 0.4)
  .alphaMin(0)                                    // never auto-stop
  .on("tick", () => {
    if (clusterSim.alpha() < 0.04) clusterSim.alpha(0.04);  // gentle simmer
    render();
  });
```

### Feel knobs (the things to tweak when it doesn't feel right)

| Knob | Default | Increase to get… |
|---|---|---|
| `charge.strength` | `-380` | More spread between siblings |
| `link.distance` | `140` | Children farther from current |
| `link.strength` | `0.5` | Tighter cluster (children snap back faster) |
| `velocityDecay` | `0.22` | Less jiggle (`0.4` = standard, `0.1` = drifting) |
| Persistent alpha floor | `0.04` | More ambient motion (set to `0` to actually settle) |

### Transitions between states

When the user clicks a child:

1. **Selected child grows** to current-node size over 200 ms.
2. **Current node + non-selected siblings fade out** over 200 ms.
3. **Old current slides into the trail** (its position interpolated to the new trail end-point).
4. **New children spring outward from the new current** — they're created at `(cx, cy)` with random initial velocity, simulation kicks to `alpha = 0.9`.

The whole transition takes ~400 ms; cumulative, not stacked, so it stays snappy.

### Drag interaction

Cluster nodes are draggable. While dragged, the node's `fx/fy` are set; on release, they're cleared and the simulation re-energises. Yanking a node around the cluster is the most satisfying part of Gnoosic, and we should keep it.

## 8. Visual treatment

### Colour

- Background: near-white (`#fafafa`) light mode; near-black (`#0c0c0c`) dark mode via `prefers-color-scheme`.
- Nodes: small filled circles (12 px radius for children, 22 px for current, 8 px for trail). Fill = `infobox_color` if present, neutral grey otherwise. Label sits to the right of the node.
- Links (the lines): hairline (1 px) at 30% opacity; thicker (2 px) and 60% opacity for the trail.
- Current node halo: 1 px outline at 100% accent colour.
- No relation badges in the cluster — derivatives and subgenres look identical. The detail card lists every outbound relation explicitly.

### Typography

System font stack (`-apple-system, Segoe UI, …`). One typeface, two weights (400/600). Sizes: 11 px (node labels), 13 px (footer), 14/16/20 px (detail card).

### Accessibility

- SVG `<circle>` nodes are wrapped in `<a xlink:href="?path=…">` so they're keyboard-focusable and screen-reader announced.
- The cluster has `role="application"` and `aria-label="Genre cluster: 12 children of Deep house"`.
- A toggle in the footer disables the persistent alpha floor for users who set `prefers-reduced-motion`. (Auto-disabled by default for them.)
- Keyboard nav: `Tab` cycles through children in DOM order (which we order by relation then label); `Enter` drills in; `Backspace` pops a level.

---

## 9. Implementation status

The shipped `/explorer` UI keeps the intended graph-first interaction:

- No visible breadcrumbs. The URL `?path=` is restoration/share state only.
- Synthetic `Music` root resolves a curated set of top-level genres through `/v1/resolve`.
- Genre drill-down fetches child edges from `/v1/genres/{id}/edges?direction=out`.
- Visible children are `subgenre`, `derivative`, and `fusion_genre`; unresolved edges remain visible but do not drill.
- Detail cards hydrate from `/v1/genres/{id}` when a node becomes current.
- Pan, zoom, node dragging, current-node emphasis, fading context, and radial growth are preserved.
- Mobile/tablet use a bottom detail panel; desktop uses a side detail panel.

## 10. Original phase plan

| Phase | Scope | Estimate |
|---|---|---|
| **U1 — static skeleton + d3-force spike** | HTML + CSS shell; hardcoded mock cluster of 8 nodes with the cluster simulation running. Validates the feel before any data. | ½ day |
| **U2 — live data + drill** | Wire to `/v1/genres/{id}/edges`. Click-to-drill: child grows, becomes new current, new children spring outward. Trail simulation appends. | 1 day |
| **U3 — detail card** | Top-right HTML card; summary, aliases, origins, color, Wikipedia link. | ½ day |
| **U4 — synthetic root + URL state** | Curated root cluster (15 top-level genres); `?path=` URL syncing; sessionStorage cache; back/forward browser button support. | ½ day |
| **U5 — polish** | Drag interaction, empty states, keyboard nav, `prefers-reduced-motion`, dark mode, accessibility audit. | 1 day |

Total: ~3.5 days of focused work.

---

## 11. Open questions

1. ~~**Should derivatives be children?**~~ **Answered: yes, equal weight.** They're not visually differentiated in the cluster; the detail card still lists them under their own relation heading.
2. **Inbound edges as a secondary panel?** "House appears as a stylistic origin of 47 other genres" is interesting. Could be a collapsible section under the detail card, or a "see who derives from this" button that swaps the cluster to inbound edges. Punt to U6 if there's demand.
3. **Should the URL use slugs (`?path=hip-hop,trap`) instead of QIDs (`?path=wg-q…`)?** Slugs are nicer but require resolver round-trips on load. Going with QIDs for v1.
4. **Root list curation — committed or configurable?** Hard-coded in `app.js` for v1. If a future use case wants a different starting set, expose it via `GET /v1/roots` (new endpoint).
5. ~~**Mount at `/` or `/explorer`?**~~ **Answered: `/explorer`.** Keeps `/` reserved for a future landing page.

---

## 12. What this isn't (yet)

Things explicitly punted to "if there's demand":

- **Search bar inside the UI.** Possible by hitting `/v1/search`. Useful but not the point of the explorer.
- **Side-by-side compare.** Two genres in two columns. Useful for journalism workflows; out of scope here.
- **Graph thumbnail / minimap.** Most exploratory graph UIs grow this naturally; deferred until people complain about losing context.
- **Sharing/embedding cards.** A "share this view" button copying the URL is enough for v1.
- **Edit / suggest.** This is a read-only mirror of Wikipedia. Edits happen upstream.
