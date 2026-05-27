/**
 * wiki-genres explorer: API-backed radial drill graph.
 *
 * The UI intentionally stays graph-first: no visible breadcrumbs, no list
 * fallback, and no simplified tree. The URL path is only restoration state.
 */

import {
  forceSimulation,
  forceX,
  forceY,
} from "https://esm.sh/d3-force@3.0.0";
import {
  geoAlbersUsa,
  geoNaturalEarth1,
  geoPath,
} from "https://esm.sh/d3-geo@3.1.1";
import { feature, mesh as topoMesh } from "https://esm.sh/topojson-client@3.1.0";

const ROOT_KEY = "__music_root__";
const ROOT_TITLES = [
  "Rock music",
  "Pop music",
  "Hip hop music",
  "Electronic music",
  "Jazz",
  "Classical music",
  "Rhythm and blues",
  "Country music",
  "Folk music",
  "Blues",
  "Heavy metal music",
  "Reggae",
  "World music",
  "Soundtrack",
  "Experimental music",
  "Religious music",
  "Latin music",
];

const CHILD_RELATIONS = new Set(["subgenre", "derivative", "fusion_genre"]);
const RELATED_CHILD_RELATION = "related_genre";
const ORIGIN_PARENT_RELATION = "origin_parent";
const RELATION_RANK = new Map([
  ["subgenre", 0],
  ["derivative", 1],
  ["fusion_genre", 2],
  [ORIGIN_PARENT_RELATION, 3],
]);

const R = 210;
const SPINE_FACTOR = 2;
const CHILD_STAGGER_MS = 35;
const CHILD_PREWARM_MS = 160;
const PARENT_TRACE_AFTER_CHILD_REVEAL_MS = 120;
const CHILD_CLEARANCE_RATIO = 0.96;
const CHILD_CLEARANCE_MAX_WAIT_MS = 1000;
const SELECTED_EDGE_LENGTHEN_MS = 760;
const FETCH_RETRY_DELAYS_MS = [350, 900, 1800];
const FETCH_TIMEOUT_MS = 12000;
const STREAM_CONNECT_TIMEOUT_MS = 15000;
const STREAM_READ_TIMEOUT_MS = 15000;
const ROOT_RESOLVE_CONCURRENCY = 4;
const PARENT_TRACE_STEP_MS = 85;
const PARENT_TRACE_LINK_MS = 110;
const PARENT_TRACE_MAX_ANGLE_STEP = 0.28;
const PARENT_TRACE_SEGMENT_SCALE = 0.42;
const TRACE_PARENT_LINK_SCALE = 1.55;
const TRACE_INTERMEDIATE_LINK_SCALE = 0.56;
const TRACE_ROOT_HALF_ARC = Math.PI * 0.47;
const TRACE_ROOT_CENTER_GAP = 0.16;
const TRACE_LINE_CLEARANCE = 18;
const TRACE_LINE_CIRCLE_RADIUS = 20;
const TRACE_LINE_CIRCLE_SPACING = 92;
const TRACE_LINE_CIRCLE_REPEL_GAIN = 0.55;
const TRACE_LINE_CIRCLE_MAX_SAMPLES = 5;
const TRACE_LINE_MAX_LENGTHEN = 260;
const TRACE_LINE_MAX_BEND = 0.22;
const EDGE_GRADIENT_SELECTED_OVERSHOOT = 0.22;
const PARENT_CHILD_SWAP_CONFIDENCE = 0.34;
const RELATED_PARENT_CHILD_SWAP_MAX_PAGEVIEW_SCORE = 0.28;
const RELATED_PARENT_CHILD_SWAP_MIN_PARENT_DEPTH = 4;
const DERIVATIVE_PARENT_CHILD_SWAP_MAX_PAGEVIEW_SCORE = 0.22;
const DERIVATIVE_PARENT_CHILD_SWAP_MIN_PARENT_DEPTH = 3;
const YEAR_PARENT_LATER_TOLERANCE = 2;
const TRACE_INTERMEDIATE_COLLISION_SCALE = 2;
const NODE_LINE_CLEARANCE = 12;
const NODE_LINE_REPEL_STRENGTH = 0.42;
const LAYOUT_PRESSURE_MIN_OVERLAP = 4;
const LAYOUT_PRESSURE_CLUSTER_GAIN = 1.35;
const LAYOUT_PRESSURE_EDGE_GAIN = 1.0;
const LAYOUT_PRESSURE_GROWTH = 0.12;
const LAYOUT_PRESSURE_DECAY = 0.91;
const TRACE_SEGMENT_PRESSURE_GROWTH = 0.055;
const TRACE_SEGMENT_PRESSURE_DECAY = 0.985;
const TRACE_SEGMENT_PRESSURE_HOLD_TICKS = 6;
const LAYOUT_PRESSURE_EPSILON = 0.6;
const LAYOUT_PRESSURE_RELAYOUT_EPSILON = 0.55;
const TRACE_LAYOUT_PRESSURE_GAIN = 1.7;
const TRACE_LINE_PRESSURE_GAIN = 1.35;
const TRACE_ADJACENT_LINE_GROW_GAIN = 2.15;
const TRACE_LAYOUT_PRESSURE_ARC_GAIN = 2.15;
const TRACE_LAYOUT_PRESSURE_LENGTH_GAIN = 2.4;
const TRACE_LAYOUT_PRESSURE_LENGTH_MAX_RATIO = 0.62;
const TRACE_PROGRESSIVE_ARC_GAIN = 0.14;
const SELECTED_COLLISION_RELEASE_START_RATIO = 0.74;
const SELECTED_COLLISION_RELEASE_END_RATIO = 0.93;
const MANUAL_LENGTH_BLEND = 0.85;
const MANUAL_LENGTH_MAX_OFFSET = 360;
const RENDER_STABILIZE_ALPHA = 0.035;
const RENDER_STABILIZE_VELOCITY = 0.16;
const RENDER_STABILIZE_DEADBAND_PX = 0.42;
const GRAPH_RENDER_COORD_PRECISION = 10;
const TRACE_JITTER_SUPPRESS_ALPHA = 0.16;
const TRACE_JITTER_STEP_PX = 9;
const TRACE_JITTER_VELOCITY = 1.25;
const TRACE_JITTER_LOW_VELOCITY_JUMP = 0.12;
const TRACE_JITTER_HOME_RESET_PX = 6;
const TRACE_JITTER_SETTLE_COUNT = 2;
const WHEEL_ZOOM_STEP = 1.025;
const TRACKPAD_ZOOM_SPEED = 0.02;
const TRACKPAD_PAN_SPEED = 0.55;
const CURRENT_NODE_SCALE = 1.5;
const ANCESTOR_TRIM_THRESHOLD = 10;
const TRIM_ANIMATION_MS = 360;
const DETAIL_CARD_REAPPEAR_DELAY_MS = 1050;
const STORAGE_ROOTS_KEY = "wiki-genres:root-genres:v5";
const EXPLORER_SELECTION_STORAGE_KEY = "wiki-genres:explorer-selection:v1";
const YOUTUBE_PLAYBACK_STORAGE_KEY = "wiki-genres:youtube-playback:v1";
const YOUTUBE_AUTOPLAY_STORAGE_KEY = "wiki-genres:youtube-should-autoplay:v1";
const YOUTUBE_LEGACY_AUTOPLAY_PAUSED_KEY = "wiki-genres:youtube-autoplay-paused:v1";
const YOUTUBE_LEGACY_VOLUME_STORAGE_KEY = "wiki-genres:youtube-volume:v1";
const WORLD_ATLAS_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json";
const US_ATLAS_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json";
const MAP_VIEWBOX_DEFAULT = { x: 0, y: 0, w: 320, h: 174 };
const MAP_MIN_ZOOM = 1;
const MAP_MAX_ZOOM = 6;
const MAP_FIT_PADDING = 9;
const MAP_VIEWBOX_ANIM_MS = 420;
const MAP_FOCUS_MIN_OVERLAP = 18;
const MAP_FOCUS_OVERSCROLL = 16;
const MAP_PAN_SETTLE_DELAY_MS = 90;
const MAP_BUFFER_BASE_PX = 12;
const MAP_BUFFER_MAX_PX = 34;
const MAP_BUFFER_SMALL_RADIUS_PX = 20;
const MAP_BUFFER_SMALL_RADIUS_GAIN = 0.85;
const MAP_BUFFER_SELECTABLE_BONUS = 0.18;
const MAP_BUFFER_LARGE_AREA_PENALTY = 0.035;
const MAP_HOVER_SWITCH_SCORE_MARGIN = 0.22;
const MAP_DEFINITIONS = {
  world: {
    url: WORLD_ATLAS_URL,
    objectName: "countries",
    projection: "naturalEarth",
    viewBox: MAP_VIEWBOX_DEFAULT,
  },
  us: {
    url: US_ATLAS_URL,
    objectName: "states",
    projection: "albersUsa",
    viewBox: MAP_VIEWBOX_DEFAULT,
  },
};
const SEARCH_DEBOUNCE_MS = 180;
const MAP_COUNTRY_ALIASES = new Map([
  ["United States", "United States of America"],
  ["Czech Republic", "Czechia"],
  ["Bosnia and Herzegovina", "Bosnia and Herz."],
  ["North Macedonia", "Macedonia"],
  ["Dominican Republic", "Dominican Rep."],
  ["Central African Republic", "Central African Rep."],
  ["Democratic Republic of the Congo", "Dem. Rep. Congo"],
  ["Republic of the Congo", "Congo"],
  ["South Sudan", "S. Sudan"],
]);
const GEO_TERM_RULES = [
  { terms: ["american", "usa", "u.s.", "u.s.a.", "united states"], countries: ["United States"] },
  { terms: ["british", "uk", "u.k.", "united kingdom"], countries: ["United Kingdom"] },
  { terms: ["korean"], countries: ["South Korea", "North Korea"] },
  { terms: ["taiwanese"], countries: ["Taiwan"] },
  { terms: ["scandinavia", "scandinavian", "nordic"], countries: ["Norway", "Sweden", "Denmark", "Finland", "Iceland"] },
  { terms: ["british isles"], countries: ["United Kingdom", "Ireland"] },
  { terms: ["iberian", "iberian peninsula"], countries: ["Spain", "Portugal"] },
  { terms: ["benelux"], countries: ["Belgium", "Netherlands", "Luxembourg"] },
  { terms: ["balkan", "balkans"], countries: ["Greece", "Albania", "Bulgaria", "Bosnia and Herz.", "Croatia", "Macedonia", "Montenegro", "Serbia", "Slovenia"] },
  { terms: ["caribbean"], countries: ["Cuba", "Jamaica", "Haiti", "Dominican Rep.", "Puerto Rico", "Trinidad and Tobago"] },
  { terms: ["latin american", "latin america"], countries: ["Mexico", "Brazil", "Argentina", "Colombia", "Cuba", "Venezuela", "Peru", "Chile"] },
  { terms: ["south american", "south america"], countries: ["Brazil", "Argentina", "Colombia", "Venezuela", "Peru", "Chile", "Bolivia", "Paraguay", "Uruguay", "Ecuador"] },
  { terms: ["north american", "north america"], countries: ["United States", "Canada", "Mexico"] },
  { terms: ["west african", "west africa"], countries: ["Nigeria", "Ghana", "Senegal", "Mali", "Guinea", "Côte d'Ivoire"] },
  { terms: ["east african", "east africa"], countries: ["Kenya", "Ethiopia", "Tanzania", "Uganda", "Somalia"] },
  { terms: ["north african", "north africa"], countries: ["Morocco", "Algeria", "Tunisia", "Libya", "Egypt"] },
  { terms: ["south asian", "south asia"], countries: ["India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal"] },
  { terms: ["east asian", "east asia"], countries: ["China", "Japan", "South Korea", "North Korea", "Taiwan"] },
  { terms: ["southeast asian", "southeast asia"], countries: ["Indonesia", "Malaysia", "Philippines", "Thailand", "Vietnam", "Cambodia", "Laos", "Myanmar"] },
  { terms: ["middle eastern", "middle east"], countries: ["Turkey", "Egypt", "Iran", "Iraq", "Syria", "Israel", "Jordan", "Saudi Arabia"] },
  { terms: ["arab", "arabic"], countries: ["Morocco", "Algeria", "Tunisia", "Libya", "Egypt", "Saudi Arabia", "Iraq", "Syria", "Jordan"] },
  { terms: ["oceanian", "oceania"], countries: ["Australia", "New Zealand", "Papua New Guinea", "Fiji"] },
];
const GEO_CITY_RULES = [
  ["new york", "United States"], ["chicago", "United States"], ["detroit", "United States"], ["los angeles", "United States"],
  ["seattle", "United States"], ["nashville", "United States"], ["memphis", "United States"], ["new orleans", "United States"],
  ["atlanta", "United States"], ["miami", "United States"], ["baltimore", "United States"], ["toronto", "Canada"],
  ["montreal", "Canada"], ["vancouver", "Canada"], ["london", "United Kingdom"], ["liverpool", "United Kingdom"],
  ["manchester", "United Kingdom"], ["bristol", "United Kingdom"], ["berlin", "Germany"], ["hamburg", "Germany"],
  ["paris", "France"], ["marseille", "France"], ["madrid", "Spain"], ["barcelona", "Spain"], ["lisbon", "Portugal"],
  ["rome", "Italy"], ["milan", "Italy"], ["naples", "Italy"], ["stockholm", "Sweden"], ["oslo", "Norway"],
  ["helsinki", "Finland"], ["copenhagen", "Denmark"], ["amsterdam", "Netherlands"], ["rotterdam", "Netherlands"],
  ["brussels", "Belgium"], ["warsaw", "Poland"], ["athens", "Greece"], ["istanbul", "Turkey"], ["ankara", "Turkey"],
  ["moscow", "Russia"], ["cairo", "Egypt"], ["alexandria", "Egypt"], ["lagos", "Nigeria"], ["accra", "Ghana"],
  ["addis ababa", "Ethiopia"], ["nairobi", "Kenya"], ["johannesburg", "South Africa"], ["cape town", "South Africa"],
  ["mumbai", "India"], ["delhi", "India"], ["kolkata", "India"], ["chennai", "India"], ["bengaluru", "India"],
  ["karachi", "Pakistan"], ["lahore", "Pakistan"], ["dhaka", "Bangladesh"], ["colombo", "Sri Lanka"],
  ["beijing", "China"], ["shanghai", "China"], ["hong kong", "China"], ["taipei", "Taiwan"], ["tokyo", "Japan"],
  ["osaka", "Japan"], ["seoul", "South Korea"], ["pyongyang", "North Korea"], ["manila", "Philippines"],
  ["jakarta", "Indonesia"], ["bangkok", "Thailand"], ["hanoi", "Vietnam"], ["ho chi minh", "Vietnam"],
  ["kuala lumpur", "Malaysia"], ["sydney", "Australia"], ["melbourne", "Australia"], ["auckland", "New Zealand"],
  ["wellington", "New Zealand"], ["rio de janeiro", "Brazil"], ["sao paulo", "Brazil"], ["buenos aires", "Argentina"],
  ["bogota", "Colombia"], ["havana", "Cuba"], ["kingston", "Jamaica"],
].map(([term, country]) => ({ terms: [term], countries: [country] }));

const MODE_ICONS = {
  clockArrowDown: "clock_arrow_down",
  scatterPlot: "scatter_plot",
  mist: "mist",
  polyline: "polyline",
};

function setModeButtonIcon(button, iconName) {
  if (!button) return;
  let symbol = button.querySelector(".mode-symbol");
  if (!symbol) {
    symbol = document.createElement("span");
    symbol.className = "material-symbols-rounded mode-symbol";
    symbol.setAttribute("aria-hidden", "true");
    button.prepend(symbol);
  }
  symbol.textContent = MODE_ICONS[iconName] || "";
  button.dataset.iconName = iconName;
}

function setModeButtonLabel(button, label) {
  if (!button) return;
  let labelEl = button.querySelector(".mode-toggle-label");
  if (!labelEl) {
    labelEl = document.createElement("span");
    labelEl.className = "mode-toggle-label";
    button.append(labelEl);
  }
  labelEl.textContent = label;
}

function setModeButtonState(button, { icon, label, ariaLabel }) {
  if (!button) return;
  setModeButtonIcon(button, icon);
  setModeButtonLabel(button, label);
  button.setAttribute("aria-label", ariaLabel || label);
}

function readExplorerSelectionState(store = sessionStorage) {
  try {
    const parsed = JSON.parse(store.getItem(EXPLORER_SELECTION_STORAGE_KEY) || "null");
    if (!parsed || typeof parsed !== "object") return null;
    return {
      mode: typeof parsed.mode === "string" ? parsed.mode : "",
      path: typeof parsed.path === "string" ? parsed.path : "",
      timelineSelected: typeof parsed.timelineSelected === "string" ? parsed.timelineSelected : "",
      cloudRoot: typeof parsed.cloudRoot === "string" ? parsed.cloudRoot : "",
      cloudRegion: typeof parsed.cloudRegion === "string" ? parsed.cloudRegion : "",
      cloudSelected: typeof parsed.cloudSelected === "string" ? parsed.cloudSelected : "",
    };
  } catch {
    return null;
  }
}

function writeExplorerSelectionState(url = new URL(window.location.href), store = sessionStorage) {
  try {
    store.setItem(EXPLORER_SELECTION_STORAGE_KEY, JSON.stringify({
      mode: (url.searchParams.get("mode") || "").trim(),
      path: (url.searchParams.get("path") || "").trim(),
      timelineSelected: (url.searchParams.get("timeline_selected") || "").trim(),
      cloudRoot: (url.searchParams.get("cloud_root") || "").trim(),
      cloudRegion: (url.searchParams.get("cloud_region") || "").trim(),
      cloudSelected: (url.searchParams.get("cloud_selected") || "").trim(),
    }));
  } catch {}
}

function resolvedExplorerUrlState() {
  const url = new URL(window.location.href);
  const explicitMode = url.searchParams.get("mode");
  return {
    url,
    mode: (explicitMode || "").trim(),
    rawPath: (url.searchParams.get("path") || "").trim(),
    selectedTimeline: (url.searchParams.get("timeline_selected") || "").trim() || null,
    cloudRoot: (url.searchParams.get("cloud_root") || "").trim() || null,
    cloudRegion: (url.searchParams.get("cloud_region") || "").trim() || null,
    selectedCloud: (url.searchParams.get("cloud_selected") || "").trim() || null,
  };
}

const svg = document.getElementById("canvas");
const bootLoading = document.getElementById("boot-loading");
const cloudLabelCanvas = document.getElementById("cloud-label-canvas");
const cloudLabelCtx = cloudLabelCanvas?.getContext?.("2d") || null;
const panTarget = document.getElementById("pan-target");
const world = document.getElementById("world");
const edgesG = document.getElementById("edges-layer");
const nodesG = document.getElementById("nodes-layer");

const detailCard = document.getElementById("detail-card");
const cardRelation = document.getElementById("card-relation");
const cardTitle = document.getElementById("card-title");
const cardSummary = document.getElementById("card-summary");
const cardSynonyms = document.getElementById("card-synonyms");
const cardMeta = document.getElementById("card-meta");
const cardWikiLink = document.getElementById("card-wiki-link");
const cardTargetButton = document.getElementById("card-target-button");
const cardCloseButton = document.getElementById("card-close-button");
const detailRestoreButton = document.getElementById("detail-restore-button");
const detailCardSlot = document.getElementById("detail-card-slot");
const rightPanel = document.getElementById("right-panel");
const searchCard = document.getElementById("search-card");
const searchInput = document.getElementById("genre-search-input");
const searchResults = document.getElementById("genre-search-results");
const randomGenreButton = document.getElementById("random-genre-button");
const cloudToggleButton = document.getElementById("cloud-toggle-button");
const navControls = document.getElementById("nav-controls");
const navBackButton = document.getElementById("nav-back-button");
const navForwardButton = document.getElementById("nav-forward-button");
const timelinePanel = document.getElementById("timeline-panel");
const timelineCanvas = document.getElementById("timeline-canvas");
const timelineTitle = document.getElementById("timeline-title");
const timelineStatus = document.getElementById("timeline-status");
const timelineConfidence = document.getElementById("timeline-confidence");
const timelineToggleButton = document.getElementById("timeline-toggle-button");
const timelineCloseButton = document.getElementById("timeline-close-button");
const timelineYearRail = document.getElementById("timeline-year-rail");
const mobilePanelTabs = document.getElementById("mobile-panel-tabs");
const youtubeCard = document.getElementById("youtube-card");
const youtubeCloseButton = document.getElementById("youtube-close-button");
let youtubeFrame = document.getElementById("youtube-frame");
const youtubeFrameHost = youtubeFrame?.parentElement || null;
const youtubeGenreTitle = document.getElementById("youtube-genre-title");
const youtubeSongTitle = document.getElementById("youtube-song-title");
const youtubeArtistTitle = document.getElementById("youtube-artist-title");
const youtubeEmptyMessage = document.getElementById("youtube-empty-message");
const youtubeSubmitButton = document.getElementById("youtube-submit-button");
const youtubeVolumeControl = document.querySelector(".youtube-volume-control");
const youtubeVolumePanel = document.querySelector(".youtube-volume-panel");
const youtubeVolumeInput = document.getElementById("youtube-volume-input");
const youtubePauseButton = document.getElementById("youtube-pause-button");
const youtubeSkipButton = document.getElementById("youtube-skip-button");
const youtubePinIndicator = document.getElementById("youtube-pin-indicator");
const youtubeMenuButton = document.getElementById("youtube-menu-button");
const youtubeContextMenu = document.getElementById("youtube-context-menu");
const youtubePinButton = document.getElementById("youtube-pin-button");
const youtubeOpenButton = document.getElementById("youtube-open-button");
const youtubeFeedbackButton = document.getElementById("youtube-feedback-button");
const detailFeedbackButton = document.getElementById("detail-feedback-button");
const feedbackModal = document.getElementById("feedback-modal");
const feedbackModalTitle = document.getElementById("feedback-modal-title");
const feedbackForm = document.getElementById("feedback-form");
const feedbackContextEl = document.getElementById("feedback-context");
const feedbackNotes = document.getElementById("feedback-notes");
const feedbackStatus = document.getElementById("feedback-status");
const feedbackSubmitButton = document.getElementById("feedback-submit-button");
const feedbackCloseButton = document.getElementById("feedback-close-button");
const mobileDetailTab = document.getElementById("mobile-detail-tab");
const mobileMapTab = document.getElementById("mobile-map-tab");
const mapCard = document.getElementById("map-card");
const mapTitle = document.getElementById("map-title");
const mapParentLabel = document.getElementById("map-parent-label");
const mapParentLabelText = document.getElementById("map-parent-label-text");
const mapWorldButton = document.getElementById("map-world-button");
const mapListButton = document.getElementById("map-list-button");
const mapExpandButton = document.getElementById("map-expand-button");
const mapResetButton = document.getElementById("map-reset-button");
const mapListSearchInput = document.getElementById("map-list-search-input");
const mapListSearchButton = document.getElementById("map-list-search-button");
const regionMap = document.getElementById("region-map");
const mapList = document.getElementById("map-list");
const mapClipDefs = document.getElementById("map-clip-defs");
const mapCountryLayer = document.getElementById("map-country-layer");
const mapHighlightLayer = document.getElementById("map-highlight-layer");
const mapHitLayer = document.getElementById("map-hit-layer");
const mapPoints = document.getElementById("map-points");
const footerDepth = document.getElementById("footer-depth");
const footerZoom = document.getElementById("footer-zoom");
let footerZoomFill = document.getElementById("footer-zoom-fill");
let footerZoomLabel = document.getElementById("footer-zoom-label");
const footerHint = document.getElementById("footer-hint");
let footerZoomDragging = false;

const nodes = new Map();
const edges = [];
const detailCache = new Map();
const childrenCache = new Map();
const regionalCache = new Map();
const mapContextCache = new Map();
const reachableParentsCache = new Map();
let rootChildrenPromise = null;
const layoutPressureDebug = {
  maxOverlap: 0,
  clusterBoosts: [],
  edgeBoosts: [],
  traceBoosts: [],
  traceSegments: [],
};

let currentKey = ROOT_KEY;
let viewTx = 0;
let viewTy = 0;
let viewScale = 1;
let sim = null;
let tickTimer = null;
let layoutPressureFrame = 0;
let followMode = false;
let panAnimTimer = null;
let panInertiaTimer = null;
let focusToken = 0;
let activeLeafKey = null;
let restoringUrl = false;
let trimCleanupTimer = null;
let mapToken = 0;
let scheduledMapCardUpdateFrame = 0;
let scheduledMapCardUpdateTimer = 0;
let scheduledMapCardUpdateToken = 0;
let mapViewBox = { ...MAP_VIEWBOX_DEFAULT };
let mapAutoViewBox = { ...MAP_VIEWBOX_DEFAULT };
let mapAutoViewFeatureKeys = [];
let mapViewBoxAnimFrame = 0;
let mapViewManuallyAdjusted = false;
let mapPanFocusActive = false;
let mapPanSettleTimer = 0;
let mapGesturePointers = new Map();
let mapGestureLast = null;
let mapGestureMoved = false;
let hoveredMapCountry = null;
let hoveredMapCountries = new Set();
let mapDefaultLabel = "";
let mapDefaultVariationCount = 0;
let mapDisplayedWorldOverride = false;
let mapListMode = false;
let mapListViewState = null;
let mapListRenderToken = 0;
let mapListScrollFrame = 0;
let mapListDetailHidden = false;
let mapListSearchQuery = "";
let mapListSearchOpen = false;
let graphIsStill = true;
let graphStillTimer = null;
let hoveredNodeKey = null;
let detailCardNodeKey = null;
let detailIndicatorPreviewKey = null;
let detailCardSuppressed = false;
let holdDetailCardDuringLocate = false;
let detailCardMovementUntil = 0;
let detailCardMovementTimer = 0;
let manualUiDimPending = false;
let manualUiDimUntil = 0;
let manualUiDimTimer = 0;
let manualMovementGesture = null;
let manualWheelDistance = 0;
let manualWheelLastAt = 0;
let uiHoverRestoreUntil = 0;
let uiHoverRestoreTimer = 0;
let uiHovering = false;
const uiHoverRoots = new Set();
let activePointerButtons = 0;
let lastPointerClientX = Number.NaN;
let lastPointerClientY = Number.NaN;
let detailCardRenderedKey = null;
let detailCardIdleTimer = 0;
let detailCardHoverSwapActive = false;
let detailCardContentSwapTimer = 0;
let detailCardContentSwapToken = 0;
let detailCardHeightResetTimer = 0;
let detailCardTransitionClone = null;
let detailCardTransitionCleanupTimer = 0;
let hoverCardToken = 0;
let hoverCardDelayTimer = 0;
let pendingHoverCardKey = null;
let searchTimer = null;
let searchToken = 0;
let searchBusy = false;
let cloudMode = false;
let cloudData = null;
let cloudRootGenreId = null;
let cloudRegionId = null;
let cloudSelectedGenreId = null;
let cloudNodeEls = new Map();
let cloudTextEls = new Map();
let cloudNodeById = new Map();
let cloudScene = null;
let cloudVisibleNodeIds = new Set();
let cloudRenderFrame = null;
let cloudSceneDomPrepared = false;
let cloudRenderedLayerScale = null;
let cloudRenderedTextScale = 0;
let cloudRenderedWindowSignature = "";
let cloudCanvasFrame = 0;
let cloudCanvasDpr = 1;
let cloudCanvasNodes = [];
let cloudCanvasHitNodes = [];
let cloudCanvasVisibleIds = new Set();
let cloudCanvasAlphaById = new Map();
let cloudRenderSnapshot = null;
let cloudRenderTransition = null;
let cloudPresentationById = new Map();
let cloudPresentationLastAt = 0;
let cloudPresentationTargetSignature = "";
let cloudSelectedLabelAlphaById = new Map();
let cloudHoverUnderlineAlphaById = new Map();
let cloudRelationshipAlphaById = new Map();
let cloudBackgroundCache = null;
let cloudBackgroundBuildTimer = 0;
let cloudBackgroundBuildSignature = "";
let cloudFadeFrame = 0;
let cloudCanvasFadeFrame = 0;
let cloudSelectedLabelFadeFrame = 0;
let cloudHoverUnderlineFadeFrame = 0;
let cloudRelationshipFadeFrame = 0;
let cloudLabelSpriteCache = new Map();
let cloudCanvasStyleCache = null;
let cloudHoveredNodeId = null;
let cloudHoverCardDelayTimer = 0;
let pendingCloudHoverCardKey = null;
let cloudInitialRenderPending = false;
let cloudSelectedMarker = null;
let cloudSelectedMarkerFrame = 0;
let cloudClickEnabled = true;
let cloudClickEnableTimer = 0;
let cloudClickEnableAt = 0;
let cloudBounds = null;
let cloudRequestToken = 0;
let cloudFetchTimer = 0;
let cloudStreamController = null;
let cloudLastFetchAt = 0;
let cloudLastEffectiveLodScale = 0;
let cloudQueuedFetch = false;
let cloudLastFetchSignature = "";
let cloudQueuedFetchSignature = "";
let cloudStreamRetryAfter = 0;
let timelineMode = false;
let timelineToken = 0;
let timelineDataRequestToken = 0;
let timelineStreamController = null;
let timelineRefreshTimer = null;
let timelineData = null;
let timelineSelectedGenreId = null;
let timelineDetailCardOpen = false;
let timelineYearRows = [];
let timelineNodePositions = new Map();
let timelinePlacedPositions = new Map();
let timelineLoadedRank = 0;
let timelineLoadingRank = 0;
let timelineQueuedRank = 0;
let timelineRenderedSignature = "";
let timelineRenderedNodeIds = new Set();
let timelineRenderedEdgeKeys = new Set();
let timelineNodeDetailSignature = "";
let timelineYearMarkerSignature = "";
let timelineYearMarkerEls = new Map();
let timelineViewportFrame = null;
let timelineRenderFrame = null;
let timelineRenderTimer = null;
let timelineNeedsRender = false;
let timelineInteractUntil = 0;
let timelineInteractTimer = null;
let timelineNoFadeNextRender = false;
let timelineLastDataRefreshAt = 0;
let timelineLastDataSignature = "";
let timelineStreamRetryAfter = 0;
let timelineEdgeLayerEl = null;
let timelineNodeLayerEl = null;
let timelineGridLayerEl = null;
let timelineEdgeElByKey = new Map();
let timelineNodeElById = new Map();
let timelineLastStreamRenderAt = 0;
let timelineVisibilityCache = null;
let timelineVisibilityCacheData = null;
let timelineNodeByIdCache = null;
let timelineNodeByIdCacheData = null;
let timelineDecadeCache = null;
let timelineDecadeCacheData = null;
let timelineVisibility = {
  nodeRanks: new Map(),
  nodeScores: new Map(),
  nodeWidths: new Map(),
  edgeRanks: new Map(),
  edgesByNode: new Map(),
  focusNodeIds: new Set(),
  focusDistances: new Map(),
  sortedNodeIds: [],
  clusters: [],
};

const MAP_LIST_HEADER_HEIGHT = 26;
const MAP_LIST_ITEM_HEIGHT = 56;
const MAP_LIST_OVERSCAN_PX = 160;
const MAP_LIST_CONTENT_TOP_PAD = 6;
const MAP_LIST_CONTENT_BOTTOM_PAD = 10;
const MAP_LIST_ICON_WIDTH = 38;
const MAP_LIST_ICON_HEIGHT = 26;
const MAP_LIST_TOP_INSET = 40;
const MAP_LIST_PARENT_TOP_INSET = 64;
const MAP_LIST_BOTTOM_INSET = 10;
const MAP_LIST_MIN_CARD_HEIGHT = 180;
const MAP_LIST_DETAIL_GAP_PX = 18;

function timelineIsInteracting() {
  return Date.now() < timelineInteractUntil || document.body.classList.contains("is-panning-canvas");
}

function markTimelineInteracting() {
  if (!timelineMode) return;
  markDetailCardMoving(520);
  timelineInteractUntil = Date.now() + 120;
  timelineNeedsRender = true;
  scheduleTimelineDataWindowRefresh({ allowDuringInteraction: true });
  timelineNoFadeNextRender = false;
  if (timelineInteractTimer) return;
  timelineInteractTimer = window.setTimeout(() => {
    timelineInteractTimer = null;
    if (!timelineMode) return;
    if (timelineIsInteracting()) {
      markTimelineInteracting();
      return;
    }
    if (timelineNeedsRender) {
      timelineNeedsRender = false;
      scheduleTimelineRender({ urgent: true, noFade: false });
    }
  }, 140);
}
let youtubeItems = [];
let youtubeIndex = 0;
let youtubePaused = false;
let youtubePlaylistKey = "";
let youtubePlaybackNode = null;
let youtubePinned = false;
let youtubeDeferredSelectionNode = null;
let youtubeCardHovered = false;
let youtubeHoverCardToken = 0;
let youtubeLoadToken = 0;
let youtubeErrorTimer = 0;
let youtubeReadyTimer = 0;
let youtubeProgressTimer = 0;
let youtubeStatePollTimer = 0;
let youtubeTrackLoading = false;
let youtubeErroredUrls = new Set();
let youtubeReportedFailureTokens = new Set();
let youtubePlaybackErrorExhausted = false;
let youtubeDevPlaybackStatus = "";
let youtubeResumeSeconds = 0;
let youtubeLastKnownSeconds = 0;
let youtubeTrackStartedAt = 0;
let youtubeIsPlaying = false;
let youtubeAutoplayBlocked = false;
let youtubePlayRequested = false;
let youtubeUserPaused = readYoutubeUserPaused();
// `youtubeVolume` is the user target. `youtubeAppliedVolume` is only the
// transient value used for fade-in/fade-out ramps.
let youtubeVolume = readYoutubeVolume();
let youtubeAppliedVolume = youtubeVolume;
let youtubeVolumeFadeFrame = 0;
let youtubeVolumeFadeToken = 0;
let youtubePlaylistTransitionToken = 0;
let youtubeVolumePanelCloseTimer = 0;
let youtubeVolumePanelMounted = false;
let youtubeApiLoading = false;
let youtubeApiReady = false;
let youtubePlayer = null;
let youtubeDeferredLoadIndex = null;
const YOUTUBE_REPORTABLE_ERROR_CODES = new Set(["2", "5", "100", "101", "150"]);
let feedbackKind = "relationship";
let historyNavigating = false;
let appHistoryEntries = [];
let appHistoryIndex = -1;
let appNavigatingHistory = false;
const mapFeaturePromises = new Map();
const mapTopologyPromises = new Map();
let activeMapKey = null;
let activeMapTopology = null;
let activeMapTopologyObject = null;
let activeMapPath = null;
let mapParentTargetKey = null;
let mapParentTargetCloud = null;
let mapContextOwnerKey = null;
const countryElsByName = new Map();
const countryHighlightElsByName = new Map();
const countryHitElsByName = new Map();
const countryAreaByName = new Map();
const countryBoundsByName = new Map();
const countryBoundarySamplesByName = new Map();
const mapItemsByCountryName = new Map();
const mapHoverCountriesByCountryName = new Map();
const mapSuperregionCountriesByGroupKey = new Map();
const mapSuperregionGroupKeyByCountryName = new Map();
const mapSuperregionBorderElsByGroupKey = new Map();
const mapCountryRenderStateByName = new Map();
const mapSuperregionRenderStateByKey = new Map();
const MIN_VIEW_SCALE = 0.12;
const MAX_VIEW_SCALE = 3.0;
const GRAPH_MIN_VIEW_SCALE = 0.25;
const GRAPH_MAX_VIEW_SCALE = 1.0;
const GRAPH_AUTO_MIN_VIEW_SCALE = 0.4;
const GRAPH_AUTO_MAX_VIEW_SCALE = 0.7;
const CLOUD_MAX_VIEW_SCALE = 1.1;
const UI_HOVER_SELECTOR = "#nav-controls, #map-card, #right-panel, #timeline-panel, #mobile-panel-tabs, #detail-restore-button, #footer-zoom, #youtube-context-menu, .youtube-volume-panel, #feedback-modal";
const UI_HOVER_RESTORE_HOLD_MS = 950;
const DETAIL_CARD_RADIO_IDLE_MS = 45000;
const DETAIL_HOVER_SWAP_DELAY_MS = 300;
const CLOUD_HOVER_DETAIL_SWAP_DELAY_MS = DETAIL_HOVER_SWAP_DELAY_MS + 140;
const CLOUD_HOVER_UNDERLINE_FADE_IN_MS = 260;
const CLOUD_HOVER_UNDERLINE_FADE_OUT_MS = 180;
const GRAPH_LABEL_Y = 0;
const TIMELINE_LABEL_Y = 0;
const UI_TOOLTIP_DELAY_MS = 360;
const UI_TOOLTIP_GAP_PX = 8;
const DETAIL_CARD_HEIGHT_STABILIZE_MS = 140;
const DETAIL_CARD_HEIGHT_ANIMATION_MS = 190;
const MAP_DEFERRED_UPDATE_DELAY_MS = 90;
const MANUAL_UI_DIM_DRAG_DISTANCE_PX = 18;
const MANUAL_UI_DIM_DRAG_TIME_MS = 220;
const MANUAL_UI_DIM_DRAG_MIN_DISTANCE_PX = 5;
const MANUAL_UI_DIM_WHEEL_DISTANCE_PX = 28;
const MANUAL_UI_DIM_WHEEL_WINDOW_MS = 240;
const TIMELINE_MIN_SERVER_RANK = 0.04;
const TIMELINE_RANK_PREFETCH = 0.075;
const TIMELINE_ZOOM_PREFETCH_MIN_SCALE = 0.18;
const TIMELINE_ZOOM_PREFETCH_FACTOR = 1.55;
const TIMELINE_RANK_RELOAD_EPSILON = 0.012;
const TIMELINE_RENDER_RANK_EPSILON = 0.024;
const TIMELINE_VIEWPORT_CULL_SCALE = 1.35;
const TIMELINE_VIEWPORT_MARGIN_PX = 220;
const TIMELINE_VIEWPORT_TILE = 520;
const TIMELINE_NODE_OVERLAP_PAD_PX = 8;
const TIMELINE_EXTRA_EDGE_MAX = 8;
const TIMELINE_NON_CORE_SIDE_EDGE_LIMIT = 1;
const TIMELINE_PLACEMENT_MAX_SCREEN_OFFSET = 180;
const CLOUD_FONT_SIZE = 13;
const CLOUD_LABEL_PAD_PX = 6.5;
const CLOUD_LABEL_PAD_Y_PX = 4;
const CLOUD_SELECTED_LABEL_EXTRA_PAD_PX = 3;
const CLOUD_VIEWPORT_MARGIN_PX = 180;
const CLOUD_DOM_WINDOW_MARGIN_PX = 96;
const CLOUD_DOM_WINDOW_TILE_PX = 220;
const CLOUD_CANVAS_HIT_PAD_PX = 6;
const CLOUD_CANVAS_TRANSITION_MS = 520;
const CLOUD_CANVAS_FADE_IN_MS = CLOUD_CANVAS_TRANSITION_MS;
const CLOUD_CANVAS_FADE_OUT_MS = 95;
const CLOUD_PRESENTATION_EPSILON = 0.006;
const CLOUD_SELECTED_LABEL_FADE_IN_MS = 220;
const CLOUD_SELECTED_LABEL_FADE_OUT_MS = 170;
const CLOUD_RELATIONSHIP_ALPHA_FADE_MS = 320;
const CLOUD_RELATIONSHIP_ALPHA_FLOOR = 0.0275;
const CLOUD_RELATIONSHIP_ALPHA_DISTANCE_STEPS = 4;
const CLOUD_CATALOG_PREVIEW_NODE_LIMIT = 180;
const CLOUD_LAYER_READY_EPSILON = 0.026;
const CLOUD_SPATIAL_CELL_PX = 320;
const CLOUD_CLICK_IDLE_ENABLE_MS = 300;
const CLOUD_SELECTED_MARKER_RADIUS_PX = 4.5;
const CLOUD_SELECTED_MARKER_VIEWPORT_MARGIN_PX = 6;
const CLOUD_SELECTED_MARKER_CLEARANCE_PX = 0.75;
const CLOUD_SELECTED_MARKER_FADE_OUT_MS = 110;
const CLOUD_SELECTED_MARKER_FADE_IN_MS = 150;
const CLOUD_BACKGROUND_OPTIONS = {
  fieldWidth: 420,
  graphNeighborLimit: 32,
  largeContributorLimit: 24,
  mediumContributorLimit: 10,
  hueBucketCount: 18,
  selfWeight: 1.0,
  graphWeight: 0.6,
  largeFieldWeight: 0.64,
  mediumFieldWeight: 0.36,
  spatialSigmaLargeRatio: 0.105,
  spatialSigmaMediumRatio: 0.036,
  densityLow: 0.32,
  densityHigh: 4.2,
  darkBaseAlpha: 0.14,
  lightBaseAlpha: 0.095,
  darkTargetLightness: 0.34,
  lightTargetLightness: 0.82,
  darkChromaScale: 0.44,
  lightChromaScale: 0.34,
  darkChromaMax: 0.09,
  lightChromaMax: 0.065,
  noiseScale: 0.006,
  warpStrength: 3.0,
  noiseSeed: 1337,
};

function vw() { return svg.clientWidth || window.innerWidth; }
function vh() { return svg.clientHeight || window.innerHeight; }
function isCompact() { return vw() < 900; }
function defaultScale() { return isCompact() ? 0.84 : 1; }
function reservedRight() { return isCompact() ? 0 : 340; }
function reservedBottom() { return isCompact() ? Math.min(280, Math.max(190, vh() * 0.34)) : 64; }
function edgeBaseLength() { return isCompact() ? 155 : R; }
function focusX() { return (vw() - reservedRight()) / 2; }
function focusY() {
  const graphHeight = vh() - reservedBottom();
  return isCompact()
    ? Math.max(150, graphHeight * 0.42)
    : Math.max(170, graphHeight * 0.54);
}

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function setStatus(text = "") {
  footerHint.textContent = text;
}

function ensureFooterZoomFill() {
  if (!footerZoom) return null;
  if (!footerZoomFill || footerZoomFill.parentElement !== footerZoom) {
    footerZoom.replaceChildren();
    footerZoomFill = document.createElement("span");
    footerZoomFill.id = "footer-zoom-fill";
    footerZoomFill.className = "zoom-progress-fill";
    footerZoomLabel = document.createElement("span");
    footerZoomLabel.id = "footer-zoom-label";
    footerZoomLabel.className = "zoom-progress-label";
    footerZoom.appendChild(footerZoomFill);
    footerZoom.appendChild(footerZoomLabel);
    return footerZoomFill;
  }
  if (!footerZoomLabel || footerZoomLabel.parentElement !== footerZoom) {
    footerZoomLabel = document.createElement("span");
    footerZoomLabel.id = "footer-zoom-label";
    footerZoomLabel.className = "zoom-progress-label";
    footerZoom.appendChild(footerZoomLabel);
  }
  for (const child of Array.from(footerZoom.childNodes)) {
    if (child !== footerZoomFill && child !== footerZoomLabel) child.remove();
  }
  return footerZoomFill;
}

function updateFooterZoom() {
  const fill = ensureFooterZoomFill();
  const minScale = currentMinViewScale();
  const maxScale = currentMaxViewScale();
  const progress = clamp((viewScale - minScale) / Math.max(0.0001, maxScale - minScale), 0, 1);
  footerZoom.style.setProperty("--zoom-progress", progress.toFixed(4));
  if (fill) fill.style.transform = `scaleX(${progress.toFixed(4)})`;
  if (footerZoomLabel) footerZoomLabel.textContent = `Zoom ${Math.round(progress * 100)}%`;
  footerZoom.setAttribute("role", "progressbar");
  footerZoom.setAttribute("aria-valuemin", "0");
  footerZoom.setAttribute("aria-valuemax", "100");
  footerZoom.setAttribute("aria-valuenow", String(Math.round(progress * 100)));
  footerZoom.setAttribute("aria-label", `Zoom ${Math.round(progress * 100)} percent`);
  footerZoom.title = `Zoom ${viewScale.toFixed(2)}x`;
}

function footerZoomProgressFromClientX(clientX) {
  if (!footerZoom) return null;
  const rect = footerZoom.getBoundingClientRect();
  if (!rect.width) return null;
  return clamp((clientX - rect.left) / rect.width, 0, 1);
}

function setViewScaleAroundViewportCenter(nextScale) {
  const viewport = cameraViewportRect();
  const mx = (viewport.left + viewport.right) / 2;
  const my = (viewport.top + viewport.bottom) / 2;
  const wx = (mx - viewTx) / viewScale;
  const wy = (my - viewTy) / viewScale;
  viewScale = clampViewScale(nextScale);
  viewTx = mx - wx * viewScale;
  viewTy = my - wy * viewScale;
  writeWorldTransform();
}

function setZoomFromFooterProgress(progress) {
  const minScale = currentMinViewScale();
  const maxScale = currentMaxViewScale();
  const nextScale = minScale + (maxScale - minScale) * clamp(progress, 0, 1);
  followMode = false;
  stopPanInertia();
  if (panAnimTimer) clearInterval(panAnimTimer);
  markGraphMoving(360);
  setViewScaleAroundViewportCenter(nextScale);
  if (timelineMode) markTimelineInteracting();
  scheduleGraphStill(520);
}

function setZoomFromFooterClientX(clientX) {
  const progress = footerZoomProgressFromClientX(clientX);
  if (progress == null) return;
  setZoomFromFooterProgress(progress);
}

function currentZoomProgress() {
  const minScale = currentMinViewScale();
  const maxScale = currentMaxViewScale();
  return clamp((viewScale - minScale) / Math.max(0.0001, maxScale - minScale), 0, 1);
}

function currentMaxViewScale() {
  if (!cloudMode && !timelineMode) return GRAPH_MAX_VIEW_SCALE;
  return cloudMode ? CLOUD_MAX_VIEW_SCALE : MAX_VIEW_SCALE;
}

function currentMinViewScale() {
  return (!cloudMode && !timelineMode) ? GRAPH_MIN_VIEW_SCALE : MIN_VIEW_SCALE;
}

function clampViewScale(scale) {
  return Math.max(currentMinViewScale(), Math.min(currentMaxViewScale(), scale));
}

function graphAutoViewScale(scale = viewScale) {
  if (cloudMode || timelineMode) return clampViewScale(scale);
  return Math.max(GRAPH_AUTO_MIN_VIEW_SCALE, Math.min(GRAPH_AUTO_MAX_VIEW_SCALE, scale));
}

function finiteBounds(bounds) {
  if (!bounds) return null;
  const minX = Number(bounds.minX);
  const maxX = Number(bounds.maxX);
  const minY = Number(bounds.minY);
  const maxY = Number(bounds.maxY);
  if (![minX, maxX, minY, maxY].every(Number.isFinite)) return null;
  if (maxX <= minX || maxY <= minY) return null;
  return { minX, maxX, minY, maxY };
}

function apiBounds(bounds) {
  if (!bounds) return null;
  return finiteBounds({
    minX: bounds.min_x ?? bounds.minX,
    maxX: bounds.max_x ?? bounds.maxX,
    minY: bounds.min_y ?? bounds.minY,
    maxY: bounds.max_y ?? bounds.maxY,
  });
}

function graphContentBounds() {
  const renderNodes = [...nodes.values()].filter(node => node && node.isRevealed !== false && !node.isTrimming);
  if (!renderNodes.length) return null;
  const bounds = renderNodes.reduce((acc, node) => {
    const x = Number(nodeRenderX(node));
    const y = Number(nodeRenderY(node));
    if (!Number.isFinite(x) || !Number.isFinite(y)) return acc;
    const box = nodeBox(node, 60, 44);
    acc.minX = Math.min(acc.minX, x - box.w / 2);
    acc.maxX = Math.max(acc.maxX, x + box.w / 2);
    acc.minY = Math.min(acc.minY, y - box.h / 2);
    acc.maxY = Math.max(acc.maxY, y + box.h / 2);
    return acc;
  }, { minX: Number.POSITIVE_INFINITY, maxX: Number.NEGATIVE_INFINITY, minY: Number.POSITIVE_INFINITY, maxY: Number.NEGATIVE_INFINITY });
  return finiteBounds(bounds);
}

function timelineContentBounds() {
  const streamBounds = apiBounds(timelineData?.stats?.bounds);
  if (streamBounds) return streamBounds;
  const sourceNodes = timelineData?.nodes || [];
  if (!sourceNodes.length) return null;
  return finiteBounds(sourceNodes.reduce((acc, node) => {
    const x = Number(node.renderX ?? node.x);
    const y = Number(node.renderY ?? node.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return acc;
    acc.minX = Math.min(acc.minX, x - 170);
    acc.maxX = Math.max(acc.maxX, x + 170);
    acc.minY = Math.min(acc.minY, y - 70);
    acc.maxY = Math.max(acc.maxY, y + 70);
    return acc;
  }, { minX: Number.POSITIVE_INFINITY, maxX: Number.NEGATIVE_INFINITY, minY: Number.POSITIVE_INFINITY, maxY: Number.NEGATIVE_INFINITY }));
}

function currentContentBounds() {
  if (cloudMode) return cloudStatsBounds(cloudData) || cloudBounds;
  if (timelineMode) return timelineContentBounds();
  return graphContentBounds();
}

function cameraViewportRect() {
  if (!cloudMode && !timelineMode) {
    return {
      left: 0,
      right: Math.max(1, vw() - reservedRight()),
      top: 0,
      bottom: Math.max(1, vh() - reservedBottom()),
    };
  }
  return { left: 0, right: vw(), top: 0, bottom: vh() };
}

function clampAxisTranslate(tx, minWorld, maxWorld, scale, viewportMin, viewportMax, padding) {
  const minTx = viewportMin + padding - maxWorld * scale;
  const maxTx = viewportMax - padding - minWorld * scale;
  if (minTx > maxTx) {
    return (viewportMin + viewportMax) / 2 - ((minWorld + maxWorld) / 2) * scale;
  }
  return Math.max(minTx, Math.min(maxTx, tx));
}

function clampViewTranslation() {
  const bounds = finiteBounds(currentContentBounds());
  if (!bounds) return;
  const scale = Math.max(0.001, viewScale);
  const viewport = cameraViewportRect();
  const viewportWidth = Math.max(1, viewport.right - viewport.left);
  const viewportHeight = Math.max(1, viewport.bottom - viewport.top);
  const padX = Math.min(Math.max(80, viewportWidth * 0.18), 220);
  const padY = Math.min(Math.max(70, viewportHeight * 0.18), 180);
  viewTx = clampAxisTranslate(viewTx, bounds.minX, bounds.maxX, scale, viewport.left, viewport.right, padX);
  viewTy = clampAxisTranslate(viewTy, bounds.minY, bounds.maxY, scale, viewport.top, viewport.bottom, padY);
}

function setBusy(isBusy) {
  document.body.classList.toggle("is-loading", isBusy);
  updateDetailCardVisibility();
}

function setCloudInitialLoading(isLoading) {
  cloudInitialRenderPending = Boolean(isLoading);
  document.body.classList.toggle("cloud-loading", cloudInitialRenderPending);
  if (bootLoading) bootLoading.setAttribute("aria-hidden", cloudInitialRenderPending ? "false" : "true");
  if (window.__wikiGenresCloudCullDebug) {
    window.__wikiGenresCloudCullDebug.cloudLoading = cloudInitialRenderPending;
  }
}

function finishCloudInitialLoadingAfterPaint() {
  if (!cloudInitialRenderPending) return;
  requestAnimationFrame(() => {
    scheduleCloudCanvasRender();
    requestAnimationFrame(() => {
      if (cloudMode) scheduleCloudCanvasRender();
      requestAnimationFrame(() => {
        setCloudInitialLoading(false);
      });
    });
  });
}

function detailCardMovementActive() {
  return Date.now() < detailCardMovementUntil;
}

function manualUiDimExplicitActive() {
  return Date.now() < manualUiDimUntil;
}

function uiHoverRestoreActive() {
  return !pointerDragActive() && Date.now() < uiHoverRestoreUntil;
}

function pointerDragActive() {
  return activePointerButtons > 0 || document.body.classList.contains("is-panning-canvas");
}

function setActivePointerButtons(buttons = 0) {
  activePointerButtons = Math.max(0, Number(buttons) || 0);
  document.body.classList.toggle("is-pointer-down", activePointerButtons > 0);
}

function updateLastPointerPosition(clientX, clientY) {
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
  lastPointerClientX = clientX;
  lastPointerClientY = clientY;
}

function liveUiHoverRoot() {
  if (pointerDragActive()) return null;
  if (!Number.isFinite(lastPointerClientX) || !Number.isFinite(lastPointerClientY)) return null;
  const hovered = document.elementFromPoint(lastPointerClientX, lastPointerClientY);
  const root = hovered?.closest?.(UI_HOVER_SELECTOR) || null;
  if (!root?.isConnected || root.hidden || root.getClientRects().length === 0) return null;
  return root;
}

function isUiHoverTarget(target) {
  if (pointerDragActive()) return false;
  return target instanceof Element && Boolean(target.closest(UI_HOVER_SELECTOR));
}

function uiHoverActive() {
  if (uiHovering || liveUiHoverRoot()) return true;
  for (const root of Array.from(uiHoverRoots)) {
    if (!root?.isConnected || root.hidden || root.getClientRects().length === 0) {
      uiHoverRoots.delete(root);
      continue;
    }
    return true;
  }
  return false;
}

function uiHoverRestoring() {
  if (pointerDragActive()) return false;
  return uiHoverActive() || uiHoverRestoreActive();
}

function triggerUiHoverRestoreHold(duration = UI_HOVER_RESTORE_HOLD_MS) {
  if (pointerDragActive()) return;
  uiHoverRestoreUntil = Math.max(uiHoverRestoreUntil, Date.now() + duration);
  window.clearTimeout(uiHoverRestoreTimer);
  const delay = Math.max(0, uiHoverRestoreUntil - Date.now()) + 20;
  uiHoverRestoreTimer = window.setTimeout(() => {
    uiHoverRestoreTimer = 0;
    updateManualUiDimClass();
  }, delay);
}

function manualUiDimActive() {
  if (cloudMode) return false;
  if (!manualUiDimPending) return false;
  return manualUiDimExplicitActive() || !graphIsStill || detailCardMovementActive();
}

function updateManualUiDimClass() {
  document.body.classList.toggle("ui-hover-restoring", uiHoverRestoring());
  const active = manualUiDimActive();
  document.body.classList.toggle("ui-manual-moving", active);
  if (!active) {
    setDetailCardHoverSwapActive(false);
  }
  if (!active && !manualUiDimExplicitActive()) {
    manualUiDimPending = false;
  }
}

function applyDetailCardMovingClass() {
  document.body.classList.toggle("detail-card-moving", detailCardMovementActive());
}

function setDetailCardHoverSwapActive(active) {
  detailCardHoverSwapActive = Boolean(active);
  document.body.classList.toggle("detail-card-hover-swap-active", detailCardHoverSwapActive);
}

function markDetailCardMoving(duration = 620) {
  detailCardMovementUntil = Math.max(detailCardMovementUntil, Date.now() + duration);
  applyDetailCardMovingClass();
  window.clearTimeout(detailCardMovementTimer);
  const delay = Math.max(0, detailCardMovementUntil - Date.now()) + 20;
  detailCardMovementTimer = window.setTimeout(() => {
    detailCardMovementTimer = 0;
    updateDetailCardVisibility();
  }, delay);
  updateDetailCardVisibility();
}

function markManualUiMoving(duration = 620) {
  manualUiDimPending = true;
  manualUiDimUntil = Math.max(manualUiDimUntil, Date.now() + duration);
  updateManualUiDimClass();
  window.clearTimeout(manualUiDimTimer);
  const delay = Math.max(0, manualUiDimUntil - Date.now()) + 20;
  manualUiDimTimer = window.setTimeout(() => {
    manualUiDimTimer = 0;
    updateManualUiDimClass();
  }, delay);
}

function beginManualMovementGesture(clientX, clientY) {
  manualMovementGesture = {
    startX: clientX,
    startY: clientY,
    lastX: clientX,
    lastY: clientY,
    startedAt: Date.now(),
    cumulative: 0,
    dimmed: false,
  };
}

function clearManualMovementGesture() {
  manualMovementGesture = null;
}

function markManualUiMovingAfterGestureThreshold(clientX, clientY, duration = 620) {
  if (!manualMovementGesture) beginManualMovementGesture(clientX, clientY);
  const gesture = manualMovementGesture;
  const dx = clientX - gesture.startX;
  const dy = clientY - gesture.startY;
  const step = Math.hypot(clientX - gesture.lastX, clientY - gesture.lastY);
  gesture.lastX = clientX;
  gesture.lastY = clientY;
  gesture.cumulative += step;
  const directDistance = Math.hypot(dx, dy);
  const elapsed = Date.now() - gesture.startedAt;
  if (
    gesture.dimmed ||
    directDistance >= MANUAL_UI_DIM_DRAG_DISTANCE_PX ||
    (elapsed >= MANUAL_UI_DIM_DRAG_TIME_MS && gesture.cumulative >= MANUAL_UI_DIM_DRAG_MIN_DISTANCE_PX)
  ) {
    gesture.dimmed = true;
    markManualUiMoving(duration);
  }
}

function markManualUiMovingAfterWheelThreshold(event, duration = 620) {
  const now = Date.now();
  if (now - manualWheelLastAt > MANUAL_UI_DIM_WHEEL_WINDOW_MS) {
    manualWheelDistance = 0;
  }
  manualWheelLastAt = now;
  const lineScale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1;
  const pageScale = event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? Math.max(1, vh() * 0.85) : lineScale;
  manualWheelDistance += (Math.abs(event.deltaX) + Math.abs(event.deltaY)) * pageScale;
  if (manualWheelDistance >= MANUAL_UI_DIM_WHEEL_DISTANCE_PX) {
    markManualUiMoving(duration);
  }
}

function isManualGraphDragTarget(target) {
  if (!(target instanceof Element)) return false;
  if (target.closest(UI_HOVER_SELECTOR)) return false;
  return Boolean(target.closest("#canvas"));
}

function updateDetailCardVisibility() {
  syncDetailNodeIndicators();
  updateDetailRestoreButtonEligibility();
  if (
    document.body.classList.contains("is-loading") ||
    document.body.classList.contains("app-booting") ||
    detailCardSuppressed ||
    (mapListMode && mapListDetailHidden)
  ) {
    clearDetailCardIdleTimer();
    cancelDetailCardContentSwap();
    setDetailCardHoverSwapActive(false);
    document.body.classList.remove("detail-card-visible");
    document.body.classList.remove("detail-card-moving");
    updateManualUiDimClass();
    return;
  }
  const modeHasCard = cloudMode
    ? Boolean(detailCardNodeKey || cloudSelectedGenreId)
    : timelineMode
    ? timelineDetailCardOpen
    : Boolean(currentDetailFallbackNode());
  const graphMovingWithCard =
    !cloudMode &&
    !timelineMode &&
    modeHasCard &&
    !graphIsStill &&
    !hoveredNodeKey &&
    !holdDetailCardDuringLocate;
  const moving = detailCardMovementActive() || graphMovingWithCard;
  document.body.classList.toggle("detail-card-moving", moving);
  document.body.classList.toggle(
    "detail-card-visible",
    youtubeCardHovered
      ? Boolean(youtubePlaybackNode)
      : cloudMode
      ? Boolean(detailCardNodeKey || cloudSelectedGenreId)
      : timelineMode
      ? timelineDetailCardOpen
      : graphIsStill || Boolean(hoveredNodeKey) || holdDetailCardDuringLocate || graphMovingWithCard
  );
  if (!document.body.classList.contains("detail-card-visible")) {
    clearDetailCardIdleTimer();
    cancelDetailCardContentSwap();
    setDetailCardHoverSwapActive(false);
  } else {
    scheduleDetailCardIdleReturn();
  }
  updateManualUiDimClass();
}

function setGraphStill(isStill) {
  graphIsStill = isStill;
  updateDetailCardVisibility();
  syncDetailNodeIndicators();
}

function clearGraphStillTimer() {
  if (!graphStillTimer) return;
  window.clearTimeout(graphStillTimer);
  graphStillTimer = null;
}

function markGraphMoving(duration = 620) {
  clearGraphStillTimer();
  markDetailCardMoving(duration);
  setGraphStill(false);
}

function scheduleGraphStill(delay = DETAIL_CARD_REAPPEAR_DELAY_MS, onStill = null) {
  clearGraphStillTimer();
  graphStillTimer = window.setTimeout(() => {
    graphStillTimer = null;
    setGraphStill(true);
    if (onStill) onStill();
  }, delay);
}

function setHoveredNode(key = null) {
  hoveredNodeKey = key;
  updateDetailCardVisibility();
}

function detailKeyForTimelineNodeId(nodeId) {
  return nodeId ? `timeline-${nodeId}` : "";
}

function detailKeyForCloudNodeId(nodeId) {
  return nodeId ? `cloud-${nodeId}` : "";
}

function cloudNodeIdFromDetailKey(key = "") {
  return String(key || "").startsWith("cloud-") ? String(key).slice(6) : "";
}

function activeDetailIndicatorKey() {
  return detailIndicatorPreviewKey || detailCardNodeKey || "";
}

function detailCardIndicatorKey() {
  return detailCardNodeKey || "";
}

function cloudDetailIndicatorKey() {
  return activeDetailIndicatorKey();
}

function effectiveDetailIndicatorKey() {
  return (!detailIndicatorPreviewKey && !graphIsStill) ? "" : activeDetailIndicatorKey();
}

function syncDetailNodeIndicators() {
  const graphIndicatorKey = activeDetailIndicatorKey();
  for (const [nodeKey, el] of nodeEls.entries()) {
    const isDetailNode = nodeKey === graphIndicatorKey;
    el.classList.toggle(
      "node-detail-preview",
      isDetailNode
    );
  }
  for (const [nodeId, el] of timelineNodeElById.entries()) {
    const isDetailNode = detailKeyForTimelineNodeId(nodeId) === detailCardIndicatorKey();
    el.classList.toggle(
      "timeline-node-detail-preview",
      isDetailNode
    );
  }
  for (const [nodeId, el] of cloudNodeEls.entries()) {
    el.classList.toggle(
      "cloud-node-detail-preview",
      detailKeyForCloudNodeId(nodeId) === cloudDetailIndicatorKey()
    );
  }
  if (cloudMode) {
    updateCloudHoverUnderlineAlphaTargets(cloudCanvasNodes);
    scheduleCloudCanvasRender();
  }
}

function setDetailCardNodeKey(key = null) {
  const nextKey = key || null;
  detailCardNodeKey = nextKey;
  if (detailIndicatorPreviewKey === nextKey) detailIndicatorPreviewKey = null;
  syncDetailNodeIndicators();
}

function setDetailIndicatorPreviewKey(key = null) {
  detailIndicatorPreviewKey = key || null;
  syncDetailNodeIndicators();
}

function setUiHover(root, isHovered) {
  if (!root) return;
  if (isHovered) {
    uiHovering = true;
    uiHoverRoots.add(root);
    triggerUiHoverRestoreHold();
  } else {
    uiHoverRoots.delete(root);
    if (!uiHoverRoots.size) uiHovering = false;
  }
  updateManualUiDimClass();
}

function allowDetailCardForManualSelection() {
  if (detailCardSuppressed) return;
  detailCardSuppressed = false;
}

function suppressDetailCardUntilSelection() {
  detailCardSuppressed = true;
  hoveredNodeKey = null;
  cancelScheduledHoverCard();
  setDetailCardNodeKey(null);
  hoverCardToken++;
  clearDetailCardIdleTimer();
  updateDetailCardVisibility();
}

function currentDetailFallbackNode() {
  if (cloudMode) {
    const hoveredDetailId = cloudNodeIdFromDetailKey(detailCardNodeKey);
    if (hoveredDetailId) {
      return cloudNodeById.get(hoveredDetailId) ||
        cloudScene?.nodesById?.get(hoveredDetailId) ||
        selectedCloudNode();
    }
    return selectedCloudNode();
  }
  if (timelineMode) return selectedTimelineNode();
  return (
    (hoveredNodeKey && nodes.get(hoveredNodeKey)) ||
    nodes.get(activeLeafKey) ||
    nodes.get(currentKey) ||
    null
  );
}

function nodeHasRestorableDetail(node) {
  return Boolean(node && !isMusicCoreNode(node) && (node.genreId || node.id || node.wikipedia_url));
}

function updateDetailRestoreButtonEligibility() {
  const node = youtubeCardHovered
    ? playbackDetailNode()
    : currentDetailFallbackNode();
  document.body.classList.toggle("detail-restore-available", nodeHasRestorableDetail(node));
}

function restoreDetailCardFromButton() {
  setMobileCardsHidden(false);
  if (mapListMode) setMapListMode(false);
  detailCardSuppressed = false;
  youtubeCardHovered = false;
  if (timelineMode && timelineSelectedGenreId) timelineDetailCardOpen = true;
  if (!cloudMode && !timelineMode) graphIsStill = true;
  const node = currentDetailFallbackNode();
  if (node) {
    setDetailCardNodeKey(node.key || detailCardNodeKey);
    updateCard(node);
  }
  updateDetailCardVisibility();
}

function mapCountryForNode(node) {
  if (!node?.genreId) return null;
  if (node.regionName) return mapCountryName(node.regionName);
  for (const [countryName, item] of mapItemsByCountryName.entries()) {
    if (item?.genre_id === node.genreId) return countryName;
  }
  return null;
}

function setHoveredMapItemForNode(node) {
  const countryName = mapCountryForNode(node);
  if (countryName) setMapHoveredCountry(countryName);
}

function clearHoveredMapItemForNode(node) {
  const countryName = mapCountryForNode(node);
  if (countryName) clearMapHoveredCountry(countryName);
}

function cancelScheduledHoverCard(nodeKey = null) {
  if (nodeKey && pendingHoverCardKey && pendingHoverCardKey !== nodeKey) return;
  const canceledKey = pendingHoverCardKey || nodeKey;
  window.clearTimeout(hoverCardDelayTimer);
  hoverCardDelayTimer = 0;
  pendingHoverCardKey = null;
  if (
    detailIndicatorPreviewKey &&
    (!nodeKey || detailIndicatorPreviewKey === nodeKey || detailIndicatorPreviewKey === canceledKey)
  ) {
    setDetailIndicatorPreviewKey(null);
  }
}

function scheduleHoverCard(nodeKey) {
  cancelScheduledHoverCard();
  if (detailCardSuppressed || !nodeKey) return;
  if (!graphNodeAllowsHoverDetail(nodes.get(nodeKey), nodeEls.get(nodeKey))) return;
  setDetailIndicatorPreviewKey(nodeKey);
  pendingHoverCardKey = nodeKey;
  hoverCardDelayTimer = window.setTimeout(() => {
    hoverCardDelayTimer = 0;
    const wantedKey = pendingHoverCardKey;
    pendingHoverCardKey = null;
    if (hoveredNodeKey !== wantedKey) return;
    if (!graphNodeAllowsHoverDetail(nodes.get(wantedKey), nodeEls.get(wantedKey))) return;
    void showHoverCard(wantedKey);
  }, prefersReducedMotion() ? 0 : DETAIL_HOVER_SWAP_DELAY_MS);
}

function scheduleTimelineHoverCard(node) {
  const key = detailKeyForTimelineNodeId(node?.id);
  cancelScheduledHoverCard();
  if (!key || detailCardSuppressed) return;
  if (!timelineNodeAllowsHoverDetail(timelineNodeElById.get(node.id))) return;
  setDetailIndicatorPreviewKey(key);
  pendingHoverCardKey = key;
  hoverCardDelayTimer = window.setTimeout(() => {
    hoverCardDelayTimer = 0;
    if (pendingHoverCardKey !== key) return;
    pendingHoverCardKey = null;
    if (!timelineNodeAllowsHoverDetail(timelineNodeElById.get(node.id))) return;
    void showTimelineHoverCard(node);
  }, prefersReducedMotion() ? 0 : DETAIL_HOVER_SWAP_DELAY_MS);
}

async function showHoverCard(nodeKey) {
  if (detailCardSuppressed) return;
  if (!graphNodeAllowsHoverDetail(nodes.get(nodeKey), nodeEls.get(nodeKey))) return;
  const token = ++hoverCardToken;
  const node = nodes.get(nodeKey);
  if (!node) return;
  setDetailCardNodeKey(nodeKey);
  if (!node.genreId || node.isUnresolved) {
    updateCard(node, { hoverSwap: true });
    return;
  }

  try {
    const hydrated = await hydrateNodeDetail(node);
    if (token !== hoverCardToken || detailCardNodeKey !== nodeKey) return;
    if (!relationshipLine(hydrated)) {
      hydrated.parentRelationshipRows = await getReachableParents(hydrated.genreId).catch(() => []);
      if (token !== hoverCardToken || detailCardNodeKey !== nodeKey) return;
    }
    updateCard(hydrated, { hoverSwap: true });
  } catch (err) {
    console.error("[wiki-genres] hover detail failed", err);
    if (token === hoverCardToken && detailCardNodeKey === nodeKey) {
      updateCard(node, { hoverSwap: true });
    }
  }
}

function restoreSelectedCardAfterHover(nodeKey) {
  if (hoveredNodeKey !== nodeKey) return;
  cancelScheduledHoverCard(nodeKey);
  hoveredNodeKey = null;
  updateDetailCardVisibility();
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, prefersReducedMotion() ? 0 : ms));
}

function requestTimeoutError(url, timeoutMs, phase = "request") {
  const err = new Error(`${phase} timed out after ${timeoutMs}ms: ${url}`);
  err.name = "TimeoutError";
  return err;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
  const { timeoutMs: _timeoutMs, readTimeoutMs: _readTimeoutMs, ...fetchOptions } = options;
  const controller = new AbortController();
  let didTimeout = false;
  let timeoutId = 0;
  const parentSignal = fetchOptions.signal;
  const abortFromParent = () => controller.abort(parentSignal.reason);
  if (parentSignal?.aborted) {
    abortFromParent();
  } else if (parentSignal) {
    parentSignal.addEventListener("abort", abortFromParent, { once: true });
  }
  if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
    timeoutId = window.setTimeout(() => {
      didTimeout = true;
      controller.abort(requestTimeoutError(url, timeoutMs));
    }, timeoutMs);
  }
  try {
    return await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
    });
  } catch (err) {
    if (didTimeout) throw requestTimeoutError(url, timeoutMs);
    throw err;
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
    if (parentSignal) parentSignal.removeEventListener("abort", abortFromParent);
  }
}

async function readStreamChunkWithTimeout(reader, url, timeoutMs = STREAM_READ_TIMEOUT_MS) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) return reader.read();
  let timeoutId = 0;
  try {
    return await Promise.race([
      reader.read(),
      new Promise((_, reject) => {
        timeoutId = window.setTimeout(() => {
          reject(requestTimeoutError(url, timeoutMs, "stream read"));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
  }
}

async function fetchJson(url, options = {}) {
  let lastError = null;
  for (let attempt = 0; attempt <= FETCH_RETRY_DELAYS_MS.length; attempt++) {
    const res = await fetchWithTimeout(url, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
    }, options.timeoutMs ?? FETCH_TIMEOUT_MS);
    if (res.ok) return res.json();

    const msg = await res.text().catch(() => "");
    lastError = new Error(`${res.status} ${res.statusText}${msg ? `: ${msg}` : ""}`);
    if (res.status !== 429 || attempt >= FETCH_RETRY_DELAYS_MS.length) break;

    const retryAfter = Number(res.headers.get("Retry-After"));
    const retryDelay = Number.isFinite(retryAfter)
      ? retryAfter * 1000
      : FETCH_RETRY_DELAYS_MS[attempt];
    await sleep(retryDelay);
  }
  throw lastError;
}

async function streamNdjson(url, options = {}) {
  const res = await fetchWithTimeout(url, {
    signal: options.signal,
    headers: { Accept: "application/x-ndjson", ...(options.headers || {}) },
  }, options.timeoutMs ?? STREAM_CONNECT_TIMEOUT_MS);
  if (!res.ok) {
    const msg = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${msg ? `: ${msg}` : ""}`);
  }
  if (!res.body?.getReader) {
    const data = await res.json();
    if (data) options.onSnapshot?.(data, { complete: true, index: 0 });
    return data;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalData = null;
  while (true) {
    let readResult;
    try {
      readResult = await readStreamChunkWithTimeout(reader, url, options.readTimeoutMs ?? STREAM_READ_TIMEOUT_MS);
    } catch (err) {
      if (err?.name === "TimeoutError") {
        await reader.cancel(err).catch(() => {});
      }
      if (finalData) return finalData;
      throw err;
    }
    const { done, value } = readResult;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const packet = JSON.parse(line);
      if (packet.type === "snapshot") {
        finalData = packet.data;
        options.onSnapshot?.(packet.data, packet);
      }
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    const packet = JSON.parse(buffer);
    if (packet.type === "snapshot") {
      finalData = packet.data;
      options.onSnapshot?.(packet.data, packet);
    }
  }
  return finalData;
}

async function mapWithConcurrency(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workers = Array.from(
    { length: Math.min(limit, items.length) },
    async () => {
      while (nextIndex < items.length) {
        const index = nextIndex++;
        try {
          results[index] = { status: "fulfilled", value: await worker(items[index], index) };
        } catch (reason) {
          results[index] = { status: "rejected", reason };
        }
      }
    }
  );
  await Promise.all(workers);
  return results;
}

function normalizeLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function slug(value) {
  return normalizeLabel(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function labelFromTitle(title) {
  return normalizeLabel(title)
    .replace(/\s+\((music|genre|music genre)\)$/i, "")
    .replace(/\s+music$/i, "");
}

function displayLabel(label) {
  const max = isCompact() ? 22 : 34;
  const clean = normalizeLabel(label);
  return clean.length > max ? `${clean.slice(0, max - 1)}...` : clean;
}

function relationSummary(relations) {
  const counts = { subgenre: 0, derivative: 0, fusion_genre: 0, unresolved: 0 };
  for (const child of relations) {
    const primary = child.relations?.[0] || child.relation;
    if (primary in counts) counts[primary] += 1;
    if (child.isUnresolved) counts.unresolved += 1;
  }
  const parts = [];
  const total = relations.length;
  parts.push(`${total} ${total === 1 ? "child" : "children"}`);
  if (counts.subgenre) parts.push(`${counts.subgenre} subgenre`);
  if (counts.derivative) parts.push(`${counts.derivative} derivative`);
  if (counts.fusion_genre) parts.push(`${counts.fusion_genre} fusion`);
  if (counts.unresolved) parts.push(`${counts.unresolved} unresolved`);
  return parts.join(" · ");
}

function childRelationForEdge(edge) {
  if (CHILD_RELATIONS.has(edge.relation)) return edge.relation;
  if (
    edge.relation === RELATED_CHILD_RELATION &&
    CHILD_RELATIONS.has(edge.evidence_relation)
  ) {
    return edge.evidence_relation;
  }
  return null;
}

function relationLabel(relation) {
  const labels = {
    music_root: "Root genre from",
    subgenre: "Subgenre of",
    derivative: "Derived from",
    fusion_genre: "Fusion genre of",
    origin_parent: "Stylistic origin of",
    regional_variant: "Regional variation of",
  };
  return labels[relation] || "Related to";
}

function parentRelationshipRowLine(row) {
  if (!row?.parent_title || row.parent_genre_id === ROOT_KEY) return "";
  const relation = row.parent_relation || row.parent_stored_relation;
  if (!relation || relation === "music_root") return "";
  return `${relationLabel(relation)} ${labelFromTitle(row.parent_title)}`;
}

function fallbackParentRelationshipLine(node) {
  if (!node?.genreId || node.key === ROOT_KEY) return "";
  const rows = reachableParentsCache.get(node.genreId) || node.parentRelationshipRows || [];
  return [...rows]
    .filter(row => row && row.parent_genre_id !== ROOT_KEY && row.parent_title)
    .sort((a, b) => {
      const ar = RELATION_RANK.get(a.parent_relation) ?? 99;
      const br = RELATION_RANK.get(b.parent_relation) ?? 99;
      return (
        ar - br ||
        (a.parent_depth_from_music ?? 99) - (b.parent_depth_from_music ?? 99) ||
        traceSteps(a) - traceSteps(b) ||
        labelFromTitle(a.parent_title).localeCompare(labelFromTitle(b.parent_title))
      );
    })
    .map(parentRelationshipRowLine)
    .find(Boolean) || "";
}

function cloudContextGenreId() {
  return cloudScene?.stats?.selected_genre_id ||
    cloudSelectedGenreId ||
    cloudRootGenreId ||
    ROOT_KEY;
}

function cloudContextLabel(contextId = cloudContextGenreId()) {
  if (!contextId || contextId === ROOT_KEY) return "Music";
  const detail = detailCache.get(contextId);
  if (detail?.label) return detail.label;
  const node = cloudNodeById.get(contextId) || cloudScene?.nodesById?.get(contextId);
  if (node?.label) return node.label;
  if (node?.wikipedia_title) return labelFromTitle(node.wikipedia_title);
  return "Music";
}

function cloudRelationLine(node) {
  if (!cloudMode || !node) return "";
  const genreId = node.genreId || node.id;
  const contextId = cloudContextGenreId();
  if (!genreId || !contextId) return "";
  const cloudNode = cloudNodeById.get(genreId) || cloudScene?.nodesById?.get(genreId) || null;
  const rawDistance = genreId === contextId
    ? 0
    : Number.isFinite(Number(cloudNode?.selected_distance))
      ? Number(cloudNode.selected_distance)
      : Number.isFinite(Number(node.selected_distance))
        ? Number(node.selected_distance)
        : null;
  if (rawDistance == null) return "";
  const steps = Math.max(0, Math.round(rawDistance));
  return `${steps} ${steps === 1 ? "step" : "steps"} from ${cloudContextLabel(contextId)}`;
}

function relationshipLine(node) {
  if (cloudMode) {
    const cloudLine = cloudRelationLine(node);
    if (cloudLine) return cloudLine;
  }
  const parent = node.parentKey ? nodes.get(node.parentKey) : null;
  if (node?.key === ROOT_KEY) return "";
  if (!parent) return fallbackParentRelationshipLine(node);
  const relation = relationLabel(node.relation);
  if (parent.key === ROOT_KEY && relation === "Related to") {
    return fallbackParentRelationshipLine(node);
  }
  return `${relation} ${parent.label}`;
}

function uniqueStrings(items) {
  const seen = new Set();
  const result = [];
  for (const item of items || []) {
    const value = String(item || "").trim();
    const key = value.toLocaleLowerCase();
    if (!value || seen.has(key)) continue;
    seen.add(key);
    result.push(value);
  }
  return result;
}

function normalizeYoutubeUrlList(items) {
  const values = Array.isArray(items) ? items : [items];
  return uniqueStrings(values.map(item => {
    if (!item) return "";
    if (typeof item === "string") return item;
    return item.url || item.youtube_url || item.href || "";
  }));
}

function normalizeYoutubeItems(items) {
  const values = Array.isArray(items) ? items : [items];
  const result = [];
  const seen = new Set();
  for (const item of values) {
    const url = typeof item === "string"
      ? item
      : item?.url || item?.youtube_url || item?.href || "";
    const cleanUrl = String(url || "").trim();
    const key = cleanUrl.toLocaleLowerCase();
    if (!cleanUrl || seen.has(key)) continue;
    seen.add(key);
    result.push({
      genreId: typeof item === "object" ? (item.genre_id || item.genreId || "") : "",
      ordinal: typeof item === "object" ? (item.ordinal ?? null) : null,
      url: cleanUrl,
      title: typeof item === "object" ? (item.title || item.song_title || item.name || "") : "",
      artist: typeof item === "object" ? (item.artist || item.artist_name || item.channel_title || "") : "",
    });
  }
  return result;
}

function youtubeItemsForNode(node) {
  return normalizeYoutubeItems(
    node?.youtubeItems ||
    node?.youtube_items ||
    node?.youtubeVideos ||
    node?.youtube_videos ||
    node?.youtubeUrls ||
    node?.youtube_urls ||
    node?.youtubePlaylistUrls ||
    node?.youtube_playlist_urls ||
    []
  ).filter(item => youtubeUrlParts(item.url));
}

function nodeHasYoutubePlaylistData(node) {
  if (!node) return false;
  return [
    "youtubeItems",
    "youtube_items",
    "youtubeVideos",
    "youtube_videos",
    "youtubeUrls",
    "youtube_urls",
    "youtubePlaylistUrls",
    "youtube_playlist_urls",
  ].some(key => {
    if (!Object.prototype.hasOwnProperty.call(node, key)) return false;
    const value = node[key];
    return Array.isArray(value) ? value.length > 0 : Boolean(value);
  });
}

function nodeHasExplicitNoPlaylist(node) {
  return node?.hasPlaylist === false || node?.has_playlist === false;
}

function isMusicCoreNode(node) {
  return Boolean(node?.key === ROOT_KEY || node?.id === ROOT_KEY || (!node?.genreId && (node?.label || node?.title) === "Music"));
}

function shuffledYoutubeItems(items) {
  const shuffled = [...(items || [])];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
  }
  return shuffled;
}

function youtubePlaybackStore() {
  try {
    const parsed = JSON.parse(localStorage.getItem(YOUTUBE_PLAYBACK_STORAGE_KEY) || "null");
    if (parsed && typeof parsed === "object") {
      if (parsed.entry && typeof parsed.entry === "object") {
        return {
          version: 2,
          playlistKey: String(parsed.playlistKey || ""),
          entry: parsed.entry,
        };
      }
      if (parsed.entries && typeof parsed.entries === "object") {
        const latest = Object.entries(parsed.entries)
          .filter(([, entry]) => entry && typeof entry === "object")
          .sort((a, b) => (b[1]?.updatedAt || 0) - (a[1]?.updatedAt || 0))[0];
        if (latest) {
          return {
            version: 2,
            playlistKey: latest[0],
            entry: latest[1],
          };
        }
      }
    }
  } catch {
    // Ignore malformed local storage and start fresh.
  }
  return { version: 3, playlistKey: "", entry: null };
}

function writeYoutubePlaybackStore(store) {
  try {
    localStorage.setItem(YOUTUBE_PLAYBACK_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Playback progress persistence is best-effort.
  }
}

function clearYoutubePlaybackStore() {
  try {
    localStorage.removeItem(YOUTUBE_PLAYBACK_STORAGE_KEY);
  } catch {
    // Playback progress persistence is best-effort.
  }
}

function youtubeCurrentSeconds() {
  try {
    const value = youtubePlayer?.getCurrentTime?.();
    if (Number.isFinite(value) && value > 0.1) {
      youtubeLastKnownSeconds = Math.max(0, value);
      return youtubeLastKnownSeconds;
    }
  } catch {
    // Fall back to local elapsed time below.
  }
  if (youtubeTrackStartedAt && !youtubeTrackLoading && !youtubePaused) {
    youtubeLastKnownSeconds = Math.max(0, (Date.now() - youtubeTrackStartedAt) / 1000);
  }
  return youtubeLastKnownSeconds || youtubeResumeSeconds || 0;
}

function cleanupLegacyYoutubePlaybackMemory() {
  try {
    localStorage.removeItem(YOUTUBE_LEGACY_VOLUME_STORAGE_KEY);
  } catch {
    // Playback memory cleanup is best-effort.
  }
}

function readYoutubeVolume() {
  cleanupLegacyYoutubePlaybackMemory();
  return 70;
}

function readYoutubeShouldAutoplay() {
  try {
    const stored = localStorage.getItem(YOUTUBE_AUTOPLAY_STORAGE_KEY);
    if (stored === "0") return false;
    if (stored === "1") return true;

    const legacyPaused = localStorage.getItem(YOUTUBE_LEGACY_AUTOPLAY_PAUSED_KEY);
    if (legacyPaused === "1" || legacyPaused === "0") {
      const shouldAutoplay = legacyPaused !== "1";
      localStorage.setItem(YOUTUBE_AUTOPLAY_STORAGE_KEY, shouldAutoplay ? "1" : "0");
      localStorage.removeItem(YOUTUBE_LEGACY_AUTOPLAY_PAUSED_KEY);
      return shouldAutoplay;
    }
  } catch {
    // Autoplay preference persistence is best-effort.
  }
  return true;
}

function readYoutubeUserPaused() {
  return !readYoutubeShouldAutoplay();
}

function setYoutubeUserPaused(isPaused) {
  youtubeUserPaused = Boolean(isPaused);
  try {
    localStorage.setItem(YOUTUBE_AUTOPLAY_STORAGE_KEY, youtubeUserPaused ? "0" : "1");
    localStorage.removeItem(YOUTUBE_LEGACY_AUTOPLAY_PAUSED_KEY);
    localStorage.removeItem(YOUTUBE_LEGACY_VOLUME_STORAGE_KEY);
  } catch {
    // Autoplay preference persistence is best-effort.
  }
}

function setYoutubeAppliedVolume(value) {
  youtubeAppliedVolume = clamp(Number(value) || 0, 0, 100);
  try {
    youtubePlayer?.setVolume?.(youtubeAppliedVolume);
    if (youtubeAppliedVolume > 0) youtubePlayer?.unMute?.();
  } catch {
    // Fall back to postMessage commands below.
  }
  youtubeCommand("setVolume", [youtubeAppliedVolume]);
  if (youtubeAppliedVolume > 0) youtubeCommand("unMute");
}

function applyYoutubeVolume(value = youtubeVolume) {
  if (youtubeVolumeInput) youtubeVolumeInput.value = String(youtubeVolume);
  setYoutubeAppliedVolume(value);
}

function lowYoutubeVolume() {
  return clamp(Math.max(4, Math.round(youtubeVolume * 0.12)), 1, Math.max(1, youtubeVolume));
}

function fadeYoutubeVolume(toVolume, duration = 360) {
  window.cancelAnimationFrame(youtubeVolumeFadeFrame);
  const token = ++youtubeVolumeFadeToken;
  const fromVolume = youtubeAppliedVolume;
  const targetVolume = clamp(Number(toVolume) || 0, 0, 100);
  const startedAt = performance.now();
  return new Promise(resolve => {
    const step = now => {
      if (token !== youtubeVolumeFadeToken) {
        resolve(false);
        return;
      }
      const progress = duration <= 0 ? 1 : clamp((now - startedAt) / duration, 0, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setYoutubeAppliedVolume(fromVolume + ((targetVolume - fromVolume) * eased));
      if (progress < 1) {
        youtubeVolumeFadeFrame = window.requestAnimationFrame(step);
      } else {
        resolve(true);
      }
    };
    youtubeVolumeFadeFrame = window.requestAnimationFrame(step);
  });
}

function setYoutubeVolume(value, { persist = true } = {}) {
  youtubeVolume = clamp(Number(value) || 0, 0, 100);
  cleanupLegacyYoutubePlaybackMemory();
  fadeYoutubeVolume(youtubeVolume, 180);
}

function ensureYoutubeVolumePanelMounted() {
  if (!youtubeVolumePanel || youtubeVolumePanelMounted) return;
  document.body.appendChild(youtubeVolumePanel);
  youtubeVolumePanelMounted = true;
}

function syncYoutubeVolumePanelPosition() {
  if (!youtubeVolumeControl || !youtubeVolumePanel) return;
  const button = youtubeVolumeControl.querySelector("#youtube-volume-button");
  if (!(button instanceof HTMLElement)) return;
  const rect = button.getBoundingClientRect();
  const gap = 6;
  const width = youtubeVolumePanel.offsetWidth || 84;
  const height = youtubeVolumePanel.offsetHeight || 32;
  const left = clamp(rect.left, 8, window.innerWidth - width - 8);
  const top = clamp(rect.bottom + gap, 8, window.innerHeight - height - 8);
  youtubeVolumePanel.style.left = `${left}px`;
  youtubeVolumePanel.style.top = `${top}px`;
}

function setYoutubeVolumePanelOpen(isOpen) {
  if (!youtubeVolumeControl || !youtubeVolumePanel) return;
  youtubeVolumeControl.classList.toggle("volume-panel-open", isOpen);
  youtubeVolumePanel.classList.toggle("volume-panel-open", isOpen);
  youtubeVolumePanel.hidden = !isOpen;
  if (isOpen) syncYoutubeVolumePanelPosition();
}

function openYoutubeVolumePanel() {
  window.clearTimeout(youtubeVolumePanelCloseTimer);
  ensureYoutubeVolumePanelMounted();
  setYoutubeVolumePanelOpen(true);
}

function closeYoutubeVolumePanel(event = null) {
  window.clearTimeout(youtubeVolumePanelCloseTimer);
  youtubeVolumePanelCloseTimer = 0;
  const related = event?.relatedTarget;
  if (
    related &&
    (
      youtubeVolumeControl?.contains(related) ||
      youtubeVolumePanel?.contains?.(related)
    )
  ) {
    return;
  }
  setYoutubeVolumePanelOpen(false);
}

function persistYoutubePlayback() {
  if (!youtubePlaylistKey || !youtubeItems.length) return;
  if (youtubeTrackLoading || youtubePaused || youtubeUserPaused || !youtubeIsPlaying) return;
  const seconds = youtubeCurrentSeconds();
  writeYoutubePlaybackStore({
    version: 3,
    playlistKey: youtubePlaylistKey,
    entry: {
      itemUrls: youtubeItems.map(item => item.url),
      index: clamp(youtubeIndex, 0, youtubeItems.length - 1),
      seconds,
    },
  });
}

function restoredYoutubePlayback(playlistKey, items, store = youtubePlaybackStore()) {
  if (!playlistKey || !items.length) return null;
  if (store.playlistKey !== playlistKey) return null;
  const entry = store.entry;
  if (!entry || !Array.isArray(entry.itemUrls)) return null;
  const available = new Map(items.map(item => [item.url, item]));
  const restored = [];
  const seen = new Set();
  for (const url of entry.itemUrls) {
    const item = available.get(url);
    if (!item || seen.has(url)) continue;
    restored.push(item);
    seen.add(url);
  }
  for (const item of items) {
    if (seen.has(item.url)) continue;
    restored.push(item);
  }
  if (!restored.length) return null;
  return {
    items: restored,
    index: clamp(Number(entry.index) || 0, 0, restored.length - 1),
    seconds: Number.isFinite(Number(entry.seconds)) ? Math.max(0, Number(entry.seconds)) : 0,
  };
}

function startYoutubeProgressTimer() {
  window.clearInterval(youtubeProgressTimer);
  youtubeProgressTimer = window.setInterval(() => {
    if (!youtubeTrackLoading && youtubeItems.length && !youtubePaused) {
      persistYoutubePlayback();
    }
  }, 2500);
}

function youtubeUrlParts(rawUrl) {
  const raw = String(rawUrl || "").trim();
  if (!raw) return null;

  try {
    const url = new URL(raw, window.location.origin);
    let videoId = "";
    let playlistId = url.searchParams.get("list") || "";

    if (url.hostname.includes("youtu.be")) {
      videoId = url.pathname.split("/").filter(Boolean)[0] || "";
    } else if (url.pathname.includes("/embed/")) {
      videoId = url.pathname.split("/embed/")[1]?.split("/")[0] || "";
    } else if (url.pathname.includes("/shorts/")) {
      videoId = url.pathname.split("/shorts/")[1]?.split("/")[0] || "";
    } else {
      videoId = url.searchParams.get("v") || "";
    }

    if (!videoId && !playlistId) return null;
    return { videoId, playlistId };
  } catch {
    return null;
  }
}

function youtubeEmbedUrl(rawUrl, playlistItems = [], playlistStartIndex = 0, startSeconds = 0, { autoplay = true } = {}) {
  const parts = youtubeUrlParts(rawUrl);
  if (!parts) return "";

  const params = new URLSearchParams({
    autoplay: autoplay ? "1" : "0",
    enablejsapi: "1",
    origin: window.location.origin,
    playsinline: "1",
    rel: "0",
  });

  if (startSeconds > 1) params.set("start", String(Math.floor(startSeconds)));

  if (!parts.videoId && parts.playlistId) {
    params.set("list", parts.playlistId);
    return `https://www.youtube-nocookie.com/embed/videoseries?${params.toString()}`;
  }
  if (!parts.videoId) return "";

  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(parts.videoId)}?${params.toString()}`;
}

function youtubeWatchUrl(rawUrl, startSeconds = 0) {
  const parts = youtubeUrlParts(rawUrl);
  if (!parts) return String(rawUrl || "");
  const seconds = Math.max(0, Math.floor(Number(startSeconds) || 0));
  if (parts.videoId) {
    const params = new URLSearchParams({ v: parts.videoId });
    if (parts.playlistId) params.set("list", parts.playlistId);
    params.set("t", `${seconds}s`);
    return `https://www.youtube.com/watch?${params.toString()}`;
  }
  if (parts.playlistId) {
    const params = new URLSearchParams({ list: parts.playlistId });
    return `https://www.youtube.com/playlist?${params.toString()}`;
  }
  return String(rawUrl || "");
}

function ensureYoutubeApi() {
  if (window.YT?.Player) {
    youtubeApiReady = true;
    attachYoutubePlayer();
    return;
  }
  if (youtubeApiLoading) return;
  youtubeApiLoading = true;
  const previousReady = window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady = () => {
    if (typeof previousReady === "function") previousReady();
    youtubeApiReady = true;
    if (youtubeDeferredLoadIndex !== null) {
      const index = youtubeDeferredLoadIndex;
      youtubeDeferredLoadIndex = null;
      loadYoutubeIndex(index);
      return;
    }
    attachYoutubePlayer();
  };
  const script = document.createElement("script");
  script.src = "https://www.youtube.com/iframe_api";
  script.async = true;
  document.head.appendChild(script);
}

function ensureYoutubeFrameElement() {
  if (youtubeFrame?.isConnected) return youtubeFrame;
  if (!youtubeFrameHost) return youtubeFrame;
  const frame = document.createElement("iframe");
  frame.id = "youtube-frame";
  frame.setAttribute("aria-label", "YouTube genre playlist");
  frame.setAttribute("allow", "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share");
  frame.setAttribute("allowfullscreen", "");
  const overlay = youtubeFrameHost.querySelector(".youtube-empty");
  youtubeFrameHost.insertBefore(frame, overlay || youtubeFrameHost.firstChild);
  youtubeFrame = frame;
  return youtubeFrame;
}

function attachYoutubePlayer() {
  ensureYoutubeFrameElement();
  if (!youtubeApiReady || !youtubeFrame?.src || youtubePlayer || !window.YT?.Player) return;
  youtubePlayer = new window.YT.Player(youtubeFrame, {
    events: {
      onReady: () => {
        applyYoutubeVolume();
        if (!youtubeUserPaused) youtubeCommand("playVideo");
      },
      onError: handleYoutubeError,
      onStateChange: handleYoutubeStateChange,
    },
  });
}

function clearYoutubeFrameSource() {
  youtubeDeferredLoadIndex = null;
  try {
    youtubePlayer?.destroy?.();
  } catch {
    // The iframe may already have been detached by YouTube.
  }
  youtubePlayer = null;
  ensureYoutubeFrameElement();
  if (youtubeFrame) youtubeFrame.removeAttribute("src");
}

function youtubePlayerState() {
  try {
    return youtubePlayer?.getPlayerState?.();
  } catch {
    return null;
  }
}

function youtubeCurrentVideoLooksPlayable() {
  try {
    const duration = youtubePlayer?.getDuration?.();
    if (Number.isFinite(duration) && duration > 0) return true;
  } catch {
    // Fall through to other player metadata checks.
  }
  try {
    const loadedFraction = youtubePlayer?.getVideoLoadedFraction?.();
    if (Number.isFinite(loadedFraction) && loadedFraction > 0) return true;
  } catch {
    // Fall through to player video data below.
  }
  try {
    const data = youtubePlayer?.getVideoData?.();
    const videoId = String(data?.video_id || data?.videoId || "").trim();
    const title = String(data?.title || "").trim();
    return Boolean(videoId && title);
  } catch {
    return false;
  }
}

function youtubeVideoIdFromUrl(rawUrl) {
  return youtubeUrlParts(rawUrl)?.videoId || "";
}

function youtubePlayerCurrentVideoId() {
  try {
    const data = youtubePlayer?.getVideoData?.();
    const dataId = String(data?.video_id || data?.videoId || "").trim();
    if (dataId) return dataId;
  } catch {
    // Fall through to getVideoUrl.
  }
  try {
    return youtubeVideoIdFromUrl(youtubePlayer?.getVideoUrl?.() || "");
  } catch {
    return "";
  }
}

function youtubeErrorMatchesCurrentTrack() {
  const expectedId = youtubeVideoIdFromUrl(youtubeItems[youtubeIndex]?.url || "");
  const actualId = youtubePlayerCurrentVideoId();
  return Boolean(!expectedId || !actualId || expectedId === actualId);
}

function youtubeNormalizedErrorCode(error) {
  const value = String(error ?? "").trim();
  if (!value) return "";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? String(numeric) : value;
}

function youtubeErrorIsReportable(error) {
  return YOUTUBE_REPORTABLE_ERROR_CODES.has(youtubeNormalizedErrorCode(error));
}

function youtubeDevErrorScoringEnabled() {
  return ["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname);
}

function youtubeDevPlaybackDiagnosticsEnabled() {
  return youtubeDevErrorScoringEnabled();
}

function markYoutubeTrackInteractive() {
  if (!youtubeTrackLoading) return;
  youtubeTrackLoading = false;
  youtubePlayRequested = false;
  youtubeDevPlaybackStatus = "";
  window.clearTimeout(youtubeReadyTimer);
  updateYoutubeTrackText();
  updateYoutubeControls();
}

function syncYoutubePlaybackState() {
  const state = youtubePlayerState();
  if (state === window.YT?.PlayerState?.PLAYING) {
    youtubeIsPlaying = true;
    youtubeAutoplayBlocked = false;
    youtubePaused = false;
    setYoutubeUserPaused(false);
    markYoutubeTrackReady();
    void fadeYoutubeVolume(youtubeVolume, 1500);
    updateYoutubeControls();
    return true;
  }
  if (state === window.YT?.PlayerState?.PAUSED || state === window.YT?.PlayerState?.CUED) {
    const wasLoading = youtubeTrackLoading;
    if (wasLoading) {
      if (!youtubePlayRequested) {
        markYoutubeTrackInteractive();
      }
      updateYoutubeTrackText();
      updateYoutubeControls();
      return false;
    }
    youtubeIsPlaying = false;
    youtubePaused = true;
    if (!wasLoading) setYoutubeUserPaused(true);
    updateYoutubeTrackText();
    updateYoutubeControls();
  }
  return false;
}

function startYoutubeStatePolling(duration = 6500) {
  window.clearInterval(youtubeStatePollTimer);
  const startedAt = Date.now();
  youtubeStatePollTimer = window.setInterval(() => {
    const detected = syncYoutubePlaybackState();
    if (detected || Date.now() - startedAt >= duration) {
      window.clearInterval(youtubeStatePollTimer);
      youtubeStatePollTimer = 0;
    }
  }, 250);
}

function handleYoutubeStateChange(event) {
  if (!youtubeItems.length) return;
  if (
    event?.data === window.YT?.PlayerState?.PLAYING
  ) {
    syncYoutubePlaybackState();
  } else if (event?.data === window.YT?.PlayerState?.PAUSED || event?.data === window.YT?.PlayerState?.CUED) {
    const wasLoading = youtubeTrackLoading;
    youtubeIsPlaying = false;
    youtubePaused = true;
    if (wasLoading) {
      if (!youtubePlayRequested) {
        markYoutubeTrackInteractive();
      }
    } else {
      setYoutubeUserPaused(true);
    }
    updateYoutubeTrackText();
    updateYoutubeControls();
  }
  if (event?.data === window.YT?.PlayerState?.ENDED && youtubeItems.length > 1) {
    youtubeIsPlaying = false;
    persistYoutubePlayback();
    loadNextYoutubeIndex();
  }
}

function handleYoutubeError(event) {
  if (!youtubeTrackLoading) return;
  youtubeDevPlaybackStatus = `YouTube error ${youtubeNormalizedErrorCode(event?.data) || "unknown"}; trying next...`;
  failCurrentYoutubeTrack(event?.data ?? "player_error", {
    report: youtubeDevErrorScoringEnabled() && youtubeErrorIsReportable(event?.data),
  });
}

function reportYoutubePlaybackError(item, error, token) {
  if (!youtubeDevErrorScoringEnabled()) return;
  const genreId =
    item?.genreId ||
    nodes.get(activeLeafKey)?.genreId ||
    nodes.get(currentKey)?.genreId ||
    "";
  if (!genreId || !item?.url || youtubeReportedFailureTokens.has(token)) return;
  youtubeReportedFailureTokens.add(token);

  const body = JSON.stringify({
    genre_id: genreId,
    youtube_url: item.url,
    youtube_title: item.title || "",
    youtube_artist: item.artist || "",
    error: String(error ?? "unknown").slice(0, 120),
    page_url: window.location.href,
  });
  try {
    if (navigator.sendBeacon) {
      const sent = navigator.sendBeacon(
        "/v1/feedback/youtube-error",
        new Blob([body], { type: "application/json" })
      );
      if (sent) return;
    }
  } catch {
    // Fall through to fetch.
  }
  fetch("/v1/feedback/youtube-error", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {});
}

function failCurrentYoutubeTrack(error = "unknown", { report = youtubeErrorIsReportable(error) } = {}) {
  const token = youtubeLoadToken;
  const currentItem = youtubeItems[youtubeIndex] || null;
  const currentUrl = currentItem?.url || "";
  if (currentUrl) youtubeErroredUrls.add(currentUrl);
  if (report) reportYoutubePlaybackError(currentItem, error, token);
  window.clearTimeout(youtubeErrorTimer);
  window.clearTimeout(youtubeReadyTimer);
  window.clearInterval(youtubeStatePollTimer);
  youtubeStatePollTimer = 0;
  youtubeTrackLoading = true;
  youtubePaused = true;
  youtubeIsPlaying = false;
  youtubeAutoplayBlocked = false;
  youtubePlayRequested = false;
  youtubeDevPlaybackStatus = `Error ${youtubeNormalizedErrorCode(error) || "unknown"}; trying next...`;
  updateYoutubeTrackText({ loading: true });
  updateYoutubeControls({ loading: true });
  youtubeErrorTimer = window.setTimeout(() => {
    if (token !== youtubeLoadToken) return;
    loadNextYoutubeIndex();
  }, 250);
}

function youtubeStateAllowsManualPlay(state) {
  return (
    state === window.YT?.PlayerState?.PAUSED ||
    state === window.YT?.PlayerState?.CUED
  );
}

function youtubeHasActivePlayback() {
  return Boolean(youtubeItems.length && youtubeIsPlaying && !youtubePaused && !youtubeUserPaused && !youtubeTrackLoading);
}

function markYoutubeAutoplayBlocked() {
  youtubePaused = true;
  youtubeIsPlaying = false;
  youtubeAutoplayBlocked = true;
  youtubePlayRequested = false;
  youtubeDevPlaybackStatus = "Playable embed found; autoplay blocked or not started.";
  window.clearTimeout(youtubeReadyTimer);
  youtubeTrackLoading = false;
  updateYoutubeTrackText();
  updateYoutubeControls();
}

function scheduleYoutubeReadyTimeout(delay = 5000, token = youtubeLoadToken) {
  window.clearTimeout(youtubeReadyTimer);
  youtubeReadyTimer = window.setTimeout(() => {
    if (token !== youtubeLoadToken) return;
    if (youtubeTrackLoading) {
      if (!syncYoutubePlaybackState()) {
        const state = youtubePlayerState();
        const looksPlayable = youtubeCurrentVideoLooksPlayable();
        if (youtubePlayRequested) {
          if (looksPlayable) {
            markYoutubeAutoplayBlocked();
          }
        } else if (youtubeStateAllowsManualPlay(state) || looksPlayable) {
          markYoutubeTrackInteractive();
        }
      }
    }
  }, delay);
}

function markYoutubeTrackReady() {
  if (!youtubeTrackLoading) return;
  youtubeTrackLoading = false;
  youtubeDevPlaybackStatus = "";
  window.clearTimeout(youtubeReadyTimer);
  youtubeLastKnownSeconds = youtubeResumeSeconds || youtubeLastKnownSeconds || 0;
  youtubeTrackStartedAt = Date.now() - (youtubeLastKnownSeconds * 1000);
  if (youtubeResumeSeconds > 1) {
    try {
      youtubePlayer?.seekTo?.(youtubeResumeSeconds, true);
    } catch {
      // The embed start parameter already covers the common resume path.
    }
    youtubeResumeSeconds = 0;
  }
  persistYoutubePlayback();
  startYoutubeProgressTimer();
  updateYoutubeTrackText();
  updateYoutubeControls();
}

function showYoutubePlaybackErrorState() {
  youtubeItems = [];
  youtubeIndex = 0;
  youtubeDeferredLoadIndex = null;
  youtubeResumeSeconds = 0;
  youtubeLastKnownSeconds = 0;
  youtubeTrackStartedAt = 0;
  youtubeTrackLoading = false;
  youtubePaused = true;
  youtubeIsPlaying = false;
  youtubeAutoplayBlocked = false;
  youtubePlayRequested = false;
  youtubePlaybackErrorExhausted = true;
  youtubeDevPlaybackStatus = "";
  window.clearTimeout(youtubeErrorTimer);
  window.clearTimeout(youtubeReadyTimer);
  window.clearInterval(youtubeStatePollTimer);
  youtubeStatePollTimer = 0;
  youtubeCommand("pauseVideo");
  clearYoutubeFrameSource();
  updateYoutubeTrackText({ noPlaylist: true, genreName: youtubeGenreTitle?.textContent || "this genre" });
  updateYoutubeControls({ noPlaylist: true });
}

function loadNextYoutubeIndex({ direction = 1 } = {}) {
  if (!youtubeItems.length) return;
  if (youtubeItems.length < 2) {
    showYoutubePlaybackErrorState();
    return;
  }
  const total = youtubeItems.length;
  for (let offset = 1; offset <= total; offset += 1) {
    const nextIndex = (youtubeIndex + (offset * direction) + total) % total;
    const nextUrl = youtubeItems[nextIndex]?.url || "";
    if (nextUrl && youtubeErroredUrls.has(nextUrl)) continue;
    persistYoutubePlayback();
    loadYoutubeIndex(nextIndex);
    updateYoutubeControls();
    return;
  }
  showYoutubePlaybackErrorState();
}

function youtubeCommand(command, args = []) {
  ensureYoutubeFrameElement();
  if (!youtubeFrame?.contentWindow) return;
  youtubeFrame.contentWindow.postMessage(
    JSON.stringify({ event: "command", func: command, args }),
    "https://www.youtube-nocookie.com"
  );
}

function youtubeLoadVideoWithApi(item, startSeconds = 0, shouldAutoplay = true) {
  ensureYoutubeFrameElement();
  const parts = youtubeUrlParts(item?.url);
  if (!youtubePlayer || !youtubeFrame?.src || !parts?.videoId) return false;
  const payload = {
    videoId: parts.videoId,
    startSeconds: Math.max(0, Math.floor(Number(startSeconds) || 0)),
  };
  const command = shouldAutoplay ? "loadVideoById" : "cueVideoById";
  try {
    youtubePlayer?.[command]?.(payload);
    return true;
  } catch {
    return false;
  }
}

function loadYoutubeIndex(index) {
  youtubeLoadToken += 1;
  window.clearTimeout(youtubeErrorTimer);
  window.clearTimeout(youtubeReadyTimer);
  youtubeIndex = clamp(index, 0, Math.max(0, youtubeItems.length - 1));
  const item = youtubeItems[youtubeIndex];
  if (item?.url && youtubeErroredUrls.has(item.url)) {
    if (youtubeItems.length > 1) {
      loadNextYoutubeIndex();
    } else {
      showYoutubePlaybackErrorState();
    }
    return;
  }
  const startSeconds = youtubeResumeSeconds > 1 ? youtubeResumeSeconds : 0;
  const shouldAutoplay = !youtubeUserPaused;
  const src = youtubeEmbedUrl(item?.url, youtubeItems, youtubeIndex, startSeconds, {
    autoplay: shouldAutoplay,
  });
  ensureYoutubeFrameElement();
  if (!youtubeFrame || !src) return;
  youtubePlaybackErrorExhausted = false;
  youtubeDevPlaybackStatus = "";
  youtubeLastKnownSeconds = startSeconds;
  youtubeTrackStartedAt = 0;
  youtubeTrackLoading = true;
  youtubePaused = true;
  youtubeIsPlaying = false;
  youtubeAutoplayBlocked = false;
  youtubePlayRequested = shouldAutoplay;
  youtubeDevPlaybackStatus = shouldAutoplay
    ? "Requesting autoplay; waiting for play or error..."
    : "Autoplay disabled; waiting for cue...";
  applyYoutubeVolume(lowYoutubeVolume());
  if (!youtubePlayer && !window.YT?.Player) {
    youtubeDeferredLoadIndex = youtubeIndex;
    youtubeDevPlaybackStatus = "Waiting for YouTube iframe API...";
    ensureYoutubeApi();
    updateYoutubeTrackText({ loading: true });
    updateYoutubeControls({ loading: true });
    return;
  }
  const loadedViaApi = youtubeLoadVideoWithApi(item, startSeconds, shouldAutoplay);
  if (!loadedViaApi) {
    youtubeDevPlaybackStatus = "Mounting iframe; waiting for player event...";
    if (youtubePlayer) clearYoutubeFrameSource();
    youtubeFrame.src = src;
    ensureYoutubeApi();
    attachYoutubePlayer();
  } else {
    youtubeDevPlaybackStatus = shouldAutoplay
      ? "loadVideoById sent; waiting for play or error..."
      : "cueVideoById sent; waiting for cue...";
  }
  if (shouldAutoplay) {
    window.setTimeout(() => {
      if (youtubeUserPaused) return;
      applyYoutubeVolume(lowYoutubeVolume());
      if (loadedViaApi) {
        try {
          youtubePlayer?.playVideo?.();
        } catch {
          youtubeCommand("playVideo");
        }
      } else {
        youtubeCommand("playVideo");
      }
      startYoutubeStatePolling();
    }, 800);
    scheduleYoutubeReadyTimeout();
  } else {
    scheduleYoutubeReadyTimeout(3500);
  }
  updateYoutubeTrackText({ loading: true });
  updateYoutubeControls({ loading: true });
}

function updateYoutubeControls({ noPlaylist = false, loading = false } = {}) {
  const hasEmbed = youtubeItems.some(item => youtubeEmbedUrl(item.url, [item], 0));
  loading = Boolean(loading || youtubeTrackLoading);
  noPlaylist = noPlaylist && !loading;
  if (youtubeCard) {
    youtubeCard.classList.toggle("youtube-empty-state", loading);
    youtubeCard.classList.toggle("youtube-no-playlist-state", noPlaylist);
    youtubeCard.classList.toggle("youtube-playback-error-state", noPlaylist && youtubePlaybackErrorExhausted);
    youtubeCard.classList.toggle("youtube-dev-diagnostics-state", youtubeDevPlaybackDiagnosticsEnabled());
  }
  document.body.classList.toggle("youtube-no-playlist-active", noPlaylist);
  if (youtubeVolumeInput) youtubeVolumeInput.disabled = !hasEmbed || noPlaylist;
  if (youtubePauseButton) {
    const isPausedState = !loading && (!youtubeIsPlaying || youtubePaused || youtubeUserPaused);
    youtubePauseButton.disabled = !hasEmbed || loading;
    youtubePauseButton.classList.toggle("is-playing", youtubeIsPlaying && !youtubePaused);
    youtubePauseButton.classList.toggle("is-paused", isPausedState);
    youtubePauseButton.classList.toggle("autoplay-blocked", youtubeAutoplayBlocked);
    youtubePauseButton.setAttribute(
      "aria-label",
      youtubeIsPlaying && !youtubePaused ? "Pause YouTube" : "Play YouTube"
    );
  }
  if (youtubeSkipButton) youtubeSkipButton.disabled = youtubeItems.length < 2;
  if (!hasEmbed) clearYoutubeFrameSource();
  updateYoutubePinUi();
}

function clearYoutubePlaybackSurface() {
  youtubeItems = [];
  youtubeIndex = 0;
  youtubeDeferredLoadIndex = null;
  youtubeResumeSeconds = 0;
  youtubeTrackLoading = false;
  youtubePlaybackErrorExhausted = false;
  youtubePaused = true;
  youtubeIsPlaying = false;
  youtubeAutoplayBlocked = false;
  youtubePlayRequested = false;
  youtubeLastKnownSeconds = 0;
  youtubeTrackStartedAt = 0;
  window.clearTimeout(youtubeErrorTimer);
  window.clearTimeout(youtubeReadyTimer);
  window.clearInterval(youtubeStatePollTimer);
  youtubeStatePollTimer = 0;
  youtubeCommand("pauseVideo");
  clearYoutubeFrameSource();
  if (youtubeSongTitle) {
    youtubeSongTitle.textContent = "";
    youtubeSongTitle.hidden = true;
    youtubeSongTitle.classList.remove("youtube-loading-title", "youtube-dev-loading-title", "youtube-openable-title");
    youtubeSongTitle.removeAttribute("role");
    youtubeSongTitle.removeAttribute("tabindex");
    youtubeSongTitle.removeAttribute("title");
  }
  if (youtubeArtistTitle) {
    youtubeArtistTitle.textContent = "";
    youtubeArtistTitle.style.display = "none";
  }
}

function hideYoutubeCardForSelection() {
  clearYoutubePlaybackStore();
  youtubePlaybackNode = null;
  youtubeDeferredSelectionNode = null;
  youtubePlaylistKey = "";
  clearYoutubePlaybackSurface();
  if (youtubeGenreTitle) youtubeGenreTitle.textContent = "";
  updateYoutubeTrackText();
  updateYoutubeControls();
  if (youtubeCard) {
    youtubeCard.classList.add("youtube-card-hidden");
    youtubeCard.classList.remove("youtube-empty-state", "youtube-no-playlist-state", "youtube-playback-error-state");
  }
  document.body.classList.remove("youtube-no-playlist-active");
}

function updateYoutubeTrackText({ noPlaylist = false, loading = false, genreName = "" } = {}) {
  const currentItem = youtubeItems[youtubeIndex] || null;
  const hasEmbed = Boolean(currentItem);
  loading = Boolean(loading || youtubeTrackLoading);
  noPlaylist = noPlaylist && !loading;
  const artist = String(currentItem?.artist || "").trim();
  const devLoading = Boolean(loading && hasEmbed && youtubeDevPlaybackDiagnosticsEnabled());
  if (youtubeSongTitle) {
    youtubeSongTitle.textContent = devLoading
      ? `Trying: ${currentItem.title || "Untitled video"}`
      : loading
      ? "Loading..."
      : (hasEmbed ? (currentItem.title || "Untitled video") : "");
    youtubeSongTitle.hidden = !loading && !hasEmbed;
    youtubeSongTitle.classList.toggle("youtube-loading-title", loading && !devLoading);
    youtubeSongTitle.classList.toggle("youtube-dev-loading-title", devLoading);
    youtubeSongTitle.classList.toggle("youtube-openable-title", hasEmbed && !loading);
    if (hasEmbed && !loading) {
      youtubeSongTitle.setAttribute("role", "link");
      youtubeSongTitle.setAttribute("tabindex", "0");
    } else {
      youtubeSongTitle.removeAttribute("role");
      youtubeSongTitle.removeAttribute("tabindex");
      youtubeSongTitle.removeAttribute("title");
    }
  }
  if (youtubeArtistTitle) {
    const devStatus = youtubeDevPlaybackStatus || (artist ? `Artist: ${artist}` : "Waiting for YouTube...");
    youtubeArtistTitle.textContent = devLoading ? devStatus : (!loading && hasEmbed ? artist : "");
    youtubeArtistTitle.style.display = (devLoading || (!loading && hasEmbed && artist)) ? "" : "none";
  }
  if (youtubeEmptyMessage) {
    const name = genreName || youtubeGenreTitle?.textContent || "this genre";
    youtubeEmptyMessage.replaceChildren();
    if (noPlaylist && youtubePlaybackErrorExhausted) {
      youtubeEmptyMessage.append("We couldn't play videos for ");
      const genreNameEl = document.createElement("span");
      genreNameEl.className = "youtube-empty-genre-name";
      genreNameEl.textContent = name;
      youtubeEmptyMessage.append(genreNameEl, " right now.");
    } else if (noPlaylist) {
      youtubeEmptyMessage.append("We haven't found any good examples of ");
      const genreNameEl = document.createElement("span");
      genreNameEl.className = "youtube-empty-genre-name";
      genreNameEl.textContent = name;
      youtubeEmptyMessage.append(genreNameEl);
    }
    youtubeEmptyMessage.hidden = !noPlaylist;
  }
  if (youtubeSubmitButton) {
    youtubeSubmitButton.hidden = !noPlaylist;
  }
}

function youtubeNodeIdentity(node) {
  return String(node?.genreId || node?.key || node?.id || "");
}

function youtubePinnedSelectionDiffers() {
  if (!youtubePinned || !youtubePlaybackNode || !youtubeDeferredSelectionNode) return false;
  return youtubeNodeIdentity(youtubePlaybackNode) !== youtubeNodeIdentity(youtubeDeferredSelectionNode);
}

function currentSelectionNodeForYoutube() {
  if (cloudMode) return selectedCloudNode();
  if (timelineMode) return selectedTimelineNode();
  return (
    nodes.get(activeLeafKey) ||
    nodes.get(currentKey) ||
    nodes.get(detailCardNodeKey) ||
    null
  );
}

function setYoutubeMenuOpen(open) {
  if (!youtubeContextMenu || !youtubeMenuButton) return;
  youtubeContextMenu.hidden = !open;
  youtubeMenuButton.setAttribute("aria-expanded", open ? "true" : "false");
  youtubeMenuButton.classList.toggle("menu-open", open);
  if (!open) return;

  const buttonRect = youtubeMenuButton.getBoundingClientRect();
  const menuRect = youtubeContextMenu.getBoundingClientRect();
  const gap = 6;
  const left = clamp(buttonRect.right - menuRect.width, 8, window.innerWidth - menuRect.width - 8);
  const top = clamp(buttonRect.bottom + gap, 8, window.innerHeight - menuRect.height - 8);
  youtubeContextMenu.style.left = `${left}px`;
  youtubeContextMenu.style.top = `${top}px`;
}

function updateYoutubePinUi() {
  const pinnedDiffers = youtubePinnedSelectionDiffers();
  const playbackName = youtubePlaybackNode?.label || youtubeGenreTitle?.textContent || "genre";
  if (youtubePinIndicator) {
    youtubePinIndicator.hidden = !youtubePinned || !youtubePlaybackNode;
    youtubePinIndicator.title = youtubePinned ? `${playbackName} radio is pinned` : "";
    youtubePinIndicator.setAttribute("aria-label", youtubePinned ? `${playbackName} radio is pinned` : "Pinned radio");
    youtubePinIndicator.classList.toggle("pin-selection-differs", pinnedDiffers);
  }
  if (youtubePinButton) {
    const label = `${youtubePinned ? "Unpin" : "Pin"} ${playbackName} radio`;
    const text = youtubePinButton.querySelector("span:last-child");
    if (text) text.textContent = label;
    else youtubePinButton.textContent = label;
    youtubePinButton.disabled = !youtubePlaybackNode || (!youtubePinned && !youtubeItems.length);
  }
  if (youtubeOpenButton) {
    youtubeOpenButton.disabled = youtubeTrackLoading || !youtubeItems[youtubeIndex]?.url;
  }
  if (youtubeMenuButton) {
    youtubeMenuButton.classList.toggle("menu-open", youtubeContextMenu ? !youtubeContextMenu.hidden : false);
    if (youtubeContextMenu && !youtubeContextMenu.hidden) setYoutubeMenuOpen(true);
  }
}

function toggleYoutubePin() {
  if (!youtubePlaybackNode || (!youtubePinned && !youtubeItems.length)) return;
  if (youtubePinned) {
    youtubePinned = false;
    const nextNode = youtubeDeferredSelectionNode || currentSelectionNodeForYoutube();
    youtubeDeferredSelectionNode = null;
    updateYoutubePinUi();
    if (nextNode && youtubeNodeIdentity(nextNode) !== youtubeNodeIdentity(youtubePlaybackNode)) {
      updateYoutubeCardForSelection(nextNode);
    }
    return;
  }
  youtubePinned = true;
  youtubeDeferredSelectionNode = null;
  updateYoutubePinUi();
}

async function transitionYoutubePlaylist(nextKey, nextItems, { noPlaylist, loading, genreName } = {}) {
  const token = ++youtubePlaylistTransitionToken;
  const isSwappingRadio = Boolean(youtubePlaylistKey && youtubePlaylistKey !== nextKey);
  let storedPlayback = youtubePlaybackStore();
  const isStoredRadioMismatch = Boolean(storedPlayback.playlistKey && storedPlayback.playlistKey !== nextKey);
  if (isSwappingRadio || isStoredRadioMismatch) {
    clearYoutubePlaybackStore();
    storedPlayback = { version: 3, playlistKey: "", entry: null };
  }
  if (!nextItems.length) {
    youtubePlaylistKey = nextKey;
    youtubeErroredUrls = new Set();
    youtubeReportedFailureTokens = new Set();
    youtubePlaybackErrorExhausted = false;
    clearYoutubePlaybackSurface();
    updateYoutubeTrackText({ noPlaylist, loading, genreName });
    updateYoutubeControls({ noPlaylist, loading });
    return;
  }
  const hadActivePlayer = Boolean(youtubeFrame?.getAttribute("src") && youtubeItems.length);
  if (isSwappingRadio && hadActivePlayer) {
    clearYoutubePlaybackSurface();
    updateYoutubeTrackText({ loading: true, genreName });
    updateYoutubeControls({ loading: true });
  } else if (hadActivePlayer) {
    await fadeYoutubeVolume(lowYoutubeVolume(), 1000);
    if (token !== youtubePlaylistTransitionToken) return;
  }
  youtubePlaylistKey = nextKey;
  youtubeErroredUrls = new Set();
  youtubeReportedFailureTokens = new Set();
  youtubePlaybackErrorExhausted = false;
  const restored = restoredYoutubePlayback(nextKey, nextItems, storedPlayback);
  youtubeItems = restored?.items || shuffledYoutubeItems(nextItems);
  youtubeIndex = restored?.index || 0;
  youtubeResumeSeconds = restored?.seconds || 0;
  if (youtubeItems.length) {
    loadYoutubeIndex(youtubeIndex);
  } else {
    youtubeResumeSeconds = 0;
    updateYoutubeTrackText({ noPlaylist, loading, genreName });
    updateYoutubeControls({ noPlaylist, loading });
  }
}

function updateYoutubeCardForSelection(node) {
  if (!youtubeCard || !youtubeGenreTitle) return;

  const nextItems = youtubeItemsForNode(node);
  const isCoreNode = isMusicCoreNode(node);
  const hasKnownPlaylistState = Boolean(
    node?.isDetailLoaded ||
    nodeHasYoutubePlaylistData(node) ||
    nodeHasExplicitNoPlaylist(node) ||
    isCoreNode
  );
  const nextKey = youtubeNodeIdentity(node);
  if (
    youtubePinned &&
    youtubePlaybackNode &&
    nextKey &&
    nextKey !== youtubeNodeIdentity(youtubePlaybackNode)
  ) {
    youtubeDeferredSelectionNode = node;
    updateYoutubePinUi();
    return;
  }
  if (isCoreNode && !youtubePinned) {
    hideYoutubeCardForSelection();
    return;
  }

  const previousPlaybackKey = youtubeNodeIdentity(youtubePlaybackNode);
  if (!youtubePinned && nextKey && previousPlaybackKey && nextKey !== previousPlaybackKey) {
    clearYoutubePlaybackSurface();
  }
  youtubeCard.classList.remove("youtube-card-hidden");
  youtubePlaybackNode = node || null;
  scheduleDetailCardIdleReturn();
  if (!youtubePinned) youtubeDeferredSelectionNode = null;
  youtubeGenreTitle.textContent = node?.label || "Music";
  const noPlaylist = Boolean(hasKnownPlaylistState && !nextItems.length);
  const loading = Boolean(!hasKnownPlaylistState && !nextItems.length);
  if (loading && nextKey !== youtubePlaylistKey) {
    clearYoutubePlaybackSurface();
    updateYoutubeTrackText({ loading: true, genreName: node?.label || "Music" });
    updateYoutubeControls({ loading: true });
    updateYoutubePinUi();
    return;
  }
  if (nextKey !== youtubePlaylistKey) {
    void transitionYoutubePlaylist(nextKey, nextItems, {
      noPlaylist,
      loading,
      genreName: node?.label || "Music",
    });
  }
  updateYoutubeTrackText({ noPlaylist, loading, genreName: node?.label || "Music" });
  updateYoutubeControls({ noPlaylist, loading });
  updateYoutubePinUi();
}

function openCurrentYoutubeTrack() {
  const item = youtubeItems[youtubeIndex];
  if (!item?.url || youtubeTrackLoading) return;
  const seconds = youtubeCurrentSeconds();
  persistYoutubePlayback();
  youtubePaused = true;
  youtubeIsPlaying = false;
  youtubeAutoplayBlocked = false;
  setYoutubeUserPaused(true);
  youtubeCommand("pauseVideo");
  updateYoutubeTrackText();
  updateYoutubeControls();
  window.open(youtubeWatchUrl(item.url, seconds), "_blank", "noopener");
}

async function selectPlaybackGenreInCurrentGraph() {
  const node = playbackDetailNode() || youtubePlaybackNode;
  const genreId = youtubeNodeIdentity(node);
  if (!genreId || genreId === ROOT_KEY) return;
  try {
    if (cloudMode) {
      await openCloudGenre(genreId);
      return;
    }
    if (timelineMode) {
      const timelineNode = timelineData?.nodes?.find(item => item.id === genreId);
      await openTimelineNode(timelineNode || {
        id: genreId,
        label: node?.label || node?.title || "",
        wikipedia_title: node?.title || node?.label || "",
      });
      return;
    }
    const visible = (node?.key && nodes.has(node.key)) ? nodes.get(node.key) : findVisibleGenreNode(genreId);
    if (visible) {
      await activateNode(visible.key);
      return;
    }
    await ensureGraphSelectionByGenreId(genreId);
  } catch (err) {
    console.error("[wiki-genres] playback genre selection failed", err);
    setStatus("Could not select playback genre");
  }
}

function playbackDetailNode() {
  if (!youtubePlaybackNode) return null;
  if (youtubePlaybackNode.genreId && detailCache.has(youtubePlaybackNode.genreId)) {
    return detailCache.get(youtubePlaybackNode.genreId);
  }
  return youtubePlaybackNode;
}

async function showPlaybackDetailCard(options = {}) {
  const token = ++youtubeHoverCardToken;
  youtubeCardHovered = true;
  if (options.forceOpen) allowDetailCardForManualSelection();
  const node = playbackDetailNode();
  updateDetailCardVisibility();
  if (!node) return;
  updateCard(node, { preserveRelation: true });
  const genreId = node.genreId;
  if (!genreId || node.isDetailLoaded) return;
  try {
    const detail = await getGenreDetail(genreId);
    if (token !== youtubeHoverCardToken || !youtubeCardHovered) return;
    updateCard(detail, { preserveRelation: true });
  } catch (err) {
    console.error("[wiki-genres] playback detail failed", err);
  }
}

function restoreDetailCardAfterPlaybackHover() {
  youtubeCardHovered = false;
  youtubeHoverCardToken++;
  updateDetailCardVisibility();

  const node = currentDetailFallbackNode();
  if (node) updateCard(node);
}

function playbackRadioDetailNode() {
  const node = playbackDetailNode() || youtubePlaybackNode;
  return nodeHasRestorableDetail(node) ? node : null;
}

function clearDetailCardIdleTimer() {
  window.clearTimeout(detailCardIdleTimer);
  detailCardIdleTimer = 0;
}

function scheduleDetailCardIdleReturn(renderedKey = detailCardRenderedKey) {
  clearDetailCardIdleTimer();
  const playbackNode = playbackRadioDetailNode();
  if (!playbackNode) return;
  if (!document.body.classList.contains("detail-card-visible")) return;
  if (detailCardSuppressed || youtubeCardHovered || hoveredNodeKey) return;
  if (renderedKey && renderedKey === detailCardIdentity(playbackNode)) return;
  detailCardIdleTimer = window.setTimeout(() => {
    detailCardIdleTimer = 0;
    const nextNode = playbackRadioDetailNode();
    if (!nextNode) return;
    if (!document.body.classList.contains("detail-card-visible")) return;
    if (detailCardSuppressed || youtubeCardHovered || hoveredNodeKey) return;
    updateCard(nextNode, { idleReturn: true });
  }, DETAIL_CARD_RADIO_IDLE_MS);
}

function activePathLabels() {
  const labels = [];
  let node = nodes.get(currentKey);
  while (node) {
    labels.unshift(node.label || node.title || node.genreId || node.key);
    node = node.parentKey ? nodes.get(node.parentKey) : null;
  }
  return labels;
}

function feedbackContext(kind) {
  const node =
    kind === "relationship"
      ? (nodes.get(detailCardNodeKey) || nodes.get(activeLeafKey) || nodes.get(currentKey))
      : (playbackDetailNode() || nodes.get(activeLeafKey) || nodes.get(currentKey) || nodes.get(detailCardNodeKey));
  const youtubeItem = youtubeItems[youtubeIndex] || {};
  return {
    reportType: kind === "music" ? "Music submission" : (kind === "youtube" ? "YouTube playlist" : "Relationship data"),
    genreName: node?.label || "",
    genreId: node?.genreId || "",
    relationship: node ? relationshipLine(node) : "",
    youtubeUrl: youtubeItem.url || "",
    youtubeTitle: youtubeItem.title || "",
    youtubeArtist: youtubeItem.artist || "",
    pageUrl: window.location.href,
    graphPath: activePathLabels().join(" / "),
  };
}

function feedbackRequestPayload(kind) {
  const context = feedbackContext(kind);
  return {
    report_type: context.reportType,
    genre_name: context.genreName,
    genre_id: context.genreId,
    relationship: context.relationship,
    youtube_url: context.youtubeUrl,
    youtube_title: context.youtubeTitle,
    youtube_artist: context.youtubeArtist,
    page_url: context.pageUrl,
    graph_path: context.graphPath,
    notes: feedbackNotes?.value?.trim() || "",
  };
}

function updateFeedbackModalContext(kind) {
  if (!feedbackContextEl) return;
  const context = feedbackContext(kind);
  const lines = [
    ["Type", context.reportType],
    ["Genre", context.genreName],
    ["Connection", context.relationship],
    ["YouTube", context.youtubeTitle || context.youtubeUrl],
  ].filter(([, value]) => Boolean(value));
  feedbackContextEl.innerHTML = "";
  for (const [label, value] of lines) {
    const div = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = `${label}: `;
    div.append(strong, document.createTextNode(value));
    feedbackContextEl.appendChild(div);
  }
}

function openFeedbackModal(kind) {
  if (!feedbackModal) return;
  feedbackKind = kind;
  feedbackModal.hidden = false;
  if (feedbackModalTitle) {
    feedbackModalTitle.textContent = kind === "music"
      ? "Submit songs"
      : (kind === "youtube" ? "Video feedback" : "Genre feedback");
  }
  if (feedbackNotes) feedbackNotes.value = "";
  if (feedbackStatus) feedbackStatus.textContent = "";
  updateFeedbackModalContext(kind);
  feedbackNotes?.focus();
}

function closeFeedbackModal() {
  if (!feedbackModal) return;
  feedbackModal.hidden = true;
  if (feedbackStatus) feedbackStatus.textContent = "";
}

function positiveMetricValue(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) return number;
  }
  return null;
}

function textMetricsFromPayload(payload = {}) {
  return {
    textWidth: positiveMetricValue(payload.text_width, payload.textWidth),
    textHeight: positiveMetricValue(payload.text_height, payload.textHeight),
    boxWidth: positiveMetricValue(payload.box_width, payload.boxWidth),
    boxHeight: positiveMetricValue(payload.box_height, payload.boxHeight),
    boxPadX: positiveMetricValue(payload.box_pad_x, payload.boxPadX),
    boxPadY: positiveMetricValue(payload.box_pad_y, payload.boxPadY),
  };
}

function textMetricsFromEdge(edge = {}) {
  return {
    textWidth: positiveMetricValue(edge.to_text_width, edge.toTextWidth),
    textHeight: positiveMetricValue(edge.to_text_height, edge.toTextHeight),
    boxWidth: positiveMetricValue(edge.to_box_width, edge.toBoxWidth),
    boxHeight: positiveMetricValue(edge.to_box_height, edge.toBoxHeight),
    boxPadX: positiveMetricValue(edge.to_box_pad_x, edge.toBoxPadX),
    boxPadY: positiveMetricValue(edge.to_box_pad_y, edge.toBoxPadY),
  };
}

async function submitFeedback() {
  if (!feedbackForm || !feedbackSubmitButton) return;
  feedbackSubmitButton.disabled = true;
  if (feedbackStatus) feedbackStatus.textContent = "Sending feedback...";
  try {
    await fetchJson("/v1/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(feedbackRequestPayload(feedbackKind)),
    });
    if (feedbackStatus) feedbackStatus.textContent = "Feedback sent";
    window.setTimeout(closeFeedbackModal, 650);
  } catch (err) {
    console.error("[wiki-genres] feedback failed", err);
    if (feedbackStatus) feedbackStatus.textContent = "Could not send feedback";
  } finally {
    feedbackSubmitButton.disabled = false;
  }
}

function genreFromDetail(detail, options = {}) {
  const aliases = uniqueStrings((detail.aliases || []).map(a => a.alias));
  const origins = uniqueStrings((detail.origins || []).map(o => o.value));
  return {
    genreId: detail.id,
    label: labelFromTitle(detail.wikipedia_title),
    title: normalizeLabel(detail.wikipedia_title),
    qid: detail.wikidata_qid,
    color: detail.similarity_color || detail.infobox_color,
    colorConfidence: detail.color_confidence,
    ...textMetricsFromPayload(detail),
    summary: detail.summary,
    monthlyViews: detail.monthly_views_p30,
    wikipedia_url: detail.wikipedia_url,
    aliases,
    origins,
    instruments: detail.instruments || [],
    categories: detail.categories || [],
    hasPlaylist: Boolean(
      (detail.youtube_items || detail.youtubeItems || []).length ||
      (detail.youtube_urls || detail.youtubeUrls || detail.youtube_playlist_urls || detail.youtubePlaylistUrls || []).length
    ),
    youtubeUrls: normalizeYoutubeUrlList(
      detail.youtube_urls ||
      detail.youtubeUrls ||
      detail.youtube_playlist_urls ||
      detail.youtubePlaylistUrls ||
      []
    ),
    youtubeItems: normalizeYoutubeItems(
      detail.youtube_items ||
      detail.youtubeItems ||
      detail.youtube_videos ||
      detail.youtubeVideos ||
      detail.youtube_urls ||
      detail.youtubeUrls ||
      detail.youtube_playlist_urls ||
      detail.youtubePlaylistUrls ||
      []
    ),
    isDetailLoaded: Boolean(options.detailLoaded),
    isUnresolved: false,
  };
}

function fillInlineList(container, items, className) {
  container.innerHTML = "";
  for (const item of items) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = item;
    container.appendChild(span);
  }
}

function capitalizeDisplayTerm(value) {
  return normalizeLabel(value).replace(/\S+/g, word => {
    if (/^[A-Z0-9&]{2,}$/.test(word)) return word;
    const parts = word.split("-");
    return parts.map((part, index) => {
      if (!part) return part;
      if (/^[A-Z0-9&]{2,}$/.test(part)) return part;
      const lower = part.toLocaleLowerCase();
      const first = lower.charAt(0).toLocaleUpperCase();
      return index === 0 ? `${first}${lower.slice(1)}` : lower;
    }).join("-");
  });
}

function aliasCompareKey(value) {
  return normalizeLabel(value)
    .toLocaleLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function displayAliasesForCard(g) {
  const titleKeys = new Set([
    aliasCompareKey(g?.label),
    aliasCompareKey(g?.title),
  ].filter(Boolean));
  return uniqueStrings(g?.aliases || [])
    .map(capitalizeDisplayTerm)
    .filter(Boolean)
    .filter(alias => !titleKeys.has(aliasCompareKey(alias)))
    .slice(0, 8);
}

function metadataIcon(kind) {
  if (kind === "origin") return "location_on";
  if (kind === "instrument") return "piano";
  return "info";
}

function cleanCategory(value) {
  return normalizeLabel(value).replace(/^Category:/i, "");
}

function metadataItems(g) {
  const items = [];
  const origins = uniqueStrings(g.origins).map(capitalizeDisplayTerm);
  if (origins.length) {
    items.push({ kind: "origin", value: origins.join(", ") });
  }
  const instruments = uniqueStrings(g.instruments).map(capitalizeDisplayTerm);
  if (instruments.length) {
    items.push({ kind: "instrument", value: instruments.join(", ") });
  }
  return items;
}

async function getGenreDetail(genreId) {
  const cached = detailCache.get(genreId);
  if (cached?.isDetailLoaded) return cached;
  const detail = await fetchJson(`/v1/genres/${encodeURIComponent(genreId)}`);
  const genre = genreFromDetail(detail, { detailLoaded: true });
  detailCache.set(genreId, genre);
  return genre;
}

async function resolveTitle(title) {
  const data = await fetchJson(`/v1/resolve?title=${encodeURIComponent(title)}`);
  const genre = genreFromDetail(data.genre, {
    detailLoaded: Boolean(data.genre?.outbound_edges || data.genre?.inbound_edges),
  });
  detailCache.set(genre.genreId, genre);
  return genre;
}

function readCachedRoots() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(STORAGE_ROOTS_KEY) || "null");
    if (!Array.isArray(parsed)) return null;
    const roots = parsed.filter(g => g && g.genreId && g.label && positiveMetricValue(g.textWidth, g.text_width));
    return roots.length === parsed.length ? roots : null;
  } catch {
    return null;
  }
}

function writeCachedRoots(items) {
  try {
    sessionStorage.setItem(STORAGE_ROOTS_KEY, JSON.stringify(items));
  } catch {
    // Session storage is an optimization only.
  }
}

async function loadRootChildren() {
  const cached = readCachedRoots();
  if (cached?.length) {
    for (const item of cached) detailCache.set(item.genreId, item);
    return cached;
  }

  if (!rootChildrenPromise) {
    rootChildrenPromise = mapWithConcurrency(ROOT_TITLES, ROOT_RESOLVE_CONCURRENCY, resolveTitle)
      .then(results => {
        const roots = results
          .filter(r => r.status === "fulfilled")
          .map(r => r.value)
          .sort((a, b) => a.label.localeCompare(b.label));
        writeCachedRoots(roots);
        return roots;
      })
      .finally(() => {
        rootChildrenPromise = null;
      });
  }
  return rootChildrenPromise;
}

function isRegionalMusicTitle(title) {
  return /^music of\s+/i.test(String(title || "").trim());
}

async function loadGenreChildren(genreId, parentNode = null) {
  const rawEdges = await fetchJson(`/v1/genres/${encodeURIComponent(genreId)}/edges?direction=out`);
  const grouped = new Map();
  const parentIsPromotedRegion = Boolean(parentNode?.regionId) || isRegionalMusicTitle(parentNode?.title);

  for (const edge of rawEdges) {
    const childRelation = childRelationForEdge(edge);
    if (!childRelation) continue;
    if (!edge.to_genre_id) continue;
    if (parentIsPromotedRegion && isRegionalMusicTitle(edge.to_raw_label)) continue;
    const key = edge.to_genre_id;
    const existing = grouped.get(key);
    if (existing) {
      if (!existing.relations.includes(childRelation)) existing.relations.push(childRelation);
      continue;
    }
    grouped.set(key, {
      genreId: edge.to_genre_id,
      label: labelFromTitle(edge.to_raw_label),
      title: normalizeLabel(edge.to_raw_label),
      qid: null,
      color: edge.to_similarity_color,
      colorConfidence: edge.to_color_confidence,
      ...textMetricsFromEdge(edge),
      summary: null,
      wikipedia_url: null,
      aliases: [],
      origins: [],
      monthlyViews: edge.to_monthly_views_p30,
      relation: childRelation,
      relations: [childRelation],
      isUnresolved: !edge.to_genre_id,
    });
  }

  const children = [...grouped.values()].sort((a, b) => {
    const av = a.monthlyViews ?? -1;
    const bv = b.monthlyViews ?? -1;
    if (av !== bv) return bv - av;
    const ar = RELATION_RANK.get(a.relation) ?? 99;
    const br = RELATION_RANK.get(b.relation) ?? 99;
    return ar - br || a.label.localeCompare(b.label);
  });

  if (!parentNode?.genreId) return children;
  try {
    const context = await getMapContext(parentNode);
    return filterMapAccessibleRegionalChildren(children, context);
  } catch (err) {
    console.warn("[wiki-genres] regional child cull skipped", err);
    return children;
  }
}

function normalizedMapCullTitle(value) {
  return normalizeLabel(value).toLocaleLowerCase();
}

function mapAccessibleRegionalChildIndex(context) {
  const genreIds = new Set();
  const titles = new Set();
  for (const item of context?.selectable_regions || []) {
    if (!item) continue;
    for (const genreId of [
      item.genre_id,
      item.base_genre_id,
      item.matched_genre_id,
      ...(item.represented_genre_ids || []),
    ]) {
      if (genreId) genreIds.add(genreId);
    }
    for (const title of [
      item.wikipedia_title,
      item.display_title,
      item.region_name,
      item.matched_region_name,
      ...(item.represented_titles || []),
    ]) {
      const normalized = normalizedMapCullTitle(title);
      if (normalized) titles.add(normalized);
    }
  }
  return { genreIds, titles };
}

function isMapAccessibleRegionalChild(child, index) {
  if (!child?.genreId) return false;
  if (index.genreIds.has(child.genreId)) return true;
  if ([child.title, child.label].some(title => {
    const normalized = normalizedMapCullTitle(title);
    return normalized && index.titles.has(normalized);
  })) return true;
  return false;
}

function filterMapAccessibleRegionalChildren(children, context) {
  if (!Array.isArray(children) || !children.length) return children;
  const index = mapAccessibleRegionalChildIndex(context);
  if (!index.genreIds.size && !index.titles.size) return children;
  return children.filter(child => !isMapAccessibleRegionalChild(child, index));
}

async function getChildren(node) {
  const cacheKey = node.key === ROOT_KEY ? ROOT_KEY : (node.genreId || node.key);
  if (childrenCache.has(cacheKey)) return childrenCache.get(cacheKey);
  if (!node.genreId && Array.isArray(node.mapChildren) && node.mapChildren.length) {
    const children = node.mapChildren.map(child => ({
      genreId: child.genre_id,
      label: labelFromTitle(child.display_title || child.wikipedia_title),
      title: normalizeLabel(child.display_title || child.wikipedia_title),
      qid: null,
      color: child.similarity_color || null,
      colorConfidence: child.color_confidence ?? null,
      ...textMetricsFromPayload(child),
      summary: null,
      wikipedia_url: null,
      aliases: [],
      origins: [],
      monthlyViews: child.monthly_views_p30,
      relation: child.relation || "regional_variant",
      relations: [child.relation || "regional_variant"],
      isUnresolved: !child.genre_id,
      isMapChild: true,
      mapRole: "regional_variant",
      regionName: node.regionName || null,
      regionId: node.regionId || null,
      regionKind: node.regionKind || null,
      mapKey: node.mapKey || activeMapKey || "world",
    }));
    childrenCache.set(cacheKey, children);
    return children;
  }
  if (!node.genreId && node.key !== ROOT_KEY) {
    childrenCache.set(cacheKey, []);
    return [];
  }
  const children = node.key === ROOT_KEY
    ? await loadRootChildren()
    : await loadGenreChildren(node.genreId, node);
  childrenCache.set(cacheKey, children);
  return children;
}

async function getRegionalVariants(node) {
  const key = node.key === ROOT_KEY ? ROOT_KEY : node.genreId;
  if (!key) return { items: [] };
  if (regionalCache.has(key)) return regionalCache.get(key);
  const data = await fetchJson(`/v1/genres/${encodeURIComponent(key)}/regional-variants`);
  regionalCache.set(key, data);
  return data;
}

async function getMapContext(node) {
  const key = node?.key === ROOT_KEY ? ROOT_KEY : node?.genreId;
  if (!key) return {
    active_map: "world",
    map_label: "",
    selectable_regions: [],
    context_highlights: [],
    parent_regions: [],
  };
  if (mapContextCache.has(key)) return mapContextCache.get(key);
  const data = await fetchJson(`/v1/genres/${encodeURIComponent(key)}/map-context`);
  mapContextCache.set(key, data);
  return data;
}

async function getReachableParents(genreId) {
  if (!genreId) return [];
  if (reachableParentsCache.has(genreId)) return reachableParentsCache.get(genreId);
  const rows = await fetchJson(`/v1/genres/${encodeURIComponent(genreId)}/reachable-parents`);
  reachableParentsCache.set(genreId, rows);
  return rows;
}

async function searchTraversableGenres(query) {
  return fetchJson(`/v1/search/traversable?q=${encodeURIComponent(query)}&limit=10`);
}

async function randomTraversableGenre() {
  return fetchJson("/v1/search/traversable/random");
}

function timelineDetailForScale(scale = viewScale) {
  const lowZoomDetail = Math.max(0, Math.min(0.45, ((scale - MIN_VIEW_SCALE) / 0.60) * 0.45));
  if (scale <= 0.72) return lowZoomDetail;
  return Math.max(0, Math.min(1, 0.45 + ((scale - 0.72) / 2.28) * 0.55));
}

function timelineVisibleRankCutoff(detail = timelineDetailAmount()) {
  return 0.018 + detail * 0.36;
}

function timelineCoreRankCutoff() {
  return timelineVisibleRankCutoff(timelineDetailForScale(MIN_VIEW_SCALE));
}

function timelineServerRankForScale(scale = viewScale) {
  return Math.max(
    TIMELINE_MIN_SERVER_RANK,
    Math.min(1, timelineVisibleRankCutoff(timelineDetailForScale(scale)) + TIMELINE_RANK_PREFETCH)
  );
}

function timelinePrefetchScale(scale = viewScale) {
  return Math.min(
    MAX_VIEW_SCALE,
    Math.max(scale + TIMELINE_ZOOM_PREFETCH_MIN_SCALE, scale * TIMELINE_ZOOM_PREFETCH_FACTOR)
  );
}

function timelineDesiredServerRankForScale(scale = viewScale) {
  return Math.max(
    timelineServerRankForScale(scale),
    timelineServerRankForScale(timelinePrefetchScale(scale))
  );
}

async function getTimelineData(genreId, confidence = "low", maxRank = timelineDesiredServerRankForScale()) {
  const params = new URLSearchParams({
    scope: "all",
    max_nodes: "2400",
    max_rank: maxRank.toFixed(3),
    min_confidence: confidence,
    include_routes: "false",
  });
  if (genreId) params.set("selected_genre_id", genreId);
  return fetchJson(`/v1/timeline?${params.toString()}`);
}

function timelineStreamUrl(genreId, confidence = "low", maxRank = timelineDesiredServerRankForScale()) {
  const streamScale = timelineData ? Math.max(0.001, viewScale) : MIN_VIEW_SCALE;
  const params = new URLSearchParams({
    scope: "all",
    max_nodes: "2400",
    max_rank: maxRank.toFixed(3),
    min_confidence: confidence,
    include_routes: "false",
    chunk_size: "140",
    scale: streamScale.toFixed(4),
    view_tx: viewTx.toFixed(2),
    view_ty: viewTy.toFixed(2),
    width: String(Math.round(vw())),
    height: String(Math.round(vh())),
  });
  if (timelineData) {
    const bounds = timelineViewportBounds(260);
    params.set("x_min", bounds.left.toFixed(2));
    params.set("x_max", bounds.right.toFixed(2));
    params.set("y_min", bounds.top.toFixed(2));
    params.set("y_max", bounds.bottom.toFixed(2));
  }
  if (genreId) params.set("selected_genre_id", genreId);
  return `/v1/render/timeline/stream?${params.toString()}`;
}

function timelineDataSignature(rank = timelineDesiredServerRankForScale()) {
  const scale = Math.max(0.001, viewScale);
  const bounds = timelineData ? timelineViewportBounds(260) : null;
  return [
    Math.round(rank / TIMELINE_RENDER_RANK_EPSILON),
    Math.round(Math.log(scale) / Math.log(1.08)),
    bounds ? Math.floor(bounds.left / TIMELINE_VIEWPORT_TILE) : "initial",
    bounds ? Math.floor(bounds.top / TIMELINE_VIEWPORT_TILE) : "initial",
    timelineSelectedGenreId || "",
    timelineConfidence?.value || "low",
  ].join("|");
}

function cloudViewportParams() {
  const scale = Math.max(0.001, viewScale);
  const xMin = (0 - viewTx) / scale;
  const xMax = (vw() - viewTx) / scale;
  const yMin = (0 - viewTy) / scale;
  const yMax = (vh() - viewTy) / scale;
  const params = new URLSearchParams({
    limit: "5000",
    x_min: xMin.toFixed(2),
    x_max: xMax.toFixed(2),
    y_min: yMin.toFixed(2),
    y_max: yMax.toFixed(2),
    scale: scale.toFixed(4),
    view_tx: viewTx.toFixed(2),
    view_ty: viewTy.toFixed(2),
  });
  if (cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY) params.set("selected_genre_id", cloudSelectedGenreId);
  if (cloudRootGenreId) params.set("root_genre_id", cloudRootGenreId);
  if (cloudRegionId) params.set("region_id", cloudRegionId);
  return params;
}

function cloudAtlasParams() {
  const params = new URLSearchParams({
    limit: "5000",
    atlas: "true",
  });
  if (cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY) params.set("selected_genre_id", cloudSelectedGenreId);
  if (cloudRootGenreId) params.set("root_genre_id", cloudRootGenreId);
  if (cloudRegionId) params.set("region_id", cloudRegionId);
  return params;
}

async function getCloudData(options = {}) {
  const params = options.atlas ? cloudAtlasParams() : cloudViewportParams();
  return fetchJson(`/v1/genres/cloud?${params.toString()}`, { signal: options.signal });
}

function cloudStreamUrl() {
  const params = cloudAtlasParams();
  params.set("chunk_size", "500");
  return `/v1/render/cloud/stream?${params.toString()}`;
}

function cloudViewportSignature() {
  const scale = Math.max(0.001, viewScale);
  const tile = 180 / scale;
  const xMin = (0 - viewTx) / scale;
  const yMin = (0 - viewTy) / scale;
  return [
    Math.round(Math.log(scale) / Math.log(1.06)),
    Math.floor(xMin / tile),
    Math.floor(yMin / tile),
    cloudRootGenreId || "",
    cloudRegionId || "",
    cloudSelectedGenreId || "",
  ].join("|");
}

function activePathGenreIds() {
  const ids = [];
  let node = nodes.get(currentKey);
  while (node) {
    if (node.genreId) ids.unshift(node.genreId);
    node = node.parentKey ? nodes.get(node.parentKey) : null;
  }
  return ids;
}

function samePath(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  return a.every((value, index) => value === b[index]);
}

function mapCountryName(regionName) {
  return MAP_COUNTRY_ALIASES.get(regionName) || regionName;
}

function normalizeGeoText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
    .replace(/&/g, " and ")
    .replace(/['’]/g, "")
    .replace(/[^a-z0-9.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function geoTermMatches(text, term) {
  const normalizedTerm = normalizeGeoText(term);
  if (!normalizedTerm) return false;
  return text === normalizedTerm || text.includes(` ${normalizedTerm} `) ||
    text.startsWith(`${normalizedTerm} `) || text.endsWith(` ${normalizedTerm}`);
}

function resolveMapCountry(countryName) {
  const aliased = mapCountryName(countryName);
  if (countryElsByName.has(aliased)) return aliased;
  if (countryElsByName.has(countryName)) return countryName;
  return null;
}

function geoTextForNode(node) {
  const metadata = metadataItems(node).map(item => item.value);
  return normalizeGeoText([
    node?.label,
    node?.title,
    ...(node?.aliases || []),
    ...(node?.origins || []),
    ...(node?.instruments || []),
    ...(node?.categories || []).map(cleanCategory),
    ...metadata,
  ].filter(Boolean).join(" "));
}

function addCountriesFromGeoText(countries, text) {
  if (!text) return;
  const initialSize = countries.size;
  const addCountry = countryName => {
    const resolved = resolveMapCountry(countryName);
    if (resolved) countries.add(resolved);
  };

  for (const countryName of countryElsByName.keys()) {
    if (geoTermMatches(text, countryName)) addCountry(countryName);
  }
  if (countries.size > initialSize) return;

  const rules = [...GEO_TERM_RULES, ...GEO_CITY_RULES];
  for (const rule of rules) {
    if (!rule.terms.some(term => geoTermMatches(text, term))) continue;
    for (const countryName of rule.countries) addCountry(countryName);
  }
}

function inferCountriesFromGeoValues(values) {
  const countries = new Set();
  addCountriesFromGeoText(countries, normalizeGeoText(values.filter(Boolean).join(" ")));
  return countries;
}

function directDisplayableParentTitlesForNode(node) {
  if (!node?.genreId) return [];
  const rows = reachableParentsCache.get(node.genreId) || node.parentRelationshipRows || [];
  const titles = [];
  const seen = new Set();
  for (const row of rows) {
    if (!row?.parent_title || row.parent_genre_id === ROOT_KEY) continue;
    if (seen.has(row.parent_title)) continue;
    seen.add(row.parent_title);
    titles.push(row.parent_title);
  }
  return titles;
}

function inferRegionCountriesForNode(node) {
  const regionName = node?.regionName || node?.region_name || node?.label || node?.title;
  const exactRegion = resolveMapCountry(regionName);
  if (exactRegion) return new Set([exactRegion]);
  return inferCountriesFromGeoValues([regionName]);
}

function inferCountriesForNode(node) {
  if (!node) return new Set();
  if (node.regionName || node.regionKind || node.regionId) return inferRegionCountriesForNode(node);

  const countries = new Set();
  addCountriesFromGeoText(countries, geoTextForNode(node));
  for (const parentTitle of directDisplayableParentTitlesForNode(node)) {
    addCountriesFromGeoText(countries, normalizeGeoText(parentTitle));
  }

  return countries;
}

async function loadMapFeatures(mapKey = "world") {
  const definition = MAP_DEFINITIONS[mapKey] || MAP_DEFINITIONS.world;
  if (!mapFeaturePromises.has(mapKey)) {
    const promise = loadMapTopology(mapKey)
      .then(topology => feature(topology, topology.objects[definition.objectName]).features)
      .catch(err => {
        mapFeaturePromises.delete(mapKey);
        throw err;
      });
    mapFeaturePromises.set(mapKey, promise);
  }
  return mapFeaturePromises.get(mapKey);
}

void loadRootChildren().catch(() => {});
void loadMapFeatures("world").catch(() => {});

async function loadMapTopology(mapKey = "world") {
  const definition = MAP_DEFINITIONS[mapKey] || MAP_DEFINITIONS.world;
  if (!mapTopologyPromises.has(mapKey)) {
    mapTopologyPromises.set(mapKey, fetch(definition.url)
      .then(res => {
        if (!res.ok) throw new Error(`${mapKey} map request failed: ${res.status}`);
        return res.json();
      }));
  }
  return mapTopologyPromises.get(mapKey);
}

async function ensureCountryMap(mapKey = "world") {
  if (!mapCountryLayer) return;
  const definition = MAP_DEFINITIONS[mapKey] || MAP_DEFINITIONS.world;
  if (countryElsByName.size && activeMapKey === mapKey) return;
  const switching = activeMapKey !== null && activeMapKey !== mapKey;
  if (switching) {
    mapCard?.classList.add("map-switching");
    await sleep(120);
  }
  activeMapKey = mapKey;
  mapViewBox = { ...definition.viewBox };
  const topology = await loadMapTopology(mapKey);
  const topologyObject = topology.objects[definition.objectName];
  const features = feature(topology, topologyObject).features;
  const collection = { type: "FeatureCollection", features };
  const projection = definition.projection === "albersUsa"
    ? geoAlbersUsa().fitExtent([[6, 6], [314, 168]], collection)
    : geoNaturalEarth1().fitExtent([[4, 4], [316, 170]], collection);
  const path = geoPath(projection);
  activeMapTopology = topology;
  activeMapTopologyObject = topologyObject;
  activeMapPath = path;

  mapCountryLayer.innerHTML = "";
  if (mapClipDefs) mapClipDefs.innerHTML = "";
  if (mapHighlightLayer) mapHighlightLayer.innerHTML = "";
  if (mapHitLayer) mapHitLayer.innerHTML = "";
  countryElsByName.clear();
  countryHighlightElsByName.clear();
  countryHitElsByName.clear();
  countryAreaByName.clear();
  countryBoundsByName.clear();
  countryBoundarySamplesByName.clear();
  mapCountryRenderStateByName.clear();
  mapSuperregionRenderStateByKey.clear();

  for (const [index, country] of features.entries()) {
    const name = country.properties?.name;
    const d = path(country);
    if (!name || !d) continue;
    const [[x1, y1], [x2, y2]] = path.bounds(country);
    const area = Math.max(1, (x2 - x1) * (y2 - y1));
    countryAreaByName.set(name, Math.min(countryAreaByName.get(name) || Infinity, area));
    countryBoundsByName.set(name, { minX: x1, minY: y1, maxX: x2, maxY: y2 });

    const countryPath = svgEl("path", {
      class: "map-country",
      d,
      tabindex: "-1",
      "aria-hidden": "true",
    });
    countryPath.__countryName = name;

    const clipId = `map-country-clip-${index}`;
    const clipPath = svgEl("clipPath", { id: clipId });
    clipPath.appendChild(svgEl("path", { d }));
    mapClipDefs?.appendChild(clipPath);

    const highlightPath = svgEl("path", {
      class: "map-country-highlight-border",
      d,
      "aria-hidden": "true",
    });
    highlightPath.__countryName = name;

    const hitPath = svgEl("path", {
      class: "map-country-hit",
      d,
      tabindex: "-1",
      "aria-hidden": "true",
    });
    hitPath.__countryName = name;
    hitPath.addEventListener("focus", () => setMapHoveredCountry(name));
    hitPath.addEventListener("blur", () => clearMapHoveredCountry(name));
    hitPath.addEventListener("keydown", event => {
      if (!isMapExpanded()) return;
      if (event.key !== "Enter" && event.key !== " ") return;
      const item = mapItemsByCountryName.get(name);
      if (!item) return;
      event.preventDefault();
      selectMapVariant(item);
    });

    mapCountryLayer.appendChild(countryPath);
    mapHighlightLayer?.appendChild(highlightPath);
    mapHitLayer?.appendChild(hitPath);
    if (!countryElsByName.has(name)) countryElsByName.set(name, []);
    if (!countryHighlightElsByName.has(name)) countryHighlightElsByName.set(name, []);
    if (!countryHitElsByName.has(name)) countryHitElsByName.set(name, []);
    countryElsByName.get(name).push(countryPath);
    countryHighlightElsByName.get(name).push(highlightPath);
    countryHitElsByName.get(name).push(hitPath);
    updateCountryBoundarySamples(name, countryPath);
  }
  applyMapViewBox();
  if (switching) {
    requestAnimationFrame(() => mapCard?.classList.remove("map-switching"));
  }
}

function mapVariationCountLabel(count = 0) {
  const value = Number(count) || 0;
  if (value <= 0) return "";
  return `${value} ${value === 1 ? "Variation" : "Variations"}`;
}

function setMapParentLabel(text = "", targetKey = null, options = {}) {
  const label = String(text || "").trim();
  mapParentTargetKey = label && targetKey ? targetKey : null;
  mapParentTargetCloud = label && options.cloud ? { ...options.cloud } : null;
  if (mapParentLabelText) mapParentLabelText.textContent = label;
  if (mapParentLabel) {
    mapParentLabel.hidden = !label;
    mapParentLabel.disabled = !(mapParentTargetKey || mapParentTargetCloud);
    mapParentLabel.setAttribute(
      "aria-label",
      label ? `Return to ${label}` : "Return to parent genre"
    );
  }
  mapCard?.classList.toggle("map-has-parent-label", Boolean(label));
}

function setMapLabel(text = "", variationCount = 0, metaText = "") {
  const label = String(text || "").trim();
  const metaLabel = String(metaText || "").trim() || mapVariationCountLabel(variationCount);
  mapTitle.replaceChildren();
  if (label) {
    const title = document.createElement("span");
    title.className = "map-title-main";
    title.textContent = label;
    mapTitle.append(title);
  }
  if (label && metaLabel) {
    const meta = document.createElement("span");
    meta.className = "map-title-meta";
    meta.textContent = metaLabel;
    mapTitle.append(meta);
  }
  mapTitle.classList.toggle("has-map-label", Boolean(label));
  fitMapLabelMeta();
}

function fitMapLabelMeta() {
  if (!mapTitle || mapTitle.hidden) return;
  const meta = mapTitle.querySelector(".map-title-meta");
  if (!meta) return;
  meta.hidden = false;
  requestAnimationFrame(() => {
    if (!meta.isConnected || !mapTitle || mapTitle.hidden) return;
    const overflows = mapTitle.scrollWidth > mapTitle.clientWidth + 1;
    meta.hidden = overflows;
  });
}

function setMapDefaultLabel(text = "", variationCount = 0) {
  mapDefaultLabel = text;
  mapDefaultVariationCount = Number(variationCount) || 0;
  if (!hoveredMapCountry) setMapLabel(mapDefaultLabel, mapDefaultVariationCount);
}

function mapListTopInset() {
  return mapCard?.classList.contains("map-has-parent-label") && !mapListSearchOpen
    ? MAP_LIST_PARENT_TOP_INSET
    : MAP_LIST_TOP_INSET;
}

function updateMapListBodyClasses() {
  document.body.classList.toggle("map-list-mode-active", mapListMode);
  document.body.classList.toggle("map-list-detail-hidden", mapListMode && mapListDetailHidden);
}

function mapListMaxCardHeight() {
  if (!mapCard) return MAP_LIST_MIN_CARD_HEIGHT;
  const cardRect = mapCard.getBoundingClientRect();
  if (window.matchMedia("(max-width: 899px)").matches) {
    const topInset = Math.max(12, cardRect.top || 12);
    return Math.max(MAP_LIST_MIN_CARD_HEIGHT, window.innerHeight - topInset - 12);
  }
  const bottomInset = Math.max(12, window.innerHeight - (cardRect.bottom || window.innerHeight - 20));
  let topLimit = 20;
  if (mapListMode && mapListDetailHidden && detailRestoreButton) {
    const restoreRect = detailRestoreButton.getBoundingClientRect();
    if (restoreRect.height > 0) {
      topLimit = Math.max(topLimit, restoreRect.bottom + MAP_LIST_DETAIL_GAP_PX);
    }
  }
  return Math.max(MAP_LIST_MIN_CARD_HEIGHT, window.innerHeight - bottomInset - topLimit);
}

function updateMapListCardHeight(contentHeight = 0) {
  if (!mapCard || !mapListMode) return;
  const needed = mapListTopInset() + Math.max(0, contentHeight) + MAP_LIST_BOTTOM_INSET;
  const height = Math.max(MAP_LIST_MIN_CARD_HEIGHT, Math.min(needed, mapListMaxCardHeight()));
  mapCard.style.setProperty("--map-list-card-height", `${Math.round(height)}px`);
}

function setMapListMode(enabled) {
  const nextMode = Boolean(enabled);
  if (nextMode && !mapListMode) {
    mapListDetailHidden = document.body.classList.contains("detail-card-visible");
  } else if (!nextMode) {
    mapListDetailHidden = false;
    mapListSearchQuery = "";
    mapListSearchOpen = false;
    if (mapListSearchInput) mapListSearchInput.value = "";
  }
  mapListMode = nextMode;
  mapCard?.classList.toggle("map-list-mode", mapListMode);
  mapListButton?.setAttribute("aria-pressed", String(mapListMode));
  mapListButton?.setAttribute("aria-label", mapListMode ? "Show map" : "Show variations list");
  if (mapListButton) mapListButton.dataset.tooltip = mapListMode ? "Show map" : "Show variations list";
  if (!mapListMode) {
    mapListViewState = null;
    if (mapListScrollFrame) {
      cancelAnimationFrame(mapListScrollFrame);
      mapListScrollFrame = 0;
    }
  }
  if (mapList) {
    mapList.hidden = !mapListMode;
    if (!mapListMode) mapList.innerHTML = "";
  }
  updateMapListSearchVisibility(false);
  if (regionMap) regionMap.hidden = mapListMode;
  if (!mapListMode) mapCard?.style.removeProperty("--map-list-card-height");
  updateMapListBodyClasses();
  updateMapResetButton();
  syncMapCountryInteractivity();
  updateDetailCardVisibility();
  if (mapListMode) updateMapListCardHeight(mapListViewState?.totalHeight || 0);
}

function selectableMapItems(items) {
  return (items || []).filter(item => item?.selectable !== false);
}

function mapContextHasSelectableVariants(items) {
  return selectableMapItems(items).length > 0;
}

function setMapListButtonVisible(visible) {
  if (!mapListButton) return;
  mapListButton.hidden = !visible;
  if (!visible && mapListMode) setMapListMode(false);
}

function setMapWorldButtonVisible(visible) {
  if (!mapWorldButton) return;
  mapWorldButton.hidden = !visible;
}

function normalizedRegionTitleText(value) {
  return normalizedCountryLookup(value)
    .replace(/\b(music|region|regions|state|states|province|provinces|city|cities|the)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const regionTitleAdjectiveAliases = new Map(Object.entries({
  "africa": ["african"],
  "argentina": ["argentine", "argentinian"],
  "armenia": ["armenian"],
  "australia": ["australian"],
  "azerbaijan": ["azerbaijani"],
  "belgium": ["belgian"],
  "brazil": ["brazilian"],
  "bulgaria": ["bulgarian"],
  "canada": ["canadian"],
  "denmark": ["danish"],
  "ethiopia": ["ethiopian", "ethio"],
  "finland": ["finnish"],
  "france": ["french"],
  "germany": ["german"],
  "india": ["indian"],
  "iran": ["iranian"],
  "italy": ["italian"],
  "japan": ["japanese"],
  "mexico": ["mexican"],
  "netherlands": ["dutch"],
  "poland": ["polish"],
  "russia": ["russian"],
  "south africa": ["south african"],
  "spain": ["spanish"],
  "sweden": ["swedish"],
  "united kingdom": ["british", "uk"],
  "united states": ["american", "us", "u s"],
  "united states of america": ["american", "us", "u s"],
  "zimbabwe": ["zimbabwean"],
}));

function titleMostlyIncludesRegion(title, regionName) {
  const titleText = normalizedRegionTitleText(title);
  const regionText = normalizedRegionTitleText(regionName);
  if (!titleText || !regionText) return false;
  if (titleText.includes(regionText)) return true;
  for (const alias of regionTitleAdjectiveAliases.get(regionText) || []) {
    if (titleText.includes(normalizedRegionTitleText(alias))) return true;
  }
  const regionTokens = regionText.split(" ").filter(token => token.length > 2);
  if (!regionTokens.length) return false;
  const titleTokens = new Set(titleText.split(" ").filter(Boolean));
  const matched = regionTokens.filter(token => titleTokens.has(token)).length;
  return matched / regionTokens.length >= 0.5;
}

function mapHoverVariantTitle(item, fallbackName) {
  return item?.selectable_for || item?.display_title || item?.wikipedia_title || item?.region_name || fallbackName;
}

function mapHoverRegionSuffix(item, fallbackName) {
  if (!item) return "";
  const grouped = mapHoverCountryGroup(fallbackName).size > 1;
  return (
    grouped
      ? item.matched_region_name || item.mount_parent_region_name || item.region_name
      : item.region_name || item.matched_region_name || item.mount_parent_region_name
  ) || "";
}

function mapHoverLabelParts(name) {
  const item = mapItemsByCountryName.get(name);
  if (!item) return { label: name, meta: "" };
  const label = mapHoverVariantTitle(item, name);
  const region = mapHoverRegionSuffix(item, name);
  return {
    label,
    meta: region && !titleMostlyIncludesRegion(label, region) ? region : "",
  };
}

function mapHoverLabel(name) {
  const { label, meta } = mapHoverLabelParts(name);
  return [label, meta].filter(Boolean).join(" ");
}

function setMapHoverLabel(name) {
  const { label, meta } = mapHoverLabelParts(name);
  if (label) {
    setMapLabel(label, 0, meta);
    return;
  }
  setMapLabel(name);
}

function updateMapListSearchVisibility(rootMode = false, searchable = false) {
  if (!mapListSearchInput) return;
  const available = Boolean(mapListMode && searchable);
  const visible = Boolean(available && mapListSearchOpen);
  mapListSearchInput.hidden = !visible;
  if (mapListSearchButton) {
    mapListSearchButton.hidden = !available;
    mapListSearchButton.setAttribute("aria-pressed", String(visible));
  }
  mapCard?.classList.toggle("map-list-search-mode", visible);
  mapCard?.classList.toggle("map-list-search-available", available);
  mapTitle?.toggleAttribute("hidden", visible);
  mapParentLabel?.toggleAttribute("hidden", visible || !mapParentLabelText?.textContent?.trim());
  if (mapListMode) updateMapListCardHeight(mapListViewState?.totalHeight || 0);
}

function mapVariationLabel(node, items, context = null) {
  if (!node || node.key === ROOT_KEY || node.label === "Music") return context?.map_label || "";
  if (node.label) return node.label;
  if (context?.wikipedia_title) return labelFromTitle(context.wikipedia_title);
  if (context?.map_label) return context.map_label;
  if (!items.length) return "";
  if (node.genreId && items.some(item => item.genre_id === node.genreId)) return "";
  return node.label || "";
}

function mapVariationSelectionKey(item) {
  if (!item) return "";
  if (item.genre_id) return `genre:${item.genre_id}`;
  if (item.candidate_id) return `candidate:${item.candidate_id}`;
  if (item.base_genre_id && item.display_title) return `base:${item.base_genre_id}:${item.display_title}`;
  return `feature:${item.map_key || ""}:${item.feature_key || item.region_key || item.region_id || mapListTitle(item)}`;
}

function mapVariationCount(items) {
  const keys = new Set();
  for (const item of selectableMapItems(items)) {
    const key = mapVariationSelectionKey(item);
    if (key) keys.add(key);
  }
  return keys.size;
}

function mapParentInfoForNode(node) {
  if (!node?.isMapChild || !node.parentKey) return { label: "", targetKey: null };
  const parent = nodes.get(node.parentKey);
  if (!parent) return { label: "", targetKey: null };
  if (parent.key === ROOT_KEY) return { label: "Global", targetKey: parent.key };
  return {
    label: parent.label || labelFromTitle(parent.title) || "",
    targetKey: parent.key,
  };
}

function mapParentLabelForNode(node) {
  return mapParentInfoForNode(node).label;
}

function cloudMapParentInfoForContext(context, selectedNode) {
  if (!cloudMode || !cloudRegionId) return null;
  return {
    label: "Global",
    cloud: { root: true },
  };
}

function clearScheduledCloudHoverCard(nodeKey = null) {
  if (nodeKey && pendingCloudHoverCardKey && pendingCloudHoverCardKey !== nodeKey) return;
  const canceledKey = pendingCloudHoverCardKey || nodeKey;
  window.clearTimeout(cloudHoverCardDelayTimer);
  cloudHoverCardDelayTimer = 0;
  pendingCloudHoverCardKey = null;
  if (
    detailIndicatorPreviewKey &&
    (!nodeKey || detailIndicatorPreviewKey === nodeKey || detailIndicatorPreviewKey === canceledKey)
  ) {
    setDetailIndicatorPreviewKey(null);
  }
}

function scheduleCloudHoverCard(nodeId) {
  const key = detailKeyForCloudNodeId(nodeId);
  clearScheduledCloudHoverCard();
  if (!key || detailCardSuppressed) return;
  setDetailIndicatorPreviewKey(key);
  pendingCloudHoverCardKey = key;
  cloudHoverCardDelayTimer = window.setTimeout(() => {
    cloudHoverCardDelayTimer = 0;
    const wantedKey = pendingCloudHoverCardKey;
    pendingCloudHoverCardKey = null;
    if (wantedKey !== key) return;
    if (detailCardSuppressed || !cloudMode) return;
    void showCloudHoverCard(nodeId);
  }, prefersReducedMotion() ? 0 : CLOUD_HOVER_DETAIL_SWAP_DELAY_MS);
}

async function showCloudHoverCard(nodeId) {
  if (detailCardSuppressed || !cloudMode || !nodeId) return;
  const token = ++hoverCardToken;
  const node = cloudNodeById.get(nodeId) || cloudScene?.nodesById?.get(nodeId);
  if (!node) return;
  const key = detailKeyForCloudNodeId(nodeId);
  setDetailCardNodeKey(key);
  setDetailIndicatorPreviewKey(key);
  try {
    const detail = await getGenreDetail(nodeId);
    if (token !== hoverCardToken || detailCardNodeKey !== key || !cloudMode) return;
    setDetailCardNodeKey(key);
    setDetailIndicatorPreviewKey(key);
    updateCard(detail, { hoverSwap: true });
  } catch (err) {
    console.error("[wiki-genres] cloud hover detail failed", err);
    if (token === hoverCardToken && detailCardNodeKey === key && cloudMode) {
      updateCard(cloudNodeFromPayload(node), { hoverSwap: true });
    }
  }
}

async function returnToMapParent() {
  if (mapParentTargetCloud) {
    const target = mapParentTargetCloud;
    allowDetailCardForManualSelection();
    if (target.root) {
      cloudRootGenreId = null;
      cloudRegionId = null;
      cloudSelectedGenreId = null;
      setDetailCardNodeKey(null);
      updateDetailCardVisibility();
      updateUrlState({ push: true });
      void loadCloudMode({ initial: true }).then(() => {
        if (cloudMode) void updateMapCard(nodes.get(ROOT_KEY));
      }).catch(err => {
        console.error("[wiki-genres] cloud map parent failed", err);
        setStatus("Cloud unavailable.");
      });
    }
    return;
  }
  const targetKey = mapParentTargetKey;
  const target = targetKey ? nodes.get(targetKey) : null;
  if (!target) return;
  allowDetailCardForManualSelection();
  if (target.key === ROOT_KEY) {
    activeLeafKey = null;
    for (const item of nodes.values()) item.isActiveLeaf = false;
    void renderRootState();
    updateUrlState({ push: true });
    return;
  }
  await focusOn(target.key);
}

function isRootMusicMapContext(context, selectedNode) {
  return Boolean(
    selectedNode?.key === ROOT_KEY
    || context?.wikipedia_title === "Music" && context?.genre_id == null
  );
}

function worldContextFromSubmap(context, selectedNode) {
  const regionItems = [
    ...(context?.selected_region ? [context.selected_region] : []),
    ...(context?.parent_regions || []),
    ...(context?.context_highlights || []),
    ...(context?.selectable_regions || []),
  ];
  const worldItems = regionItems
    .filter(item => item?.region_id)
    .map(item => ({
      ...item,
      map_key: "world",
      feature_key: mapCountryName(item.region_name),
      feature_name: mapCountryName(item.region_name),
      selectable: false,
      role: "context",
      match_type: item.match_type || "region_context",
    }));
  const seen = new Set();
  const contextHighlights = [];
  for (const item of worldItems) {
    const key = item.feature_key || item.region_id;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    contextHighlights.push(item);
  }
  return {
    ...(context || {}),
    active_map: "world",
    map_label: selectedNode?.label || context?.map_label || "World",
    selectable_regions: [],
    parent_regions: [],
    context_highlights: contextHighlights,
    is_world_override: true,
  };
}

function mapCountryArea(name) {
  return countryAreaByName.get(name) || Number.POSITIVE_INFINITY;
}

function compareMapCountryPriority(a, b) {
  return mapCountryArea(a) - mapCountryArea(b) || a.localeCompare(b);
}

function updateCountryBoundarySamples(countryName, pathEl) {
  if (!countryName || !pathEl || typeof pathEl.getTotalLength !== "function") return;
  let length = 0;
  try {
    length = pathEl.getTotalLength();
  } catch {
    return;
  }
  if (!Number.isFinite(length) || length <= 0) return;
  const sampleCount = clamp(Math.ceil(length / 2.5), 18, 140);
  const samples = countryBoundarySamplesByName.get(countryName) || [];
  for (let index = 0; index < sampleCount; index += 1) {
    try {
      const point = pathEl.getPointAtLength((length * index) / sampleCount);
      samples.push({ x: point.x, y: point.y });
    } catch {}
  }
  if (samples.length) countryBoundarySamplesByName.set(countryName, samples);
}

function mapPixelMetrics() {
  const rect = regionMap?.getBoundingClientRect?.();
  if (!rect) return { sx: 1, sy: 1 };
  return {
    sx: Math.max(0.001, rect.width / Math.max(1, mapViewBox.w)),
    sy: Math.max(0.001, rect.height / Math.max(1, mapViewBox.h)),
  };
}

function countryBufferRadiusPx(countryName, metrics = mapPixelMetrics()) {
  const area = Math.max(1, mapCountryArea(countryName) * metrics.sx * metrics.sy);
  const effectiveRadius = Math.sqrt(area / Math.PI);
  return clamp(
    MAP_BUFFER_BASE_PX +
      Math.max(0, MAP_BUFFER_SMALL_RADIUS_PX - effectiveRadius) *
        MAP_BUFFER_SMALL_RADIUS_GAIN,
    MAP_BUFFER_BASE_PX,
    MAP_BUFFER_MAX_PX
  );
}

function countryBoundsDistancePx(countryName, point, metrics) {
  const bounds = countryBoundsByName.get(countryName);
  if (!bounds) return Number.POSITIVE_INFINITY;
  const dx = point.x < bounds.minX
    ? bounds.minX - point.x
    : point.x > bounds.maxX
    ? point.x - bounds.maxX
    : 0;
  const dy = point.y < bounds.minY
    ? bounds.minY - point.y
    : point.y > bounds.maxY
    ? point.y - bounds.maxY
    : 0;
  return Math.hypot(dx * metrics.sx, dy * metrics.sy);
}

function countryBoundaryDistancePx(countryName, point, metrics) {
  const samples = countryBoundarySamplesByName.get(countryName) || [];
  if (!samples.length) return Number.POSITIVE_INFINITY;
  let best = Number.POSITIVE_INFINITY;
  for (const sample of samples) {
    const distance = Math.hypot(
      (sample.x - point.x) * metrics.sx,
      (sample.y - point.y) * metrics.sy
    );
    if (distance < best) best = distance;
  }
  return best;
}

function mapOceanBufferCandidate(countryName, point, metrics) {
  const radius = countryBufferRadiusPx(countryName, metrics);
  if (countryBoundsDistancePx(countryName, point, metrics) > radius) return null;
  const distance = countryBoundaryDistancePx(countryName, point, metrics);
  if (!Number.isFinite(distance) || distance > radius) return null;
  const area = Math.max(1, mapCountryArea(countryName) * metrics.sx * metrics.sy);
  const largeAreaPenalty = Math.log10(area + 10) * MAP_BUFFER_LARGE_AREA_PENALTY;
  const selectableBonus = mapItemsByCountryName.has(countryName) ? MAP_BUFFER_SELECTABLE_BONUS : 0;
  return {
    countryName,
    distance,
    radius,
    score: distance / radius + largeAreaPenalty - selectableBonus,
  };
}

function mapHoverSelectionKey(countryName) {
  const item = mapItemsByCountryName.get(countryName);
  if (!item) return "";
  return mapSelectableHoverGroupKey(item) || `country:${countryName}`;
}

function betterMapBufferCandidate(candidate, best) {
  if (!candidate) return best;
  if (!best) return candidate;
  if (candidate.score < best.score) return candidate;
  if (
    candidate.score === best.score &&
    compareMapCountryPriority(candidate.countryName, best.countryName) < 0
  ) {
    return candidate;
  }
  return best;
}

function bestMapBufferCandidate(point, metrics, countryNames) {
  let best = null;
  for (const name of countryNames) {
    if (!mapItemsByCountryName.has(name)) continue;
    best = betterMapBufferCandidate(
      mapOceanBufferCandidate(name, point, metrics),
      best
    );
  }
  return best;
}

function featureKeyForMapItem(item) {
  const feature = mapFeatureForItem(item);
  return feature ? resolveMapCountry(feature) || feature : null;
}

function mapSelectableHoverGroupKey(item) {
  if (!item) return "";
  const selectsMatchedSuperregion = Boolean(
    item.match_type === "pure_region_descendant_country" &&
    item.genre_id &&
    item.matched_genre_id &&
    item.genre_id === item.matched_genre_id &&
    item.matched_region_id &&
    item.matched_region_kind &&
    item.matched_region_kind !== "country" &&
    item.matched_region_kind !== "territory"
  );
  if (selectsMatchedSuperregion) {
    return [
      "superregion",
      item.matched_region_id,
      item.matched_genre_id,
    ].filter(Boolean).join(":");
  }
  return [
    "feature",
    item.map_key,
    item.feature_key || item.region_key || item.region_id || mapListTitle(item),
  ].filter(Boolean).join(":");
}

function rebuildMapHoverGroups(items) {
  mapHoverCountriesByCountryName.clear();
  mapSuperregionCountriesByGroupKey.clear();
  mapSuperregionGroupKeyByCountryName.clear();
  const groupedFeatures = new Map();
  for (const item of selectableMapItems(items)) {
    const feature = featureKeyForMapItem(item);
    if (!feature || !countryElsByName.has(feature)) continue;
    const groupKey = mapSelectableHoverGroupKey(item) || feature;
    if (!groupedFeatures.has(groupKey)) groupedFeatures.set(groupKey, new Set());
    groupedFeatures.get(groupKey).add(feature);
  }
  for (const features of groupedFeatures.values()) {
    const group = new Set(features);
    for (const feature of features) mapHoverCountriesByCountryName.set(feature, group);
  }
  for (const [groupKey, features] of groupedFeatures.entries()) {
    if (!groupKey.startsWith("superregion:") || features.size <= 1) continue;
    const group = new Set(features);
    mapSuperregionCountriesByGroupKey.set(groupKey, group);
    for (const feature of group) mapSuperregionGroupKeyByCountryName.set(feature, groupKey);
  }
}

function mapHoverCountryGroup(name) {
  return mapHoverCountriesByCountryName.get(name) || new Set([name]);
}

function topoFeatureName(featureItem) {
  return featureItem?.properties?.name || "";
}

function superregionGroupKeyForItem(item) {
  const featureName = featureKeyForMapItem(item);
  if (!featureName) return "";
  const groupKey = mapSelectableHoverGroupKey(item);
  const countries = groupKey ? mapSuperregionCountriesByGroupKey.get(groupKey) : null;
  return countries?.has(featureName) && countries.size > 1 ? groupKey : "";
}

function superregionBoundaryPath(countries) {
  if (!activeMapTopology || !activeMapTopologyObject || !activeMapPath || !countries?.size) {
    return "";
  }
  const boundary = topoMesh(activeMapTopology, activeMapTopologyObject, (a, b) => {
    const aIn = countries.has(topoFeatureName(a));
    const bIn = countries.has(topoFeatureName(b));
    return (aIn && a === b) || aIn !== bIn;
  });
  return activeMapPath(boundary) || "";
}

function updateSuperregionBorder(groupKey, color, { dim = true, hover = false, selected = true } = {}) {
  const countries = mapSuperregionCountriesByGroupKey.get(groupKey);
  if (!groupKey || !countries || countries.size <= 1 || !mapHighlightLayer) return;
  let borderPath = mapSuperregionBorderElsByGroupKey.get(groupKey);
  if (!borderPath) {
    borderPath = svgEl("path", {
      class: "map-superregion-border",
      "aria-hidden": "true",
    });
    mapSuperregionBorderElsByGroupKey.set(groupKey, borderPath);
    mapHighlightLayer.appendChild(borderPath);
  }
  const d = superregionBoundaryPath(countries);
  if (!d) {
    borderPath.remove();
    mapSuperregionBorderElsByGroupKey.delete(groupKey);
    return;
  }
  const pair = mapColorPair(color, { dim, hover });
  borderPath.setAttribute("d", d);
  borderPath.style.stroke = pair.stroke;
  borderPath.style.strokeWidth = hover ? "1.35" : (selected ? "1.2" : "1");
}

function mapItemFeatureKeys(items) {
  const keys = [];
  const seen = new Set();
  for (const item of items || []) {
    const feature = featureKeyForMapItem(item);
    if (!feature || !countryElsByName.has(feature) || seen.has(feature)) continue;
    seen.add(feature);
    keys.push(feature);
  }
  return keys;
}

function mapPointerSvgPoint(event) {
  if (!regionMap || typeof regionMap.createSVGPoint !== "function") return null;
  const matrix = regionMap.getScreenCTM?.();
  if (!matrix) return null;
  const point = regionMap.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  return point.matrixTransform(matrix.inverse());
}

function mapPathContainsPoint(path, point, method) {
  if (!path || !point || typeof path[method] !== "function") return false;
  try {
    return path[method](point);
  } catch {
    return false;
  }
}

function mapCountryContainsPoint(name, point) {
  return (countryElsByName.get(name) || []).some(path =>
    mapPathContainsPoint(path, point, "isPointInFill")
  );
}

function mapCountryBufferContainsPoint(name, point) {
  return Boolean(mapOceanBufferCandidate(name, point, mapPixelMetrics()));
}

function resolvedMapCountryAtPointer(event) {
  const point = mapPointerSvgPoint(event);
  if (!point) return null;

  const landMatches = [];
  for (const name of countryElsByName.keys()) {
    if (mapCountryContainsPoint(name, point)) landMatches.push(name);
  }
  if (landMatches.length) {
    const landTarget = landMatches
      .filter(name => mapItemsByCountryName.has(name))
      .sort(compareMapCountryPriority)[0] || null;
    if (landTarget) {
      if (
        hoveredMapCountry &&
        mapHoverSelectionKey(landTarget) === mapHoverSelectionKey(hoveredMapCountry)
      ) {
        return hoveredMapCountry;
      }
      return landTarget;
    }
  }

  const metrics = mapPixelMetrics();
  const best = bestMapBufferCandidate(point, metrics, mapItemsByCountryName.keys());
  if (!best) return null;

  if (hoveredMapCountry && mapItemsByCountryName.has(hoveredMapCountry)) {
    const hoveredKey = mapHoverSelectionKey(hoveredMapCountry);
    const bestKey = mapHoverSelectionKey(best.countryName);
    if (hoveredKey && hoveredKey === bestKey) return hoveredMapCountry;

    const hoveredGroup = mapHoverCountryGroup(hoveredMapCountry);
    const current = bestMapBufferCandidate(point, metrics, hoveredGroup);
    if (
      current &&
      best.score > current.score - MAP_HOVER_SWITCH_SCORE_MARGIN
    ) {
      return hoveredMapCountry;
    }
  }

  return best.countryName;
}

function updateResolvedMapHover(event) {
  if (mapListMode || !isMapExpanded()) {
    clearMapHoveredCountry();
    return;
  }
  const countryName = resolvedMapCountryAtPointer(event);
  if (countryName) {
    setMapHoveredCountry(countryName);
  } else {
    clearMapHoveredCountry();
  }
}

function selectResolvedMapCountry(event) {
  if (!isMapExpanded()) return;
  const countryName = resolvedMapCountryAtPointer(event);
  const item = countryName ? mapItemsByCountryName.get(countryName) : null;
  if (!item) return;
  event.preventDefault();
  event.stopPropagation();
  void selectMapVariant(item);
}

function setMapHoveredCountry(name) {
  if (hoveredMapCountry && hoveredMapCountry !== name) clearMapHoveredCountry(hoveredMapCountry);
  hoveredMapCountry = name;
  mapCard?.classList.add("map-hover-active");
  hoveredMapCountries = new Set(mapHoverCountryGroup(name));
  for (const countryName of hoveredMapCountries) {
    for (const countryPath of countryElsByName.get(countryName) || []) {
      countryPath.classList.add("map-country-hovered");
    }
    applyHoveredSelectableCountryStyle(countryName);
  }
  setMapHoverLabel(name);
}

function clearMapHoveredCountry(name = hoveredMapCountry) {
  if (!name || hoveredMapCountry !== name) return;
  for (const countryName of hoveredMapCountries) {
    for (const countryPath of countryElsByName.get(countryName) || []) {
      countryPath.classList.remove("map-country-hovered");
    }
    restoreSelectableCountryStyle(countryName);
  }
  hoveredMapCountries = new Set();
  hoveredMapCountry = null;
  mapCard?.classList.remove("map-hover-active");
  setMapLabel(mapDefaultLabel, mapDefaultVariationCount);
}

function setSvgClass(el, className, active) {
  if (!el) return;
  const hasClass = el.classList.contains(className);
  if (active && !hasClass) el.classList.add(className);
  if (!active && hasClass) el.classList.remove(className);
}

function setSvgStyle(el, prop, value) {
  if (!el) return;
  const cssName = prop.replace(/[A-Z]/g, match => `-${match.toLowerCase()}`);
  if (value == null || value === "") {
    if (el.style[prop]) el.style.removeProperty(cssName);
    return;
  }
  if (el.style[prop] !== String(value)) el.style[prop] = String(value);
}

function setSvgAttr(el, name, value) {
  if (!el) return;
  if (value == null || value === "") {
    if (el.hasAttribute(name)) el.removeAttribute(name);
    return;
  }
  const next = String(value);
  if (el.getAttribute(name) !== next) el.setAttribute(name, next);
}

function setMapPathTitle(pathEl, text) {
  const title = pathEl?.querySelector?.("title");
  if (!title) return;
  const next = String(text || pathEl.__countryName || title.textContent || "");
  if (title.textContent !== next) title.textContent = next;
}

function inactiveMapCountryRenderState(countryName) {
  return {
    active: false,
    context: false,
    selected: false,
    hovered: false,
    countryTitle: countryName,
    countryFill: "",
    countryStroke: "",
    countryStrokeWidth: "",
    highlightContext: false,
    highlightSelected: false,
    highlightStroke: "",
    highlightStrokeWidth: "",
    hitActive: false,
    hitTitle: countryName,
    hitTabindex: "-1",
    hitRole: "",
    hitAriaHidden: "true",
    hitAriaLabel: "",
  };
}

function mapCountryRenderSignature(state) {
  return [
    state.active ? 1 : 0,
    state.context ? 1 : 0,
    state.selected ? 1 : 0,
    state.hovered ? 1 : 0,
    state.countryTitle || "",
    state.countryFill || "",
    state.countryStroke || "",
    state.countryStrokeWidth || "",
    state.highlightContext ? 1 : 0,
    state.highlightSelected ? 1 : 0,
    state.highlightStroke || "",
    state.highlightStrokeWidth || "",
    state.hitActive ? 1 : 0,
    state.hitTitle || "",
    state.hitTabindex || "",
    state.hitRole || "",
    state.hitAriaHidden || "",
    state.hitAriaLabel || "",
  ].join("|");
}

function mapCountryState(nextStates, countryName) {
  if (!nextStates.has(countryName)) {
    const state = inactiveMapCountryRenderState(countryName);
    nextStates.set(countryName, state);
  }
  return nextStates.get(countryName);
}

function applyMapCountryRenderState(countryName, nextState = inactiveMapCountryRenderState(countryName)) {
  const nextSignature = mapCountryRenderSignature(nextState);
  const prevSignature = mapCountryRenderStateByName.get(countryName)?.signature || "";
  if (nextSignature === prevSignature) return;

  for (const countryPath of countryElsByName.get(countryName) || []) {
    countryPath.__countryName = countryName;
    setSvgClass(countryPath, "map-country-active", nextState.active);
    setSvgClass(countryPath, "map-country-context", nextState.context);
    setSvgClass(countryPath, "map-country-selected", nextState.selected);
    setSvgClass(countryPath, "map-country-hovered", nextState.hovered);
    setSvgStyle(countryPath, "fill", nextState.countryFill);
    setSvgStyle(countryPath, "stroke", nextState.countryStroke);
    setSvgStyle(countryPath, "strokeWidth", nextState.countryStrokeWidth);
    setMapPathTitle(countryPath, nextState.countryTitle || countryName);
  }

  for (const countryPath of countryHighlightElsByName.get(countryName) || []) {
    setSvgClass(countryPath, "map-country-highlight-border-context", nextState.highlightContext);
    setSvgClass(countryPath, "map-country-highlight-border-selected", nextState.highlightSelected);
    setSvgStyle(countryPath, "stroke", nextState.highlightStroke);
    setSvgStyle(countryPath, "strokeWidth", nextState.highlightStrokeWidth);
  }

  for (const countryPath of countryHitElsByName.get(countryName) || []) {
    countryPath.__countryName = countryName;
    setSvgClass(countryPath, "map-country-hit-active", nextState.hitActive);
    setSvgAttr(countryPath, "tabindex", nextState.hitTabindex || "-1");
    setSvgAttr(countryPath, "aria-hidden", nextState.hitAriaHidden || "true");
    setSvgAttr(countryPath, "role", nextState.hitRole);
    setSvgAttr(countryPath, "aria-label", nextState.hitAriaLabel);
    setMapPathTitle(countryPath, nextState.hitTitle || countryName);
  }

  if (nextSignature === mapCountryRenderSignature(inactiveMapCountryRenderState(countryName))) {
    mapCountryRenderStateByName.delete(countryName);
  } else {
    mapCountryRenderStateByName.set(countryName, { signature: nextSignature });
  }
}

function mapSuperregionRenderSignature(state) {
  if (!state) return "";
  return [
    state.countriesKey || "",
    state.color || "",
    state.dim ? 1 : 0,
    state.hover ? 1 : 0,
    state.selected ? 1 : 0,
  ].join("|");
}

function applyMapSuperregionRenderState(groupKey, state = null) {
  const nextSignature = mapSuperregionRenderSignature(state);
  const prevSignature = mapSuperregionRenderStateByKey.get(groupKey)?.signature || "";
  if (!state) {
    const borderPath = mapSuperregionBorderElsByGroupKey.get(groupKey);
    if (borderPath) borderPath.remove();
    mapSuperregionBorderElsByGroupKey.delete(groupKey);
    mapSuperregionRenderStateByKey.delete(groupKey);
    return;
  }
  if (nextSignature === prevSignature) return;
  updateSuperregionBorder(groupKey, state.color, {
    dim: state.dim,
    hover: state.hover,
    selected: state.selected,
  });
  mapSuperregionRenderStateByKey.set(groupKey, { signature: nextSignature });
}

function applyMapRenderState(nextCountryStates = new Map(), nextItemsByCountry = new Map(), nextSuperregionStates = new Map()) {
  clearMapHoveredCountry();

  mapItemsByCountryName.clear();
  for (const [countryName, item] of nextItemsByCountry.entries()) {
    mapItemsByCountryName.set(countryName, item);
  }

  const countryNames = new Set([
    ...mapCountryRenderStateByName.keys(),
    ...nextCountryStates.keys(),
  ]);
  for (const countryName of countryNames) {
    applyMapCountryRenderState(countryName, nextCountryStates.get(countryName) || inactiveMapCountryRenderState(countryName));
  }

  const superregionKeys = new Set([
    ...mapSuperregionRenderStateByKey.keys(),
    ...nextSuperregionStates.keys(),
  ]);
  for (const groupKey of superregionKeys) {
    applyMapSuperregionRenderState(groupKey, nextSuperregionStates.get(groupKey) || null);
  }
}

function clearCountryHighlights() {
  applyMapRenderState();
  mapHoverCountriesByCountryName.clear();
  mapSuperregionCountriesByGroupKey.clear();
  mapSuperregionGroupKeyByCountryName.clear();
  for (const borderPath of mapSuperregionBorderElsByGroupKey.values()) {
    borderPath.remove();
  }
  mapSuperregionBorderElsByGroupKey.clear();
  mapSuperregionRenderStateByKey.clear();
}

function isMapExpanded() {
  return Boolean(mapCard?.classList.contains("map-expanded"));
}

function syncMapCountryInteractivity() {
  const interactive = isMapExpanded() && !mapListMode;
  for (const [countryName, countryPaths] of countryHitElsByName.entries()) {
    const active = countryPaths.some(path => path.classList.contains("map-country-hit-active"));
    for (const countryPath of countryPaths) {
      if (active && interactive) {
        const item = mapItemsByCountryName.get(countryName);
        setSvgAttr(countryPath, "tabindex", "0");
        setSvgAttr(countryPath, "role", "button");
        setSvgAttr(countryPath, "aria-hidden", "false");
        setSvgAttr(countryPath, "aria-label", item?.selectable_for || `${countryName}: ${item?.display_title || item?.wikipedia_title || countryName}`);
      } else {
        setSvgAttr(countryPath, "tabindex", "-1");
        setSvgAttr(countryPath, "aria-hidden", "true");
        if (!active) {
          setSvgAttr(countryPath, "role", "");
          setSvgAttr(countryPath, "aria-label", "");
        }
      }
    }
  }
}

function mapZoomFromViewBox() {
  return Math.min(
    MAP_VIEWBOX_DEFAULT.w / Math.max(1, mapViewBox.w),
    MAP_VIEWBOX_DEFAULT.h / Math.max(1, mapViewBox.h)
  );
}

function isMapViewZoomed() {
  return (
    Math.abs(mapViewBox.w - mapAutoViewBox.w) > 0.5 ||
    Math.abs(mapViewBox.h - mapAutoViewBox.h) > 0.5 ||
    Math.abs(mapViewBox.x - mapAutoViewBox.x) > 0.5 ||
    Math.abs(mapViewBox.y - mapAutoViewBox.y) > 0.5
  );
}

function updateMapResetButton() {
  if (!mapResetButton) return;
  mapResetButton.hidden = mapListMode || !isMapExpanded() || !mapViewManuallyAdjusted;
}

function setMapViewManuallyAdjusted(adjusted) {
  mapViewManuallyAdjusted = Boolean(adjusted);
  updateMapResetButton();
}

function clampAxisToRange(value, min, max) {
  if (min > max) return (min + max) / 2;
  return clamp(value, min, max);
}

function softClampAxisToRange(value, min, max, overscroll = MAP_FOCUS_OVERSCROLL) {
  if (min > max) return (min + max) / 2;
  if (value < min) return min - Math.min(overscroll, (min - value) * 0.28);
  if (value > max) return max + Math.min(overscroll, (value - max) * 0.28);
  return value;
}

function mapWorldPanLimits(w, h) {
  return {
    minX: MAP_VIEWBOX_DEFAULT.x,
    maxX: MAP_VIEWBOX_DEFAULT.x + MAP_VIEWBOX_DEFAULT.w - w,
    minY: MAP_VIEWBOX_DEFAULT.y,
    maxY: MAP_VIEWBOX_DEFAULT.y + MAP_VIEWBOX_DEFAULT.h - h,
  };
}

function mapViewportAspect() {
  const rect = regionMap?.getBoundingClientRect?.();
  const width = Number(rect?.width);
  const height = Number(rect?.height);
  if (Number.isFinite(width) && Number.isFinite(height) && width > 4 && height > 4) {
    return clamp(width / height, 0.45, 3.2);
  }
  return MAP_VIEWBOX_DEFAULT.w / MAP_VIEWBOX_DEFAULT.h;
}

function mapSizeForAspectAndZoom(aspect = mapViewportAspect(), zoom = 1) {
  const worldAspect = MAP_VIEWBOX_DEFAULT.w / MAP_VIEWBOX_DEFAULT.h;
  const clampedZoom = clamp(Number(zoom) || 1, MAP_MIN_ZOOM, MAP_MAX_ZOOM);
  if (aspect >= worldAspect) {
    const w = MAP_VIEWBOX_DEFAULT.w / clampedZoom;
    return { w, h: w / aspect };
  }
  const h = MAP_VIEWBOX_DEFAULT.h / clampedZoom;
  return { w: h * aspect, h };
}

function mapBoxWithViewportAspect(box, aspect = mapViewportAspect()) {
  const inputW = Math.max(1, Number(box?.w) || MAP_VIEWBOX_DEFAULT.w);
  const inputH = Math.max(1, Number(box?.h) || MAP_VIEWBOX_DEFAULT.h);
  const centerX = Number.isFinite(box?.x) ? box.x + inputW / 2 : MAP_VIEWBOX_DEFAULT.x + MAP_VIEWBOX_DEFAULT.w / 2;
  const centerY = Number.isFinite(box?.y) ? box.y + inputH / 2 : MAP_VIEWBOX_DEFAULT.y + MAP_VIEWBOX_DEFAULT.h / 2;
  let w = inputW;
  let h = inputH;
  if (w / h < aspect) w = h * aspect;
  else h = w / aspect;
  const zoom = clamp(
    Math.min(MAP_VIEWBOX_DEFAULT.w / Math.max(1, w), MAP_VIEWBOX_DEFAULT.h / Math.max(1, h)),
    MAP_MIN_ZOOM,
    MAP_MAX_ZOOM
  );
  ({ w, h } = mapSizeForAspectAndZoom(aspect, zoom));
  return {
    x: centerX - w / 2,
    y: centerY - h / 2,
    w,
    h,
  };
}

function focusedPanAxisLimits(focusStart, focusSize, viewportSize, worldMin, worldMax) {
  let min;
  let max;
  if (focusSize <= viewportSize) {
    min = focusStart + focusSize - viewportSize;
    max = focusStart;
  } else {
    const overlap = Math.min(MAP_FOCUS_MIN_OVERLAP, viewportSize * 0.42, focusSize * 0.42);
    min = focusStart - viewportSize + overlap;
    max = focusStart + focusSize - overlap;
  }
  return {
    min: Math.max(worldMin, min),
    max: Math.min(worldMax, max),
  };
}

function focusedMapPanLimits(w, h) {
  const world = mapWorldPanLimits(w, h);
  if (!mapPanFocusActive) return world;
  const xLimits = focusedPanAxisLimits(
    mapAutoViewBox.x,
    mapAutoViewBox.w,
    w,
    world.minX,
    world.maxX
  );
  const yLimits = focusedPanAxisLimits(
    mapAutoViewBox.y,
    mapAutoViewBox.h,
    h,
    world.minY,
    world.maxY
  );
  return {
    minX: xLimits.min,
    maxX: xLimits.max,
    minY: yLimits.min,
    maxY: yLimits.max,
  };
}

function clampMapViewBox(box, { softFocus = false } = {}) {
  const aspect = mapViewportAspect();
  const fitted = mapBoxWithViewportAspect(box, aspect);
  const w = fitted.w;
  const h = fitted.h;
  const world = mapWorldPanLimits(w, h);
  const focus = focusedMapPanLimits(w, h);
  const clampFocus = softFocus ? softClampAxisToRange : clampAxisToRange;
  const x = clamp(
    clampFocus(fitted.x, focus.minX, focus.maxX),
    world.minX,
    world.maxX
  );
  const y = clamp(
    clampFocus(fitted.y, focus.minY, focus.maxY),
    world.minY,
    world.maxY
  );
  return {
    x,
    y,
    w,
    h,
  };
}

function applyMapViewBox(options = {}) {
  if (!regionMap) return;
  mapViewBox = clampMapViewBox(mapViewBox, options);
  regionMap.setAttribute(
    "viewBox",
    `${mapViewBox.x} ${mapViewBox.y} ${mapViewBox.w} ${mapViewBox.h}`
  );
  updateMapResetButton();
}

function cancelMapViewBoxAnimation() {
  if (!mapViewBoxAnimFrame) return;
  cancelAnimationFrame(mapViewBoxAnimFrame);
  mapViewBoxAnimFrame = 0;
}

function cancelMapPanSettle() {
  if (!mapPanSettleTimer) return;
  clearTimeout(mapPanSettleTimer);
  mapPanSettleTimer = 0;
}

function mapViewBoxCloseEnough(a, b) {
  return (
    Math.abs(a.x - b.x) < 0.25 &&
    Math.abs(a.y - b.y) < 0.25 &&
    Math.abs(a.w - b.w) < 0.25 &&
    Math.abs(a.h - b.h) < 0.25
  );
}

function easeMapViewBox(t) {
  return 1 - Math.pow(1 - t, 3);
}

function animateMapViewBoxTo(target, { immediate = false } = {}) {
  const next = clampMapViewBox(target);
  cancelMapViewBoxAnimation();
  cancelMapPanSettle();
  if (immediate || mapViewBoxCloseEnough(mapViewBox, next)) {
    mapViewBox = { ...next };
    applyMapViewBox();
    return;
  }
  const start = { ...mapViewBox };
  const startAt = performance.now();
  const step = now => {
    const t = clamp((now - startAt) / MAP_VIEWBOX_ANIM_MS, 0, 1);
    const eased = easeMapViewBox(t);
    mapViewBox = {
      x: start.x + (next.x - start.x) * eased,
      y: start.y + (next.y - start.y) * eased,
      w: start.w + (next.w - start.w) * eased,
      h: start.h + (next.h - start.h) * eased,
    };
    applyMapViewBox();
    if (t < 1) {
      mapViewBoxAnimFrame = requestAnimationFrame(step);
      return;
    }
    mapViewBoxAnimFrame = 0;
    mapViewBox = { ...next };
    applyMapViewBox();
  };
  mapViewBoxAnimFrame = requestAnimationFrame(step);
}

function resetMapViewBox() {
  refitMapAutoView({ animate: true });
}

function settleMapViewBox() {
  cancelMapPanSettle();
  const next = clampMapViewBox(mapViewBox);
  if (mapViewBoxCloseEnough(mapViewBox, next)) {
    mapViewBox = { ...next };
    applyMapViewBox();
    if (mapViewBoxCloseEnough(mapViewBox, mapAutoViewBox)) {
      setMapViewManuallyAdjusted(false);
    }
    return;
  }
  if (mapViewBoxCloseEnough(next, mapAutoViewBox)) {
    setMapViewManuallyAdjusted(false);
  }
  animateMapViewBoxTo(next);
}

function scheduleMapPanSettle() {
  cancelMapPanSettle();
  mapPanSettleTimer = window.setTimeout(settleMapViewBox, MAP_PAN_SETTLE_DELAY_MS);
}

function countrySvgBounds(countryName) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const path of countryElsByName.get(countryName) || []) {
    try {
      const box = path.getBBox();
      if (!box || box.width <= 0 || box.height <= 0) continue;
      minX = Math.min(minX, box.x);
      minY = Math.min(minY, box.y);
      maxX = Math.max(maxX, box.x + box.width);
      maxY = Math.max(maxY, box.y + box.height);
    } catch {}
  }
  if (![minX, minY, maxX, maxY].every(Number.isFinite)) return null;
  return { minX, minY, maxX, maxY };
}

function mapViewBoxForCountryFeatures(featureKeys) {
  const bounds = [];
  for (const key of featureKeys || []) {
    const resolved = resolveMapCountry(key) || key;
    const box = countrySvgBounds(resolved);
    if (box) bounds.push(box);
  }
  if (!bounds.length) return clampMapViewBox({ ...MAP_VIEWBOX_DEFAULT });

  let minX = Math.min(...bounds.map(box => box.minX));
  let minY = Math.min(...bounds.map(box => box.minY));
  let maxX = Math.max(...bounds.map(box => box.maxX));
  let maxY = Math.max(...bounds.map(box => box.maxY));
  minX -= MAP_FIT_PADDING;
  minY -= MAP_FIT_PADDING;
  maxX += MAP_FIT_PADDING;
  maxY += MAP_FIT_PADDING;

  const width = Math.max(18, maxX - minX);
  const height = Math.max(18, maxY - minY);
  const fitted = mapBoxWithViewportAspect({
    x: minX,
    y: minY,
    w: width,
    h: height,
  });
  return clampMapViewBox(fitted);
}

function normalizeMapAutoViewFeatureKeys(featureKeys) {
  const keys = [];
  const seen = new Set();
  for (const key of featureKeys || []) {
    const resolved = resolveMapCountry(key) || key;
    if (!resolved || seen.has(resolved)) continue;
    seen.add(resolved);
    keys.push(resolved);
  }
  return keys;
}

function setMapAutoViewFeatures(featureKeys, { animate = true, immediate = false } = {}) {
  setMapViewManuallyAdjusted(false);
  mapAutoViewFeatureKeys = normalizeMapAutoViewFeatureKeys(featureKeys);
  mapPanFocusActive = Boolean(mapAutoViewFeatureKeys.length);
  mapAutoViewBox = mapViewBoxForCountryFeatures(mapAutoViewFeatureKeys);
  if (animate) animateMapViewBoxTo(mapAutoViewBox, { immediate });
  else {
    cancelMapViewBoxAnimation();
    cancelMapPanSettle();
    mapViewBox = { ...mapAutoViewBox };
    applyMapViewBox();
  }
}

function refitMapAutoView({ animate = true, immediate = false } = {}) {
  if (!mapAutoViewFeatureKeys.length && !activeMapKey) return;
  setMapAutoViewFeatures(mapAutoViewFeatureKeys, { animate, immediate });
}

function updateMapAutoView(featureKeys) {
  setMapAutoViewFeatures(featureKeys, { animate: true });
}

function mapClientToViewBoxPoint(clientX, clientY, box = mapViewBox) {
  const rect = regionMap.getBoundingClientRect();
  const x = box.x + ((clientX - rect.left) / Math.max(1, rect.width)) * box.w;
  const y = box.y + ((clientY - rect.top) / Math.max(1, rect.height)) * box.h;
  return { x, y };
}

function zoomMapAt(clientX, clientY, factor) {
  setMapViewManuallyAdjusted(true);
  cancelMapViewBoxAnimation();
  cancelMapPanSettle();
  const before = mapClientToViewBoxPoint(clientX, clientY);
  const nextZoom = clamp(mapZoomFromViewBox() * factor, MAP_MIN_ZOOM, MAP_MAX_ZOOM);
  const nextW = MAP_VIEWBOX_DEFAULT.w / nextZoom;
  const nextH = MAP_VIEWBOX_DEFAULT.h / nextZoom;
  const rect = regionMap.getBoundingClientRect();
  const rx = (clientX - rect.left) / Math.max(1, rect.width);
  const ry = (clientY - rect.top) / Math.max(1, rect.height);
  mapViewBox = clampMapViewBox({
    x: before.x - rx * nextW,
    y: before.y - ry * nextH,
    w: nextW,
    h: nextH,
  });
  applyMapViewBox();
}

function panMapByClientDelta(dx, dy) {
  setMapViewManuallyAdjusted(true);
  cancelMapViewBoxAnimation();
  cancelMapPanSettle();
  const rect = regionMap.getBoundingClientRect();
  mapViewBox = clampMapViewBox({
    ...mapViewBox,
    x: mapViewBox.x - (dx / Math.max(1, rect.width)) * mapViewBox.w,
    y: mapViewBox.y - (dy / Math.max(1, rect.height)) * mapViewBox.h,
  }, { softFocus: true });
  applyMapViewBox({ softFocus: true });
}

function highlightContextCountries(node) {
  const features = [];
  if (activeMapKey !== "world") return features;
  const color = nodeMapColor(node);
  for (const countryName of inferCountriesForNode(node)) {
    if (!countryElsByName.has(countryName)) continue;
    features.push(countryName);
    for (const countryPath of countryElsByName.get(countryName) || []) {
      countryPath.classList.add("map-country-context");
    }
    for (const countryPath of countryHighlightElsByName.get(countryName) || []) {
      countryPath.classList.add("map-country-highlight-border-context");
    }
    applyMapCountryColor(countryName, color);
  }
  return features;
}

function mapFeatureForItem(item) {
  if (!item) return null;
  return item.feature_key || mapCountryName(item.region_name);
}

function dedupeMapListItems(items) {
  const seen = new Set();
  const deduped = [];
  for (const item of items || []) {
    const key = [
      item?.map_key || "",
      item?.feature_key || item?.region_key || "",
      item?.genre_id || "",
      item?.candidate_id || "",
      item?.display_title || item?.wikipedia_title || "",
    ].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
  }
  return deduped;
}

function normalizedCountryLookup(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/gi, " ")
    .trim()
    .toLowerCase();
}

const wikimediaFlagFileAliases = new Map(Object.entries({
  "bahamas": "Flag of the Bahamas.svg",
  "czech republic": "Flag of the Czech Republic.svg",
  "democratic republic of the congo": "Flag of the Democratic Republic of the Congo.svg",
  "dominican republic": "Flag of the Dominican Republic.svg",
  "gambia": "Flag of the Gambia.svg",
  "ivory coast": "Flag of Cote d'Ivoire.svg",
  "netherlands": "Flag of the Netherlands.svg",
  "philippines": "Flag of the Philippines.svg",
  "republic of the congo": "Flag of the Republic of the Congo.svg",
  "united arab emirates": "Flag of the United Arab Emirates.svg",
  "united kingdom": "Flag of the United Kingdom.svg",
  "united states": "Flag of the United States.svg",
  "united states of america": "Flag of the United States.svg",
}));

function wikimediaFlagUrlForCountry(name) {
  const cleanName = String(name || "").trim();
  if (!cleanName) return "";
  const fileTitle = wikimediaFlagFileAliases.get(normalizedCountryLookup(cleanName)) || `Flag of ${cleanName}.svg`;
  return `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(fileTitle)}?width=96`;
}

function createRootMapListFlagIcon(item) {
  const countryName = item?.region_name || mapFeatureForItem(item) || mapListTitle(item);
  const url = wikimediaFlagUrlForCountry(countryName);
  if (!url) {
    const fallback = document.createElement("span");
    fallback.className = "map-list-flag-fallback";
    fallback.setAttribute("aria-hidden", "true");
    return fallback;
  }
  const img = document.createElement("img");
  img.className = "map-list-flag";
  img.alt = "";
  img.loading = "lazy";
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.src = url;
  img.addEventListener("error", () => {
    const fallback = document.createElement("span");
    fallback.className = "map-list-flag-fallback";
    fallback.setAttribute("aria-hidden", "true");
    img.replaceWith(fallback);
  }, { once: true });
  return img;
}

let worldMiniMapDataPromise = null;

async function getWorldMiniMapData() {
  if (!worldMiniMapDataPromise) {
    worldMiniMapDataPromise = loadMapFeatures("world").then(features => {
      const collection = { type: "FeatureCollection", features };
      const projection = geoNaturalEarth1().fitExtent([[0, 0], [MAP_LIST_ICON_WIDTH * 4, MAP_LIST_ICON_HEIGHT * 4]], collection);
      const path = geoPath(projection);
      const data = new Map();
      for (const featureItem of features) {
        const name = featureItem.properties?.name;
        const d = path(featureItem);
        if (!name || !d) continue;
        data.set(name, {
          d,
          bounds: path.bounds(featureItem),
        });
      }
      return data;
    });
  }
  return worldMiniMapDataPromise;
}

function mapListTitle(item) {
  return item.selectable_for || item.display_title || item.wikipedia_title || item.region_name || "Variation";
}

function mapListMetric(item) {
  return item?.monthly_views_p30 || 0;
}

function mapListItemKey(item) {
  return [
    item?.region_id || item?.region_key || "",
    item?.genre_id || "",
    item?.candidate_id || "",
    mapListTitle(item),
  ].join("|");
}

function mapListIdentityKey(item) {
  if (isProjectedMapListItem(item)) {
    if (item?.matched_genre_id) return `genre:${item.matched_genre_id}`;
    return `projected-title:${mapListTitle(item)}`;
  }
  if (item?.genre_id) return `genre:${item.genre_id}`;
  if (item?.candidate_id) return `candidate:${item.candidate_id}`;
  if (item?.base_genre_id) return `base:${item.base_genre_id}:${mapListTitle(item)}`;
  return `title:${mapListTitle(item)}`;
}

function mapListGroupLabel(item) {
  return item?.list_group_region_name || item?.matched_region_name || "Other regions";
}

function mapListGroupKey(item) {
  return item?.list_group_region_id || item?.matched_region_id || mapListGroupLabel(item);
}

function isProjectedMapListItem(item) {
  return item?.match_type === "pure_region_descendant_country" || item?.match_type === "pure_region_child_country";
}

function mergeUniqueValues(...lists) {
  const seen = new Set();
  const merged = [];
  for (const list of lists) {
    for (const value of list || []) {
      if (!value || seen.has(value)) continue;
      seen.add(value);
      merged.push(value);
    }
  }
  return merged;
}

function chooseMapListCanonicalItem(current, candidate) {
  if (!current) return candidate;
  const currentProjected = isProjectedMapListItem(current);
  const candidateProjected = isProjectedMapListItem(candidate);
  if (currentProjected !== candidateProjected) return candidateProjected ? current : candidate;
  const currentMetric = mapListMetric(current);
  const candidateMetric = mapListMetric(candidate);
  if (candidateMetric !== currentMetric) return candidateMetric > currentMetric ? candidate : current;
  return mapListTitle(candidate).localeCompare(mapListTitle(current)) < 0 ? candidate : current;
}

function aggregateMapListItems(items) {
  const grouped = new Map();
  for (const item of dedupeMapListItems(items)) {
    const key = mapListIdentityKey(item);
    const entry = grouped.get(key) || { canonical: null, items: [] };
    entry.canonical = chooseMapListCanonicalItem(entry.canonical, item);
    entry.items.push(item);
    grouped.set(key, entry);
  }
  return [...grouped.values()].map(entry => {
    const { canonical, items: sourceItems } = entry;
    const iconFeatureKeys = mergeUniqueValues(...sourceItems.map(item => item.icon_feature_keys || []));
    const representedGenreIds = mergeUniqueValues(...sourceItems.map(item => item.represented_genre_ids || []));
    const representedTitles = mergeUniqueValues(...sourceItems.map(item => item.represented_titles || []));
    const representedChildren = [];
    const seenChildIds = new Set();
    for (const item of sourceItems) {
      for (const child of item.represented_children || []) {
        const key = child?.genre_id || child?.wikipedia_title || JSON.stringify(child);
        if (!key || seenChildIds.has(key)) continue;
        seenChildIds.add(key);
        representedChildren.push(child);
      }
    }
    return {
      ...canonical,
      icon_feature_keys: iconFeatureKeys.length ? iconFeatureKeys : mapListIconFeatureKeys(canonical),
      represented_genre_ids: representedGenreIds,
      represented_titles: representedTitles,
      represented_children: representedChildren,
    };
  });
}

function sortedMapListChildren(nodesForParent) {
  nodesForParent.sort((a, b) => {
    const av = mapListMetric(a.item);
    const bv = mapListMetric(b.item);
    return bv - av || mapListTitle(a.item).localeCompare(mapListTitle(b.item));
  });
  for (const node of nodesForParent) {
    if (node.children.length) sortedMapListChildren(node.children);
  }
}

function mapListSubtreeViews(node) {
  return mapListMetric(node.item) + node.children.reduce((sum, child) => sum + mapListSubtreeViews(child), 0);
}

function flattenMapListNode(node, depth, rows) {
  rows.push({
    type: "item",
    key: `item-${node.key}`,
    item: node.item,
    depth,
    hasParent: depth > 0,
  });
  for (const child of node.children) flattenMapListNode(child, depth + 1, rows);
}

function canParentMapListChild(parentItem, childItem) {
  if (!parentItem || !childItem) return false;
  if (parentItem.region_kind === "country") return true;
  if (parentItem.role === "regional_variant" || parentItem.role === "regional_style_candidate") {
    return false;
  }
  return parentItem.region_id === childItem.mount_parent_region_id;
}

function buildMapListRows(items) {
  const dedupedItems = aggregateMapListItems(items);
  if (!dedupedItems.length) return [];

  const nodeByKey = new Map();
  const nodeByRegionId = new Map();
  for (const item of dedupedItems) {
    const node = {
      key: mapListItemKey(item),
      item,
      children: [],
      parentKey: null,
    };
    nodeByKey.set(node.key, node);
    if (item.region_id) nodeByRegionId.set(item.region_id, node);
  }

  for (const node of nodeByKey.values()) {
    const parentRegionId = node.item.mount_parent_region_id;
    if (!parentRegionId || parentRegionId === node.item.region_id) continue;
    const parent = nodeByRegionId.get(parentRegionId);
    if (!parent || !canParentMapListChild(parent.item, node.item)) continue;
    node.parentKey = parent.key;
    parent.children.push(node);
  }

  const rootNodes = [...nodeByKey.values()].filter(node => !node.parentKey);
  const groups = new Map();
  for (const root of rootNodes) {
    const key = mapListGroupKey(root.item);
    const label = mapListGroupLabel(root.item);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label,
        roots: [],
        totalViews: 0,
      });
    }
    groups.get(key).roots.push(root);
  }

  for (const group of groups.values()) {
    sortedMapListChildren(group.roots);
    group.totalViews = group.roots.reduce((sum, root) => sum + mapListSubtreeViews(root), 0);
  }

  const rows = [];
  const sortedGroups = [...groups.values()].sort((a, b) =>
    b.totalViews - a.totalViews || a.label.localeCompare(b.label)
  );
  for (const group of sortedGroups) {
    rows.push({
      type: "header",
      key: `header-${group.key}`,
      label: group.label,
    });
    for (const root of group.roots) flattenMapListNode(root, 0, rows);
  }
  return rows;
}

function rootMapListCountrySortLabel(item) {
  return item?.region_name || mapFeatureForItem(item) || mapListTitle(item);
}

function buildRootMapListRows(items) {
  const groups = new Map();
  for (const item of dedupeMapListItems(items)) {
    const key = mapListGroupKey(item);
    const label = mapListGroupLabel(item);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label,
        items: [],
      });
    }
    groups.get(key).items.push(item);
  }

  const rows = [];
  const sortedGroups = [...groups.values()].sort((a, b) => a.label.localeCompare(b.label));
  for (const group of sortedGroups) {
    rows.push({
      type: "header",
      key: `header-${group.key}`,
      label: group.label,
    });
    group.items.sort((a, b) =>
      rootMapListCountrySortLabel(a).localeCompare(rootMapListCountrySortLabel(b))
      || mapListTitle(a).localeCompare(mapListTitle(b))
    );
    for (const item of group.items) {
      rows.push({
        type: "item",
        key: `item-root-${mapListItemKey(item)}`,
        item,
        depth: 0,
        hasParent: false,
      });
    }
  }
  return rows;
}

function mapListIndividualSearchTextForItem(item) {
  return normalizeGeoText([
    mapListTitle(item),
    rootMapListCountrySortLabel(item),
    item?.region_name,
    item?.feature_name,
    item?.feature_key,
    item?.wikipedia_title,
    ...(item?.represented_titles || []),
  ].filter(Boolean).join(" "));
}

function mapListAggregateSearchTextForItem(item) {
  return normalizeGeoText([
    mapListIndividualSearchTextForItem(item),
    mapListGroupLabel(item),
    item?.matched_region_name,
    item?.mount_parent_region_name,
  ].filter(Boolean).join(" "));
}

function mapListRowsForItems(items, rootMode) {
  return rootMode ? buildRootMapListRows(items) : buildMapListRows(items);
}

function mapListSearchAvailableForMetrics(metrics) {
  const viewportHeight = mapListMaxCardHeight() - mapListTopInset() - MAP_LIST_BOTTOM_INSET;
  return metrics.totalHeight > Math.max(MAP_LIST_MIN_CARD_HEIGHT, viewportHeight) + 4;
}

function filterMapListItemsForSearch(items, rootMode) {
  const query = normalizeGeoText(mapListSearchQuery);
  if (!query) return items;
  const individualMatches = (items || []).filter(item => mapListIndividualSearchTextForItem(item).includes(query));
  if (individualMatches.length) return individualMatches;
  return (rootMode ? dedupeMapListItems(items) : aggregateMapListItems(items))
    .filter(item => mapListAggregateSearchTextForItem(item).includes(query));
}

function mapListRowMetrics(rows) {
  let offset = MAP_LIST_CONTENT_TOP_PAD;
  const measuredRows = rows.map(row => {
    const height = row.type === "header" ? MAP_LIST_HEADER_HEIGHT : MAP_LIST_ITEM_HEIGHT;
    const measured = { ...row, top: offset, height, bottom: offset + height };
    offset += height;
    return measured;
  });
  return {
    rows: measuredRows,
    totalHeight: offset + MAP_LIST_CONTENT_BOTTOM_PAD,
  };
}

function mapListVisibleRowRange(rows, scrollTop, viewportHeight) {
  const minY = Math.max(0, scrollTop - MAP_LIST_OVERSCAN_PX);
  const maxY = scrollTop + viewportHeight + MAP_LIST_OVERSCAN_PX;
  let start = 0;
  while (start < rows.length && rows[start].bottom < minY) start += 1;
  let end = start;
  while (end < rows.length && rows[end].top <= maxY) end += 1;
  return [start, end];
}

function mapListIconFeatureKeys(item) {
  if (Array.isArray(item?.icon_feature_keys) && item.icon_feature_keys.length) {
    return item.icon_feature_keys;
  }
  const feature = mapFeatureForItem(item);
  return feature ? [feature] : [];
}

function createMapListIcon(item, worldMiniMapData, currentNode) {
  const svg = svgEl("svg", {
    class: "map-list-icon",
    viewBox: `0 0 ${MAP_LIST_ICON_WIDTH} ${MAP_LIST_ICON_HEIGHT}`,
    "aria-hidden": "true",
  });
  const keys = [...new Set(mapListIconFeatureKeys(item))];
  const features = keys.map(key => worldMiniMapData.get(key)).filter(Boolean);
  if (!features.length) return svg;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const featureItem of features) {
    const [[x1, y1], [x2, y2]] = featureItem.bounds;
    minX = Math.min(minX, x1);
    minY = Math.min(minY, y1);
    maxX = Math.max(maxX, x2);
    maxY = Math.max(maxY, y2);
  }

  const width = Math.max(1, maxX - minX);
  const height = Math.max(1, maxY - minY);
  const padding = 1.2;
  const scale = Math.min(
    (MAP_LIST_ICON_WIDTH - padding * 2) / width,
    (MAP_LIST_ICON_HEIGHT - padding * 2) / height
  );
  const translateX = padding + (MAP_LIST_ICON_WIDTH - padding * 2 - width * scale) / 2 - minX * scale;
  const translateY = padding + (MAP_LIST_ICON_HEIGHT - padding * 2 - height * scale) / 2 - minY * scale;
  const isSelected = isMapItemSelected(item, currentNode);
  const fill = mapColorPair(item.similarity_color || nodeMapColor(currentNode), { dim: isSelected }).fill;

  const group = svgEl("g", {
    transform: `translate(${translateX} ${translateY}) scale(${scale})`,
  });
  for (const featureItem of features) {
    const path = svgEl("path", {
      class: "map-list-icon-path",
      d: featureItem.d,
    });
    path.style.fill = fill;
    group.appendChild(path);
  }
  svg.appendChild(group);
  return svg;
}

function renderVisibleMapListRows() {
  if (!mapList) return;
  const state = mapListViewState;
  if (!state?.rows?.length) {
    const empty = document.createElement("div");
    empty.className = "map-list-empty";
    empty.textContent = state?.emptyMessage || "No regional variations";
    mapList.replaceChildren(empty);
    return;
  }

  const currentNode = nodes.get(currentKey);
  const viewportHeight = mapList.clientHeight || 0;
  if (viewportHeight < 24) return;
  const [start, end] = mapListVisibleRowRange(state.rows, mapList.scrollTop, viewportHeight);
  if (
    state.renderedStart === start
    && state.renderedEnd === end
    && state.renderedSelectionKey === currentKey
  ) {
    return;
  }
  const space = document.createElement("div");
  space.className = "map-list-virtual-space";
  space.style.height = `${state.totalHeight}px`;

  for (const row of state.rows.slice(start, end)) {
    if (row.type === "header") {
      const header = document.createElement("div");
      header.className = "map-list-group-header";
      header.textContent = row.label;
      header.style.top = `${row.top}px`;
      header.style.height = `${row.height}px`;
      space.appendChild(header);
      continue;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "map-list-item";
    button.style.top = `${row.top + 4}px`;
    button.style.height = `${Math.max(30, row.height - 8)}px`;
    button.style.setProperty("--tree-depth", String(row.depth));
    if (row.hasParent) button.classList.add("has-parent");
    if (isMapItemSelected(row.item, currentNode)) button.classList.add("is-selected");
    button.addEventListener("click", () => {
      void selectMapVariant(row.item);
    });

    const iconWrap = document.createElement("span");
    iconWrap.className = "map-list-icon-wrap";
    iconWrap.appendChild(state.rootMode
      ? createRootMapListFlagIcon(row.item)
      : createMapListIcon(row.item, state.worldMiniMapData, currentNode));

    const title = document.createElement("span");
    title.className = "map-list-title";
    title.textContent = mapListTitle(row.item);

    button.append(iconWrap, title);
    space.appendChild(button);
  }

  mapList.replaceChildren(space);
  state.renderedStart = start;
  state.renderedEnd = end;
  state.renderedSelectionKey = currentKey;
}

async function renderMapList(items, options = {}) {
  if (!mapList) return;
  const token = ++mapListRenderToken;
  const scrollTop = mapList.scrollTop;
  const rootMode = Boolean(options.rootMode);
  const worldMiniMapData = rootMode ? null : await getWorldMiniMapData();
  if (token !== mapListRenderToken || !mapListMode) return;
  const fullMetrics = mapListRowMetrics(mapListRowsForItems(items, rootMode));
  const searchAvailable = mapListSearchAvailableForMetrics(fullMetrics);
  if (!searchAvailable) {
    mapListSearchOpen = false;
    mapListSearchQuery = "";
    if (mapListSearchInput) mapListSearchInput.value = "";
  }
  updateMapListSearchVisibility(rootMode, searchAvailable);
  const visibleItems = filterMapListItemsForSearch(items, rootMode);
  const metrics = mapListRowMetrics(mapListRowsForItems(visibleItems, rootMode));
  mapListViewState = {
    rows: metrics.rows,
    totalHeight: metrics.totalHeight,
    worldMiniMapData,
    rootMode,
    items,
    searchAvailable,
    emptyMessage: rootMode && mapListSearchQuery ? "No matching regions" : "No regional variations",
    renderedStart: -1,
    renderedEnd: -1,
    renderedSelectionKey: "",
  };
  updateMapListCardHeight(metrics.totalHeight);
  mapList.scrollTop = scrollTop;
  renderVisibleMapListRows();
}

function parseCssColor(color) {
  const value = String(color || "").trim();
  const hex = value.match(/^#?([0-9a-f]{6}|[0-9a-f]{3})$/i)?.[1];
  if (hex) {
    const full = hex.length === 3 ? hex.split("").map(char => char + char).join("") : hex;
    return {
      r: Number.parseInt(full.slice(0, 2), 16),
      g: Number.parseInt(full.slice(2, 4), 16),
      b: Number.parseInt(full.slice(4, 6), 16),
    };
  }
  const rgb = value.match(/^rgba?\(([^)]+)\)$/i);
  if (rgb) {
    const [r, g, b] = rgb[1].split(",").map(part => Number.parseFloat(part.trim()));
    if ([r, g, b].every(Number.isFinite)) return { r, g, b };
  }
  return null;
}

function rgbToHsl({ r, g, b }) {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r:
        h = (g - b) / d + (g < b ? 6 : 0);
        break;
      case g:
        h = (b - r) / d + 2;
        break;
      default:
        h = (r - g) / d + 4;
    }
    h /= 6;
  }
  return { h, s, l };
}

function hueToRgb(p, q, t) {
  if (t < 0) t += 1;
  if (t > 1) t -= 1;
  if (t < 1 / 6) return p + (q - p) * 6 * t;
  if (t < 1 / 2) return q;
  if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
  return p;
}

function hslToRgb({ h, s, l }) {
  if (s === 0) {
    const gray = Math.round(l * 255);
    return { r: gray, g: gray, b: gray };
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return {
    r: Math.round(hueToRgb(p, q, h + 1 / 3) * 255),
    g: Math.round(hueToRgb(p, q, h) * 255),
    b: Math.round(hueToRgb(p, q, h - 1 / 3) * 255),
  };
}

function rgbToHex({ r, g, b }) {
  return `#${[r, g, b].map(value => {
    const clamped = Math.max(0, Math.min(255, Math.round(value)));
    return clamped.toString(16).padStart(2, "0");
  }).join("")}`;
}

function parseColorToRgb(color) {
  return parseCssColor(color);
}

function srgbToLinear(value) {
  const c = clamp(value / 255, 0, 1);
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function linearToSrgb(value) {
  const c = clamp(value, 0, 1);
  return c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

function rgbToOklab(rgb) {
  const r = srgbToLinear(rgb.r);
  const g = srgbToLinear(rgb.g);
  const b = srgbToLinear(rgb.b);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return {
    L: 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  };
}

function oklabToRgb(oklab) {
  const l = oklab.L + 0.3963377774 * oklab.a + 0.2158037573 * oklab.b;
  const m = oklab.L - 0.1055613458 * oklab.a - 0.0638541728 * oklab.b;
  const s = oklab.L - 0.0894841775 * oklab.a - 1.2914855480 * oklab.b;
  const l3 = l * l * l;
  const m3 = m * m * m;
  const s3 = s * s * s;
  return {
    r: Math.round(linearToSrgb(4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3) * 255),
    g: Math.round(linearToSrgb(-1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3) * 255),
    b: Math.round(linearToSrgb(-0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3) * 255),
  };
}

function oklabToOklch(oklab) {
  return {
    L: oklab.L,
    C: Math.hypot(oklab.a, oklab.b),
    h: Math.atan2(oklab.b, oklab.a),
  };
}

function oklchToOklab(oklch) {
  return {
    L: oklch.L,
    a: oklch.C * Math.cos(oklch.h),
    b: oklch.C * Math.sin(oklch.h),
  };
}

function rgbToCss(rgb) {
  return `rgb(${clamp(Math.round(rgb.r), 0, 255)}, ${clamp(Math.round(rgb.g), 0, 255)}, ${clamp(Math.round(rgb.b), 0, 255)})`;
}

function fallbackMapAccentColor() {
  const color = getComputedStyle(document.documentElement).getPropertyValue("--accent");
  return parseCssColor(color) ? color : "#2563eb";
}

function nodeMapColor(node) {
  return node?.color || node?.similarity_color || fallbackMapAccentColor();
}

function mapColorPair(color, { dim = false, hover = false } = {}) {
  const rgb = parseCssColor(color) || parseCssColor(fallbackMapAccentColor());
  const hsl = rgbToHsl(rgb);
  const normalizedLightness = 0.56;
  const fillLightness = (dim ? (hover ? 0.68 : 0.5) : 1) * normalizedLightness;
  const fill = {
    ...hsl,
    s: Math.max(0, Math.min(1, hsl.s * 0.84)),
    l: Math.max(0.16, Math.min(0.82, fillLightness)),
  };
  const stroke = {
    ...fill,
    s: Math.min(1, fill.s * 1.35 + 0.08),
    l: Math.min(0.78, fill.l + (1 - fill.l) * 0.24),
  };
  return {
    fill: rgbToHex(hslToRgb(fill)),
    stroke: rgbToHex(hslToRgb(stroke)),
  };
}

function applyMapCountryColor(countryName, color, { dim = false, selected = false, hover = false, suppressStroke = false } = {}) {
  const pair = mapColorPair(color, { dim, hover });
  for (const countryPath of countryElsByName.get(countryName) || []) {
    countryPath.style.fill = pair.fill;
    countryPath.style.stroke = suppressStroke ? "transparent" : pair.stroke;
    countryPath.style.strokeWidth = suppressStroke ? "0" : (hover ? "1.05" : (selected ? "0.95" : "0.85"));
  }
  for (const countryPath of countryHighlightElsByName.get(countryName) || []) {
    countryPath.style.stroke = suppressStroke ? "transparent" : pair.stroke;
    countryPath.style.strokeWidth = suppressStroke ? "0" : (hover ? "1.25" : (selected ? "1.15" : "0.95"));
  }
}

function selectableMapItemColor(item) {
  return item?.similarity_color || nodeMapColor(currentMapNodeForMode());
}

function restoreSelectableCountryStyle(countryName) {
  const item = mapItemsByCountryName.get(countryName);
  if (!item) return;
  const currentNode = currentMapNodeForMode();
  const isSelected = isMapItemSelected(item, currentNode);
  const useSelectedHighlightStyle = !isSelected;
  const groupKey = superregionGroupKeyForItem(item);
  const groupedSuperregion = Boolean(groupKey);
  applyMapCountryColor(countryName, selectableMapItemColor(item), {
    dim: useSelectedHighlightStyle,
    selected: useSelectedHighlightStyle,
    suppressStroke: groupedSuperregion,
  });
  if (groupedSuperregion) {
    updateSuperregionBorder(groupKey, selectableMapItemColor(item), {
      dim: useSelectedHighlightStyle,
      selected: useSelectedHighlightStyle,
    });
  }
}

function applyHoveredSelectableCountryStyle(countryName) {
  const item = mapItemsByCountryName.get(countryName);
  if (!item) return;
  const currentNode = currentMapNodeForMode();
  const isSelected = isMapItemSelected(item, currentNode);
  const useSelectedHighlightStyle = !isSelected;
  const groupKey = superregionGroupKeyForItem(item);
  const groupedSuperregion = Boolean(groupKey);
  applyMapCountryColor(countryName, selectableMapItemColor(item), {
    dim: useSelectedHighlightStyle,
    selected: useSelectedHighlightStyle,
    hover: true,
    suppressStroke: groupedSuperregion,
  });
  if (groupedSuperregion) {
    updateSuperregionBorder(groupKey, selectableMapItemColor(item), {
      dim: useSelectedHighlightStyle,
      selected: useSelectedHighlightStyle,
      hover: true,
    });
  }
}

function isMapItemSelected(item, currentNode) {
  return (
    (item.genre_id && currentNode?.genreId === item.genre_id) ||
    (item.candidate_id && currentNode?.candidateId === item.candidate_id) ||
    (item.region_id && currentNode?.regionId === item.region_id) ||
    Boolean(currentNode?.genreId && (item.represented_genre_ids || []).includes(currentNode.genreId))
  );
}

function highlightMapContextItem(item, color = null) {
  const countryName = featureKeyForMapItem(item);
  const countryPaths = countryElsByName.get(countryName);
  if (!countryPaths?.length) return;
  for (const countryPath of countryPaths) {
    countryPath.classList.add("map-country-context");
    const title = countryPath.querySelector("title");
    if (title) title.textContent = item.selectable_for || item.display_title || item.region_name || countryName;
  }
  for (const countryPath of countryHighlightElsByName.get(countryName) || []) {
    countryPath.classList.add("map-country-highlight-border-context");
  }
  applyMapCountryColor(countryName, color || item.similarity_color || fallbackMapAccentColor());
}

function highlightVariantCountry(item) {
  const countryName = featureKeyForMapItem(item);
  const countryPaths = countryElsByName.get(countryName);
  if (!countryPaths?.length) return;
  const itemLabel = item.selectable_for || `${item.display_title || item.wikipedia_title} (${item.region_name})`;

  mapItemsByCountryName.set(countryName, item);
  const currentNode = currentMapNodeForMode();
  const isSelected = isMapItemSelected(item, currentNode);
  const itemColor = selectableMapItemColor(item);
  const groupKey = superregionGroupKeyForItem(item);
  const groupedSuperregion = Boolean(groupKey);
  for (const countryPath of countryPaths) {
    countryPath.__countryName = countryName;
    countryPath.classList.add("map-country-active");
    countryPath.classList.toggle("map-country-selected", isSelected);
    const title = countryPath.querySelector("title");
    if (title) title.textContent = itemLabel;
  }
  const useSelectedHighlightStyle = !isSelected;
  if (useSelectedHighlightStyle && !groupedSuperregion) {
    for (const countryPath of countryHighlightElsByName.get(countryName) || []) {
      countryPath.classList.add("map-country-highlight-border-selected");
    }
  }
  applyMapCountryColor(countryName, itemColor, {
    dim: useSelectedHighlightStyle,
    selected: useSelectedHighlightStyle,
    suppressStroke: groupedSuperregion,
  });
  if (groupedSuperregion) {
    updateSuperregionBorder(groupKey, itemColor, {
      dim: useSelectedHighlightStyle,
      selected: useSelectedHighlightStyle,
    });
  }
  for (const countryPath of countryHitElsByName.get(countryName) || []) {
    countryPath.__countryName = countryName;
    countryPath.classList.add("map-country-hit-active");
    if (isMapExpanded() && !mapListMode) {
      countryPath.setAttribute("tabindex", "0");
      countryPath.setAttribute("role", "button");
      countryPath.setAttribute("aria-hidden", "false");
      countryPath.setAttribute("aria-label", item.selectable_for || `${countryName}: ${item.display_title || item.wikipedia_title}`);
    } else {
      countryPath.setAttribute("tabindex", "-1");
      countryPath.setAttribute("aria-hidden", "true");
    }
    const title = countryPath.querySelector("title");
    if (title) title.textContent = itemLabel;
  }
}

function inferredContextCountryFeatures(node) {
  const features = [];
  if (activeMapKey !== "world") return features;
  for (const countryName of inferCountriesForNode(node)) {
    if (countryElsByName.has(countryName)) features.push(countryName);
  }
  return features;
}

function assignContextMapCountryState(nextStates, countryName, item, color) {
  if (!countryName || !countryElsByName.has(countryName)) return;
  const state = mapCountryState(nextStates, countryName);
  const pair = mapColorPair(color || item?.similarity_color || fallbackMapAccentColor());
  state.context = true;
  state.highlightContext = true;
  state.countryTitle = item?.selectable_for || item?.display_title || item?.region_name || countryName;
  state.countryFill = pair.fill;
  state.countryStroke = pair.stroke;
  state.countryStrokeWidth = "0.85";
  state.highlightStroke = pair.stroke;
  state.highlightStrokeWidth = "0.95";
}

function assignVariantMapCountryState(nextStates, nextItemsByCountry, nextSuperregionStates, item) {
  const countryName = featureKeyForMapItem(item);
  if (!countryName || !countryElsByName.has(countryName)) return;
  const state = mapCountryState(nextStates, countryName);
  const currentNode = currentMapNodeForMode();
  const isSelected = isMapItemSelected(item, currentNode);
  const useSelectedHighlightStyle = !isSelected;
  const itemColor = selectableMapItemColor(item);
  const groupKey = superregionGroupKeyForItem(item);
  const groupedSuperregion = Boolean(groupKey);
  const pair = mapColorPair(itemColor, { dim: useSelectedHighlightStyle });
  const itemLabel = item.selectable_for || `${item.display_title || item.wikipedia_title} (${item.region_name})`;
  const hitInteractive = isMapExpanded() && !mapListMode;

  nextItemsByCountry.set(countryName, item);
  state.active = true;
  state.selected = isSelected;
  state.countryTitle = itemLabel;
  state.countryFill = pair.fill;
  state.countryStroke = groupedSuperregion ? "transparent" : pair.stroke;
  state.countryStrokeWidth = groupedSuperregion ? "0" : (useSelectedHighlightStyle ? "0.95" : "0.85");
  state.highlightStroke = groupedSuperregion ? "transparent" : pair.stroke;
  state.highlightStrokeWidth = groupedSuperregion ? "0" : (useSelectedHighlightStyle ? "1.15" : "0.95");
  state.highlightSelected = useSelectedHighlightStyle && !groupedSuperregion;
  state.hitActive = true;
  state.hitTitle = itemLabel;
  state.hitTabindex = hitInteractive ? "0" : "-1";
  state.hitRole = hitInteractive ? "button" : "";
  state.hitAriaHidden = hitInteractive ? "false" : "true";
  state.hitAriaLabel = hitInteractive ? (item.selectable_for || `${countryName}: ${item.display_title || item.wikipedia_title}`) : "";

  if (groupedSuperregion) {
    const countries = mapSuperregionCountriesByGroupKey.get(groupKey);
    nextSuperregionStates.set(groupKey, {
      countriesKey: countries ? [...countries].sort().join(",") : "",
      color: itemColor,
      dim: useSelectedHighlightStyle,
      hover: false,
      selected: useSelectedHighlightStyle,
    });
  }
}

function mapNodeKey(parent, item) {
  return `${parent.key}/region-${item.genre_id || `candidate-${item.candidate_id || item.region_id || item.feature_key}`}`;
}

function mapSourceNodeFor(node) {
  const parentScopedRoles = new Set([
    "regional_variant",
    "regional_style_candidate",
    "country_region_group",
    "inferred_country_region_group",
    "subregion",
    "territory",
  ]);
  if (
    node?.isMapChild &&
    node.parentKey &&
    nodes.has(node.parentKey) &&
    parentScopedRoles.has(node.mapRole || node.relation)
  ) {
    return mapSourceNodeFor(nodes.get(node.parentKey));
  }
  return node;
}

function findVisibleGenreNode(genreId, parentKey = null) {
  if (!genreId) return null;
  for (const node of nodes.values()) {
    if (node.genreId !== genreId) continue;
    if (parentKey && node.parentKey !== parentKey) continue;
    return node;
  }
  return null;
}

function findVisibleRegionNode(regionId, parentKey = null) {
  if (!regionId) return null;
  for (const node of nodes.values()) {
    if (node.regionId !== regionId) continue;
    if (parentKey && node.parentKey !== parentKey) continue;
    return node;
  }
  return null;
}

function mapMountParentForItem(item, focused) {
  const root = nodes.get(ROOT_KEY);
  if (!item) return mapSourceNodeFor(focused) || root;

  const requestedParentRegionId = item.mount_parent_region_id || item.parent_region_id;
  if (requestedParentRegionId) {
    if (focused?.regionId === requestedParentRegionId) return focused;
    const visibleParent = findVisibleRegionNode(requestedParentRegionId);
    if (visibleParent) return visibleParent;
  }

  if (focused?.isMapChild && focused.key === mapContextOwnerKey) return focused;

  const role = item.role || item.match_type || "";
  const peerRegionRoles = new Set(["subregion", "territory"]);
  if (
    peerRegionRoles.has(role) &&
    focused?.isMapChild &&
    focused.parentKey &&
    nodes.has(focused.parentKey) &&
    focused.mapKey === item.map_key
  ) {
    return nodes.get(focused.parentKey);
  }

  return mapSourceNodeFor(focused) || root;
}

function createRegionalNode(parent, item) {
  const existing = findVisibleGenreNode(item.genre_id, parent.key);
  if (existing) return existing;

  const key = mapNodeKey(parent, item);
  if (nodes.has(key)) return nodes.get(key);

  const existingSiblingCount = [...nodes.values()].filter(n => n.parentKey === parent.key).length;
  const angle = parent.key === ROOT_KEY ? Math.PI / 2 : parent.angle;
  const spread = parent.key === ROOT_KEY ? 0.32 : 0.24;
  const distance = edgeBaseLength() * (parent.key === ROOT_KEY ? 0.92 : 0.72);
  const displayTitle = item.display_title || item.wikipedia_title || item.region_name;
  const label = labelFromTitle(displayTitle);
  const node = {
    genreId: item.genre_id,
    baseGenreId: item.base_genre_id || null,
    candidateId: item.candidate_id || null,
    label,
    title: normalizeLabel(displayTitle),
    qid: null,
    color: item.similarity_color || null,
    colorConfidence: item.color_confidence ?? null,
    hasPlaylist: typeof item.has_playlist === "boolean" ? item.has_playlist : item.hasPlaylist,
    summary: item.genre_id
      ? null
      : `A proposed regional style variation of ${parent.label}.`,
    wikipedia_url: null,
    aliases: [],
    origins: [],
    monthlyViews: item.monthly_views_p30,
    regionName: item.region_name || null,
    regionId: item.region_id || null,
    regionKind: item.region_kind || null,
    matchedRegionId: item.matched_region_id || null,
    matchedRegionName: item.matched_region_name || null,
    matchedRegionKind: item.matched_region_kind || null,
    mountParentRegionId: item.mount_parent_region_id || null,
    representedGenreIds: item.represented_genre_ids || [],
    representedTitles: item.represented_titles || [],
    mapChildren: item.represented_children || [],
    mapKey: item.map_key || activeMapKey || "world",
    mapRole: item.role || item.match_type || "region",
    relation: item.match_type || "regional_variant",
    relations: [item.match_type || "regional_variant"],
    isUnresolved: false,
    isMapChild: true,
    isSyntheticRegionalVariant: !item.genre_id,
    key,
    angle,
    sliceStart: angle - spread / 2,
    sliceEnd: angle + spread / 2,
    depth: parent.depth + 1,
    parentKey: parent.key,
    siblingIndex: existingSiblingCount,
    siblingTotal: existingSiblingCount + 1,
    isExpanded: false,
    childCount: null,
    isFaded: false,
    isTrimming: false,
    isRevealed: true,
    distance: parent.distance + distance,
    homeX: parent.homeX + Math.cos(angle) * distance,
    homeY: parent.homeY + Math.sin(angle) * distance,
    x: parent.x + Math.cos(angle) * 28,
    y: parent.y + Math.sin(angle) * 28,
    vx: Math.cos(angle) * 0.6,
    vy: Math.sin(angle) * 0.6,
  };

  nodes.set(key, node);
  edges.push({
    from: parent.key,
    to: key,
    relation: item.match_type || "regional_variant",
    isUnresolved: false,
    isTrimming: false,
  });
  parent.isExpanded = true;
  parent.childCount = (parent.childCount || existingSiblingCount) + 1;
  return node;
}

async function selectMapVariant(item) {
  allowDetailCardForManualSelection();
  if (cloudMode && item?.genre_id) {
    openRegionalCloud(item);
    return;
  }
  mapDisplayedWorldOverride = false;
  const focused = nodes.get(currentKey) || nodes.get(ROOT_KEY);
  const parent = mapMountParentForItem(item, focused);
  if (!parent) return;
  const existing = findVisibleGenreNode(item.genre_id, parent.key);
  const node = existing || createRegionalNode(parent, item);
  if (node) {
    node.regionName = item.region_name || node.regionName || null;
    node.color = item.similarity_color || node.color || null;
    node.colorConfidence = item.color_confidence ?? node.colorConfidence ?? null;
    const traceRows = await reachableParentTraceRows(node);
    precomputeSelectedTraceDistance(node, traceRows);
  }
  recomputeLayout();
  fullRender();
  rebuildSim();
  bumpSim(0.55);
  await focusOn(node.key);
}

function renderMapContext(node, context, selectedNode = node, options = {}) {
  mapContextOwnerKey = node?.key || null;
  const allItems = context.selectable_regions || context.items || [];
  const items = selectableMapItems(allItems);
  const highlights = context.context_highlights || [];
  const selectedRegion = context.selected_region || null;
  setMapListButtonVisible(items.length > 0);
  const parentInfo = cloudMapParentInfoForContext(context, selectedNode) || mapParentInfoForNode(selectedNode);
  setMapParentLabel(parentInfo.label, parentInfo.targetKey, { cloud: parentInfo.cloud });
  setMapDefaultLabel(mapVariationLabel(selectedNode, items, context), mapVariationCount(items));
  setMapWorldButtonVisible((context.active_map || "world") !== "world" && !context.is_world_override);
  mapPoints.innerHTML = "";
  if (mapList) mapList.innerHTML = "";
  rebuildMapHoverGroups(items);
  const fitHighlights = inferredContextCountryFeatures(selectedNode);
  const inferredHighlights = selectedRegion ? [selectedRegion] : highlights;
  const selectableFeatures = mapItemFeatureKeys(items);
  const highlightFeatures = [
    ...fitHighlights,
    ...mapItemFeatureKeys(inferredHighlights),
  ];
  const autoViewFeatures = selectableFeatures.length ? selectableFeatures : highlightFeatures;

  const nextCountryStates = new Map();
  const nextItemsByCountry = new Map();
  const nextSuperregionStates = new Map();
  const contextColor = nodeMapColor(selectedNode);
  for (const countryName of fitHighlights) {
    assignContextMapCountryState(nextCountryStates, countryName, null, contextColor);
  }
  for (const item of inferredHighlights) {
    assignContextMapCountryState(nextCountryStates, featureKeyForMapItem(item), item, contextColor);
  }
  for (const item of items) {
    assignVariantMapCountryState(nextCountryStates, nextItemsByCountry, nextSuperregionStates, item);
  }
  applyMapRenderState(nextCountryStates, nextItemsByCountry, nextSuperregionStates);
  syncMapCountryInteractivity();
  if (mapListMode) {
    setMapAutoViewFeatures(autoViewFeatures, { animate: false });
    void renderMapList(items, { rootMode: isRootMusicMapContext(context, selectedNode) });
    return;
  }
  if (options.autoView === "silent") {
    setMapAutoViewFeatures(autoViewFeatures, { animate: false });
  } else if (options.autoView !== "none") {
    updateMapAutoView(autoViewFeatures);
  }
}

async function updateMapCard(node, options = {}) {
  if (!mapCard || !node) return;
  scheduledMapCardUpdateToken++;
  const token = ++mapToken;
  const showLoading = options.loading !== false;
  const clearBeforeLoad = options.clearBeforeLoad !== false;
  if (showLoading) mapCard.classList.add("map-card-loading");
  const selectedMapChild = Boolean(node?.genreId && node.isMapChild);
  let mapNode = selectedMapChild ? node : mapSourceNodeFor(node);
  setMapParentLabel("");
  setMapDefaultLabel("");
  if (clearBeforeLoad) {
    mapPoints.innerHTML = "";
    clearCountryHighlights();
  }

  try {
    let result = null;
    if (selectedMapChild) {
      result = await getMapContext(node);
      if (token !== mapToken) return;
      if (!mapContextHasSelectableVariants(result.selectable_regions || result.items)) {
        result = null;
        mapNode = mapSourceNodeFor(node);
      }
    }

    if (node?.genreId && !node.isMapChild && node.parentKey && nodes.has(node.parentKey)) {
      const parent = nodes.get(node.parentKey);
      const parentResult = await getMapContext(parent);
      if (token !== mapToken) return;
      if ((parentResult.selectable_regions || []).some(item =>
        item.genre_id === node.genreId || (item.represented_genre_ids || []).includes(node.genreId)
      )) {
        result = parentResult;
      }
    }

    if (!result) result = await getMapContext(mapNode);
    if (token !== mapToken) return;
    if ((cloudMode || mapDisplayedWorldOverride) && (result.active_map || "world") !== "world") {
      result = worldContextFromSubmap(result, node);
    } else {
      mapDisplayedWorldOverride = false;
    }
    if (mapNode?.genreId && !mapNode.isMapChild) {
      const parentRows = await getReachableParents(mapNode.genreId).catch(() => []);
      if (token !== mapToken) return;
      mapNode.parentRelationshipRows = parentRows;
      if (node?.genreId === mapNode.genreId) node.parentRelationshipRows = parentRows;
    }
    await ensureCountryMap(result.active_map || "world");
    if (token !== mapToken) return;
    renderMapContext(mapNode, result, node, { autoView: options.autoView });
    if (showLoading) mapCard.classList.remove("map-card-loading");
  } catch (err) {
    if (token !== mapToken) return;
    console.error("[wiki-genres] regional map failed", err);
    if (showLoading) mapCard.classList.remove("map-card-loading");
    setMapListButtonVisible(false);
    clearCountryHighlights();
    updateMapAutoView([]);
  }
}

function cancelScheduledMapCardUpdate() {
  if (scheduledMapCardUpdateFrame) {
    cancelAnimationFrame(scheduledMapCardUpdateFrame);
    scheduledMapCardUpdateFrame = 0;
  }
  if (scheduledMapCardUpdateTimer) {
    clearTimeout(scheduledMapCardUpdateTimer);
    scheduledMapCardUpdateTimer = 0;
  }
  scheduledMapCardUpdateToken++;
}

function scheduleMapCardUpdate(node, { delay = MAP_DEFERRED_UPDATE_DELAY_MS } = {}) {
  if (!node) return;
  cancelScheduledMapCardUpdate();
  const token = scheduledMapCardUpdateToken;
  scheduledMapCardUpdateFrame = requestAnimationFrame(() => {
    scheduledMapCardUpdateFrame = requestAnimationFrame(() => {
      scheduledMapCardUpdateFrame = 0;
      if (token !== scheduledMapCardUpdateToken) return;
      scheduledMapCardUpdateTimer = window.setTimeout(() => {
        scheduledMapCardUpdateTimer = 0;
        if (token !== scheduledMapCardUpdateToken) return;
        void updateMapCard(node, {
          autoView: "silent",
          clearBeforeLoad: false,
          loading: false,
        });
      }, Math.max(0, Number(delay) || 0));
    });
  });
}

function placeRoot() {
  nodes.set(ROOT_KEY, {
    key: ROOT_KEY,
    genreId: null,
    label: "Music",
    title: "Music",
    qid: null,
    color: null,
    summary: "A live map of music genres from the wiki-genres graph.",
    wikipedia_url: "https://en.wikipedia.org/wiki/Music",
    aliases: [],
    origins: [],
    angle: 0,
    sliceStart: -Math.PI,
    sliceEnd: Math.PI,
    depth: 0,
    parentKey: null,
    isExpanded: false,
    childCount: null,
    isFaded: false,
    isUnresolved: false,
    distance: 0,
    homeX: 0,
    homeY: 0,
    x: 0,
    y: 0,
    fx: 0,
    fy: 0,
  });
}

function childNodeKey(parent, child, index) {
  const ref = child.genreId || `raw-${slug(child.label) || index}`;
  return `${parent.key}/${ref}-${index}`;
}

function childSortKey(child, index = 0) {
  const views = child.monthlyViews ?? child.parent_monthly_views_p30 ?? -1;
  const relation = child.relation || child.parent_relation;
  return {
    views,
    relationRank: RELATION_RANK.get(relation) ?? 99,
    label: normalizeLabel(child.label || child.parent_title || child.title).toLocaleLowerCase(),
    index,
  };
}

function compareChildItems(a, b) {
  const ak = childSortKey(a.child, a.index);
  const bk = childSortKey(b.child, b.index);
  return (
    bk.views - ak.views ||
    ak.relationRank - bk.relationRank ||
    ak.label.localeCompare(bk.label) ||
    ak.index - bk.index
  );
}

function reslotChildren(parent) {
  const childEdges = edges
    .map((edge, order) => ({ edge, order, child: nodes.get(edge.to) }))
    .filter(item =>
      item.edge.from === parent.key &&
      !item.edge.isTraceLink &&
      !item.edge.isTracePath &&
      !item.edge.isTrimming &&
      item.child &&
      !item.child.isTrimming
    )
    .sort(compareChildItems);

  const total = Math.max(1, childEdges.length);
  const fan = childFan(parent, total);
  for (let index = 0; index < childEdges.length; index++) {
    const child = childEdges[index].child;
    const cSliceStart = fan.start + (index / total) * fan.width;
    const cSliceEnd = fan.start + ((index + 1) / total) * fan.width;
    child.siblingIndex = index;
    child.siblingTotal = total;
    child.sliceStart = cSliceStart;
    child.sliceEnd = cSliceEnd;
    child.angle = (cSliceStart + cSliceEnd) / 2;
  }
}

function childFan(parent, total) {
  const inheritedWidth = parent.sliceEnd - parent.sliceStart;
  if (parent.key !== currentKey || parent.key === ROOT_KEY) {
    return {
      start: parent.sliceStart,
      width: inheritedWidth,
    };
  }

  const width = Math.min(0.78, Math.max(inheritedWidth, 0.56));
  return {
    start: parent.angle - width / 2,
    width,
  };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function angleDelta(from, to) {
  let delta = to - from;
  while (delta > Math.PI) delta -= Math.PI * 2;
  while (delta < -Math.PI) delta += Math.PI * 2;
  return delta;
}

function mixAngle(from, to, t) {
  return from + angleDelta(from, to) * t;
}

function traceAngleAllowance(child) {
  const depth = Math.max(1, child.traceDepth || child.depth || 1);
  return Math.min(0.72, PARENT_TRACE_MAX_ANGLE_STEP + Math.max(0, depth - 1) * 0.11);
}

function softenTraceApproachAngle(parent, child) {
  if (!parent || parent.key === ROOT_KEY) return;

  const current = nodes.get(currentKey);
  const desiredDelta = angleDelta(parent.angle, child.angle);
  const selectedAngle = current && current !== child
    ? Math.atan2(current.homeY - parent.homeY, current.homeX - parent.homeX)
    : null;
  const selectedDelta = selectedAngle === null ? desiredDelta : angleDelta(parent.angle, selectedAngle);
  const nextDelta = desiredDelta * 0.45 + selectedDelta * 0.55;
  const allowance = traceAngleAllowance(child);
  const limitedDelta = clamp(
    nextDelta,
    -allowance,
    allowance
  );
  child.angle = parent.angle + limitedDelta;

  const halfWidth = Math.max(0.08, Math.min(0.28, (child.sliceEnd - child.sliceStart) / 2));
  child.sliceStart = child.angle - halfWidth;
  child.sliceEnd = child.angle + halfWidth;
}

function tracePathSegmentLength(parent, child, baseLen) {
  return baseLen * PARENT_TRACE_SEGMENT_SCALE;
}

function traceSegmentLengthBoost(edge, baseLen) {
  if (!edge?.layoutTraceSegmentBoost) return 0;
  return Math.min(
    baseLen * TRACE_LAYOUT_PRESSURE_LENGTH_MAX_RATIO,
    edge.layoutTraceSegmentBoost * TRACE_LAYOUT_PRESSURE_LENGTH_GAIN
  );
}

function isTraceGraphNode(node) {
  return Boolean(node?.isTraceOnly || node?.isTracePathNode || node?.isTraceParent);
}

function projectedBoxRadius(box, ux, uy) {
  return Math.abs(ux) * box.w / 2 + Math.abs(uy) * box.h / 2;
}

function traceLineAvoidance(parent, child, length) {
  if (!parent || !child) return { length, bend: 0 };

  const ux = Math.cos(child.angle);
  const uy = Math.sin(child.angle);
  const px = -uy;
  const py = ux;
  const candidateLengths = [
    length,
    length * 0.62,
    length * 0.76,
    length * 0.88,
    length + TRACE_LINE_MAX_LENGTHEN * 0.18,
    length + TRACE_LINE_MAX_LENGTHEN * 0.36,
    length + TRACE_LINE_MAX_LENGTHEN * 0.62,
    length + TRACE_LINE_MAX_LENGTHEN,
  ];
  const minLength = Math.max(edgeBaseLength() * 0.18, length * 0.52);
  let best = { length, bendPressure: 0, score: Number.POSITIVE_INFINITY };

  for (const candidate of candidateLengths) {
    const candidateLength = clamp(candidate, minLength, length + TRACE_LINE_MAX_LENGTHEN);
    let bendPressure = 0;
    let pressureScore = 0;

    for (const node of nodes.values()) {
      if (
        node.key === parent.key ||
        node.key === child.key ||
        isTraceGraphNode(node) ||
        node.isTrimming ||
        node.isRevealed === false
      ) {
        continue;
      }

      const dx = node.homeX - parent.homeX;
      const dy = node.homeY - parent.homeY;
      const along = dx * ux + dy * uy;
      if (along <= 20 || along >= candidateLength - 20) continue;

      const lateral = dx * px + dy * py;
      const box = nodeBox(node, TRACE_LINE_CLEARANCE, TRACE_LINE_CLEARANCE, false);
      const lateralLimit = projectedBoxRadius(box, px, py);
      if (Math.abs(lateral) > lateralLimit) continue;

      const depth = lateralLimit - Math.abs(lateral);
      const alongBias = 1 - Math.abs(along / candidateLength - 0.5) * 0.7;
      pressureScore += depth * depth * (0.75 + alongBias);
      bendPressure += (lateral >= 0 ? -1 : 1) * depth * alongBias;
    }

    const delta = candidateLength - length;
    const lengthPenalty = Math.abs(delta) * 0.9 + Math.max(0, delta) * 0.25;
    const score = pressureScore * 12 + lengthPenalty;
    if (score < best.score) {
      best = { length: candidateLength, bendPressure, score };
    }
  }

  return {
    length: best.length,
    bend: clamp(best.bendPressure / Math.max(80, best.length), -TRACE_LINE_MAX_BEND, TRACE_LINE_MAX_BEND),
  };
}

function traceLinkMinLength(parent, selected, baseLen) {
  const parentBox = nodeBox(parent, 24, 14, false);
  const selectedBox = nodeBox(selected, 26, 16, false);
  return Math.max(
    baseLen * TRACE_PARENT_LINK_SCALE,
    (parentBox.w + selectedBox.w) * 0.52 + baseLen * 0.48
  );
}

function traceLinkHomeAdjustment(parent, selected, minLength) {
  let dx = parent.homeX - selected.homeX;
  let dy = parent.homeY - selected.homeY;
  let len = Math.hypot(dx, dy);
  if (len < 1) {
    dx = Math.cos(parent.angle || 0);
    dy = Math.sin(parent.angle || 0);
    len = 1;
  }

  const ux = dx / len;
  const uy = dy / len;
  const px = -uy;
  const py = ux;
  let lengthen = Math.max(0, minLength - len);
  let sidePush = 0;

  for (const node of nodes.values()) {
    if (
      node.key === parent.key ||
      node.key === selected.key ||
      node.isTrimming ||
      node.isRevealed === false
    ) {
      continue;
    }

    const nx = node.homeX - selected.homeX;
    const ny = node.homeY - selected.homeY;
    const along = nx * ux + ny * uy;
    if (along <= 20 || along >= len - 20) continue;

    const lateral = nx * px + ny * py;
    const box = nodeBox(node, TRACE_LINE_CLEARANCE + 8, TRACE_LINE_CLEARANCE + 8, false);
    const limit = projectedBoxRadius(box, px, py);
    const overlap = limit - Math.abs(lateral);
    if (overlap <= 0) continue;

    const centered = 1 - Math.abs(along / len - 0.5);
    lengthen = Math.max(lengthen, overlap * (2.3 + centered));
    sidePush += (lateral >= 0 ? -1 : 1) * overlap * (0.42 + centered * 0.34);
  }

  const steps = Math.max(1, parent.traceDepth || parent.depth || 1);
  const maxSide = Math.min(180, 26 + steps * 24);
  return {
    dx: ux * Math.min(TRACE_LINE_MAX_LENGTHEN, lengthen) + px * clamp(sidePush, -maxSide, maxSide),
    dy: uy * Math.min(TRACE_LINE_MAX_LENGTHEN, lengthen) + py * clamp(sidePush, -maxSide, maxSide),
  };
}

function radiusForTraceLinkMinDistance(angle, selected, minLength, currentRadius) {
  const ux = Math.cos(angle);
  const uy = Math.sin(angle);
  const selectedDist2 = selected.homeX * selected.homeX + selected.homeY * selected.homeY;
  const selectedDot = selected.homeX * ux + selected.homeY * uy;
  const discriminant = minLength * minLength - selectedDist2 + selectedDot * selectedDot;
  if (discriminant <= 0) return currentRadius;
  return Math.max(currentRadius, selectedDot + Math.sqrt(discriminant));
}

function adjustTraceParentLinks(baseLen) {
  for (const edge of edges) {
    if (!edge.isTraceLink || edge.isTrimming) continue;

    const parent = nodes.get(edge.from);
    const selected = nodes.get(edge.to);
    if (!parent || !selected || parent.isTrimming || selected.isTrimming) continue;
    if (selected.key !== primaryTraceTargetNode()?.key) continue;

    const minLength = traceLinkMinLength(parent, selected, baseLen);
    const adjustment = traceLinkHomeAdjustment(parent, selected, minLength);
    if (!adjustment.dx && !adjustment.dy) continue;

    parent.homeX += adjustment.dx;
    parent.homeY += adjustment.dy;
    parent.angle = Math.atan2(parent.homeY, parent.homeX);
    parent.distance = Math.hypot(parent.homeX, parent.homeY);
  }
}

function activeRootChild() {
  let node = nodes.get(currentKey);
  let rootChild = null;
  while (node) {
    if (node.parentKey === ROOT_KEY) rootChild = node;
    node = node.parentKey ? nodes.get(node.parentKey) : null;
  }
  return rootChild;
}

function tracePathToRoot(parent) {
  const path = [];
  const seen = new Set();
  let node = parent;
  while (node && node.key !== ROOT_KEY && !seen.has(node.key)) {
    seen.add(node.key);
    path.unshift(node);
    node = node.parentKey ? nodes.get(node.parentKey) : null;
  }
  return path;
}

function primaryTraceTargetNode() {
  return (activeLeafKey && nodes.get(activeLeafKey)) || nodes.get(currentKey);
}

function activeTraceTargetKeys() {
  const targets = new Set([currentKey]);
  if (activeLeafKey) targets.add(activeLeafKey);
  return targets;
}

function traceLinkPaths(selected = primaryTraceTargetNode()) {
  if (!selected) return [];

  return edges
    .filter(edge => edge.isTraceLink && !edge.isTrimming && edge.to === selected.key)
    .map(edge => {
      const parent = nodes.get(edge.from);
      const nodesInPath = tracePathToRoot(parent);
      return parent && nodesInPath.length
        ? { edge, parent, nodes: nodesInPath, first: nodesInPath[0] }
        : null;
    })
    .filter(Boolean);
}

function originalRootSlotAngle(node) {
  if (!node || node.parentKey !== ROOT_KEY) return node?.angle ?? 0;
  const total = Math.max(1, node.siblingTotal || 1);
  const index = clamp(node.siblingIndex ?? 0, 0, total - 1);
  return -Math.PI + ((index + 0.5) / total) * Math.PI * 2;
}

function traceSideGroups(groups, centerAngle) {
  const sideGroups = { positive: [], negative: [] };
  for (const group of groups) {
    const sourceAngle = originalRootSlotAngle(group.first);
    const delta = angleDelta(centerAngle, sourceAngle);
    const side = delta >= 0 ? "positive" : "negative";
    sideGroups[side].push({ ...group, sourceDelta: delta });
  }

  for (const side of [sideGroups.positive, sideGroups.negative]) {
    side.sort((a, b) => (
      a.minSteps - b.minSteps ||
      Math.abs(a.sourceDelta) - Math.abs(b.sourceDelta) ||
      a.first.label.localeCompare(b.first.label)
    ));
  }

  return sideGroups;
}

function traceGroupAverageSteps(group) {
  if (!group?.paths?.length) return group?.minSteps ?? 1;
  return group.paths.reduce((sum, path) => sum + path.nodes.length, 0) / group.paths.length;
}

function setNodeHomePolar(node, angle, radius) {
  node.angle = angle;
  node.homeX = Math.cos(angle) * radius;
  node.homeY = Math.sin(angle) * radius;
  node.distance = radius;
}

function placeTraceRootNodes(paths, selected, root, baseLen) {
  const activeRoot = activeRootChild();
  const centerAngle = activeRoot
    ? activeRoot.angle
    : Math.atan2(selected.homeY - root.homeY, selected.homeX - root.homeX);
  const groups = new Map();

  for (const path of paths) {
    const key = path.first.key;
    const group = groups.get(key) || {
      first: path.first,
      paths: [],
      minSteps: Number.POSITIVE_INFINITY,
      maxSteps: 0,
    };
    group.paths.push(path);
    group.minSteps = Math.min(group.minSteps, path.nodes.length);
    group.maxSteps = Math.max(group.maxSteps, path.nodes.length);
    groups.set(key, group);
  }

  const traceGroups = [...groups.values()]
    .filter(group => group.first.key !== activeRoot?.key);
  const sideGroups = traceSideGroups(traceGroups, centerAngle);

  for (const [side, sideSign] of [[sideGroups.positive, 1], [sideGroups.negative, -1]]) {
    const step = (TRACE_ROOT_HALF_ARC - TRACE_ROOT_CENTER_GAP) / Math.max(1.35, side.length + 0.75);
    for (let i = 0; i < side.length; i++) {
      const group = side[i];
      const first = group.first;
      const rank = i + 1;
      const bothShortAndLong = group.maxSteps > group.minSteps;
      const position = bothShortAndLong ? rank - 0.5 : rank;
      const offset = TRACE_ROOT_CENTER_GAP + step * position;
      const desiredAngle = centerAngle + sideSign * Math.min(TRACE_ROOT_HALF_ARC, offset);
      const averageSteps = traceGroupAverageSteps(group);
      const desiredRadius = baseLen * (
        0.82 +
        Math.min(0.14, Math.max(0, averageSteps - 1) * 0.018) +
        Math.min(0.09, offset / TRACE_ROOT_HALF_ARC * 0.09)
      );
      const currentAngle = Math.atan2(first.homeY, first.homeX);
      const currentRadius = Math.max(baseLen * 0.72, Math.hypot(first.homeX, first.homeY));
      const angle = desiredAngle;
      const radius = currentRadius + (desiredRadius - currentRadius) * 0.28;
      setNodeHomePolar(first, angle, radius);
      first.sliceStart = angle - 0.16;
      first.sliceEnd = angle + 0.16;
    }
  }

  return centerAngle;
}

function pointToSegmentPressure(point, a, b) {
  const vx = b.x - a.x;
  const vy = b.y - a.y;
  const len = Math.hypot(vx, vy);
  if (len < 1) return 0;
  const ux = vx / len;
  const uy = vy / len;
  const px = -uy;
  const py = ux;
  const dx = point.x - a.x;
  const dy = point.y - a.y;
  const along = dx * ux + dy * uy;
  if (along <= 20 || along >= len - 20) return 0;
  const lateral = dx * px + dy * py;
  const box = collisionBox(point.node, TRACE_LINE_CLEARANCE, TRACE_LINE_CLEARANCE);
  const limit = projectedBoxRadius(box, px, py);
  return Math.max(0, limit - Math.abs(lateral));
}

function traceArcHeight(start, end, pathNodes, baseLen) {
  let pressure = 0;
  const a = { x: start.x, y: start.y };
  const b = { x: end.x, y: end.y };

  for (const node of nodes.values()) {
    if (
      pathNodes.includes(node) ||
      node.key === currentKey ||
      isTraceGraphNode(node) ||
      node.isTrimming ||
      node.isRevealed === false
    ) {
      continue;
    }
    pressure = Math.max(pressure, pointToSegmentPressure({ node, x: node.homeX, y: node.homeY }, a, b));
  }

  return Math.min(
    baseLen * 0.85,
    baseLen * 0.10 + pressure * 1.6
  );
}

function quadraticPoint(p0, c, p1, t) {
  const mt = 1 - t;
  return {
    x: mt * mt * p0.x + 2 * mt * t * c.x + t * t * p1.x,
    y: mt * mt * p0.y + 2 * mt * t * c.y + t * t * p1.y,
  };
}

function quadraticSamples(start, control, end, steps = 72) {
  const samples = [{ ...start, t: 0, length: 0 }];
  let total = 0;
  let prev = samples[0];
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const point = quadraticPoint(start, control, end, t);
    total += Math.hypot(point.x - prev.x, point.y - prev.y);
    samples.push({ ...point, t, length: total });
    prev = point;
  }
  return { samples, total };
}

function pointAtCurveDistance(curve, distance) {
  const target = clamp(distance, 0, curve.total);
  for (let i = 1; i < curve.samples.length; i++) {
    const prev = curve.samples[i - 1];
    const next = curve.samples[i];
    if (next.length < target) continue;
    const span = Math.max(1, next.length - prev.length);
    const t = (target - prev.length) / span;
    return {
      x: prev.x + (next.x - prev.x) * t,
      y: prev.y + (next.y - prev.y) * t,
      t: prev.t + (next.t - prev.t) * t,
    };
  }
  return curve.samples.at(-1);
}

function traceIntermediateMinLength(baseLen) {
  return baseLen * TRACE_INTERMEDIATE_LINK_SCALE;
}

function tracePathLaneOffsets(paths, selected, baseLen) {
  const centerAngle = Math.atan2(selected.homeY, selected.homeX);
  const groups = { positive: [], negative: [] };

  for (const path of paths) {
    const firstAngle = Math.atan2(path.first.homeY, path.first.homeX);
    const side = angleDelta(centerAngle, firstAngle) >= 0 ? "positive" : "negative";
    groups[side].push(path);
  }

  const offsets = new Map();
  const spread = Math.min(34, baseLen * 0.12);
  for (const [side, sideSign] of [[groups.positive, 1], [groups.negative, -1]]) {
    side.sort((a, b) => (
      a.nodes.length - b.nodes.length ||
      a.first.angle - b.first.angle ||
      a.parent.label.localeCompare(b.parent.label)
    ));
    const maxDepth = Math.max(1, ...side.map(path => path.nodes.length));
    for (let i = 0; i < side.length; i++) {
      const laneT = side.length <= 1 ? 0 : i / (side.length - 1);
      const innerT = Math.pow(laneT, 0.82);
      offsets.set(graphEdgeKey(side[i].edge), {
        offset: sideSign * innerT * spread * Math.max(0, side.length - 1),
        rank: i,
        count: side.length,
        sideSign,
        laneT,
        innerT,
        depthT: Math.max(0, (side[i].nodes.length - 1) / Math.max(1, maxDepth - 1)),
      });
    }
  }

  return offsets;
}

function tracePathPressure(path) {
  return Math.max(
    path.edge?.layoutTraceBoost || 0,
    path.edge?.layoutTraceSegmentBoost || 0,
    ...tracePathSegmentEdges(path).map(edge => edge?.layoutTraceSegmentBoost || 0),
    ...path.nodes.map(node => node.layoutTraceBoost || 0)
  );
}

function tracePathEdgeBetween(from, to) {
  if (!from || !to) return null;
  return edges.find(edge =>
    edge.isTracePath &&
    !edge.isTrimming &&
    edge.from === from.key &&
    edge.to === to.key &&
    hasCurrentTraceAnchor(edge)
  ) || null;
}

function tracePathSegmentEdges(path) {
  const segmentEdges = [];
  for (let i = 1; i < path.nodes.length; i++) {
    segmentEdges.push(tracePathEdgeBetween(path.nodes[i - 1], path.nodes[i]));
  }
  segmentEdges.push(path.edge || null);
  return segmentEdges;
}

function sortedTracePaths(paths) {
  return [...paths].sort((a, b) => (
    a.nodes.length - b.nodes.length ||
    (a.edge?.traceSteps ?? a.nodes.length) - (b.edge?.traceSteps ?? b.nodes.length) ||
    a.first.label.localeCompare(b.first.label) ||
    a.parent.label.localeCompare(b.parent.label)
  ));
}

function accumulateTracePosition(acc, node, x, y, weight = 1) {
  const current = acc.get(node.key) || { node, x: 0, y: 0, weight: 0 };
  current.x += x * weight;
  current.y += y * weight;
  current.weight += weight;
  acc.set(node.key, current);
}

function traceCandidateBox(node, x, y, extraX = 16, extraY = 10) {
  const box = collisionBox(node, extraX, extraY);
  return { node, x, y, w: box.w, h: box.h };
}

function boxOverlapAmount(a, b) {
  const overlapX = (a.w + b.w) / 2 - Math.abs(a.x - b.x);
  const overlapY = (a.h + b.h) / 2 - Math.abs(a.y - b.y);
  return overlapX > 0 && overlapY > 0 ? Math.min(overlapX, overlapY) : 0;
}

function candidatePointToSegmentPressure(point, segment, clearance = NODE_LINE_CLEARANCE) {
  const vx = segment.bx - segment.ax;
  const vy = segment.by - segment.ay;
  const len = Math.hypot(vx, vy);
  if (len < 1) return 0;

  const ux = vx / len;
  const uy = vy / len;
  const px = -uy;
  const py = ux;
  const dx = point.x - segment.ax;
  const dy = point.y - segment.ay;
  const along = dx * ux + dy * uy;
  if (along <= 20 || along >= len - 20) return 0;

  const lateral = dx * px + dy * py;
  const box = traceCandidateBox(point.node, point.x, point.y, TRACE_LINE_CLEARANCE, TRACE_LINE_CLEARANCE);
  const limit = projectedBoxRadius(box, px, py) + clearance;
  return Math.max(0, limit - Math.abs(lateral));
}

function candidateSegmentsForPath(first, selected, placedPoints) {
  const ordered = [
    { node: first, x: first.homeX, y: first.homeY },
    ...placedPoints,
    { node: selected, x: selected.homeX, y: selected.homeY },
  ];
  const segments = [];
  for (let i = 1; i < ordered.length; i++) {
    const from = ordered[i - 1];
    const to = ordered[i];
    segments.push({
      from: from.node,
      to: to.node,
      ax: from.x,
      ay: from.y,
      bx: to.x,
      by: to.y,
    });
  }
  return segments;
}

function segmentsShareNode(a, b) {
  return (
    a.from.key === b.from.key ||
    a.from.key === b.to.key ||
    a.to.key === b.from.key ||
    a.to.key === b.to.key
  );
}

function candidateSegmentPressure(a, b) {
  if (segmentsShareNode(a, b)) return 0;
  const minDistance = Math.min(
    pointSegmentDistance(a.ax, a.ay, b.ax, b.ay, b.bx, b.by),
    pointSegmentDistance(a.bx, a.by, b.ax, b.ay, b.bx, b.by),
    pointSegmentDistance(b.ax, b.ay, a.ax, a.ay, a.bx, a.by),
    pointSegmentDistance(b.bx, b.by, a.ax, a.ay, a.bx, a.by)
  );
  const clearance = TRACE_LINE_CLEARANCE * 1.45;
  return homeSegmentsIntersect(a, b)
    ? clearance * 1.6
    : Math.max(0, clearance - minDistance);
}

function staticTraceObstacles(pathNodes) {
  const pathKeys = new Set(pathNodes.map(node => node.key));
  pathKeys.add(ROOT_KEY);
  pathKeys.add(currentKey);
  if (activeLeafKey) pathKeys.add(activeLeafKey);
  return [...nodes.values()]
    .filter(node =>
      !pathKeys.has(node.key) &&
      !node.isTrimming &&
      node.isRevealed !== false &&
      !isTraceGraphNode(node)
    )
    .map(node => traceCandidateBox(node, node.homeX, node.homeY, 18, 10));
}

function staticTraceSegments(pathNodes) {
  const pathKeys = new Set(pathNodes.map(node => node.key));
  pathKeys.add(currentKey);
  if (activeLeafKey) pathKeys.add(activeLeafKey);
  return edges
    .filter(edge =>
      isVisibleLineEdge(edge) &&
      !edge.isTracePath &&
      !edge.isTraceLink &&
      !pathKeys.has(edge.from) &&
      !pathKeys.has(edge.to)
    )
    .map(edge => {
      const from = nodes.get(edge.from);
      const to = nodes.get(edge.to);
      return from && to
        ? { from, to, ax: from.homeX, ay: from.homeY, bx: to.homeX, by: to.homeY }
        : null;
    })
    .filter(Boolean);
}

function scoreTraceCandidate(points, segments, obstacles, placedSegments, selfSegments, arc, curveOverrun = 0) {
  let score = Math.abs(arc) * 0.05 + curveOverrun * 0.22;

  for (const point of points) {
    const box = traceCandidateBox(point.node, point.x, point.y, 18, 12);
    for (const obstacle of obstacles) {
      const overlap = boxOverlapAmount(box, obstacle);
      if (overlap > 0) {
        const weight = obstacle.isTraceObstacle ? 0.9 : 8;
        score += overlap * overlap * weight;
      }
    }

    for (const segment of [...placedSegments, ...selfSegments]) {
      if (segment.from.key === point.node.key || segment.to.key === point.node.key) continue;
      const pressure = candidatePointToSegmentPressure(point, segment, NODE_LINE_CLEARANCE * 1.15);
      if (pressure > 0) score += pressure * pressure * 24;
    }
  }

  for (const segment of segments) {
    for (const placed of placedSegments) {
      const pressure = candidateSegmentPressure(segment, placed);
      if (pressure > 0) score += pressure * pressure * 14;
    }
  }

  return score;
}

function placeTraceIntermediateNodes(paths, selected, baseLen) {
  const positions = new Map();
  const orderedPaths = sortedTracePaths(paths);
  const laneOffsets = tracePathLaneOffsets(orderedPaths, selected, baseLen);
  const placedTraceObstacles = [];
  const placedTraceSegments = [];

  for (const path of orderedPaths) {
    const pathNodes = path.nodes;
    if (pathNodes.length <= 1) {
      continue;
    }

    const first = pathNodes[0];
    const start = { x: first.homeX, y: first.homeY };
    const end = { x: selected.homeX, y: selected.homeY };
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const lineLen = Math.max(1, Math.hypot(dx, dy));
    const ux = dx / lineLen;
    const uy = dy / lineLen;
    let nx = -uy;
    let ny = ux;
    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    if (Math.hypot(midX + nx * 80, midY + ny * 80) < Math.hypot(midX - nx * 80, midY - ny * 80)) {
      nx *= -1;
      ny *= -1;
    }

    const lane = laneOffsets.get(graphEdgeKey(path.edge)) || {
      offset: 0,
      rank: 0,
      count: 1,
      sideSign: 1,
    };
    const tracePressure = tracePathPressure(path);
    const segmentCount = pathNodes.length;
    const bundleT = Math.max(lane.innerT || 0, (lane.depthT || 0) * 0.54);
    const progressiveArc = Math.max(0, segmentCount - 1) * baseLen * TRACE_PROGRESSIVE_ARC_GAIN * 0.42;
    const baseArc =
      traceArcHeight(start, end, pathNodes, baseLen) * 0.42 +
      baseLen * (0.14 + bundleT * 0.54) +
      progressiveArc +
      tracePressure * TRACE_LAYOUT_PRESSURE_ARC_GAIN * (0.18 + bundleT * 0.38);

    const obstacles = [
      ...staticTraceObstacles(pathNodes),
    ];
    const fixedSegments = [
      ...staticTraceSegments(pathNodes),
    ];
    let best = null;
    const previousArc =
      path.edge?.layoutTraceArcTarget === selected.key && Number.isFinite(path.edge?.layoutTraceArc)
        ? path.edge.layoutTraceArc
        : null;
    const arcSteps = [];
    for (let step = -0.32; step <= 1.201; step += 0.08) {
      arcSteps.push(Number(step.toFixed(2)));
    }

    for (const step of arcSteps) {
      const minArc = baseLen * 0.10;
      const maxArc = baseLen * (0.82 + bundleT * 1.18);
      const arc = clamp(baseArc + step * baseLen, minArc, maxArc);
      const control = { x: midX + nx * arc, y: midY + ny * arc };
      const curve = quadraticSamples(start, control, end);
      const points = [];

      for (let i = 1; i < pathNodes.length; i++) {
        const existing = positions.get(pathNodes[i].key);
        if (existing) {
          points.push({
            node: pathNodes[i],
            x: existing.x / existing.weight,
            y: existing.y / existing.weight,
          });
          continue;
        }
        const point = pointAtCurveDistance(curve, curve.total * (i / segmentCount));
        const laneScale = Math.min(1, 0.10 + point.t * 0.72);
        points.push({
          node: pathNodes[i],
          x: point.x + nx * (lane.offset * laneScale),
          y: point.y + ny * (lane.offset * laneScale),
        });
      }

      const candidateSegments = candidateSegmentsForPath(first, selected, points);
      const curveOverrun = Math.max(0, curve.total - lineLen);
      let score = scoreTraceCandidate(
        points,
        candidateSegments,
        obstacles,
        fixedSegments,
        candidateSegments,
        arc,
        curveOverrun
      );
      for (const point of points) {
        const box = traceCandidateBox(point.node, point.x, point.y, 18, 12);
        for (const obstacle of placedTraceObstacles) {
          const overlap = boxOverlapAmount(box, obstacle);
          if (overlap > 0) {
            score += overlap * overlap * 0.28;
          }
        }
      }
      for (const segment of candidateSegments) {
        for (const placed of placedTraceSegments) {
          const pressure = candidateSegmentPressure(segment, placed);
          if (pressure > 0) {
            score += pressure * pressure * 0.24;
          }
        }
      }
      if (previousArc !== null) {
        const arcShift = Math.abs(arc - previousArc);
        const arcContinuity = Math.min(1.8, arcShift / Math.max(1, baseLen));
        score += arcContinuity * arcContinuity * baseLen * 1.15;
      }
      if (!best || score < best.score) {
        best = { score, points, segments: candidateSegments, arc };
      }
      if (score < 0.5) break;
    }

    if (!best) continue;
    if (path.edge) {
      path.edge.layoutTraceArc = best.arc;
      path.edge.layoutTraceArcTarget = selected.key;
    }

    for (const point of best.points) {
      accumulateTracePosition(positions, point.node, point.x, point.y, 1);
      placedTraceObstacles.push({
        ...traceCandidateBox(point.node, point.x, point.y, 18, 12),
        isTraceObstacle: true,
      });
    }
    placedTraceSegments.push(...best.segments);
  }

  for (const { node, x, y, weight } of positions.values()) {
    node.homeX = x / weight;
    node.homeY = y / weight;
    node.angle = Math.atan2(node.homeY, node.homeX);
    node.distance = Math.hypot(node.homeX, node.homeY);
  }
}

function selectedFrontAngle(selected, root) {
  const parent = selected.parentKey ? nodes.get(selected.parentKey) : null;
  const origin = parent || root;
  let dx = selected.homeX - (origin?.homeX ?? 0);
  let dy = selected.homeY - (origin?.homeY ?? 0);
  if (Math.hypot(dx, dy) < 1) {
    dx = Math.cos(selected.angle || 0);
    dy = Math.sin(selected.angle || 0);
  }
  return Math.atan2(dy, dx);
}

function keepTraceParentsOffSelectedFront(paths, selected, root, baseLen) {
  const frontAngle = selectedFrontAngle(selected, root);
  const frontParents = { positive: [], negative: [] };

  for (const path of paths) {
    const parent = path.parent;
    if (!parent || parent.key === ROOT_KEY || parent.key === selected.parentKey) continue;

    let dx = parent.homeX - selected.homeX;
    let dy = parent.homeY - selected.homeY;
    let dist = Math.hypot(dx, dy);
    if (dist < 1) {
      dx = Math.cos(parent.angle || frontAngle + Math.PI);
      dy = Math.sin(parent.angle || frontAngle + Math.PI);
      dist = 1;
    }

    const delta = angleDelta(frontAngle, Math.atan2(dy, dx));
    if (Math.abs(delta) >= Math.PI / 2) continue;

    const sourceDelta = angleDelta(frontAngle, path.first.angle || parent.angle || 0);
    const sideSign = delta || sourceDelta || 1;
    const side = sideSign >= 0 ? "positive" : "negative";
    frontParents[side].push({ path, parent, dist });
  }

  for (const [sideItems, sideSign] of [[frontParents.positive, 1], [frontParents.negative, -1]]) {
    sideItems.sort((a, b) => (
      a.path.nodes.length - b.path.nodes.length ||
      a.parent.label.localeCompare(b.parent.label)
    ));

    for (let i = 0; i < sideItems.length; i++) {
      const { parent, dist } = sideItems[i];
      const offset = Math.min(Math.PI * 0.34, i * 0.10);
      const angle = frontAngle + sideSign * (Math.PI * 0.56 + offset);
      const radius = Math.max(dist, baseLen * 0.62);
      parent.homeX = selected.homeX + Math.cos(angle) * radius;
      parent.homeY = selected.homeY + Math.sin(angle) * radius;
      parent.angle = Math.atan2(parent.homeY, parent.homeX);
      parent.distance = Math.hypot(parent.homeX, parent.homeY);
    }
  }
}

function spreadTraceSameSideConnections(baseLen) {
  const outgoing = new Map();
  const incomingSelected = [];
  const activeTargets = activeTraceTargetKeys();

  for (const edge of edges) {
    if ((!edge.isTracePath && !edge.isTraceLink) || edge.isTrimming) continue;
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to || from.isTrimming || to.isTrimming) continue;

    if (edge.isTraceLink && activeTargets.has(to.key)) {
      incomingSelected.push({ edge, node: from, selected: to });
      continue;
    }

    if (!edge.isTracePath || from.key === ROOT_KEY) continue;
    const list = outgoing.get(from.key) || [];
    list.push({ edge, from, node: to });
    outgoing.set(from.key, list);
  }

  const spreadGroup = (items, origin, moveTarget) => {
    const bySide = { positive: [], negative: [] };
    for (const item of items) {
      const node = moveTarget(item);
      const angle = Math.atan2(node.homeY - origin.homeY, node.homeX - origin.homeX);
      const side = angleDelta(origin.angle || 0, angle) >= 0 ? "positive" : "negative";
      bySide[side].push({ ...item, angle });
    }

    for (const sideItems of [bySide.positive, bySide.negative]) {
      if (sideItems.length <= 1) continue;
      sideItems.sort((a, b) => a.angle - b.angle);
      const mid = (sideItems.length - 1) / 2;
      const spread = Math.min(34, baseLen * 0.10);
      for (let i = 0; i < sideItems.length; i++) {
        const item = sideItems[i];
        const node = moveTarget(item);
        if (!node || node.key === ROOT_KEY || activeTargets.has(node.key)) continue;
        const dx = node.homeX - origin.homeX;
        const dy = node.homeY - origin.homeY;
        const len = Math.hypot(dx, dy);
        if (len < 1) continue;
        const px = -dy / len;
        const py = dx / len;
        const offset = (i - mid) * spread;
        node.homeX += px * offset;
        node.homeY += py * offset;
        node.angle = Math.atan2(node.homeY, node.homeX);
        node.distance = Math.hypot(node.homeX, node.homeY);
      }
    }
  };

  for (const items of outgoing.values()) {
    spreadGroup(items, items[0].from, item => item.node);
  }

  if (incomingSelected.length > 1) {
    spreadGroup(incomingSelected, incomingSelected[0].selected, item => item.node);
  }
}

function tuckTraceChildrenNearLinkedParents(baseLen) {
  const selected = nodes.get(currentKey);
  if (!selected) return;

  const directTraceParents = new Set(
    edges
      .filter(edge => edge.isTraceLink && !edge.isTrimming && edge.to === selected.key)
      .map(edge => edge.from)
  );
  if (!directTraceParents.size) return;

  const byParent = new Map();
  for (const edge of edges) {
    if (!edge.isTracePath || edge.isTrimming) continue;
    if (!directTraceParents.has(edge.from) || !directTraceParents.has(edge.to)) continue;
    const parent = nodes.get(edge.from);
    const child = nodes.get(edge.to);
    if (!parent || !child || parent.isTrimming || child.isTrimming) continue;
    const children = byParent.get(parent.key) || [];
    children.push(child);
    byParent.set(parent.key, children);
  }

  for (const [parentKey, children] of byParent) {
    const parent = nodes.get(parentKey);
    if (!parent) continue;
    let dx = selected.homeX - parent.homeX;
    let dy = selected.homeY - parent.homeY;
    let len = Math.hypot(dx, dy);
    if (len < 1) {
      dx = Math.cos(parent.angle || 0);
      dy = Math.sin(parent.angle || 0);
      len = 1;
    }
    const ux = dx / len;
    const uy = dy / len;
    const px = -uy;
    const py = ux;
    const sideSign = angleDelta(parent.angle || 0, Math.atan2(dy, dx)) >= 0 ? 1 : -1;
    const mid = (children.length - 1) / 2;
    const step = Math.min(44, baseLen * 0.16);
    const along = Math.min(len * 0.52, traceIntermediateMinLength(baseLen) * 1.12);

    children
      .sort((a, b) => a.label.localeCompare(b.label))
      .forEach((child, index) => {
        const lateral = sideSign * (baseLen * 0.18 + (index - mid) * step);
        child.homeX = parent.homeX + ux * along + px * lateral;
        child.homeY = parent.homeY + uy * along + py * lateral;
        child.angle = Math.atan2(child.homeY, child.homeX);
        child.distance = Math.hypot(child.homeX, child.homeY);
      });
  }
}

function enforceTraceParentLinkLengths(paths, selected, baseLen) {
  for (const path of paths) {
    const parent = path.parent;
    const minLength = traceLinkMinLength(parent, selected, baseLen);
    const traceRootAngle = parent.parentKey === ROOT_KEY ? parent.angle : null;
    const adjustment = traceLinkHomeAdjustment(parent, selected, minLength);
    if (!adjustment.dx && !adjustment.dy) continue;
    if (traceRootAngle != null) {
      const ux = Math.cos(traceRootAngle);
      const uy = Math.sin(traceRootAngle);
      const radialPush = Math.max(0, adjustment.dx * ux + adjustment.dy * uy);
      const lateralX = adjustment.dx - ux * radialPush;
      const lateralY = adjustment.dy - uy * radialPush;
      const lateralPressure = Math.hypot(lateralX, lateralY);
      const radius = radiusForTraceLinkMinDistance(
        traceRootAngle,
        selected,
        minLength,
        parent.distance + radialPush + Math.min(baseLen * 0.25, lateralPressure * 0.22)
      );
      setNodeHomePolar(parent, traceRootAngle, radius);
      continue;
    }
    parent.homeX += adjustment.dx;
    parent.homeY += adjustment.dy;
    parent.angle = Math.atan2(parent.homeY, parent.homeX);
    parent.distance = Math.hypot(parent.homeX, parent.homeY);
  }
}

function shapeTracePathsForTarget(selected, root, baseLen) {
  if (!selected || !root) return false;
  const paths = traceLinkPaths(selected);
  if (!paths.length) return false;

  placeTraceRootNodes(paths, selected, root, baseLen);
  placeTraceIntermediateNodes(paths, selected, baseLen);
  keepTraceParentsOffSelectedFront(paths, selected, root, baseLen);
  return true;
}

function shapeAdditionalParentPaths(baseLen) {
  const root = nodes.get(ROOT_KEY);
  if (!root) return;

  let shaped = shapeTracePathsForTarget(nodes.get(currentKey), root, baseLen);
  if (activeLeafKey) {
    shaped = shapeTracePathsForTarget(nodes.get(activeLeafKey), root, baseLen) || shaped;
  }

  if (shaped) spreadTraceSameSideConnections(baseLen);
}

function focusedChildSlot(parent, child, baseLen) {
  const total = Math.max(1, child.siblingTotal || 1);
  const index = child.siblingIndex || 0;
  const slot = focusedChildGridSlot(total, index);
  const rowT = total >= 18
    ? centerOutInsetRowT(slot.row, slot.rowCount)
    : centerOutRowT(slot.row, slot.rowCount);
  const colT = slot.colCount <= 1 ? 0 : slot.col / (slot.colCount - 1);
  const wave = (slot.col % 2 ? 0.38 : 0) / Math.max(1, slot.rowCount - 1);
  const offsetT = ((rowT + wave) % 1) - 0.5;
  const inheritedWidth = Math.max(0.01, parent.sliceEnd - parent.sliceStart);
  const fan = Math.min(isCompact() ? 0.92 : 1.02, Math.max(inheritedWidth, isCompact() ? 0.68 : 0.76));
  const ringFan = total >= 18
    ? fan * (0.32 + colT * 0.68)
    : fan * (0.72 + colT * 0.24);
  const outwardAngle = focusedChildOutwardAngle(parent);
  const box = nodeBox(child, 20, 12, false);
  const columnGap = Math.max(
    isCompact() ? 58 : 70,
    Math.min(isCompact() ? 84 : 104, box.w * 0.44 + 28)
  );
  const radius =
    baseLen * (0.56 + colT * 0.06) +
    slot.col * columnGap +
    Math.abs(offsetT) * baseLen * 0.06;
  const lateralLimit = focusedChildLegacyLateralLimit(parent, total, baseLen, columnGap);
  const lateral = Math.sin(offsetT * ringFan) * radius;
  const limitedLateral = clamp(lateral, -lateralLimit, lateralLimit);
  const angle = outwardAngle + Math.asin(clamp(limitedLateral / Math.max(1, radius), -1, 1));

  return {
    angle,
    radius,
  };
}

function focusedChildLegacyLateralLimit(parent, total, baseLen, columnGap) {
  const rowCount = Math.max(1, Math.min(7, Math.ceil(Math.sqrt(total * 0.42))));
  const colCount = Math.ceil(total / rowCount);
  const inheritedWidth = Math.max(0.01, parent.sliceEnd - parent.sliceStart);
  const fan = Math.min(isCompact() ? 0.92 : 1.02, Math.max(inheritedWidth, isCompact() ? 0.68 : 0.76));
  let maxLateral = baseLen * 0.28;

  for (let index = 0; index < total; index++) {
    const row = index % rowCount;
    const col = Math.floor(index / rowCount);
    const colT = colCount <= 1 ? 0 : col / (colCount - 1);
    const rowT = centerOutRowT(row, rowCount);
    const wave = (col % 2 ? 0.38 : 0) / Math.max(1, rowCount - 1);
    const offsetT = ((rowT + wave) % 1) - 0.5;
    const ringFan = fan * (0.72 + colT * 0.24);
    const radius =
      baseLen * (0.56 + colT * 0.06) +
      col * columnGap +
      Math.abs(offsetT) * baseLen * 0.06;
    maxLateral = Math.max(maxLateral, Math.abs(Math.sin(offsetT * ringFan) * radius));
  }

  return maxLateral;
}

function focusedChildGridSlot(total, index) {
  const baseRows = Math.max(1, Math.min(7, Math.ceil(Math.sqrt(total * 0.42))));
  const colCount = Math.ceil(total / baseRows);
  if (total < 18 || colCount <= 1) {
    return {
      row: index % baseRows,
      rowCount: baseRows,
      col: Math.floor(index / baseRows),
      colCount,
    };
  }

  const weights = [];
  let weightSum = 0;
  for (let col = 0; col < colCount; col++) {
    const colT = colCount <= 1 ? 0 : col / (colCount - 1);
    const weight = 0.40 + Math.pow(colT, 1.08) * 1.26;
    weights.push(weight);
    weightSum += weight;
  }

  const capacities = weights.map(weight => Math.max(1, Math.floor((weight / weightSum) * total)));
  let assigned = capacities.reduce((sum, value) => sum + value, 0);
  const fractions = weights
    .map((weight, col) => ({
      col,
      fraction: (weight / weightSum) * total - Math.floor((weight / weightSum) * total),
    }))
    .sort((a, b) => b.fraction - a.fraction || a.col - b.col);
  for (let i = 0; assigned < total; i++, assigned++) {
    capacities[fractions[i % fractions.length].col] += 1;
  }
  for (let col = colCount - 1; assigned > total && col >= 0; col--) {
    if (capacities[col] <= 1) continue;
    capacities[col] -= 1;
    assigned--;
  }

  let start = 0;
  for (let col = 0; col < colCount; col++) {
    const next = start + capacities[col];
    if (index < next) {
      return {
        row: index - start,
        rowCount: capacities[col],
        col,
        colCount,
      };
    }
    start = next;
  }

  return {
    row: capacities[colCount - 1] - 1,
    rowCount: capacities[colCount - 1],
    col: colCount - 1,
    colCount,
  };
}

function focusedChildOutwardAngle(parent) {
  const origin = parent?.parentKey ? nodes.get(parent.parentKey) : null;
  if (origin) {
    const dx = parent.homeX - origin.homeX;
    const dy = parent.homeY - origin.homeY;
    if (Math.hypot(dx, dy) > 1) return Math.atan2(dy, dx);
  }
  return parent?.angle || 0;
}

function centerOutRowT(row, rowCount) {
  if (rowCount <= 1) return 0.5;
  const center = (rowCount - 1) / 2;
  if (row === 0) return 0.5;
  const step = Math.ceil(row / 2);
  const direction = row % 2 ? -1 : 1;
  const ordered = Math.max(0, Math.min(rowCount - 1, center + direction * step));
  return ordered / (rowCount - 1);
}

function centerOutInsetRowT(row, rowCount) {
  if (rowCount <= 1) return 0.5;
  const center = (rowCount - 1) / 2;
  if (row === 0) return 0.5;
  const step = Math.ceil(row / 2);
  const direction = row % 2 ? -1 : 1;
  const ordered = Math.max(0, Math.min(rowCount - 1, center + direction * step));
  return (ordered + 0.5) / rowCount;
}

function isRegionalRootChild(node) {
  if (!node || node.parentKey !== ROOT_KEY) return false;
  if (node.isMapChild || node.relation === "regional_variant" || node.relations?.includes("regional_variant")) {
    return true;
  }
  return /^music of\b/i.test(node.title || node.label || "");
}

function rootChildCrowdingMetrics() {
  let visibleCount = 0;
  let regionalCount = 0;

  for (const node of nodes.values()) {
    if (
      node.parentKey !== ROOT_KEY ||
      node.isTrimming ||
      node.isTraceOnly ||
      node.isTracePathNode ||
      node.isRevealed === false
    ) {
      continue;
    }

    visibleCount += 1;
    if (isRegionalRootChild(node)) regionalCount += 1;
  }

  return { visibleCount, regionalCount };
}

function rootChildCrowdingBoost(baseLen) {
  const { visibleCount, regionalCount } = rootChildCrowdingMetrics();
  const baselineBoost = visibleCount >= ROOT_TITLES.length
    ? baseLen * (isCompact() ? 0.18 : 0.25)
    : 0;
  const extraVisible = Math.max(0, visibleCount - ROOT_TITLES.length);
  const visibleBoost = Math.min(baseLen * 0.90, Math.sqrt(extraVisible) * baseLen * 0.085);
  const regionalBoost = Math.min(baseLen * 0.80, Math.sqrt(regionalCount) * baseLen * 0.070);
  return baselineBoost + visibleBoost + regionalBoost;
}

function rootChildEdgeLength(child, baseLen, { selected = false } = {}) {
  const crowdBoost = rootChildCrowdingBoost(baseLen);
  const selectedTraceMetrics = child?.rootTraceMetrics;
  const traceCountBoost = selected && selectedTraceMetrics?.traceLinkCount
    ? Math.min(baseLen * 1.10, Math.sqrt(selectedTraceMetrics.traceLinkCount) * baseLen * 0.13)
    : 0;
  const traceDepthBoost = selected && selectedTraceMetrics?.maxTraceSteps
    ? Math.min(baseLen * 0.90, Math.max(0, selectedTraceMetrics.maxTraceSteps - 1) * baseLen * 0.10)
    : 0;
  const regionalPageBoost = selected && isRegionalRootChild(child) ? baseLen * 0.82 : 0;
  // Root view should not collapse in on itself. Crowding boost is primarily
  // needed even when nothing is selected.
  const crowdMultiplier = selected ? 1.0 : 0.95;
  return baseLen + crowdBoost * crowdMultiplier + regionalPageBoost + traceCountBoost + traceDepthBoost;
}

function defaultSelectedEdgeLength(parent, child, baseLen) {
  return parent.key === ROOT_KEY ? rootChildEdgeLength(child, baseLen, { selected: true }) : baseLen;
}

function selectedTraceMusicDistanceFromMetrics(metrics, baseLen) {
  const visualTraceCount = Math.max(metrics?.traceLinkCount || 0, metrics?.visualTraceCount || 0);
  if (!visualTraceCount) return null;
  const traceNodeCount = [...nodes.values()].filter(node =>
    metrics.traceNodeKeys?.has(node.genreId)
  ).length;
  const precomputedTraceNodeCount = Math.max(metrics.traceNodeCount || 0, traceNodeCount);
  const maxTraceSteps = Math.max(1, metrics.maxTraceSteps || 1);
  const maxMusicSteps = Math.max(maxTraceSteps, metrics.maxMusicSteps || 1);
  const countBoost = Math.min(baseLen * 1.45, Math.sqrt(visualTraceCount) * baseLen * 0.24);
  const depthBoost = Math.min(baseLen * 1.75, Math.max(0, maxTraceSteps - 1) * baseLen * 0.20);
  const musicDepthFloor = maxMusicSteps > 1
    ? baseLen * Math.min(7.20, 0.58 + maxMusicSteps * 0.46)
    : 0;
  const nodeBoost = Math.min(baseLen * 4.20, precomputedTraceNodeCount * baseLen * 0.11);
  return Math.min(
    baseLen * 7.20,
    Math.max(musicDepthFloor, baseLen * 1.05 + countBoost + depthBoost + nodeBoost)
  );
}

function relaxFocusedChildClusterHomes(spine) {
  const parents = [...nodes.values()].filter(parent =>
    parent.key !== ROOT_KEY &&
    spine.has(parent.key)
  );

  for (const parent of parents) {
    const children = [...nodes.values()].filter(child =>
      child.parentKey === parent.key &&
      !spine.has(child.key) &&
      !child.isTraceOnly &&
      !child.isTracePathNode &&
      !child.isTrimming
    );
    if (children.length < 2) continue;

    const origin = parent.parentKey ? nodes.get(parent.parentKey) : null;
    let ux = parent.homeX - (origin?.homeX ?? 0);
    let uy = parent.homeY - (origin?.homeY ?? 0);
    let len = Math.hypot(ux, uy);
    if (len < 1) {
      ux = Math.cos(parent.angle || 0);
      uy = Math.sin(parent.angle || 0);
      len = Math.hypot(ux, uy) || 1;
    }
    ux /= len;
    uy /= len;
    const px = -uy;
    const py = ux;

    const local = new Map();
    const bounds = children.reduce((acc, child) => {
      const dx = child.homeX - parent.homeX;
      const dy = child.homeY - parent.homeY;
      const along = dx * ux + dy * uy;
      const lateral = dx * px + dy * py;
      local.set(child.key, { along, lateral });
      acc.minAlong = Math.min(acc.minAlong, along);
      acc.maxAlong = Math.max(acc.maxAlong, along);
      acc.minLateral = Math.min(acc.minLateral, lateral);
      acc.maxLateral = Math.max(acc.maxLateral, lateral);
      return acc;
    }, {
      minAlong: Infinity,
      maxAlong: -Infinity,
      minLateral: Infinity,
      maxLateral: -Infinity,
    });

    for (let iter = 0; iter < 10; iter++) {
      let moved = false;
      for (let i = 0; i < children.length; i++) {
        const a = children[i];
        const al = local.get(a.key);
        const abox = nodeBox(a, 24, 18, false);
        for (let j = i + 1; j < children.length; j++) {
          const b = children[j];
          const bl = local.get(b.key);
          const bbox = nodeBox(b, 24, 18, false);
          let dx = bl.lateral - al.lateral;
          let dy = bl.along - al.along;
          if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
            dx = Math.cos((i + 1) * 17.17 + (j + 1) * 3.31);
            dy = Math.sin((i + 1) * 5.43 + (j + 1) * 19.19);
          }

          const overlapX = (abox.w + bbox.w) / 2 - Math.abs(dx);
          if (overlapX <= 0) continue;
          const overlapY = (abox.h + bbox.h) / 2 - Math.abs(dy);
          if (overlapY <= 0) continue;

          const pushX = overlapX < overlapY ? (dx < 0 ? -1 : 1) * (overlapX + 2.5) * 0.58 : 0;
          const pushY = overlapY <= overlapX ? (dy < 0 ? -1 : 1) * (overlapY + 2.5) * 0.58 : 0;
          al.lateral = clamp(al.lateral - pushX, bounds.minLateral, bounds.maxLateral);
          bl.lateral = clamp(bl.lateral + pushX, bounds.minLateral, bounds.maxLateral);
          al.along = clamp(al.along - pushY, bounds.minAlong, bounds.maxAlong);
          bl.along = clamp(bl.along + pushY, bounds.minAlong, bounds.maxAlong);
          moved = true;
        }
      }
      if (!moved) break;
    }

    for (const child of children) {
      const point = local.get(child.key);
      child.homeX = parent.homeX + ux * point.along + px * point.lateral;
      child.homeY = parent.homeY + uy * point.along + py * point.lateral;
      child.angle = Math.atan2(child.homeY - parent.homeY, child.homeX - parent.homeX);
      child.distance = parent.distance + Math.hypot(point.along, point.lateral);
    }
  }
}

function precomputeSelectedTraceDistance(selectedNode, rows) {
  if (!selectedNode || selectedNode.key === ROOT_KEY) return;

  const visualTraceRows = rows || [];
  const parentTraceRows = visualTraceRows.filter(row => !shouldSwapParentToChild(row, selectedNode));
  const traceNodeKeys = new Set();
  for (const row of visualTraceRows) {
    for (const genreId of row.path_genre_ids?.slice(0, -1) || []) {
      if (genreId && genreId !== ROOT_KEY) traceNodeKeys.add(genreId);
    }
    if (row.parent_genre_id && row.parent_genre_id !== ROOT_KEY) {
      traceNodeKeys.add(row.parent_genre_id);
    }
  }

  const metrics = {
    traceLinkCount: parentTraceRows.length,
    visualTraceCount: visualTraceRows.length,
    traceNodeCount: traceNodeKeys.size,
    traceNodeKeys,
    maxTraceSteps: Math.max(0, ...parentTraceRows.map(row => row.trace_steps || traceSteps(row))),
    maxMusicSteps: Math.max(
      0,
      ...visualTraceRows.map(row => Math.max(
        row.trace_steps || traceSteps(row),
        row.depth_from_music || 0,
        Number.isFinite(row.parent_depth_from_music) ? row.parent_depth_from_music + 1 : 0
      ))
    ),
  };
  selectedNode.rootTraceMetrics = metrics;
  selectedNode.precomputedTraceMusicDistance =
    selectedTraceMusicDistanceFromMetrics(metrics, edgeBaseLength());
}

function prepareTraceDistanceShrinkAnimation(node) {
  if (!node || node.key === ROOT_KEY || prefersReducedMotion()) return;
  if (!node.precomputedTraceMusicDistance && !node.rootTraceMetrics) return;
  const parent = node.parentKey ? nodes.get(node.parentKey) : null;
  if (!parent) return;

  const baseLen = edgeBaseLength();
  const currentLength = Math.max(
    baseLen * 0.18,
    (!node.edgeLengthAnim?.done ? node.edgeLengthAnim?.current : null) ||
      Math.hypot(node.homeX - parent.homeX, node.homeY - parent.homeY) ||
      Math.hypot(node.x - parent.x, node.y - parent.y) ||
      baseLen
  );
  const nextTraceDistance = null;
  const nextMetrics = null;
  const previousTraceDistance = node.precomputedTraceMusicDistance;
  const previousMetrics = node.rootTraceMetrics;

  node.precomputedTraceMusicDistance = nextTraceDistance;
  node.rootTraceMetrics = nextMetrics;
  const nextTarget = selectedChildEdgeLength(parent, node, baseLen);
  node.precomputedTraceMusicDistance = previousTraceDistance;
  node.rootTraceMetrics = previousMetrics;

  if (currentLength <= nextTarget + 1) return;
  node.edgeLengthAnim = {
    parentKey: parent.key,
    startedAt: Date.now(),
    start: currentLength,
    current: currentLength,
    target: nextTarget,
    done: false,
  };
}

function clearInactiveTraceDistanceAccounting(activeAnchors = activeTraceAnchorKeys()) {
  for (const node of nodes.values()) {
    if (activeAnchors.has(node.key)) continue;
    prepareTraceDistanceShrinkAnimation(node);
    node.rootTraceMetrics = null;
    node.precomputedTraceMusicDistance = null;
  }
}

function selectedChildEdgeLength(parent, child, baseLen) {
  let longestSibling = 0;

  if (parent.key !== ROOT_KEY) {
    for (const edge of edges) {
      if (edge.isTraceLink || edge.isTracePath) continue;
      if (edge.from !== parent.key || edge.to === child.key || edge.isTrimming) continue;
      const sibling = nodes.get(edge.to);
      if (!sibling || sibling.isTraceOnly || sibling.isTrimming) continue;

      longestSibling = Math.max(
        longestSibling,
        sibling.clearLengthCap || focusedChildSlot(parent, sibling, baseLen).radius
      );
    }
  }

  const localTarget = parent.key === ROOT_KEY
    ? defaultSelectedEdgeLength(parent, child, baseLen)
    : Math.max(longestSibling || baseLen, baseLen) * 1.06 + Math.min(130, baseLen * 0.62);
  const musicDistanceTarget = child.precomputedTraceMusicDistance;
  if (!musicDistanceTarget) return localTarget;

  const traceEdgeTarget = Math.max(baseLen * 0.18, musicDistanceTarget - (parent.distance || 0));
  return Math.max(localTarget, traceEdgeTarget);
}

function activeLeafEdgeLength(parent, child, baseLen, slotRadius) {
  const musicDistanceTarget = child.precomputedTraceMusicDistance;
  if (!musicDistanceTarget) return slotRadius;

  const traceEdgeTarget = Math.max(baseLen * 0.18, musicDistanceTarget - (parent.distance || 0));
  return Math.max(slotRadius, traceEdgeTarget);
}

function captureClearingSiblingCaps(currentNode) {
  const parent = currentNode?.parentKey ? nodes.get(currentNode.parentKey) : null;
  if (!currentNode || !parent) return;
  if (parent.key === ROOT_KEY) return;

  const baseLen = edgeBaseLength();
  for (const edge of edges) {
    if (edge.isTraceLink || edge.isTracePath) continue;
    if (edge.from !== parent.key || edge.to === currentNode.key || edge.isTrimming) continue;
    const sibling = nodes.get(edge.to);
    if (!sibling || sibling.isTraceOnly || sibling.isTrimming) continue;
    const slot = focusedChildSlot(parent, sibling, baseLen);
    sibling.clearLengthCap = Math.max(baseLen * 0.5, slot.radius);
    sibling.clearLateralCap = baseLen * 0.36;
  }
}

function clearClearingState(currentNode) {
  if (currentNode) {
    currentNode.isClearingCluster = false;
  }
  for (const node of nodes.values()) {
    node.clearLengthCap = null;
    node.clearLateralCap = null;
  }
}

function clearLayoutPressure(node) {
  if (!node) return;
  node.layoutClusterBoost = 0;
  node.layoutEdgeBoost = 0;
  node.layoutTraceBoost = 0;
  node.layoutTraceBoostApplied = 0;
  node.manualEdgeBoost = 0;
}

function manualLengthOffset(node, scale = 1) {
  return ((node?.layoutEdgeBoost || 0) + (node?.manualEdgeBoost || 0)) * scale;
}

function commitManualLengthTarget(node) {
  if (!node || node.key === ROOT_KEY) return;
  const parent = node.parentKey ? nodes.get(node.parentKey) : null;
  if (!parent) return;

  const currentAutoTarget = Math.max(
    1,
    Math.hypot(node.homeX - parent.homeX, node.homeY - parent.homeY) - (node.manualEdgeBoost || 0)
  );
  const draggedLength = Math.max(
    1,
    Math.hypot((node.fx ?? node.x) - parent.x, (node.fy ?? node.y) - parent.y)
  );
  const nextOffset = clamp(
    (node.manualEdgeBoost || 0) + (draggedLength - currentAutoTarget) * MANUAL_LENGTH_BLEND,
    -currentAutoTarget * 0.55,
    MANUAL_LENGTH_MAX_OFFSET
  );
  node.manualEdgeBoost = nextOffset;
}

function shouldUseClearingCluster(node, childCount) {
  return Boolean(childCount > 0 && node?.parentKey && node.parentKey !== ROOT_KEY);
}

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}

function easeInOutCubic(t) {
  const value = clamp(t, 0, 1);
  return value < 0.5
    ? 4 * value * value * value
    : 1 - Math.pow(-2 * value + 2, 3) / 2;
}

function animatedChildEdgeLength(parent, child, baseLen, target, shouldAnimate) {
  const canAnimate = shouldAnimate || child.edgeLengthAnim;

  if (!canAnimate || prefersReducedMotion()) {
    child.edgeLengthAnim = null;
    return target;
  }

  const now = Date.now();
  if (
    child.edgeLengthAnim?.done &&
    child.edgeLengthAnim.parentKey === parent.key &&
    Math.abs(child.edgeLengthAnim.target - target) <= 1
  ) {
    return target;
  }

  if (
    !child.edgeLengthAnim ||
    child.edgeLengthAnim.parentKey !== parent.key ||
    Math.abs(child.edgeLengthAnim.target - target) > 1
  ) {
    const currentDistance = Math.hypot(child.x - parent.x, child.y - parent.y);
    child.edgeLengthAnim = {
      parentKey: parent.key,
      startedAt: now,
      start: Math.max(baseLen, currentDistance || baseLen),
      target,
    };
  }

  const anim = child.edgeLengthAnim;
  const t = Math.min(1, (now - anim.startedAt) / SELECTED_EDGE_LENGTHEN_MS);
  const length = anim.start + (anim.target - anim.start) * easeOutCubic(t);
  if (t >= 1) {
    child.edgeLengthAnim = { ...anim, start: target, startedAt: now, current: target, done: true };
    return target;
  }
  child.edgeLengthAnim = { ...anim, current: length, done: false };
  return length;
}

function selectedChildAnimatedEdgeLength(parent, child, baseLen) {
  return animatedChildEdgeLength(
    parent,
    child,
    baseLen,
    selectedChildEdgeLength(parent, child, baseLen),
    child.key === currentKey || child.key === activeLeafKey || child.isClearingCluster
  );
}

function activeLeafAnimatedEdgeLength(parent, child, baseLen, slotRadius) {
  return animatedChildEdgeLength(
    parent,
    child,
    baseLen,
    activeLeafEdgeLength(parent, child, baseLen, slotRadius),
    child.key === activeLeafKey
  );
}

function updateLengtheningLayouts() {
  for (const node of nodes.values()) {
    if (node.edgeLengthAnim && !node.edgeLengthAnim.done) {
      recomputeLayout();
      return true;
    }
  }
  return false;
}

function floatSelectedNodeToTarget() {
  const node = nodes.get(currentKey);
  if (!node || !isSelectedFloatingNode(node)) return;
  const t = prefersReducedMotion() ? 1 : 0.24;
  node.x += (node.homeX - node.x) * t;
  node.y += (node.homeY - node.y) * t;
  node.vx = 0;
  node.vy = 0;
}

async function waitForSelectedChildClearance(nodeKey, token) {
  if (prefersReducedMotion()) return;
  const started = Date.now();

  while (token === focusToken && Date.now() - started < CHILD_CLEARANCE_MAX_WAIT_MS) {
    const node = nodes.get(nodeKey);
    const parent = node?.parentKey ? nodes.get(node.parentKey) : null;
    if (!node || !parent) return;

    const targetDistance =
      node.edgeLengthAnim?.target ||
      Math.hypot(node.homeX - parent.homeX, node.homeY - parent.homeY);
    if (targetDistance < 1) return;

    const currentDistance = Math.hypot(node.x - parent.x, node.y - parent.y);
    if (currentDistance >= targetDistance * CHILD_CLEARANCE_RATIO) return;

    await sleep(32);
  }
}

function seedPendingChildren(newNodes) {
  for (const child of newNodes) {
    const parent = child.parentKey ? nodes.get(child.parentKey) : null;
    const { ux, uy } = outwardUnit(child, parent);
    child.x = child.homeX - ux * 18;
    child.y = child.homeY - uy * 18;
    child.vx = 0;
    child.vy = 0;
  }

  const renderNodes = [...nodes.values()];
  for (let i = 0; i < 8; i++) {
    for (const node of renderNodes) {
      limitNodeStretch(node);
    }
    resolveRectCollisions(renderNodes);
  }
}

function createChildNode(parent, child, index, total, options = {}) {
  const key = childNodeKey(parent, child, index);
  if (nodes.has(key)) return null;

  const fan = childFan(parent, total);
  const cSliceStart = fan.start + (index / total) * fan.width;
  const cSliceEnd = fan.start + ((index + 1) / total) * fan.width;
  const cAngle = (cSliceStart + cSliceEnd) / 2;
  const known = child.genreId ? detailCache.get(child.genreId) : null;
  const data = known ? { ...child, ...known } : child;
  // Preserve edge-derived colors if a cached/known record lacks color.
  if (child?.color && !data.color) data.color = child.color;
  if (child?.colorConfidence != null && data.colorConfidence == null) data.colorConfidence = child.colorConfidence;
  // If a child has no known color, inherit the parent's domain color so clusters
  // remain visually coherent (e.g. Electronic children).
  if (!data.color && parent?.color) data.color = parent.color;
  const startRadius = isCompact() ? 18 : 26;

  const n = {
    ...data,
    isUnresolved: Boolean(data.isUnresolved),
    key,
    angle: cAngle,
    sliceStart: cSliceStart,
    sliceEnd: cSliceEnd,
    depth: parent.depth + 1,
    parentKey: parent.key,
    siblingIndex: index,
    siblingTotal: total,
    isExpanded: false,
    childCount: null,
    isFaded: false,
    isTrimming: false,
    isTraceOnly: Boolean(options.traceOnly),
    isTraceParent: Boolean(options.traceParent),
    isTracePathNode: Boolean(options.tracePath && options.traceParent),
    traceAnchorKeys: options.traceAnchorKey ? [options.traceAnchorKey] : [],
    traceDepth: options.traceDepth ?? null,
    traceToken: options.traceToken ?? null,
    isRevealed: !options.hidden,
    distance: 0,
    homeX: 0,
    homeY: 0,
    x: parent.x + Math.cos(cAngle) * startRadius,
    y: parent.y + Math.sin(cAngle) * startRadius,
    vx: Math.cos(cAngle) * 0.6,
    vy: Math.sin(cAngle) * 0.6,
  };

  nodes.set(key, n);
  edges.push({
    key: options.edgeKey,
    from: parent.key,
    to: key,
    relation: child.relation,
    isUnresolved: Boolean(child.isUnresolved),
    isTrimming: false,
    isTracePath: Boolean(options.tracePath),
    isTraceChild: Boolean(options.traceChild),
    traceAnchorKeys: options.traceAnchorKey ? [options.traceAnchorKey] : [],
    traceDepth: options.traceDepth ?? null,
    traceToken: options.traceToken ?? null,
    isRevealed: !options.hidden,
  });
  return n;
}

async function expand(nodeKey, options = {}) {
  const node = nodes.get(nodeKey);
  if (!node || Boolean(node.isUnresolved)) return [];

  const children = options.children || await getChildren(node);
  node.isExpanded = true;
  node.childCount = children.length;
  if (!children.length) return [];

  const newNodes = [];

  for (let i = 0; i < children.length; i++) {
    if (options.token !== undefined && options.token !== focusToken) break;
    const existingKey = childNodeKey(node, children[i], i);
    const existing = nodes.get(existingKey);
    if (existing) {
      existing.siblingIndex = i;
      existing.siblingTotal = children.length;
      existing.isRevealed = true;
      existing.isTrimming = false;
      existing.isFaded = false;
      const edge = edges.find(e => e.from === node.key && e.to === existing.key);
      if (edge) {
        edge.isRevealed = true;
        edge.isTrimming = false;
      }
      continue;
    }
    const child = createChildNode(node, children[i], i, children.length, {
      hidden: options.stagger,
    });
    if (!child) continue;
    newNodes.push(child);
  }

  if (options.stagger && newNodes.length) {
    recomputeLayout();
    seedPendingChildren(newNodes);
    fullRender();
    rebuildSim();
    bumpSim(0.48);

    if (options.prewarmMs) {
      await sleep(options.prewarmMs);
    }

    for (let i = 0; i < newNodes.length; i++) {
      if (options.token !== undefined && options.token !== focusToken) break;
      if (i > 0) {
        await sleep(CHILD_STAGGER_MS);
      }
      newNodes[i].isRevealed = true;
      newNodes[i].isTrimming = false;
      if (i === 0 && typeof options.onRevealStart === "function") {
        options.onRevealStart();
      }
      const el = nodeEls.get(newNodes[i].key);
      if (el) {
        el.classList.remove("pending");
        el.classList.remove("trimming");
        el.classList.add("revealed");
      }
      const edge = edges.find(e => e.from === node.key && e.to === newNodes[i].key);
      if (edge) {
        edge.isTrimming = false;
        edge.isRevealed = true;
      }
      const edgeEl = edge ? edgeEls.get(graphEdgeKey(edge)) : null;
      if (edgeEl) {
        edgeEl.classList.remove("pending");
        edgeEl.classList.remove("trimming");
        edgeEl.classList.add("revealed");
      }
      bumpSim(0.10);
    }
  } else {
    for (const child of newNodes) {
      child.isRevealed = true;
    }
  }

  return newNodes;
}

function visibleChildByGenre(parent, genreId) {
  for (const node of nodes.values()) {
    if (node.parentKey === parent.key && node.genreId === genreId && !node.isTrimming) {
      return node;
    }
  }
  return null;
}

function traceSteps(row) {
  return Math.max(1, row.path_genre_ids?.length || row.depth_from_music || 1);
}

function pageviewRatioScore(parentViews, selectedViews) {
  const parent = Math.max(1, parentViews ?? 1);
  const selected = Math.max(1, selectedViews ?? 1);
  return clamp((Math.log2(parent / selected) + 4) / 8, 0, 1);
}

function chronologyScore(parentYear, selectedYear) {
  if (!Number.isFinite(parentYear) || !Number.isFinite(selectedYear)) return null;
  const delta = selectedYear - parentYear;
  if (delta >= 0) return clamp(0.72 + Math.min(delta, 40) / 140, 0, 1);
  return clamp(0.18 + Math.max(-40, delta) / 90, 0, 0.32);
}

function parentTraceConfidence(row, selectedNode) {
  const steps = traceSteps(row);
  const parentDepth = Math.max(0, row.parent_depth_from_music ?? steps - 1);
  const selectedViews = row.genre_monthly_views_p30 ?? selectedNode?.monthlyViews;
  const ratioScore = pageviewRatioScore(row.parent_monthly_views_p30, selectedViews);
  const yearScore = chronologyScore(row.parent_year_start, row.genre_year_start);
  const distanceScore = 1 / (
    1 +
    Math.max(0, parentDepth - 2) * 0.32 +
    Math.max(0, steps - 3) * 0.18
  );
  if (yearScore !== null) {
    return clamp(yearScore * 0.62 + ratioScore * 0.23 + distanceScore * 0.15, 0, 1);
  }
  return clamp(ratioScore * 0.70 + distanceScore * 0.30, 0, 1);
}

function annotateTraceRow(row) {
  return {
    ...row,
    trace_steps: traceSteps(row),
  };
}

function traceRowsForNode(node, rows) {
  if (!node?.genreId) return [];
  const activeIds = activePathGenreIds();
  const visibleParent = node.parentKey ? nodes.get(node.parentKey) : null;
  const visibleParentId = visibleParent?.key === ROOT_KEY
    ? ROOT_KEY
    : visibleParent?.genreId;
  const seen = new Set();
  const result = [];

  for (const row of rows || []) {
    if (!Array.isArray(row.path_genre_ids) || row.path_genre_ids.at(-1) !== node.genreId) continue;
    if (samePath(row.path_genre_ids, activeIds)) continue;
    if (row.parent_genre_id === ROOT_KEY) continue;
    if (row.parent_genre_id === visibleParentId) continue;

    const key = `${row.parent_genre_id}|${row.parent_relation}|${row.path_genre_ids.join(">")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(annotateTraceRow(row));
  }

  return result.sort((a, b) => {
    const ar = RELATION_RANK.get(a.parent_relation) ?? 99;
    const br = RELATION_RANK.get(b.parent_relation) ?? 99;
    return (
      a.trace_steps - b.trace_steps ||
      a.parent_depth_from_music - b.parent_depth_from_music ||
      ar - br ||
      a.parent_title.localeCompare(b.parent_title)
    );
  });
}

function parentSwapLimits(row) {
  if (row.parent_relation === ORIGIN_PARENT_RELATION) {
    return null;
  }
  if (row.parent_stored_relation === RELATED_CHILD_RELATION) {
    return {
      maxPageviewScore: RELATED_PARENT_CHILD_SWAP_MAX_PAGEVIEW_SCORE,
      minParentDepth: RELATED_PARENT_CHILD_SWAP_MIN_PARENT_DEPTH,
    };
  }
  if (row.parent_stored_relation === "derivative") {
    return {
      maxPageviewScore: DERIVATIVE_PARENT_CHILD_SWAP_MAX_PAGEVIEW_SCORE,
      minParentDepth: DERIVATIVE_PARENT_CHILD_SWAP_MIN_PARENT_DEPTH,
    };
  }
  return null;
}

function shouldSwapParentToChild(row, selectedNode) {
  const limits = parentSwapLimits(row);
  if (!limits) return false;

  const yearScore = chronologyScore(row.parent_year_start, row.genre_year_start);
  if (
    yearScore !== null &&
    row.parent_year_start <= row.genre_year_start + YEAR_PARENT_LATER_TOLERANCE
  ) {
    return false;
  }

  const pageviewScore = pageviewRatioScore(
    row.parent_monthly_views_p30,
    row.genre_monthly_views_p30 ?? selectedNode?.monthlyViews
  );
  const parentDepth = Math.max(0, row.parent_depth_from_music ?? traceSteps(row) - 1);
  if (yearScore === null) {
    if (
      pageviewScore > limits.maxPageviewScore ||
      parentDepth < limits.minParentDepth
    ) {
      return false;
    }
  }

  const confidence = parentTraceConfidence(row, selectedNode);
  row.trace_confidence = confidence;
  return confidence < PARENT_CHILD_SWAP_CONFIDENCE;
}

async function traceChildData(parent, genreId, fallbackTitle) {
  const children = await getChildren(parent);
  const index = children.findIndex(child => child.genreId === genreId);
  if (index >= 0) {
    return {
      child: children[index],
      index,
      total: children.length,
    };
  }

  const detail = await getGenreDetail(genreId).catch(() => null);
  if (!detail && !fallbackTitle) return null;
  const base = detail || {
    genreId,
    label: labelFromTitle(fallbackTitle),
    title: normalizeLabel(fallbackTitle),
    qid: null,
    color: null,
    summary: null,
    wikipedia_url: null,
    aliases: [],
    origins: [],
    instruments: [],
    categories: [],
    isUnresolved: false,
  };
  const siblingCount = [...nodes.values()].filter(n => n.parentKey === parent.key).length;
  return {
    child: {
      ...base,
      relation: parent.key === ROOT_KEY ? "music_root" : "subgenre",
      relations: [parent.key === ROOT_KEY ? "music_root" : "subgenre"],
    },
    index: siblingCount,
    total: Math.max(1, children.length + 1, siblingCount + 1),
    fallback: true,
  };
}

function markBacktraceParentNode(node, anchorKey) {
  if (!node || node.key === ROOT_KEY) return;
  node.isTraceParent = true;
  node.isTraceOnly = false;
  addTraceAnchor(node, anchorKey);
}

async function revealTraceNode(node, parent, token) {
  if (token !== focusToken || !node || !parent) return false;
  recomputeLayout();
  seedPendingChildren([node]);
  fullRender();
  rebuildSim();
  bumpSim(0.34);
  await sleep(PARENT_TRACE_STEP_MS);
  if (token !== focusToken || !nodes.has(node.key)) return false;

  node.isRevealed = true;
  node.isTrimming = false;
  const edge = edges.find(e => e.from === parent.key && e.to === node.key);
  if (edge) edge.isRevealed = true;
  updateClasses();
  bumpSim(0.24);
  return true;
}

async function ensureTracePathNode(parent, genreId, fallbackTitle, row, token, traceDepth = 1, anchorKey = null) {
  if (token !== focusToken || !parent || !genreId) return null;

  const existing = visibleChildByGenre(parent, genreId);
  if (existing) {
    markBacktraceParentNode(existing, anchorKey);
    const edge = edges.find(e => e.from === parent.key && e.to === existing.key);
    addTraceAnchor(edge, anchorKey);
    if (existing.isRevealed === false) {
      existing.isRevealed = true;
      if (edge) edge.isRevealed = true;
      updateClasses();
    }
    return existing;
  }

  const data = await traceChildData(parent, genreId, fallbackTitle);
  if (token !== focusToken || !data) return null;

  const child = createChildNode(parent, data.child, data.index, data.total, {
    hidden: true,
    traceOnly: true,
    traceParent: true,
    tracePath: true,
    traceDepth,
    traceToken: token,
    traceAnchorKey: anchorKey,
    edgeKey: `trace-path|${parent.key}|${genreId}|${data.index}`,
  });
  if (!child) return visibleChildByGenre(parent, genreId);
  markBacktraceParentNode(child, anchorKey);
  softenTraceApproachAngle(parent, child);
  await revealTraceNode(child, parent, token);
  return child;
}

async function addTraceLink(parent, selectedNode, row, token) {
  if (token !== focusToken || !parent || !selectedNode) return;
  if (parent.key === selectedNode.parentKey) return;
  const anchorKey = selectedNode.key;

  const key = [
    "trace-link",
    parent.key,
    selectedNode.key,
    row.parent_relation,
    row.parent_source,
    row.parent_ordinal,
  ].join("|");
  let edge = edges.find(e => graphEdgeKey(e) === key);
  if (!edge) {
    edge = {
      key,
      from: parent.key,
      to: selectedNode.key,
      relation: row.parent_relation,
      source: row.parent_source,
      ordinal: row.parent_ordinal,
      isTraceLink: true,
      traceSteps: row.trace_steps ?? null,
      traceAnchorKeys: [anchorKey],
      isTrimming: false,
      isRevealed: false,
    };
    edges.push(edge);
  } else {
    addTraceAnchor(edge, anchorKey);
    edge.isTrimming = false;
    edge.isRevealed = false;
    edge.traceSteps = row.trace_steps ?? edge.traceSteps;
  }

  fullRender();
  rebuildSim();
  bumpSim(0.22);
  await sleep(PARENT_TRACE_LINK_MS);
  if (token !== focusToken || !nodes.has(parent.key) || !nodes.has(selectedNode.key)) return;
  edge.isRevealed = true;
  recomputeLayout();
  updateClasses();
  renderTick();
  rebuildSim();
  bumpSim(0.28);
}

async function swappedRelatedChildData(row) {
  const detail = await getGenreDetail(row.parent_genre_id).catch(() => null);
  if (detail) {
    return {
      ...detail,
      relation: row.parent_relation,
      relations: [row.parent_relation],
      monthlyViews: row.parent_monthly_views_p30 ?? detail.monthlyViews,
    };
  }

  return {
    genreId: row.parent_genre_id,
    label: labelFromTitle(row.parent_title),
    title: normalizeLabel(row.parent_title),
    qid: null,
    color: null,
    colorConfidence: null,
    summary: null,
    wikipedia_url: null,
    aliases: [],
    origins: [],
    instruments: [],
    categories: [],
    monthlyViews: row.parent_monthly_views_p30,
    relation: row.parent_relation,
    relations: [row.parent_relation],
    isUnresolved: false,
  };
}

async function addSwappedRelatedChild(selectedNode, row, token) {
  if (token !== focusToken || !selectedNode || selectedNode.key !== currentKey) return;
  const anchorKey = selectedNode.key;
  const existing = visibleChildByGenre(selectedNode, row.parent_genre_id);
  if (existing) {
    addTraceAnchor(existing, anchorKey);
    addTraceAnchor(edges.find(e => e.from === selectedNode.key && e.to === existing.key), anchorKey);
    existing.isRevealed = true;
    existing.isTrimming = false;
    if (!existing.relations?.includes(row.parent_relation)) {
      existing.relations = [...(existing.relations || []), row.parent_relation];
    }
    reslotChildren(selectedNode);
    recomputeLayout();
    updateClasses();
    bumpSim(0.22);
    return;
  }

  const childData = await swappedRelatedChildData(row);
  if (token !== focusToken || selectedNode.key !== currentKey) return;

  const siblingCount = [...nodes.values()]
    .filter(n => n.parentKey === selectedNode.key && !n.isTrimming)
    .length;
  const child = createChildNode(
    selectedNode,
    childData,
    siblingCount,
    Math.max(1, siblingCount + 1),
    {
      hidden: true,
      traceOnly: true,
      traceChild: true,
      traceDepth: 1,
      traceToken: token,
      traceAnchorKey: anchorKey,
      edgeKey: `trace-child|${selectedNode.key}|${row.parent_genre_id}|${row.parent_source}|${row.parent_ordinal}`,
    }
  );
  if (!child) return;
  reslotChildren(selectedNode);
  await revealTraceNode(child, selectedNode, token);
}

async function reachableParentTraceRows(selectedNode) {
  if (!selectedNode?.genreId || selectedNode.key === ROOT_KEY) return [];
  const rows = await getReachableParents(selectedNode.genreId).catch(() => []);
  return traceRowsForNode(selectedNode, rows);
}

async function revealReachableParentTraces(selectedNode, token, precomputedRows = null) {
  if (!selectedNode?.genreId || selectedNode.key === ROOT_KEY) return;
  const rows = precomputedRows || await reachableParentTraceRows(selectedNode);
  if (token !== focusToken) return;

  if (!selectedNode.precomputedTraceMusicDistance) {
    precomputeSelectedTraceDistance(selectedNode, rows);
    recomputeLayout();
    refreshHomeForces();
    if (nodeEls.size) {
      updateClasses();
      renderTick();
    }
    rebuildSim();
    bumpSim(rows.length ? 0.38 : 0.18);
  }

  if (!rows.length) return;

  for (const row of rows) {
    if (token !== focusToken) return;
    if (shouldSwapParentToChild(row, selectedNode)) {
      await addSwappedRelatedChild(selectedNode, row, token);
      continue;
    }

    const anchorKey = selectedNode.key;
    let parent = nodes.get(ROOT_KEY);
    const path = row.path_genre_ids.slice(0, -1);
    for (let i = 0; i < path.length; i++) {
      parent = await ensureTracePathNode(parent, path[i], row.path_titles?.[i], row, token, i + 1, anchorKey);
      if (token !== focusToken || !parent) break;
    }
    if (token !== focusToken || !parent) return;
    const currentSelected = nodes.get(selectedNode.key);
    if (!currentSelected || (currentSelected.key !== currentKey && currentSelected.key !== activeLeafKey)) return;
    await addTraceLink(parent, currentSelected, row, token);
  }
}

function getSpine() {
  const s = new Set();
  let n = nodes.get(currentKey);
  while (n) {
    s.add(n.key);
    n = n.parentKey ? nodes.get(n.parentKey) : null;
  }
  return s;
}

function pruneToActivePath(options = {}) {
  const animate = options.animate && !prefersReducedMotion();
  const spine = getSpine();
  const preservedParentKey = options.preserveParentContext
    ? nodes.get(currentKey)?.parentKey
    : null;
  const traceAnchors = activeTraceAnchorKeys(preservedParentKey);
  const activeTraceParents = activeTraceParentKeys(spine, preservedParentKey);
  const keep = new Set([ROOT_KEY]);
  const spineChildByParent = new Map();

  for (const node of nodes.values()) {
    if (node.parentKey && spine.has(node.key)) {
      spineChildByParent.set(node.parentKey, node.key);
    }
  }

  for (const node of nodes.values()) {
    if (spine.has(node.key) || node.key === activeLeafKey) {
      keep.add(node.key);
      continue;
    }

    if (node.isTracePathNode) {
      if (activeTraceParents.has(node.key)) keep.add(node.key);
      continue;
    }

    if (node.isTraceOnly) {
      if (hasTraceAnchorIn(node, traceAnchors) && node.parentKey && (spine.has(node.parentKey) || activeTraceParents.has(node.parentKey))) {
        keep.add(node.key);
      }
      continue;
    }

    if (!node.parentKey || !spine.has(node.parentKey)) continue;

    if (node.parentKey === preservedParentKey) {
      keep.add(node.key);
      continue;
    }

    const parent = nodes.get(node.parentKey);
    const parentChildren = [...nodes.values()].filter(n => n.parentKey === node.parentKey);
    const shouldTrim =
      parent &&
      parent.key !== ROOT_KEY &&
      parent.key !== currentKey &&
      parentChildren.length >= ANCESTOR_TRIM_THRESHOLD;

    if (!shouldTrim) {
      keep.add(node.key);
      continue;
    }

    const spineChild = spineChildByParent.get(node.parentKey);
    const visibleLimit = Math.min(
      parentChildren.length,
      Math.max(ANCESTOR_TRIM_THRESHOLD, Math.ceil(parentChildren.length * 0.1))
    );
    const topChildren = new Set(
      parentChildren
        .sort((a, b) => {
          const av = a.monthlyViews ?? -1;
          const bv = b.monthlyViews ?? -1;
          return bv - av || a.label.localeCompare(b.label);
        })
        .slice(0, visibleLimit)
        .map(child => child.key)
    );

    if (topChildren.has(node.key) || node.key === spineChild) {
      keep.add(node.key);
    }
  }

  for (const key of [...nodes.keys()]) {
    const node = nodes.get(key);
    if (!node) continue;
    if (keep.has(key)) {
      node.isTrimming = false;
      continue;
    }
    clearLayoutPressure(node);
    if (animate && nodeEls.has(key)) {
      node.isFaded = true;
      node.isTrimming = true;
    } else {
      nodes.delete(key);
    }
  }

  for (let i = edges.length - 1; i >= 0; i--) {
    const edge = edges[i];
    const isTraceScopedEdge = edge.isTracePath || edge.isTraceLink || edge.isTraceChild;
    const traceContextLost =
      isTraceScopedEdge &&
      (!hasTraceAnchorIn(edge, traceAnchors) || (edge.isTraceLink && !traceAnchors.has(edge.to)));
    if (traceContextLost || !keep.has(edge.from) || !keep.has(edge.to)) {
      if (animate && edgeEls.has(graphEdgeKey(edge))) {
        edge.isTrimming = true;
      } else {
        edges.splice(i, 1);
      }
    } else {
      edge.isTrimming = false;
    }
  }

  if (animate) scheduleTrimCleanup();
  if (animate && nodeEls.size) updateClasses();
  clearInactiveTraceDistanceAccounting(traceAnchors);

  for (const node of nodes.values()) {
    if (node.isTrimming) continue;
    const hasExpandedChildren = edges.some(
      e => e.from === node.key && !e.isTracePath && !e.isTraceLink
    );
    node.isExpanded = hasExpandedChildren;
    if (node.key !== currentKey && !hasExpandedChildren && node.childCount !== 0) {
      node.childCount = null;
    }
  }
}

function scheduleTrimCleanup() {
  if (trimCleanupTimer) clearTimeout(trimCleanupTimer);
  trimCleanupTimer = setTimeout(() => {
    trimCleanupTimer = null;
    for (const [key, node] of [...nodes.entries()]) {
      if (node.isTrimming) nodes.delete(key);
    }
    for (let i = edges.length - 1; i >= 0; i--) {
      if (edges[i].isTrimming || !nodes.has(edges[i].from) || !nodes.has(edges[i].to)) {
        edges.splice(i, 1);
      }
    }
    fullRender();
  }, TRIM_ANIMATION_MS);
}

function recomputeLayout() {
  const spine = getSpine();
  const root = nodes.get(ROOT_KEY);
  root.distance = 0;
  root.homeX = 0;
  root.homeY = 0;
  root.isFaded = false;

  const queue = [ROOT_KEY];
  const seen = new Set(queue);

  while (queue.length) {
    const parentKey = queue.shift();
    const parent = nodes.get(parentKey);
    for (const e of edges) {
      if (e.isTraceLink) continue;
      if (e.from !== parentKey || seen.has(e.to)) continue;
      if (e.isTrimming) continue;
      seen.add(e.to);
      const child = nodes.get(e.to);
      if (!child || child.isTrimming) continue;
      const isSpineEdge = spine.has(parent.key) && spine.has(child.key);
      const childHasChildren = child.childCount === null ? true : child.childCount > 0;
      const baseLen = edgeBaseLength();
      const isTracePath = Boolean(e.isTracePath || child.isTracePathNode);
      const isTraceChild = Boolean(e.isTraceChild || (child.isTraceOnly && !isTracePath));
      const parentIsActiveAncestor = spine.has(parent.key) && parent.key !== ROOT_KEY;
      const slot = parentIsActiveAncestor && !isSpineEdge && !isTracePath
        ? focusedChildSlot(parent, child, baseLen)
        : null;
      const isInactiveChild =
        spine.has(parent.key) &&
        parent.key !== currentKey &&
        !spine.has(child.key) &&
        !isTracePath;
      const isActiveLeafChild = child.key === activeLeafKey && parent.key === currentKey;
      const slotRadius = slot
        ? Math.max(
            slot.radius,
            isActiveLeafChild ? activeLeafAnimatedEdgeLength(parent, child, baseLen, slot.radius) : 0
          ) * (isInactiveChild ? 0.85 : 1) + manualLengthOffset(child, isInactiveChild ? 0.85 : 1)
        : null;
      const clusterBoost = slot
        ? (parent.layoutClusterBoost || 0) * (isInactiveChild ? 0.85 : 1)
        : 0;
      const defaultTreeEdgeLength = parent.key === ROOT_KEY
        ? rootChildEdgeLength(child, baseLen, { selected: false })
        : baseLen * (isInactiveChild ? 0.5 : 1);
      let edgeLen = slotRadius ??
        (isTracePath
          ? tracePathSegmentLength(parent, child, baseLen)
          : (isSpineEdge ? selectedChildAnimatedEdgeLength(parent, child, baseLen) : defaultTreeEdgeLength));
      if (isTracePath) {
        edgeLen += traceSegmentLengthBoost(e, baseLen);
      }
      if (!slot && !isTracePath) {
        edgeLen += manualLengthOffset(child, isInactiveChild ? 0.5 : 1);
      }
      edgeLen = Math.max(baseLen * 0.18, edgeLen);
      child.distance = parent.distance + edgeLen;

      child.isFaded = isInactiveChild;

      if (slot) {
        child.angle = slot.angle;
        const boostAngle = parent.angle || slot.angle;
        child.homeX =
          parent.homeX +
          Math.cos(boostAngle) * clusterBoost +
          Math.cos(slot.angle) * edgeLen;
        child.homeY =
          parent.homeY +
          Math.sin(boostAngle) * clusterBoost +
          Math.sin(slot.angle) * edgeLen;
      } else if (isTracePath) {
        softenTraceApproachAngle(parent, child);
        const avoidance = traceLineAvoidance(parent, child, edgeLen);
        child.angle += avoidance.bend;
        edgeLen = avoidance.length;
        child.distance = parent.distance + edgeLen;
        child.homeX = parent.homeX + Math.cos(child.angle) * edgeLen;
        child.homeY = parent.homeY + Math.sin(child.angle) * edgeLen;
      } else {
        child.homeX = parent.homeX + Math.cos(child.angle) * edgeLen;
        child.homeY = parent.homeY + Math.sin(child.angle) * edgeLen;
      }
      queue.push(child.key);
    }
  }

  relaxFocusedChildClusterHomes(spine);
  shapeAdditionalParentPaths(edgeBaseLength());
}

function graphNodeFontWeight(node) {
  if (node?.key === currentKey) return 700;
  if (node?.key === ROOT_KEY) return 600;
  return 500;
}

function scaledDbTextWidth(node, label, fontSize) {
  const measuredWidth = positiveMetricValue(node?.textWidth, node?.text_width, node?.width);
  if (measuredWidth) return measuredWidth * (fontSize / CLOUD_FONT_SIZE);
  return cloudFallbackTextWidth(label) * (fontSize / CLOUD_FONT_SIZE);
}

function svgPretextWidth(node, label, fontSize, fontWeight) {
  return Math.ceil(scaledDbTextWidth(node, label, fontSize));
}

function pillWidthFromPretext(node, label, fontSize, fontWeight, padX, minWidth, maxWidth) {
  const textWidth = svgPretextWidth(node, label, fontSize, fontWeight);
  return Math.min(maxWidth, Math.max(minWidth, textWidth + padX * 2));
}

function nodeBox(d, extraX = 12, extraY = 8, includeVisualScale = true) {
  const label = normalizeLabel(d.label);
  const fontSize = d.key === ROOT_KEY ? 17 : 15;
  const fontWeight = graphNodeFontWeight(d);
  const scale = includeVisualScale && d.key === currentKey ? CURRENT_NODE_SCALE : 1;
  const padX = isCompact() ? 12 : 14;
  const padY = isCompact() ? 5 : 6;
  const w = pillWidthFromPretext(d, label, fontSize, fontWeight, padX, 1, Number.POSITIVE_INFINITY);
  const h = fontSize + padY * 2;
  return {
    w: w * scale + extraX,
    h: h * scale + extraY,
  };
}

function nodeBoundaryPoint(node, toward) {
  const nodeX = nodeRenderX(node);
  const nodeY = nodeRenderY(node);
  const towardX = nodeRenderX(toward);
  const towardY = nodeRenderY(toward);
  const dx = towardX - nodeX;
  const dy = towardY - nodeY;
  const len = Math.hypot(dx, dy);
  if (len < 0.001) return { x: nodeX, y: nodeY };

  const ux = dx / len;
  const uy = dy / len;
  const box = nodeBox(node, -10, -8, true);
  const rx = Math.max(1, box.w / 2);
  const ry = Math.max(1, box.h / 2);
  const boundary = 1 / Math.sqrt((ux * ux) / (rx * rx) + (uy * uy) / (ry * ry));
  const strokeClearance = -2.5;

  return {
    x: nodeX + ux * (boundary + strokeClearance),
    y: nodeY + uy * (boundary + strokeClearance),
  };
}

function edgeEndpoints(from, to) {
  return {
    start: nodeBoundaryPoint(from, to),
    end: nodeBoundaryPoint(to, from),
  };
}

function isSelectedFloatingNode(d) {
  return d.key === currentKey && d.edgeLengthAnim && !d.edgeLengthAnim.done;
}

function shouldReleaseSelectedCollision(d) {
  if (d.key !== currentKey || !d.edgeLengthAnim) return false;
  if (d.edgeLengthAnim.done) return false;
  const elapsed = Date.now() - d.edgeLengthAnim.startedAt;
  const progress = elapsed / SELECTED_EDGE_LENGTHEN_MS;
  return (
    progress >= SELECTED_COLLISION_RELEASE_START_RATIO &&
    progress < SELECTED_COLLISION_RELEASE_END_RATIO
  );
}

function collisionBox(d, extraX = 12, extraY = 8) {
  if (d.isTracePathNode && d.parentKey !== currentKey) {
    const box = nodeBox(d, extraX, extraY);
    return {
      w: box.w * TRACE_INTERMEDIATE_COLLISION_SCALE,
      h: box.h * TRACE_INTERMEDIATE_COLLISION_SCALE,
    };
  }
  if (isSelectedFloatingNode(d)) {
    const size = isCompact() ? 42 : 54;
    return { w: size + extraX, h: size + extraY };
  }
  return nodeBox(d, extraX, extraY);
}

function lineRepulsionBox(d) {
  if (d.isTracePathNode && d.parentKey !== currentKey) {
    const box = nodeBox(d, 0, 0, false);
    return {
      w: box.w * 2,
      h: box.h * 2,
    };
  }
  return nodeBox(d, NODE_LINE_CLEARANCE * 2, NODE_LINE_CLEARANCE * 1.5, false);
}

function isCollisionAnchored(d) {
  return d.key === ROOT_KEY || d.key === currentKey || d.fx != null || d.fy != null;
}

function collisionShares(a, b) {
  const aFocusedChild = a.parentKey === currentKey;
  const bFocusedChild = b.parentKey === currentKey;
  if (aFocusedChild && bFocusedChild) {
    const ai = Math.max(0, a.siblingIndex ?? 0) + 1;
    const bi = Math.max(0, b.siblingIndex ?? 0) + 1;
    const total = ai + bi;
    return {
      aShare: total ? ai / total : 0.5,
      bShare: total ? bi / total : 0.5,
    };
  }

  const aFixed = isCollisionAnchored(a);
  const bFixed = isCollisionAnchored(b);
  if (aFixed && bFixed) return { aShare: 0, bShare: 0 };
  if (aFixed) return { aShare: 0, bShare: 1 };
  if (bFixed) return { aShare: 1, bShare: 0 };

  const aPending = a.isRevealed === false;
  const bPending = b.isRevealed === false;
  if (aPending && !bPending) return { aShare: 1, bShare: 0 };
  if (bPending && !aPending) return { aShare: 0, bShare: 1 };

  return { aShare: 0.5, bShare: 0.5 };
}

function forceRectCollide() {
  let forceNodes = [];
  const strength = 1.22;
  const iterations = 4;

  function force(alpha) {
    const boxes = forceNodes.map(d => collisionBox(d, 24, 16));
    const push = strength * alpha;

    for (let iter = 0; iter < iterations; iter++) {
      for (let i = 0; i < forceNodes.length; i++) {
        const a = forceNodes[i];
        if (shouldReleaseSelectedCollision(a)) continue;
        const abox = boxes[i];
        for (let j = i + 1; j < forceNodes.length; j++) {
          const b = forceNodes[j];
          if (shouldReleaseSelectedCollision(b)) continue;
          const bbox = boxes[j];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
            dx = Math.cos((i + 1) * 12.9898 + (j + 1) * 78.233);
            dy = Math.sin((i + 1) * 39.3468 + (j + 1) * 11.135);
          }

          const overlapX = (abox.w + bbox.w) / 2 - Math.abs(dx);
          if (overlapX <= 0) continue;
          const overlapY = (abox.h + bbox.h) / 2 - Math.abs(dy);
          if (overlapY <= 0) continue;

          const { aShare, bShare } = collisionShares(a, b);

          if (overlapX < overlapY) {
            const sx = (dx < 0 ? -1 : 1) * overlapX * push;
            a.vx -= sx * aShare;
            b.vx += sx * bShare;
          } else {
            const sy = (dy < 0 ? -1 : 1) * overlapY * push;
            a.vy -= sy * aShare;
            b.vy += sy * bShare;
          }
        }
      }
    }
  }

  force.initialize = nextNodes => {
    forceNodes = nextNodes;
  };

  return force;
}

function resolveRectCollisions(renderNodes, strength = 1) {
  const boxes = renderNodes.map(d => collisionBox(d, 24, 16));
  const correctionStrength = clamp(strength, 0.08, 1);

  for (let i = 0; i < renderNodes.length; i++) {
    const a = renderNodes[i];
    if (shouldReleaseSelectedCollision(a)) continue;
    const abox = boxes[i];
    for (let j = i + 1; j < renderNodes.length; j++) {
      const b = renderNodes[j];
      if (shouldReleaseSelectedCollision(b)) continue;
      const bbox = boxes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
        dx = Math.cos((i + 1) * 12.9898 + (j + 1) * 78.233);
        dy = Math.sin((i + 1) * 39.3468 + (j + 1) * 11.135);
      }

      const overlapX = (abox.w + bbox.w) / 2 - Math.abs(dx);
      if (overlapX <= 0) continue;
      const overlapY = (abox.h + bbox.h) / 2 - Math.abs(dy);
      if (overlapY <= 0) continue;

      const { aShare, bShare } = collisionShares(a, b);

      if (overlapX < overlapY) {
        const sx = (dx < 0 ? -1 : 1) * (overlapX + 0.6) * correctionStrength;
        a.x -= sx * aShare;
        b.x += sx * bShare;
      } else {
        const sy = (dy < 0 ? -1 : 1) * (overlapY + 0.6) * correctionStrength;
        a.y -= sy * aShare;
        b.y += sy * bShare;
      }
    }
  }
}

function slotClusterParent(node, spine) {
  if (!node || node.key === ROOT_KEY || node.key === currentKey) return null;
  if (node.isTraceOnly || node.isTracePathNode) return null;
  if (!node.parentKey || spine.has(node.key)) return null;

  const parent = nodes.get(node.parentKey);
  if (!parent || parent.key === ROOT_KEY || !spine.has(parent.key)) return null;
  return parent;
}

function tracePressureNode(node, spine, activeTraceParents) {
  if (!node || node.key === ROOT_KEY || node.key === currentKey) return null;
  if (!node.isTracePathNode && !node.isTraceParent) return null;
  if (!isBacktraceParentNode(node, spine, activeTraceParents)) return null;
  return node;
}

function activeTraceSegments() {
  const result = [];
  const anchors = activeTraceAnchorKeys();
  for (const edge of edges) {
    if ((!edge.isTracePath && !edge.isTraceLink) || !isVisibleLineEdge(edge)) continue;
    if (!hasCurrentTraceAnchor(edge)) continue;
    if (edge.isTraceLink && !anchors.has(edge.to)) continue;
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to) continue;
    result.push({
      edge,
      from,
      to,
      key: graphEdgeKey(edge),
      ax: from.homeX,
      ay: from.homeY,
      bx: to.homeX,
      by: to.homeY,
    });
  }
  return result;
}

function activeTraceCircleSegments(traceSegments) {
  if (!traceSegments.length) return traceSegments;

  const result = [...traceSegments];
  for (const key of activeTraceTargetKeys()) {
    const target = nodes.get(key);
    const parent = target?.parentKey ? nodes.get(target.parentKey) : null;
    if (!target || !parent) continue;
    const edge = edges.find(e =>
      !e.isTracePath &&
      !e.isTraceLink &&
      !e.isTrimming &&
      e.from === parent.key &&
      e.to === target.key
    );
    if (!edge || result.some(segment => segment.key === graphEdgeKey(edge))) continue;
    result.push({
      edge,
      from: parent,
      to: target,
      key: graphEdgeKey(edge),
      passiveCircleSource: true,
      ax: parent.homeX,
      ay: parent.homeY,
      bx: target.homeX,
      by: target.homeY,
    });
  }

  return result;
}

function pointToHomeSegmentPressure(node, segment) {
  if (node.key === segment.from.key || node.key === segment.to.key) return 0;
  const vx = segment.bx - segment.ax;
  const vy = segment.by - segment.ay;
  const len = Math.hypot(vx, vy);
  if (len < 1) return 0;
  const ux = vx / len;
  const uy = vy / len;
  const px = -uy;
  const py = ux;
  const dx = node.homeX - segment.ax;
  const dy = node.homeY - segment.ay;
  const along = dx * ux + dy * uy;
  if (along <= 18 || along >= len - 18) return 0;
  const lateral = dx * px + dy * py;
  const box = collisionBox(node, TRACE_LINE_CLEARANCE, TRACE_LINE_CLEARANCE);
  const limit = projectedBoxRadius(box, px, py) + NODE_LINE_CLEARANCE;
  return Math.max(0, limit - Math.abs(lateral));
}

function pointSegmentDistance(px, py, ax, ay, bx, by) {
  const vx = bx - ax;
  const vy = by - ay;
  const len2 = vx * vx + vy * vy;
  if (len2 < 1) return Math.hypot(px - ax, py - ay);
  const t = clamp(((px - ax) * vx + (py - ay) * vy) / len2, 0, 1);
  return Math.hypot(px - (ax + vx * t), py - (ay + vy * t));
}

function orientation(ax, ay, bx, by, cx, cy) {
  return (by - ay) * (cx - bx) - (bx - ax) * (cy - by);
}

function homeSegmentsIntersect(a, b) {
  const o1 = orientation(a.ax, a.ay, a.bx, a.by, b.ax, b.ay);
  const o2 = orientation(a.ax, a.ay, a.bx, a.by, b.bx, b.by);
  const o3 = orientation(b.ax, b.ay, b.bx, b.by, a.ax, a.ay);
  const o4 = orientation(b.ax, b.ay, b.bx, b.by, a.bx, a.by);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

function traceSegmentPressure(a, b) {
  if (segmentsShareNode(a, b)) return 0;
  const minDistance = Math.min(
    pointSegmentDistance(a.ax, a.ay, b.ax, b.ay, b.bx, b.by),
    pointSegmentDistance(a.bx, a.by, b.ax, b.ay, b.bx, b.by),
    pointSegmentDistance(b.ax, b.ay, a.ax, a.ay, a.bx, a.by),
    pointSegmentDistance(b.bx, b.by, a.ax, a.ay, a.bx, a.by)
  );
  const clearance = TRACE_LINE_CLEARANCE * 1.4;
  return homeSegmentsIntersect(a, b)
    ? clearance
    : Math.max(0, clearance - minDistance);
}

function traceSegmentRepulsionCircles(segment) {
  const dx = segment.bx - segment.ax;
  const dy = segment.by - segment.ay;
  const len = Math.hypot(dx, dy);
  if (len < TRACE_LINE_CIRCLE_SPACING * 0.72) return [];

  const sampleCount = Math.max(
    1,
    Math.min(TRACE_LINE_CIRCLE_MAX_SAMPLES, Math.floor(len / TRACE_LINE_CIRCLE_SPACING))
  );
  const circles = [];
  for (let i = 1; i <= sampleCount; i++) {
    const t = i / (sampleCount + 1);
    circles.push({
      x: segment.ax + dx * t,
      y: segment.ay + dy * t,
      segment,
    });
  }
  return circles;
}

function addTraceLineCirclePressures(segmentPressure, traceSegments) {
  const diameter = TRACE_LINE_CIRCLE_RADIUS * 2;
  const cellSize = diameter;
  const grid = new Map();
  const segmentOverlaps = new Map();
  let maxOverlap = 0;

  const cellKey = (x, y) => `${Math.floor(x / cellSize)},${Math.floor(y / cellSize)}`;
  const addSample = sample => {
    const gx = Math.floor(sample.x / cellSize);
    const gy = Math.floor(sample.y / cellSize);

    for (let ox = -1; ox <= 1; ox++) {
      for (let oy = -1; oy <= 1; oy++) {
        const bucket = grid.get(`${gx + ox},${gy + oy}`);
        if (!bucket) continue;

        for (const other of bucket) {
          if (segmentsShareNode(sample.segment, other.segment)) continue;
          const distance = Math.hypot(other.x - sample.x, other.y - sample.y);
          const overlap = diameter - distance;
          if (overlap <= LAYOUT_PRESSURE_MIN_OVERLAP) continue;
          const softened = overlap / diameter;
          const pressure = overlap * (0.42 + softened * 0.58);
          maxOverlap = Math.max(maxOverlap, pressure);
          if (!sample.segment.passiveCircleSource) {
            addPressure(segmentOverlaps, sample.segment.key, pressure);
          }
          if (!other.segment.passiveCircleSource) {
            addPressure(segmentOverlaps, other.segment.key, pressure);
          }
        }
      }
    }

    const key = cellKey(sample.x, sample.y);
    const bucket = grid.get(key) || [];
    bucket.push(sample);
    grid.set(key, bucket);
  };

  for (const segment of traceSegments) {
    for (const sample of traceSegmentRepulsionCircles(segment)) {
      addSample(sample);
    }
  }

  for (const [key, pressure] of segmentOverlaps) {
    const overlap = pressure - LAYOUT_PRESSURE_MIN_OVERLAP;
    if (overlap <= 0) continue;
    addPressure(segmentPressure, key, overlap * TRACE_LINE_CIRCLE_REPEL_GAIN);
  }

  return Math.max(0, maxOverlap - LAYOUT_PRESSURE_MIN_OVERLAP);
}

function traceLineCirclePressure(a, b) {
  if (segmentsShareNode(a, b)) return 0;

  const circlesA = traceSegmentRepulsionCircles(a);
  const circlesB = traceSegmentRepulsionCircles(b);
  if (!circlesA.length || !circlesB.length) return 0;

  const diameter = TRACE_LINE_CIRCLE_RADIUS * 2;
  let pressure = 0;
  for (const ca of circlesA) {
    for (const cb of circlesB) {
      const distance = Math.hypot(cb.x - ca.x, cb.y - ca.y);
      const overlap = diameter - distance;
      if (overlap <= 0) continue;
      const softened = overlap / diameter;
      pressure = Math.max(pressure, overlap * (0.42 + softened * 0.58));
    }
  }

  return pressure;
}

function addPressure(map, key, value) {
  if (!key || value <= 0) return;
  map.set(key, Math.max(map.get(key) || 0, value));
}

function addAdjacentTraceSegmentPressure(segmentPressure, traceSegments, node, overlap, gain = 1, excludeKey = null) {
  if (!node?.key || overlap <= 0) return;
  for (const segment of traceSegments) {
    if (segment.key === excludeKey) continue;
    if (segment.from.key !== node.key && segment.to.key !== node.key) continue;
    addPressure(
      segmentPressure,
      segment.key,
      overlap * TRACE_ADJACENT_LINE_GROW_GAIN * gain
    );
  }
}

function nextPressureBoost(current, target, maxBoost) {
  const value = current || 0;
  const next = target > value
    ? value + (target - value) * LAYOUT_PRESSURE_GROWTH
    : value * LAYOUT_PRESSURE_DECAY;
  return next < LAYOUT_PRESSURE_EPSILON ? 0 : Math.min(maxBoost, next);
}

function nextTraceSegmentBoost(edge, target, maxBoost) {
  const value = edge.layoutTraceSegmentBoost || 0;
  const activeTarget = target || 0;
  if (activeTarget > value) {
    edge.layoutTraceSegmentQuietTicks = 0;
    const next = value + (activeTarget - value) * TRACE_SEGMENT_PRESSURE_GROWTH;
    return next < LAYOUT_PRESSURE_EPSILON ? 0 : Math.min(maxBoost, next);
  }

  if (activeTarget > LAYOUT_PRESSURE_EPSILON) {
    edge.layoutTraceSegmentQuietTicks = 0;
    return Math.min(maxBoost, Math.max(activeTarget, value * 0.996));
  }

  edge.layoutTraceSegmentQuietTicks = (edge.layoutTraceSegmentQuietTicks || 0) + 1;
  if (edge.layoutTraceSegmentQuietTicks <= TRACE_SEGMENT_PRESSURE_HOLD_TICKS) {
    return value;
  }

  const next = value * TRACE_SEGMENT_PRESSURE_DECAY;
  return next < LAYOUT_PRESSURE_EPSILON ? 0 : Math.min(maxBoost, next);
}

function pressureRelayoutChanged(owner, appliedKey, nextValue) {
  const applied = owner[appliedKey] ?? 0;
  if (
    Math.abs(applied - nextValue) <= LAYOUT_PRESSURE_RELAYOUT_EPSILON &&
    !(applied > 0 && nextValue === 0)
  ) {
    return false;
  }
  owner[appliedKey] = nextValue;
  return true;
}

function refreshHomeForces() {
  if (!sim) return;
  const fx = sim.force("homeX");
  const fy = sim.force("homeY");
  if (fx?.x) fx.x(d => d.homeX);
  if (fy?.y) fy.y(d => d.homeY);
}

function nodeLinePressure(node, edge) {
  if (edge.from === node.key || edge.to === node.key) return 0;
  const from = nodes.get(edge.from);
  const to = nodes.get(edge.to);
  if (!from || !to) return 0;

  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy);
  if (len < 1) return 0;

  const ux = dx / len;
  const uy = dy / len;
  const px = -uy;
  const py = ux;
  const nx = node.x - from.x;
  const ny = node.y - from.y;
  const along = nx * ux + ny * uy;
  if (along <= 18 || along >= len - 18) return 0;

  const lateral = nx * px + ny * py;
  const box = lineRepulsionBox(node);
  const limit = projectedBoxRadius(box, px, py) + NODE_LINE_CLEARANCE;
  return Math.max(0, limit - Math.abs(lateral));
}

function applyLayoutPressure(renderNodes) {
  const activeNodes = renderNodes.filter(node =>
    !node.isTrimming &&
    node.isRevealed !== false
  );
  const boxes = activeNodes.map(node => collisionBox(node, 18, 10));
  const spine = getSpine();
  const activeTraceParents = activeTraceParentKeys(spine);
  const tracePressure = new Map();
  const segmentPressure = new Map();
  const traceSegments = activeTraceSegments();
  let maxOverlap = 0;

  for (let i = 0; i < activeNodes.length; i++) {
    const a = activeNodes[i];
    const abox = boxes[i];
    for (let j = i + 1; j < activeNodes.length; j++) {
      const b = activeNodes[j];
      const bbox = boxes[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const overlapX = (abox.w + bbox.w) / 2 - Math.abs(dx);
      if (overlapX <= LAYOUT_PRESSURE_MIN_OVERLAP) continue;
      const overlapY = (abox.h + bbox.h) / 2 - Math.abs(dy);
      if (overlapY <= LAYOUT_PRESSURE_MIN_OVERLAP) continue;

      const overlap = Math.min(overlapX, overlapY) - LAYOUT_PRESSURE_MIN_OVERLAP;
      maxOverlap = Math.max(maxOverlap, overlap);

      const aTrace = tracePressureNode(a, spine, activeTraceParents);
      const bTrace = tracePressureNode(b, spine, activeTraceParents);

      if (aTrace && isTraceGraphNode(b)) continue;
      if (bTrace && isTraceGraphNode(a)) continue;

      if (aTrace) {
        addPressure(tracePressure, aTrace.key, overlap * TRACE_LAYOUT_PRESSURE_GAIN);
      }

      if (bTrace) {
        addPressure(tracePressure, bTrace.key, overlap * TRACE_LAYOUT_PRESSURE_GAIN);
      }
    }
  }

  const activeEdges = edges.filter(edge =>
    isVisibleLineEdge(edge) &&
    !edge.isTracePath &&
    !edge.isTraceLink
  );
  for (const node of activeNodes) {
    const traceNode = tracePressureNode(node, spine, activeTraceParents);
    if (!traceNode) continue;
    for (const edge of activeEdges) {
      const pressure = nodeLinePressure(traceNode, edge);
      if (pressure <= LAYOUT_PRESSURE_MIN_OVERLAP) continue;
      const overlap = pressure - LAYOUT_PRESSURE_MIN_OVERLAP;
      maxOverlap = Math.max(maxOverlap, overlap);
      addPressure(tracePressure, traceNode.key, overlap * TRACE_LINE_PRESSURE_GAIN);
      addAdjacentTraceSegmentPressure(segmentPressure, traceSegments, traceNode, overlap, 1.25);
    }
  }

  for (const segment of traceSegments) {
    for (const node of activeNodes) {
      const pressure = pointToHomeSegmentPressure(node, segment);
      if (pressure <= LAYOUT_PRESSURE_MIN_OVERLAP) continue;
      const overlap = pressure - LAYOUT_PRESSURE_MIN_OVERLAP;
      maxOverlap = Math.max(maxOverlap, overlap);
      addPressure(segmentPressure, segment.key, overlap * TRACE_LINE_PRESSURE_GAIN);
      const traceNode = tracePressureNode(node, spine, activeTraceParents);
      if (traceNode) {
        addAdjacentTraceSegmentPressure(segmentPressure, traceSegments, traceNode, overlap, 1.05, segment.key);
      }
    }
  }

  for (let i = 0; i < traceSegments.length; i++) {
    for (let j = i + 1; j < traceSegments.length; j++) {
      const pressure = traceSegmentPressure(traceSegments[i], traceSegments[j]);
      if (pressure <= LAYOUT_PRESSURE_MIN_OVERLAP) continue;
      const overlap = pressure - LAYOUT_PRESSURE_MIN_OVERLAP;
      maxOverlap = Math.max(maxOverlap, overlap);
      addPressure(segmentPressure, traceSegments[i].key, overlap * TRACE_LAYOUT_PRESSURE_GAIN);
      addPressure(segmentPressure, traceSegments[j].key, overlap * TRACE_LAYOUT_PRESSURE_GAIN);
    }
  }

  const circleMaxOverlap = addTraceLineCirclePressures(
    segmentPressure,
    activeTraceCircleSegments(traceSegments)
  );
  maxOverlap = Math.max(maxOverlap, circleMaxOverlap);

  const baseLen = edgeBaseLength();
  const maxTraceBoost = baseLen * 1.75;
  let changed = false;

  for (const node of nodes.values()) {
    const nextTrace = nextPressureBoost(
      node.layoutTraceBoost,
      tracePressure.get(node.key) || 0,
      maxTraceBoost
    );

    if (node.layoutClusterBoost || node.layoutEdgeBoost) {
      node.layoutClusterBoost = 0;
      node.layoutEdgeBoost = 0;
      changed = true;
    }

    node.layoutTraceBoost = nextTrace;
    if (pressureRelayoutChanged(node, "layoutTraceBoostApplied", nextTrace)) {
      changed = true;
    }
  }

  for (const edge of edges) {
    const nextSegment = nextTraceSegmentBoost(
      edge,
      segmentPressure.get(graphEdgeKey(edge)) || 0,
      maxTraceBoost
    );

    if (edge.layoutTraceBoost) {
      edge.layoutTraceBoost = 0;
      changed = true;
    }

    edge.layoutTraceSegmentBoost = nextSegment;
    if (pressureRelayoutChanged(edge, "layoutTraceSegmentBoostApplied", nextSegment)) {
      changed = true;
    }
  }

  layoutPressureDebug.maxOverlap = Math.round(maxOverlap);
  layoutPressureDebug.traceLineCircleOverlap = Math.round(circleMaxOverlap);
  layoutPressureDebug.clusterBoosts = [...nodes.values()]
    .filter(node => (node.layoutClusterBoost || 0) > 0)
    .map(node => ({ label: node.label, boost: Math.round(node.layoutClusterBoost) }))
    .sort((a, b) => b.boost - a.boost)
    .slice(0, 8);
  layoutPressureDebug.edgeBoosts = [...nodes.values()]
    .filter(node => (node.layoutEdgeBoost || 0) > 0)
    .map(node => ({ label: node.label, boost: Math.round(node.layoutEdgeBoost) }))
    .sort((a, b) => b.boost - a.boost)
    .slice(0, 8);
  layoutPressureDebug.traceBoosts = [...nodes.values()]
    .filter(node => (node.layoutTraceBoost || 0) > 0)
    .map(node => ({ label: node.label, boost: Math.round(node.layoutTraceBoost) }))
    .sort((a, b) => b.boost - a.boost)
    .slice(0, 8);
  layoutPressureDebug.traceSegments = [...edges]
    .filter(edge => (edge.layoutTraceSegmentBoost || 0) > 0)
    .map(edge => ({
      from: nodes.get(edge.from)?.label || "",
      to: nodes.get(edge.to)?.label || "",
      boost: Math.round(edge.layoutTraceSegmentBoost),
    }))
    .sort((a, b) => b.boost - a.boost)
    .slice(0, 10);

  if (changed) {
    recomputeLayout();
    refreshHomeForces();
  }

  return changed;
}

function applyTraceLineCollisions(renderNodes) {
  const activeNodes = renderNodes.filter(node => !node.isTrimming && node.isRevealed !== false);

  for (const edge of edges) {
    if ((!edge.isTracePath && !edge.isTraceLink) || edge.isTrimming || edge.isRevealed === false) {
      continue;
    }

    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to || from.isTrimming || to.isTrimming) continue;

    const movable = to.isTraceOnly ? to : (from.isTraceOnly ? from : null);
    if (!movable || movable.fx != null || movable.fy != null) continue;

    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const len = Math.hypot(dx, dy);
    if (len < 1) continue;

    const ux = dx / len;
    const uy = dy / len;
    const px = -uy;
    const py = ux;
    const moveSign = movable === to ? 1 : -1;
    let alongPush = 0;
    let sidePush = 0;

    for (const node of activeNodes) {
      if (node.key === from.key || node.key === to.key) continue;
      if (isTraceGraphNode(node)) continue;

      const nx = node.x - from.x;
      const ny = node.y - from.y;
      const along = nx * ux + ny * uy;
      if (along <= 16 || along >= len - 16) continue;

      const lateral = nx * px + ny * py;
      const box = collisionBox(node, TRACE_LINE_CLEARANCE, TRACE_LINE_CLEARANCE);
      const limit = projectedBoxRadius(box, px, py);
      const overlap = limit - Math.abs(lateral);
      if (overlap <= 0) continue;

      const centered = 1 - Math.abs(along / len - 0.5);
      alongPush = Math.max(alongPush, overlap * (0.14 + centered * 0.16));
      sidePush += (lateral >= 0 ? -1 : 1) * overlap * (0.18 + centered * 0.20);
    }

    if (!alongPush && !sidePush) continue;

    const cappedAlong = Math.min(8, alongPush);
    const cappedSide = clamp(sidePush, -10, 10);
    movable.x += ux * cappedAlong * moveSign + px * cappedSide;
    movable.y += uy * cappedAlong * moveSign + py * cappedSide;
    movable.vx = (movable.vx || 0) * 0.45;
    movable.vy = (movable.vy || 0) * 0.45;
  }
}

function isVisibleLineEdge(edge) {
  if (edge.isTrimming || edge.isRevealed === false) return false;
  const from = nodes.get(edge.from);
  const to = nodes.get(edge.to);
  if (!from || !to) return false;
  if (from.isTrimming || to.isTrimming) return false;
  if (from.isRevealed === false || to.isRevealed === false) return false;
  return true;
}

function applyNodeLineRepulsion(renderNodes) {
  const spine = getSpine();
  const activeTraceParents = activeTraceParentKeys(spine);
  const activeNodes = renderNodes.filter(node =>
    !node.isTrimming &&
    node.isRevealed !== false &&
    node.key !== ROOT_KEY &&
    node.key !== currentKey &&
    node.parentKey !== currentKey &&
    node.isTracePathNode &&
    isBacktraceParentNode(node, spine, activeTraceParents) &&
    node.fx == null &&
    node.fy == null
  );
  const activeEdges = edges.filter(edge =>
    isVisibleLineEdge(edge) &&
    !edge.isTracePath &&
    !edge.isTraceLink
  );

  for (const node of activeNodes) {
    let pushX = 0;
    let pushY = 0;

    for (const edge of activeEdges) {
      if (edge.from === node.key || edge.to === node.key) continue;

      const from = nodes.get(edge.from);
      const to = nodes.get(edge.to);
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const len = Math.hypot(dx, dy);
      if (len < 1) continue;

      const ux = dx / len;
      const uy = dy / len;
      const px = -uy;
      const py = ux;
      const nx = node.x - from.x;
      const ny = node.y - from.y;
      const along = nx * ux + ny * uy;
      if (along <= 18 || along >= len - 18) continue;

      const lateral = nx * px + ny * py;
      const box = lineRepulsionBox(node);
      const limit = projectedBoxRadius(box, px, py) + NODE_LINE_CLEARANCE;
      const overlap = limit - Math.abs(lateral);
      if (overlap <= 0) continue;

      const side = lateral >= 0 ? 1 : -1;
      const centered = 1 - Math.abs(along / len - 0.5);
      const push = overlap * NODE_LINE_REPEL_STRENGTH * (0.72 + centered * 0.36);
      pushX += px * side * push;
      pushY += py * side * push;
    }

    if (!pushX && !pushY) continue;
    const mag = Math.hypot(pushX, pushY);
    const cap = node.isTracePathNode ? 18 : 12;
    const scale = mag > cap ? cap / mag : 1;
    node.x += pushX * scale;
    node.y += pushY * scale;
    node.vx = (node.vx || 0) * 0.42;
    node.vy = (node.vy || 0) * 0.42;
  }
}

function homeStrength(d) {
  if (d.key === ROOT_KEY) return 1;
  if (isSelectedFloatingNode(d)) return 0;
  if (d.key === currentKey) return d.isClearingCluster ? 0.20 : 0.12;
  if (d.parentKey === currentKey) return 0.085;
  return 0.20;
}

function rebuildSim() {
  if (sim) sim.stop();
  sim = forceSimulation([...nodes.values()])
    .force("homeX", forceX(d => d.homeX).strength(homeStrength))
    .force("homeY", forceY(d => d.homeY).strength(homeStrength))
    .force("collide", forceRectCollide())
    .velocityDecay(prefersReducedMotion() ? 0.82 : 0.55)
    .alphaDecay(prefersReducedMotion() ? 0.04 : 0.012)
    .alphaMin(0.002)
    .stop();
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function ensureTickLoop() {
  if (tickTimer) return;
  if (timelineMode) return;
  markGraphMoving();
  tickTimer = setInterval(() => {
    if (timelineMode) {
      clearInterval(tickTimer);
      tickTimer = null;
      setGraphStill(true);
      return;
    }
    if (!sim) {
      clearInterval(tickTimer);
      tickTimer = null;
      setGraphStill(true);
      return;
    }
    updateLengtheningLayouts();
    sim.tick();
    floatSelectedNodeToTarget();
    if (followMode) {
      const cur = nodes.get(currentKey);
      if (cur) {
        const targetTx = focusX() - cur.x * viewScale;
        const targetTy = focusY() - cur.y * viewScale;
        const dx = targetTx - viewTx;
        const dy = targetTy - viewTy;
        const lerp = prefersReducedMotion() ? 0.18 : 0.07;
        viewTx += dx * lerp;
        viewTy += dy * lerp;
        writeWorldTransform();
        if (Math.abs(dx) < 0.4 && Math.abs(dy) < 0.4) followMode = false;
      }
    }
    renderTick();
    if (!followMode && sim.alpha() <= sim.alphaMin() * 1.25) {
      sim.stop();
      clearInterval(tickTimer);
      tickTimer = null;
      setGraphStill(true);
    }
  }, prefersReducedMotion() ? 32 : 16);
}

function bumpSim(alpha = 0.7) {
  if (!sim) return;
  if (timelineMode) return;
  markGraphMoving();
  sim.stop();
  sim.alpha(prefersReducedMotion() ? Math.min(alpha, 0.25) : alpha);
  ensureTickLoop();
}

function outwardUnit(d, parent = null) {
  let ux = d.homeX - (parent?.homeX ?? 0);
  let uy = d.homeY - (parent?.homeY ?? 0);
  let len = Math.hypot(ux, uy);
  if (len < 0.001) {
    ux = Math.cos(d.angle || 0);
    uy = Math.sin(d.angle || 0);
    len = Math.hypot(ux, uy) || 1;
  }
  return { ux: ux / len, uy: uy / len };
}

function clampToOutwardCorridor(d, originX, originY, ux, uy, limits) {
  const dx = d.x - originX;
  const dy = d.y - originY;
  const along = dx * ux + dy * uy;
  const lx = dx - ux * along;
  const ly = dy - uy * along;
  const lateral = Math.hypot(lx, ly);

  const nextAlong = Math.max(limits.minAlong, Math.min(limits.maxAlong, along));
  let nextLx = lx;
  let nextLy = ly;
  if (lateral > limits.maxLateral) {
    const ratio = limits.maxLateral / lateral;
    nextLx *= ratio;
    nextLy *= ratio;
  }

  if (nextAlong !== along || nextLx !== lx || nextLy !== ly) {
    d.x = originX + ux * nextAlong + nextLx;
    d.y = originY + uy * nextAlong + nextLy;
    d.vx *= 0.35;
    d.vy *= 0.35;
  }
}

function softenFocusedChildEdgePressure(d, parent, ux, uy, baseLen) {
  const rankT = Math.max(0, Math.min(1, (d.siblingIndex ?? 0) / Math.max(1, (d.siblingTotal ?? 1) - 1)));
  const homeDx = d.x - d.homeX;
  const homeDy = d.y - d.homeY;
  const homeAlong = homeDx * ux + homeDy * uy;
  const homeLx = homeDx - ux * homeAlong;
  const homeLy = homeDy - uy * homeAlong;
  const homeLateral = Math.hypot(homeLx, homeLy);
  const homeMaxLateral = baseLen * (0.42 + rankT * 0.58);

  if (homeAlong < -baseLen * 0.55) {
    const push = (-baseLen * 0.55 - homeAlong) * 0.08;
    d.x += ux * push;
    d.y += uy * push;
  }

  if (homeLateral > homeMaxLateral) {
    const pull = (homeLateral - homeMaxLateral) * 0.12;
    d.x -= (homeLx / homeLateral) * pull;
    d.y -= (homeLy / homeLateral) * pull;
  }

  if (!parent) return;

  const parentDx = d.x - parent.x;
  const parentDy = d.y - parent.y;
  const parentAlong = parentDx * ux + parentDy * uy;
  const parentLx = parentDx - ux * parentAlong;
  const parentLy = parentDy - uy * parentAlong;
  const parentLateral = Math.hypot(parentLx, parentLy);
  const expected = Math.max(1, Math.hypot(d.homeX - parent.homeX, d.homeY - parent.homeY));
  const minAlong = expected * 0.18;
  const maxAlong = expected * (1.12 + rankT * 0.72);
  const parentMaxLateral = Math.max(baseLen * 0.44, expected * (0.70 + rankT * 0.62));

  if (parentAlong < minAlong) {
    const push = (minAlong - parentAlong) * 0.10;
    d.x += ux * push;
    d.y += uy * push;
  }

  if (parentAlong > maxAlong) {
    const pull = (parentAlong - maxAlong) * 0.14;
    d.x -= ux * pull;
    d.y -= uy * pull;
  }

  if (parentLateral > parentMaxLateral) {
    const pull = (parentLateral - parentMaxLateral) * 0.10;
    d.x -= (parentLx / parentLateral) * pull;
    d.y -= (parentLy / parentLateral) * pull;
  }
}

function limitNodeStretch(d) {
  if (d.key === ROOT_KEY || d.fx != null || d.fy != null) return;

  const parent = d.parentKey ? nodes.get(d.parentKey) : null;
  const baseLen = edgeBaseLength();
  const { ux, uy } = outwardUnit(d, parent);
  const isFocusedChild = d.parentKey === currentKey;
  const spine = getSpine();
  const isActiveSpineNode = spine.has(d.key) && d.key !== ROOT_KEY;
  const current = nodes.get(currentKey);
  const isClearingSibling =
    current?.isClearingCluster &&
    current.parentKey &&
    d.parentKey === current.parentKey &&
    d.key !== currentKey;

  if (isFocusedChild || isActiveSpineNode) {
    softenFocusedChildEdgePressure(d, parent, ux, uy, baseLen);
    return;
  }

  if (parent && isClearingSibling) {
    const expected = Math.max(1, Math.hypot(d.homeX - parent.homeX, d.homeY - parent.homeY));
    const maxAlong = Math.max(1, d.clearLengthCap || expected);
    clampToOutwardCorridor(d, parent.x, parent.y, ux, uy, {
      minAlong: expected * 0.38,
      maxAlong,
      maxLateral: d.clearLateralCap || baseLen * 0.36,
    });
    return;
  }

  clampToOutwardCorridor(d, d.homeX, d.homeY, ux, uy, {
    minAlong: -(isFocusedChild ? baseLen * 0.60 : baseLen * 0.35),
    maxAlong: isFocusedChild ? Number.POSITIVE_INFINITY : baseLen * 1.35,
    maxLateral: isFocusedChild ? baseLen * 1.05 : baseLen * 0.48,
  });

  if (!parent) return;

  const expected = Math.max(1, Math.hypot(d.homeX - parent.homeX, d.homeY - parent.homeY));
  clampToOutwardCorridor(d, parent.x, parent.y, ux, uy, {
    minAlong: expected * 0.52,
    maxAlong: isFocusedChild ? Number.POSITIVE_INFINITY : expected * 1.85,
    maxLateral: isFocusedChild ? baseLen * 1.10 : baseLen * 0.56,
  });
}

let nodeEls = new Map();
let edgeEls = new Map();
let edgeGradientEls = new Map();

function graphEdgeKey(edge) {
  return edge.key || `${edge.from}|${edge.to}`;
}

function renderQuantum() {
  const dpr = Number(window.devicePixelRatio) || 1;
  return 1 / Math.max(1, dpr);
}

function quantizeRenderCoord(value) {
  const quantum = renderQuantum();
  if (quantum <= 0) return value;
  return Math.round(value / quantum) * quantum;
}

function graphCoord(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  const rounded = Math.round(number * GRAPH_RENDER_COORD_PRECISION) / GRAPH_RENDER_COORD_PRECISION;
  return Object.is(rounded, -0) ? "0" : String(rounded);
}

function graphTranslate(x, y) {
  return `translate(${graphCoord(x)} ${graphCoord(y)})`;
}

function setGraphAttr(el, name, value) {
  if (!el) return false;
  const next = String(value);
  if (el.getAttribute(name) === next) return false;
  el.setAttribute(name, next);
  return true;
}

function setGraphCoordAttr(el, name, value) {
  return setGraphAttr(el, name, graphCoord(value));
}

function edgeNeedsPositionUpdate(edge, line, movedNodeKeys, gradient = null) {
  if (!line?.hasAttribute?.("x1")) return true;
  if (gradient && !gradient.hasAttribute("x1")) return true;
  return movedNodeKeys.has(edge.from) || movedNodeKeys.has(edge.to);
}

function raiseGraphFocusNodes(currentEl, activeLeafEl) {
  if (!nodesG) return;
  if (currentEl && activeLeafEl && currentEl !== activeLeafEl) {
    if (
      nodesG.lastElementChild === activeLeafEl &&
      activeLeafEl.previousElementSibling === currentEl
    ) {
      return;
    }
    nodesG.appendChild(currentEl);
    nodesG.appendChild(activeLeafEl);
    return;
  }
  const focusEl = activeLeafEl || currentEl;
  if (focusEl && nodesG.lastElementChild !== focusEl) nodesG.appendChild(focusEl);
}

function nodeRenderX(node) {
  return Number.isFinite(node.renderX) ? node.renderX : node.x;
}

function nodeRenderY(node) {
  return Number.isFinite(node.renderY) ? node.renderY : node.y;
}

function nodeDebugMatchesLabel(node, label) {
  const wanted = String(label || "").trim().toLowerCase();
  if (!wanted) return false;
  return [node.label, node.title, node.genreId, node.qid]
    .filter(Boolean)
    .some(value => String(value).trim().toLowerCase() === wanted);
}

function findDebugNodes(label) {
  return [...nodes.values()].filter(node => nodeDebugMatchesLabel(node, label));
}

function debugNodeSnapshot(node) {
  if (!node) return null;
  const el = nodeEls.get(node.key);
  return {
    key: node.key,
    label: node.label,
    genreId: node.genreId,
    x: node.x,
    y: node.y,
    renderX: nodeRenderX(node),
    renderY: nodeRenderY(node),
    homeX: node.homeX,
    homeY: node.homeY,
    vx: node.vx || 0,
    vy: node.vy || 0,
    traceJitterCount: node.traceJitterCount || 0,
    isTraceOnly: Boolean(node.isTraceOnly),
    isTraceParent: Boolean(node.isTraceParent),
    isTracePathNode: Boolean(node.isTracePathNode),
    isRevealed: node.isRevealed !== false,
    isTrimming: Boolean(node.isTrimming),
    className: el?.getAttribute("class") || "",
    transform: el?.getAttribute("transform") || "",
  };
}

function monitorNodeMotion(label, options = {}) {
  const durationMs = Math.max(100, Number(options.durationMs ?? 4000));
  const sampleMs = Math.max(16, Number(options.sampleMs ?? 50));
  const includeSamples = options.includeSamples !== false;
  const startedAt = performance.now();
  const samples = [];
  let last = null;
  let maxStep = 0;
  let totalDistance = 0;
  let flipCount = 0;
  let missingCount = 0;

  return new Promise(resolve => {
    const tick = () => {
      const now = performance.now();
      const matches = findDebugNodes(label);
      const node = matches[0] || null;
      const snap = debugNodeSnapshot(node);

      if (!snap) {
        missingCount += 1;
      } else if (last) {
        const dx = snap.renderX - last.renderX;
        const dy = snap.renderY - last.renderY;
        const step = Math.hypot(dx, dy);
        maxStep = Math.max(maxStep, step);
        totalDistance += step;
        if (
          step > 0.08 &&
          last.step > 0.08 &&
          dx * last.dx + dy * last.dy < -0.05
        ) {
          flipCount += 1;
        }
        snap.dx = dx;
        snap.dy = dy;
        snap.step = step;
      } else if (snap) {
        snap.dx = 0;
        snap.dy = 0;
        snap.step = 0;
      }

      if (snap) {
        snap.t = Math.round(now - startedAt);
        snap.matchCount = matches.length;
        if (includeSamples) samples.push(snap);
        last = snap;
      }

      if (now - startedAt >= durationMs) {
        resolve({
          label,
          durationMs: Math.round(now - startedAt),
          sampleMs,
          sampleCount: samples.length,
          missingCount,
          maxStep: Number(maxStep.toFixed(3)),
          totalDistance: Number(totalDistance.toFixed(3)),
          flipCount,
          final: last,
          samples,
        });
        return;
      }

      setTimeout(tick, sampleMs);
    };

    tick();
  });
}

function shouldStabilizeNodeRender(node, alpha) {
  if (alpha > RENDER_STABILIZE_ALPHA) return false;
  if (node.fx != null || node.fy != null) return false;
  if (node.isTrimming || node.isRevealed === false) return false;
  if (node.edgeLengthAnim && !node.edgeLengthAnim.done) return false;
  return true;
}

function resetTraceJitterState(node) {
  node.traceJitterLastX = null;
  node.traceJitterLastY = null;
  node.traceJitterDx = 0;
  node.traceJitterDy = 0;
  node.traceJitterStableX = null;
  node.traceJitterStableY = null;
  node.traceJitterCount = 0;
  node.traceJitterHomeX = node.homeX;
  node.traceJitterHomeY = node.homeY;
}

function suppressBacktraceJitter(renderNodes) {
  const alpha = sim?.alpha?.() ?? 0;
  const spine = getSpine();
  const activeTraceParents = activeTraceParentKeys(spine);

  for (const node of renderNodes) {
    const isActiveTraceNode =
      node.fx == null &&
      node.fy == null &&
      !node.isTrimming &&
      node.isRevealed !== false &&
      node.key !== ROOT_KEY &&
      node.key !== currentKey &&
      isTraceGraphNode(node) &&
      isBacktraceParentNode(node, spine, activeTraceParents);

    if (!isActiveTraceNode || alpha > TRACE_JITTER_SUPPRESS_ALPHA) {
      resetTraceJitterState(node);
      continue;
    }

    const homeShift = Math.hypot(
      node.homeX - (node.traceJitterHomeX ?? node.homeX),
      node.homeY - (node.traceJitterHomeY ?? node.homeY)
    );
    if (homeShift > TRACE_JITTER_HOME_RESET_PX) {
      resetTraceJitterState(node);
    }

    if (!Number.isFinite(node.traceJitterLastX) || !Number.isFinite(node.traceJitterLastY)) {
      node.traceJitterLastX = node.x;
      node.traceJitterLastY = node.y;
      node.traceJitterStableX = node.x;
      node.traceJitterStableY = node.y;
      node.traceJitterHomeX = node.homeX;
      node.traceJitterHomeY = node.homeY;
      continue;
    }

    const dx = node.x - node.traceJitterLastX;
    const dy = node.y - node.traceJitterLastY;
    const step = Math.hypot(dx, dy);
    const velocity = Math.hypot(node.vx || 0, node.vy || 0);
    const prevStep = Math.hypot(node.traceJitterDx || 0, node.traceJitterDy || 0);
    const flipped =
      step > 0.08 &&
      prevStep > 0.08 &&
      dx * (node.traceJitterDx || 0) + dy * (node.traceJitterDy || 0) < -0.05;
    const smallMotion = step <= TRACE_JITTER_STEP_PX && velocity <= TRACE_JITTER_VELOCITY;
    const lowVelocityJump =
      step > RENDER_STABILIZE_DEADBAND_PX &&
      step <= TRACE_JITTER_STEP_PX &&
      velocity <= TRACE_JITTER_LOW_VELOCITY_JUMP;

    if (smallMotion && (flipped || lowVelocityJump)) {
      node.traceJitterCount = lowVelocityJump
        ? Math.max(TRACE_JITTER_SETTLE_COUNT, (node.traceJitterCount || 0) + 1.5)
        : (node.traceJitterCount || 0) + 1;
    } else if (!smallMotion) {
      node.traceJitterCount = 0;
      node.traceJitterStableX = node.x;
      node.traceJitterStableY = node.y;
    } else {
      node.traceJitterCount = Math.max(0, (node.traceJitterCount || 0) - 0.08);
    }

    const stableX = Number.isFinite(node.traceJitterStableX) ? node.traceJitterStableX : node.x;
    const stableY = Number.isFinite(node.traceJitterStableY) ? node.traceJitterStableY : node.y;
    const stableFollow = (node.traceJitterCount || 0) > 0 ? 0.05 : 0.12;
    node.traceJitterStableX = stableX * (1 - stableFollow) + node.x * stableFollow;
    node.traceJitterStableY = stableY * (1 - stableFollow) + node.y * stableFollow;

    if ((node.traceJitterCount || 0) >= TRACE_JITTER_SETTLE_COUNT) {
      const settleBlend = (node.traceJitterCount || 0) >= TRACE_JITTER_SETTLE_COUNT + 2 ? 0.48 : 0.30;
      node.x = node.x * (1 - settleBlend) + node.traceJitterStableX * settleBlend;
      node.y = node.y * (1 - settleBlend) + node.traceJitterStableY * settleBlend;
      node.vx = (node.vx || 0) * 0.18;
      node.vy = (node.vy || 0) * 0.18;
    } else if (smallMotion) {
      node.vx = (node.vx || 0) * 0.42;
      node.vy = (node.vy || 0) * 0.42;
    }

    node.traceJitterLastX = node.x;
    node.traceJitterLastY = node.y;
    node.traceJitterDx = dx;
    node.traceJitterDy = dy;
    node.traceJitterHomeX = node.homeX;
    node.traceJitterHomeY = node.homeY;
  }
}

function updateRenderPositions(renderNodes) {
  const alpha = sim?.alpha?.() ?? 0;
  for (const node of renderNodes) {
    if (!shouldStabilizeNodeRender(node, alpha)) {
      node.renderX = node.x;
      node.renderY = node.y;
      continue;
    }

    const nextX = quantizeRenderCoord(node.x);
    const nextY = quantizeRenderCoord(node.y);
    if (!Number.isFinite(node.renderX) || !Number.isFinite(node.renderY)) {
      node.renderX = nextX;
      node.renderY = nextY;
      continue;
    }

    const dx = nextX - node.renderX;
    const dy = nextY - node.renderY;
    const velocity = Math.hypot(node.vx || 0, node.vy || 0);
    const distance = Math.hypot(dx, dy);
    if (
      velocity <= RENDER_STABILIZE_VELOCITY * 0.5 &&
      distance <= RENDER_STABILIZE_DEADBAND_PX * 0.38
    ) {
      continue;
    }

    if (velocity <= RENDER_STABILIZE_VELOCITY && distance <= RENDER_STABILIZE_DEADBAND_PX) {
      node.renderX += dx * 0.32;
      node.renderY += dy * 0.32;
      continue;
    }

    node.renderX = nextX;
    node.renderY = nextY;
  }
}

function hashForDomId(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function edgeGradientId(edge) {
  return `edge-gradient-${hashForDomId(graphEdgeKey(edge))}`;
}

function ensureEdgeGradientDefs() {
  let defs = document.getElementById("edge-gradient-defs");
  if (!defs) {
    defs = svgEl("defs", { id: "edge-gradient-defs" });
    svg.insertBefore(defs, world);
  }
  return defs;
}

function addTraceAnchor(target, anchorKey) {
  if (!target || !anchorKey) return;
  if (!Array.isArray(target.traceAnchorKeys)) target.traceAnchorKeys = [];
  if (!target.traceAnchorKeys.includes(anchorKey)) {
    target.traceAnchorKeys.push(anchorKey);
  }
}

function hasCurrentTraceAnchor(target) {
  return hasTraceAnchorIn(target, activeTraceAnchorKeys());
}

function activeTraceAnchorKeys(extraAnchorKey = null) {
  const anchors = new Set([currentKey]);
  if (activeLeafKey) anchors.add(activeLeafKey);
  if (extraAnchorKey) anchors.add(extraAnchorKey);
  const current = nodes.get(currentKey);
  if (current?.childCount === 0 && current.parentKey) {
    anchors.add(current.parentKey);
  }
  return anchors;
}

function hasTraceAnchorIn(target, anchors) {
  if (!target?.traceAnchorKeys?.length) return false;
  return target.traceAnchorKeys.some(key => anchors.has(key));
}

function activeTraceParentKeys(spine, extraAnchorKey = null) {
  const active = new Set();
  const anchors = activeTraceAnchorKeys(extraAnchorKey);

  for (const edge of edges) {
    if (
      !edge.isTraceLink ||
      edge.isTrimming ||
      !anchors.has(edge.to) ||
      !hasTraceAnchorIn(edge, anchors)
    ) {
      continue;
    }

    let key = edge.from;
    const seen = new Set();
    while (key && key !== ROOT_KEY && !seen.has(key)) {
      seen.add(key);
      const node = nodes.get(key);
      if (!node) break;
      if (node.isTraceParent) active.add(key);
      if (spine.has(node.parentKey)) break;
      key = node.parentKey;
    }
  }

  return active;
}

function isBacktraceParentNode(node, spine, activeTraceParents = activeTraceParentKeys(spine)) {
  return Boolean(node?.isTraceParent && activeTraceParents.has(node.key));
}

function isDirectSelectedParent(node, spine, activeTraceParents) {
  if (!node || activeTraceTargetKeys().has(node.key)) return false;
  const targets = [...activeTraceTargetKeys()]
    .map(key => nodes.get(key))
    .filter(Boolean);
  if (targets.some(target => target.parentKey === node.key)) return true;
  if (!isBacktraceParentNode(node, spine, activeTraceParents)) return false;
  return edges.some(edge =>
    edge.isTraceLink &&
    !edge.isTrimming &&
    edge.from === node.key &&
    activeTraceTargetKeys().has(edge.to) &&
    hasCurrentTraceAnchor(edge)
  );
}

function isImmediateSelectedParent(node) {
  if (!node || activeTraceTargetKeys().has(node.key)) return false;
  return [...activeTraceTargetKeys()]
    .map(key => nodes.get(key))
    .filter(Boolean)
    .some(target => target.parentKey === node.key);
}

function shouldShowPersistentNodeColor(node, spine, activeTraceParents) {
  if (!node?.color) return false;
  if (node.key === activeLeafKey) return false;
  if (isDirectSelectedParent(node, spine, activeTraceParents)) return false;
  return (
    node.key === currentKey ||
    (node.parentKey === currentKey && !node.isTrimming && !node.isFaded)
  );
}

function shouldUseEdgeGradient(edge, spine, activeTraceParents) {
  if (!edge || edge.isTrimming || edge.isUnresolved) return false;
  const from = nodes.get(edge.from);
  const to = nodes.get(edge.to);
  if (!from?.color || !to?.color || !activeTraceTargetKeys().has(to.key)) return false;
  if (from.key === to.parentKey) return true;
  return Boolean(
    edge.isTraceLink &&
    isDirectSelectedParent(from, spine, activeTraceParents)
  );
}

function syncEdgeGradients(spine, activeTraceParents) {
  const gradientDefs = ensureEdgeGradientDefs();
  gradientDefs.innerHTML = "";
  edgeGradientEls = new Map();

  for (const edge of edges) {
    const line = edgeEls.get(graphEdgeKey(edge));
    if (!line) continue;
    line.style.removeProperty("stroke");
    if (!shouldUseEdgeGradient(edge, spine, activeTraceParents)) continue;

    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from?.color || !to?.color) continue;

    const gradientId = edgeGradientId(edge);
    const gradient = svgEl("linearGradient", {
      id: gradientId,
      gradientUnits: "userSpaceOnUse",
    });
    gradient.appendChild(svgEl("stop", { offset: "0%", "stop-color": from.color }));
    gradient.appendChild(svgEl("stop", { offset: "100%", "stop-color": to.color }));
    gradientDefs.appendChild(gradient);
    edgeGradientEls.set(graphEdgeKey(edge), gradient);
    line.style.stroke = `url(#${gradientId})`;
  }
}

function graphNodeAllowsHoverDetail(node, el = null) {
  if (!node) return false;
  const spine = getSpine();
  const activeTraceParents = activeTraceParentKeys(spine);
  if (spine.has(node.key) || isBacktraceParentNode(node, spine, activeTraceParents) || isDirectSelectedParent(node, spine, activeTraceParents)) {
    return !node.isTrimming && node.isRevealed !== false && !el?.classList?.contains("trimming") && !el?.classList?.contains("pending");
  }
  if (node.isFaded || node.isTrimming || node.isRevealed === false || Boolean(node.isUnresolved)) return false;
  if (
    el?.classList?.contains("faded") ||
    el?.classList?.contains("pending") ||
    el?.classList?.contains("trimming") ||
    el?.classList?.contains("unresolved")
  ) {
    return false;
  }
  return true;
}

function selectedGradientEnd(start, end) {
  return {
    x: end.x + (end.x - start.x) * EDGE_GRADIENT_SELECTED_OVERSHOOT,
    y: end.y + (end.y - start.y) * EDGE_GRADIENT_SELECTED_OVERSHOOT,
  };
}

function fullRender() {
  if (cloudMode) {
    if (cloudData) renderCloud(cloudData, { preserveView: true });
    return;
  }
  if (timelineMode) {
    if (timelineData) renderTimeline(timelineData, { preserveView: true });
    return;
  }
  edgesG.innerHTML = "";
  nodesG.innerHTML = "";
  nodeEls = new Map();
  edgeEls = new Map();
  edgeGradientEls = new Map();
  ensureEdgeGradientDefs().innerHTML = "";

  const spine = getSpine();
  const activeTraceParents = activeTraceParentKeys(spine);
  const traceAnchors = activeTraceAnchorKeys();
  for (const e of edges) {
    const target = nodes.get(e.to);
    const isTraceActive =
      Boolean(e.isTracePath || e.isTraceLink) &&
      hasCurrentTraceAnchor(e) &&
      (!e.isTraceLink || traceAnchors.has(e.to));
    const isSpine =
      isTraceActive ||
      (spine.has(e.from) && (spine.has(e.to) || isBacktraceParentNode(target, spine, activeTraceParents)));
    const isFaded = spine.has(e.from) && e.from !== currentKey && !spine.has(e.to);
    if (isSpine) e.isTrimming = false;
    const classes = ["edge"];
    if (isSpine) classes.push("spine-edge");
    if (isFaded) classes.push("faded");
    if (!isSpine && (target?.isRevealed === false || e.isRevealed === false)) classes.push("pending");
    if (e.isTrimming) classes.push("trimming");
    if (Boolean(e.isUnresolved)) classes.push("unresolved-edge");
    if (e.isTracePath || e.isTraceLink) classes.push("trace-edge");
    if (e.isTraceLink) classes.push("trace-link");
    const line = svgEl("line", { class: classes.join(" ") });
    edgesG.appendChild(line);
    edgeEls.set(graphEdgeKey(e), line);
  }
  syncEdgeGradients(spine, activeTraceParents);

  const renderOrder = [...nodes.values()].sort((a, b) => {
    if (a.key === currentKey) return 1;
    if (b.key === currentKey) return -1;
    if (a.key === activeLeafKey) return 1;
    if (b.key === activeLeafKey) return -1;
    return 0;
  });
  for (const d of renderOrder) {
    const nodeEl = buildNodeEl(d, spine, activeTraceParents);
    nodesG.appendChild(nodeEl);
  }
  renderTick();
}

function buildNodeEl(d, spine = getSpine(), activeTraceParents = activeTraceParentKeys(spine)) {
  const isCurrent = d.key === currentKey;
  const isActiveLeaf = d.key === activeLeafKey;
  const isSpineNode = spine.has(d.key);
  const isBacktraceParent = isBacktraceParentNode(d, spine, activeTraceParents);
  const isRoot = d.key === ROOT_KEY;
  const label = normalizeLabel(d.label);
  const fontSize = isRoot ? 17 : 15;
  const { w, h } = nodeBox(d, 0, 0, false);

  const classes = ["node"];
  if (isSpineNode || isBacktraceParent || isActiveLeaf) {
    d.isFaded = false;
    d.isTrimming = false;
    d.isRevealed = true;
  }
  if (isCurrent) classes.push("node-current");
  if (isActiveLeaf) classes.push("node-active-leaf");
  if (isSpineNode || isBacktraceParent) classes.push("node-spine");
  if (isDirectSelectedParent(d, spine, activeTraceParents)) classes.push("direct-parent");
  if (isImmediateSelectedParent(d)) classes.push("immediate-parent");
  if (isRoot) classes.push("node-root");
  if (isCurrent) d.isTrimming = false;
  if (d.isFaded && !isCurrent && !isSpineNode && !isBacktraceParent && !isActiveLeaf) classes.push("faded");
  if (Boolean(d.isUnresolved)) classes.push("unresolved");
  if (!isCurrent && !isSpineNode && !isBacktraceParent && d.isRevealed === false) classes.push("pending");
  if (d.isTrimming) classes.push("trimming");
  if (d.color) classes.push("has-color");
  if (d.key === activeDetailIndicatorKey()) classes.push("node-detail-preview");

  const g = svgEl("g", {
    class: classes.join(" "),
    role: "button",
    tabindex: "0",
    "aria-label": Boolean(d.isUnresolved) ? `${d.label}, not yet in the graph` : d.label,
  });

  const inner = svgEl("g", { class: "node-inner" });
  g.appendChild(inner);

  inner.appendChild(svgEl("rect", {
    class: "node-pill",
    width: w,
    height: h,
    rx: h / 2,
    ry: h / 2,
    x: -w / 2,
    y: -h / 2,
  }));

  const text = svgEl("text", {
    class: "node-label",
    x: 0,
    y: GRAPH_LABEL_Y,
    "dominant-baseline": "central",
    "text-anchor": "middle",
  });
  const readableColor = d.color;
  if (readableColor) {
    g.style.setProperty("--genre-color", readableColor);
    if (shouldShowPersistentNodeColor(d, spine, activeTraceParents)) {
      text.style.fill = readableColor;
    }
  }
  text.textContent = label;
  inner.appendChild(text);
  inner.appendChild(svgEl("rect", {
    class: "node-hit-area",
    width: w,
    height: h,
    rx: h / 2,
    ry: h / 2,
    x: -w / 2,
    y: -h / 2,
  }));

  g.setAttribute("transform", graphTranslate(d.x, d.y));
  attachNodeInteraction(g, d);
  nodeEls.set(d.key, g);
  return g;
}

function renderTick() {
  if (cloudMode) return;
  if (timelineMode) return;
  const renderNodes = [...nodes.values()];
  const activeNodes = renderNodes.filter(node => !node.isTrimming);
  const alpha = sim?.alpha?.() ?? 0;
  const collisionStrength = alpha > 0.08
    ? 1
    : clamp(alpha / 0.08, 0.18, 1);
  layoutPressureFrame += 1;
  const pressureInterval = alpha > 0.02 ? 1 : 2;
  if (layoutPressureFrame % pressureInterval === 1) {
    applyLayoutPressure(activeNodes);
  }
  for (let i = 0; i < 7; i++) {
    for (const d of activeNodes) {
      limitNodeStretch(d);
    }
    resolveRectCollisions(activeNodes, collisionStrength);
  }
  for (const d of activeNodes) {
    limitNodeStretch(d);
  }
  for (let i = 0; i < 5; i++) {
    resolveRectCollisions(activeNodes, collisionStrength);
  }

  suppressBacktraceJitter(activeNodes);
  updateRenderPositions(renderNodes);

  const movedNodeKeys = new Set();
  for (const d of renderNodes) {
    const el = nodeEls.get(d.key);
    if (el && setGraphAttr(el, "transform", graphTranslate(nodeRenderX(d), nodeRenderY(d)))) {
      movedNodeKeys.add(d.key);
    }
  }
  updateTargetButtonVisibility();
  const currentEl = nodeEls.get(currentKey);
  const activeLeafEl = activeLeafKey ? nodeEls.get(activeLeafKey) : null;
  raiseGraphFocusNodes(currentEl, activeLeafEl);
  for (const e of edges) {
    const line = edgeEls.get(graphEdgeKey(e));
    const f = nodes.get(e.from);
    const t = nodes.get(e.to);
    if (!line || !f || !t) continue;
    const gradient = edgeGradientEls.get(graphEdgeKey(e));
    if (!edgeNeedsPositionUpdate(e, line, movedNodeKeys, gradient)) continue;
    const endpoints = edgeEndpoints(f, t);
    setGraphCoordAttr(line, "x1", endpoints.start.x);
    setGraphCoordAttr(line, "y1", endpoints.start.y);
    setGraphCoordAttr(line, "x2", endpoints.end.x);
    setGraphCoordAttr(line, "y2", endpoints.end.y);
    if (gradient) {
      const gradientEnd = selectedGradientEnd(endpoints.start, endpoints.end);
      setGraphCoordAttr(gradient, "x1", endpoints.start.x);
      setGraphCoordAttr(gradient, "y1", endpoints.start.y);
      setGraphCoordAttr(gradient, "x2", gradientEnd.x);
      setGraphCoordAttr(gradient, "y2", gradientEnd.y);
    }
  }
}

function updateClasses() {
  if (cloudMode) {
    if (cloudData) renderCloud(cloudData, { preserveView: true });
    return;
  }
  if (timelineMode) {
    if (timelineData) renderTimeline(timelineData, { preserveView: true });
    return;
  }
  const spine = getSpine();
  const activeTraceParents = activeTraceParentKeys(spine);
  const traceAnchors = activeTraceAnchorKeys();
  for (const d of nodes.values()) {
    const el = nodeEls.get(d.key);
    if (!el) continue;
    const isCurrent = d.key === currentKey;
    const isActiveLeaf = d.key === activeLeafKey;
    const isSpineNode = spine.has(d.key);
    const isBacktraceParent = isBacktraceParentNode(d, spine, activeTraceParents);
    if (isCurrent || isSpineNode || isBacktraceParent || isActiveLeaf) {
      d.isFaded = false;
      d.isTrimming = false;
    }
    if (isCurrent || isSpineNode || isBacktraceParent || isActiveLeaf) d.isRevealed = true;
    const label = el.querySelector(".node-label");
    const readableColor = d.color;
    if (readableColor) {
      el.style.setProperty("--genre-color", readableColor);
    } else {
      el.style.removeProperty("--genre-color");
    }
    if (label) {
      if (readableColor && shouldShowPersistentNodeColor(d, spine, activeTraceParents)) label.style.fill = readableColor;
      else label.style.removeProperty("fill");
    }
    el.classList.toggle("node-current", isCurrent);
    el.classList.toggle("node-active-leaf", isActiveLeaf);
    el.classList.toggle("node-spine", isSpineNode || isBacktraceParent);
    el.classList.toggle("direct-parent", isDirectSelectedParent(d, spine, activeTraceParents));
    el.classList.toggle("immediate-parent", isImmediateSelectedParent(d));
    el.classList.toggle("node-root", d.key === ROOT_KEY);
    el.classList.toggle("faded", d.isFaded && !isCurrent && !isSpineNode && !isBacktraceParent && !isActiveLeaf);
    el.classList.toggle("unresolved", Boolean(d.isUnresolved));
    el.classList.toggle("pending", !isCurrent && !isSpineNode && !isBacktraceParent && d.isRevealed === false);
    el.classList.toggle("trimming", !isCurrent && d.isTrimming);
    el.classList.toggle("has-color", Boolean(d.color));
    el.classList.toggle("node-detail-preview", d.key === activeDetailIndicatorKey());
  }
  for (const e of edges) {
    const line = edgeEls.get(graphEdgeKey(e));
    if (!line) continue;
    const target = nodes.get(e.to);
    const isTraceActive =
      Boolean(e.isTracePath || e.isTraceLink) &&
      hasCurrentTraceAnchor(e) &&
      (!e.isTraceLink || traceAnchors.has(e.to));
    const isSpine =
      isTraceActive ||
      (spine.has(e.from) && (spine.has(e.to) || isBacktraceParentNode(target, spine, activeTraceParents)));
    const isFaded = spine.has(e.from) && e.from !== currentKey && !spine.has(e.to);
    if (isSpine) e.isTrimming = false;
    line.classList.toggle("spine-edge", isSpine);
    line.classList.toggle("faded", isFaded);
    line.classList.toggle("pending", !isSpine && (target?.isRevealed === false || e.isRevealed === false));
    line.classList.toggle("trimming", e.isTrimming);
    line.classList.toggle("unresolved-edge", Boolean(e.isUnresolved));
    line.classList.toggle("trace-edge", Boolean(e.isTracePath || e.isTraceLink));
    line.classList.toggle("trace-link", Boolean(e.isTraceLink));
  }
  syncEdgeGradients(spine, activeTraceParents);
}

function attachNodeInteraction(g, d) {
  let dragging = false;
  let moved = false;
  let startX = 0;
  let startY = 0;

  g.addEventListener("pointerenter", () => {
    if (!graphNodeAllowsHoverDetail(d, g)) return;
    setHoveredNode(d.key);
    setHoveredMapItemForNode(d);
    scheduleHoverCard(d.key);
  });
  g.addEventListener("pointerleave", () => {
    if (!graphNodeAllowsHoverDetail(d, g)) return;
    clearHoveredMapItemForNode(d);
    restoreSelectedCardAfterHover(d.key);
  });

  g.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    dragging = true;
    moved = false;
    startX = e.clientX;
    startY = e.clientY;
    beginManualMovementGesture(e.clientX, e.clientY);
    cancelScheduledHoverCard(d.key);
    g.setPointerCapture?.(e.pointerId);

    const onMove = me => {
      if (!dragging) return;
      const dx = me.clientX - startX;
      const dy = me.clientY - startY;
      if (!moved && (Math.abs(dx) > 4 || Math.abs(dy) > 4)) moved = true;
      if (!moved) return;
      markManualUiMovingAfterGestureThreshold(me.clientX, me.clientY);
      d.fx = (d.x || d.homeX) + dx / viewScale;
      d.fy = (d.y || d.homeY) + dy / viewScale;
      startX = me.clientX;
      startY = me.clientY;
      bumpSim(0.5);
    };

    const onUp = me => {
      g.releasePointerCapture?.(me.pointerId);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      dragging = false;
      clearManualMovementGesture();
      if (moved) {
        if (d.key !== ROOT_KEY) {
          commitManualLengthTarget(d);
          d.fx = null;
          d.fy = null;
          recomputeLayout();
          rebuildSim();
        }
        bumpSim(0.4);
      } else {
        activateNode(d.key);
      }
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  });

  g.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      activateNode(d.key);
    }
  });
}

function writeWorldTransform() {
  viewScale = clampViewScale(viewScale);
  clampViewTranslation();
  world.setAttribute("transform", `translate(${viewTx} ${viewTy}) scale(${viewScale})`);
  updateFooterZoom();
  if (cloudMode && cloudData) {
    updateCloudLodVisibility({ immediate: true });
  } else if (timelineMode && timelineData) {
    if (!timelineViewportFrame) {
      timelineViewportFrame = requestAnimationFrame(() => {
        timelineViewportFrame = null;
        updateTimelineYearMarkers();
        updateTimelineZoomDetail();
      });
    }
  }
  updateTargetButtonVisibility();
}

function stopPanInertia() {
  if (panInertiaTimer) {
    clearInterval(panInertiaTimer);
    panInertiaTimer = null;
  }
}

function tweenPanTo(targetTx, targetTy, duration = 650, onStill = null, targetScale = viewScale) {
  if (panAnimTimer) clearInterval(panAnimTimer);
  const startTx = viewTx;
  const startTy = viewTy;
  const startScale = viewScale;
  const t0 = Date.now();
  const total = prefersReducedMotion() ? 1 : duration;
  markGraphMoving(total + 420);
  panAnimTimer = setInterval(() => {
    const u = Math.min(1, (Date.now() - t0) / total);
    const eased = 1 - Math.pow(1 - u, 3);
    viewScale = startScale + (targetScale - startScale) * eased;
    viewTx = startTx + (targetTx - startTx) * eased;
    viewTy = startTy + (targetTy - startTy) * eased;
    writeWorldTransform();
    if (u >= 1) {
      clearInterval(panAnimTimer);
      panAnimTimer = null;
      scheduleGraphStill(DETAIL_CARD_REAPPEAR_DELAY_MS, onStill);
    }
  }, 16);
}

function panToCurrent(options = {}) {
  const cur = nodes.get(currentKey);
  if (!cur) return;
  panToGraphNode(cur, options);
}

function panToGraphNode(node, options = {}) {
  if (!node) return;
  const targetScale = options.normalizeZoom ? graphAutoViewScale(viewScale) : viewScale;
  if (options.holdDetailCard) {
    holdDetailCardDuringLocate = true;
    updateDetailCardVisibility();
  }
  const renderX = nodeRenderX(node);
  const renderY = nodeRenderY(node);
  const x = Number.isFinite(renderX) ? renderX : node.homeX;
  const y = Number.isFinite(renderY) ? renderY : node.homeY;
  tweenPanTo(
    focusX() - x * targetScale,
    focusY() - y * targetScale,
    650,
    options.holdDetailCard
      ? () => {
          holdDetailCardDuringLocate = false;
          updateDetailCardVisibility();
        }
      : null,
    targetScale
  );
}

function selectedCenterTargetNode() {
  if (cloudMode) return cloudSelectedGenreId ? cloudNodeById.get(cloudSelectedGenreId) : null;
  if (timelineMode) {
    return timelineSelectedGenreId
      ? timelineData?.nodes?.find(node => node.id === timelineSelectedGenreId) || null
      : null;
  }
  return (activeLeafKey && nodes.get(activeLeafKey)) || nodes.get(currentKey);
}

function selectedCenterTargetPoint() {
  const node = selectedCenterTargetNode();
  if (!node) return null;
  if (cloudMode) return { node, x: node.x, y: node.y };
  if (timelineMode) {
    const placed = timelineSelectedGenreId ? timelinePlacedPositions.get(timelineSelectedGenreId) : null;
    const original = timelineSelectedGenreId ? timelineNodePositions.get(timelineSelectedGenreId) : null;
    return {
      node,
      x: placed?.x ?? original?.x ?? node.renderX ?? node.x,
      y: placed?.y ?? original?.y ?? node.renderY ?? node.y,
    };
  }
  const renderX = nodeRenderX(node);
  const renderY = nodeRenderY(node);
  return {
    node,
    x: Number.isFinite(renderX) ? renderX : node.homeX,
    y: Number.isFinite(renderY) ? renderY : node.homeY,
  };
}

function selectedTargetScreenDistance() {
  const target = selectedCenterTargetPoint();
  if (!target) return 0;
  const x = target.x * viewScale + viewTx;
  const y = target.y * viewScale + viewTy;
  return Math.hypot(x - focusX(), y - focusY());
}

function updateTargetButtonVisibility() {
  if (!cardTargetButton) return;
  const node = selectedCenterTargetNode();
  const isRoot = !cloudMode && !timelineMode && node?.key === ROOT_KEY;
  const shouldShow = Boolean(node && !isRoot && selectedTargetScreenDistance() > 130);
  cardTargetButton.classList.toggle("card-target-button-inactive", !shouldShow);
  cardTargetButton.disabled = !shouldShow;
  cardTargetButton.toggleAttribute("aria-hidden", !shouldShow);
}

function panToSelectedCenterTarget(options = {}) {
  const target = selectedCenterTargetPoint();
  if (!target) return;
  const targetScale = options.normalizeZoom && !cloudMode && !timelineMode ? graphAutoViewScale(viewScale) : viewScale;
  if (options.holdDetailCard) {
    holdDetailCardDuringLocate = true;
    updateDetailCardVisibility();
  }
  tweenPanTo(
    focusX() - target.x * targetScale,
    focusY() - target.y * targetScale,
    cloudMode ? 520 : 650,
    options.holdDetailCard
      ? () => {
          holdDetailCardDuringLocate = false;
          updateDetailCardVisibility();
        }
      : null,
    targetScale
  );
}

function selectedGenreIdFromUrlPath() {
  const pathIds = (new URL(window.location.href).searchParams.get("path") || "")
    .split(",")
    .map(value => value.trim())
    .filter(Boolean);
  return pathIds.at(-1) || null;
}

function selectedGenreIdFromUrlState() {
  const url = new URL(window.location.href);
  return (url.searchParams.get("cloud_selected") || "").trim() ||
    (url.searchParams.get("timeline_selected") || "").trim() ||
    selectedGenreIdFromUrlPath();
}

function activeSelectedGenreId() {
  if (cloudMode && cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY) return cloudSelectedGenreId;
  if (timelineMode && timelineSelectedGenreId) return timelineSelectedGenreId;
  const node = (activeLeafKey && nodes.get(activeLeafKey)) || nodes.get(currentKey);
  if (!node || node.key === ROOT_KEY || node.genreId === ROOT_KEY) return selectedGenreIdFromUrlPath();
  if (node.genreId) return node.genreId;
  return selectedGenreIdFromUrlPath();
}

function selectedGenreIdForModeTransfer() {
  const selected = activeSelectedGenreId() || selectedGenreIdFromUrlState();
  return selected && selected !== ROOT_KEY ? selected : null;
}

function startFollow() {
  if (panAnimTimer) {
    clearInterval(panAnimTimer);
    panAnimTimer = null;
  }
  stopPanInertia();
  followMode = true;
  ensureTickLoop();
}

{
  let panState = null;
  panTarget.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    updateLastPointerPosition(e.clientX, e.clientY);
    window.getSelection?.()?.removeAllRanges?.();
    markGraphMoving();
    beginManualMovementGesture(e.clientX, e.clientY);
    if (cloudMode) clearCloudHover();
    stopPanInertia();
    followMode = false;
    if (panAnimTimer) clearInterval(panAnimTimer);
    panState = {
      sx: e.clientX,
      sy: e.clientY,
      ttx: viewTx,
      tty: viewTy,
      lastX: e.clientX,
      lastY: e.clientY,
      lastT: Date.now(),
      vx: 0,
      vy: 0,
      moved: false,
    };
    try {
      panTarget.setPointerCapture?.(e.pointerId);
    } catch {
      // Synthetic and cancelled pointer streams can fail capture; panning still works.
    }
    svg.classList.add("panning");
    document.body.classList.add("is-panning-canvas");
  });

  window.addEventListener("pointermove", e => {
    if (!panState) return;
    e.preventDefault();
    updateLastPointerPosition(e.clientX, e.clientY);
    window.getSelection?.()?.removeAllRanges?.();
    viewTx = panState.ttx + (e.clientX - panState.sx);
    viewTy = panState.tty + (e.clientY - panState.sy);
    const now = Date.now();
    if (Math.hypot(e.clientX - panState.sx, e.clientY - panState.sy) > 4) {
      panState.moved = true;
      if (cloudMode) clearCloudHover();
    }
    const dt = Math.max(1, now - panState.lastT);
    const ivx = (e.clientX - panState.lastX) / dt;
    const ivy = (e.clientY - panState.lastY) / dt;
    panState.vx = panState.vx * 0.5 + ivx * 0.5;
    panState.vy = panState.vy * 0.5 + ivy * 0.5;
    panState.lastX = e.clientX;
    panState.lastY = e.clientY;
    panState.lastT = now;
    writeWorldTransform();
    markGraphMoving();
    markManualUiMovingAfterGestureThreshold(e.clientX, e.clientY);
    if (timelineMode) markTimelineInteracting();
  });

  const endPan = e => {
    if (!panState) return;
    try {
      panTarget.releasePointerCapture?.(e.pointerId);
    } catch {
      // Ignore stale pointer capture during cancelled or synthetic pointer streams.
    }
    const { vx, vy, lastT, moved } = panState;
    const idle = Date.now() - lastT;
    panState = null;
    clearManualMovementGesture();
    svg.classList.remove("panning");
    document.body.classList.remove("is-panning-canvas");
    window.getSelection?.()?.removeAllRanges?.();
    if (cloudMode && moved) {
      scheduleCloudClickEnable();
    }
    if (cloudMode && !moved && cloudCanClickNodes()) {
      if (cloudSelectedMarkerHit(e.clientX, e.clientY)) {
        focusCloudSelectedMarker();
        scheduleGraphStill();
        return;
      }
      const hitNode = cloudCanvasHitTest(e.clientX, e.clientY);
      if (hitNode?.id) {
        void openCloudGenre(hitNode.id);
        scheduleGraphStill();
        return;
      }
    }
    if (prefersReducedMotion() || idle > 80 || (Math.abs(vx) < 0.05 && Math.abs(vy) < 0.05)) {
      scheduleGraphStill();
      return;
    }
    let cvx = vx * 16;
    let cvy = vy * 16;
    panInertiaTimer = setInterval(() => {
      viewTx += cvx;
      viewTy += cvy;
      cvx *= 0.92;
      cvy *= 0.92;
      writeWorldTransform();
      markDetailCardMoving(520);
      if (timelineMode) markTimelineInteracting();
      if (Math.abs(cvx) < 0.1 && Math.abs(cvy) < 0.1) {
        stopPanInertia();
        scheduleGraphStill();
      }
    }, 16);
  };

  window.addEventListener("pointerup", endPan);
  window.addEventListener("pointercancel", endPan);
  window.addEventListener("blur", () => {
    if (!panState) return;
    panState = null;
    clearManualMovementGesture();
    svg.classList.remove("panning");
    document.body.classList.remove("is-panning-canvas");
    if (cloudMode) {
      scheduleCloudClickEnable();
      syncCloudClickAffordance();
    }
  });

  panTarget.addEventListener("pointermove", e => {
    if (panState || !cloudMode) return;
    updateLastPointerPosition(e.clientX, e.clientY);
    updateCloudHoverFromPoint(e.clientX, e.clientY);
  });

  panTarget.addEventListener("pointerleave", () => {
    if (!cloudMode || panState) return;
    clearCloudHover();
  });
}

svg.addEventListener("wheel", e => {
  e.preventDefault();
  updateLastPointerPosition(e.clientX, e.clientY);
  markGraphMoving();
  stopPanInertia();
  followMode = false;
  if (panAnimTimer) clearInterval(panAnimTimer);

  const isPixelWheel = e.deltaMode === WheelEvent.DOM_DELTA_PIXEL;
  const looksLikeTrackpadPan =
    isPixelWheel &&
    !e.ctrlKey &&
    (Math.abs(e.deltaX) > 0 || Math.abs(e.deltaY) < 60);

  markManualUiMovingAfterWheelThreshold(e);
  if (looksLikeTrackpadPan) {
    viewTx -= e.deltaX * TRACKPAD_PAN_SPEED;
    viewTy -= e.deltaY * TRACKPAD_PAN_SPEED;
    writeWorldTransform();
    if (timelineMode) markTimelineInteracting();
    scheduleGraphStill();
    return;
  }

  const rect = svg.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const wx = (mx - viewTx) / viewScale;
  const wy = (my - viewTy) / viewScale;
  const factor = e.ctrlKey
    ? Math.max(0.82, Math.min(1.22, Math.exp(-e.deltaY * TRACKPAD_ZOOM_SPEED)))
    : (e.deltaY < 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP);
  viewScale = clampViewScale(viewScale * factor);
  viewTx = mx - wx * viewScale;
  viewTy = my - wy * viewScale;
  writeWorldTransform();
  if (timelineMode) markTimelineInteracting();
  scheduleGraphStill();
}, { passive: false });

async function hydrateNodeDetail(node) {
  if (!node.genreId || Boolean(node.isUnresolved)) return node;
  const detail = await getGenreDetail(node.genreId);
  Object.assign(node, detail);
  return node;
}

function updateUrl() {
  updateUrlState({ push: false });
}

function updateAppHistoryButtons() {
  if (navBackButton) navBackButton.disabled = appHistoryIndex <= 0;
  if (navForwardButton) navForwardButton.disabled = appHistoryIndex < 0 || appHistoryIndex >= appHistoryEntries.length - 1;
}

function recordAppHistory(url, { push = false } = {}) {
  if (appNavigatingHistory) {
    updateAppHistoryButtons();
    return;
  }
  const value = String(url);
  if (!value) return;
  if (appHistoryIndex < 0) {
    appHistoryEntries = [value];
    appHistoryIndex = 0;
  } else if (push) {
    if (appHistoryEntries[appHistoryIndex] !== value) {
      appHistoryEntries = appHistoryEntries.slice(0, appHistoryIndex + 1);
      appHistoryEntries.push(value);
      appHistoryIndex = appHistoryEntries.length - 1;
    }
  } else {
    appHistoryEntries[appHistoryIndex] = value;
  }
  updateAppHistoryButtons();
}

async function navigateAppHistory(direction) {
  const nextIndex = appHistoryIndex + direction;
  if (nextIndex < 0 || nextIndex >= appHistoryEntries.length) return;
  appHistoryIndex = nextIndex;
  appNavigatingHistory = true;
  historyNavigating = true;
  history.replaceState(null, "", appHistoryEntries[appHistoryIndex]);
  try {
    await init();
  } finally {
    historyNavigating = false;
    appNavigatingHistory = false;
    await applyModeFromUrl();
    updateAppHistoryButtons();
  }
}

function updateUrlState(options = {}) {
  if (restoringUrl || historyNavigating) return;
  const ids = [];
  let n = (activeLeafKey && nodes.get(activeLeafKey)) || nodes.get(currentKey);
  while (n) {
    if (n.genreId) ids.unshift(n.genreId);
    n = n.parentKey ? nodes.get(n.parentKey) : null;
  }
  const url = new URL(window.location.href);
  if (ids.length) url.searchParams.set("path", ids.join(","));
  else url.searchParams.delete("path");
  if (timelineMode) {
    url.searchParams.set("mode", "timeline");
    if (timelineSelectedGenreId) url.searchParams.set("timeline_selected", timelineSelectedGenreId);
    else url.searchParams.delete("timeline_selected");
    url.searchParams.delete("cloud_root");
    url.searchParams.delete("cloud_region");
    url.searchParams.delete("cloud_selected");
  } else if (cloudMode) {
    url.searchParams.set("mode", "cloud");
    if (cloudRootGenreId) url.searchParams.set("cloud_root", cloudRootGenreId);
    else url.searchParams.delete("cloud_root");
    if (cloudRegionId) url.searchParams.set("cloud_region", cloudRegionId);
    else url.searchParams.delete("cloud_region");
    if (cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY) url.searchParams.set("cloud_selected", cloudSelectedGenreId);
    else url.searchParams.delete("cloud_selected");
    url.searchParams.delete("timeline_selected");
  } else {
    url.searchParams.delete("mode");
    url.searchParams.delete("timeline_selected");
    url.searchParams.delete("cloud_root");
    url.searchParams.delete("cloud_region");
    url.searchParams.delete("cloud_selected");
  }
  if (options.push) history.pushState(null, "", url);
  else history.replaceState(null, "", url);
  writeExplorerSelectionState(url);
  recordAppHistory(url.href, { push: Boolean(options.push) });
}

function setSearchExpanded(expanded) {
  if (!searchInput || !searchResults) return;
  searchInput.setAttribute("aria-expanded", expanded ? "true" : "false");
  searchResults.hidden = !expanded;
}

function clearSearchResults() {
  if (!searchResults) return;
  searchResults.innerHTML = "";
  setSearchExpanded(false);
}

function pathPreview(hit) {
  const titles = hit.path_titles || [];
  if (!titles.length) return "Music";
  return ["Music", ...titles.map(labelFromTitle)].join(" / ");
}

function selectedTimelineNode() {
  if (timelineSelectedGenreId) {
    const detail = detailCache.get(timelineSelectedGenreId);
    if (detail) return detail;
    const timelineNode = timelineData?.nodes?.find(node => node.id === timelineSelectedGenreId);
    if (timelineNode) return timelineNodeFromPayload(timelineNode);
  }
  if (activeLeafKey && nodes.has(activeLeafKey)) return nodes.get(activeLeafKey);
  if (detailCardNodeKey && nodes.has(detailCardNodeKey)) return nodes.get(detailCardNodeKey);
  if (currentKey && currentKey !== ROOT_KEY && nodes.has(currentKey)) return nodes.get(currentKey);
  return null;
}

function selectedCloudNode() {
  if (!cloudSelectedGenreId) return null;
  const detail = detailCache.get(cloudSelectedGenreId);
  if (detail) return detail;
  const cloudNode = cloudNodeById.get(cloudSelectedGenreId);
  return cloudNode ? cloudNodeFromPayload(cloudNode) : null;
}

function currentMapNodeForMode() {
  if (cloudMode) {
    if (!cloudSelectedGenreId || cloudSelectedGenreId === ROOT_KEY) {
      return nodes.get(ROOT_KEY) || null;
    }
    return selectedCloudNode() || {
      key: `cloud-${cloudSelectedGenreId}`,
      id: cloudSelectedGenreId,
      genreId: cloudSelectedGenreId,
      label: "",
      title: "",
      isUnresolved: false,
    };
  }
  if (timelineMode) {
    return selectedTimelineNode() || nodes.get(currentKey) || nodes.get(ROOT_KEY) || null;
  }
  return nodes.get(currentKey) || nodes.get(ROOT_KEY) || null;
}

function cloudNodeFromPayload(node) {
  return {
    key: `cloud-${node.id}`,
    genreId: node.id === ROOT_KEY ? null : node.id,
    id: node.id,
    label: node.label || labelFromTitle(node.wikipedia_title),
    title: normalizeLabel(node.wikipedia_title),
    qid: null,
    color: node.similarity_color,
    colorConfidence: node.color_confidence,
    hasPlaylist: typeof node.has_playlist === "boolean" ? node.has_playlist : node.hasPlaylist,
    summary: "",
    monthlyViews: node.monthly_views_p30,
    wikipedia_url: null,
    aliases: [],
    origins: [],
    instruments: [],
    categories: [],
    youtubeItems: [],
    youtubeUrls: [],
    selected_distance: Number.isFinite(Number(node.selected_distance)) ? Number(node.selected_distance) : null,
    isDetailLoaded: node.id === ROOT_KEY,
    isUnresolved: false,
  };
}

function cloudStableUnit(value) {
  let hash = 2166136261;
  const text = String(value || "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 100000) / 100000;
}

function cloudFallbackTextWidth(label) {
  const text = String(label || "");
  let width = 0;
  for (const char of text) {
    if (char === " ") width += 0.32;
    else if ("ijlI!|.,'`:/;[](){}".includes(char)) width += 0.34;
    else if ("rtf-".includes(char)) width += 0.42;
    else if ("MW@#%&".includes(char)) width += 0.86;
    else if (/[\u3000-\u9FFF\uAC00-\uD7AF\u3040-\u30FF]/u.test(char)) width += 0.98;
    else if (/[A-Z]/.test(char)) width += 0.68;
    else if (/[0-9]/.test(char)) width += 0.56;
    else width += 0.56;
  }
  return Math.ceil(Math.max(22, width * CLOUD_FONT_SIZE) + 0.75);
}

function cloudFallbackTextHeight() {
  return Math.ceil(CLOUD_FONT_SIZE * 1.25 + 0.25);
}

function cloudRenderMetrics(node) {
  if (!node) {
    const textWidth = cloudFallbackTextWidth("");
    const textHeight = cloudFallbackTextHeight();
    return {
      textWidth,
      textHeight,
      boxPadX: CLOUD_LABEL_PAD_PX,
      boxPadY: CLOUD_LABEL_PAD_Y_PX,
      boxWidth: textWidth + CLOUD_LABEL_PAD_PX * 2,
      selectedPillWidth: textWidth + (CLOUD_LABEL_PAD_PX + CLOUD_SELECTED_LABEL_EXTRA_PAD_PX) * 2,
      boxHeight: textHeight + CLOUD_LABEL_PAD_Y_PX * 2,
    };
  }
  if (node.__cloudRenderMetrics) return node.__cloudRenderMetrics;
  const label = node.label || node.wikipedia_title;
  const textWidth = positiveMetricValue(node.text_width, node.textWidth, node.width) ||
    cloudFallbackTextWidth(label);
  const textHeight = positiveMetricValue(node.text_height, node.textHeight, node.height) ||
    cloudFallbackTextHeight();
  const boxPadX = positiveMetricValue(node.box_pad_x, node.boxPadX) || CLOUD_LABEL_PAD_PX;
  const boxPadY = positiveMetricValue(node.box_pad_y, node.boxPadY) || CLOUD_LABEL_PAD_Y_PX;
  const metrics = {
    textWidth,
    textHeight,
    boxPadX,
    boxPadY,
    boxWidth: positiveMetricValue(node.box_width, node.boxWidth) || Math.ceil(textWidth + boxPadX * 2),
    selectedPillWidth: Math.ceil(textWidth + (boxPadX + CLOUD_SELECTED_LABEL_EXTRA_PAD_PX) * 2),
    boxHeight: positiveMetricValue(node.box_height, node.boxHeight) || Math.ceil(textHeight + boxPadY * 2),
  };
  try {
    Object.defineProperty(node, "__cloudRenderMetrics", {
      value: metrics,
      configurable: true,
      writable: true,
    });
  } catch {
    node.__cloudRenderMetrics = metrics;
  }
  return metrics;
}

function cloudTextWidth(node) {
  return cloudRenderMetrics(node).textWidth;
}

function cloudTextHeight(node) {
  return cloudRenderMetrics(node).textHeight;
}

function cloudBoxPadX(node) {
  return cloudRenderMetrics(node).boxPadX;
}

function cloudBoxPadY(node) {
  return cloudRenderMetrics(node).boxPadY;
}

function cloudPretextBoxWidth(node, extraPadX = 0) {
  const metrics = cloudRenderMetrics(node);
  return Math.ceil(metrics.textWidth + (metrics.boxPadX + extraPadX) * 2);
}

function cloudBoxWidth(node) {
  return cloudRenderMetrics(node).boxWidth;
}

function cloudSelectedPillWidth(node) {
  return cloudRenderMetrics(node).selectedPillWidth;
}

function cloudRenderedBoxWidth(node) {
  return node?.id === cloudSelectedGenreId ? cloudSelectedPillWidth(node) : cloudBoxWidth(node);
}

function cloudBoxHeight(node) {
  return cloudRenderMetrics(node).boxHeight;
}

function cloudBoundsForNodes(nodes = []) {
  if (!nodes.length) return null;
  return {
    min_x: Math.min(...nodes.map(node => node.x - cloudBoxWidth(node) / 2)),
    max_x: Math.max(...nodes.map(node => node.x + cloudBoxWidth(node) / 2)),
    min_y: Math.min(...nodes.map(node => node.y - cloudBoxHeight(node) / 2)),
    max_y: Math.max(...nodes.map(node => node.y + cloudBoxHeight(node) / 2)),
  };
}

function normalizedCloudData(data) {
  const rawNodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const hasCoordinates = rawNodes.every(node => Number.isFinite(Number(node.x)) && Number.isFinite(Number(node.y)));
  if (hasCoordinates) {
    const nodesWithSize = rawNodes.map(node => {
      const label = node.label || labelFromTitle(node.wikipedia_title);
      const textWidth = Number(node.text_width) || Number(node.width) || cloudFallbackTextWidth(label);
      const textHeight = Number(node.text_height) || Number(node.height) || cloudFallbackTextHeight();
      const boxPadX = Number(node.box_pad_x) || CLOUD_LABEL_PAD_PX;
      const boxPadY = Number(node.box_pad_y) || CLOUD_LABEL_PAD_Y_PX;
      return {
        ...node,
        label,
        x: Number(node.x),
        y: Number(node.y),
        width: textWidth,
        height: textHeight,
        text_width: textWidth,
        text_height: textHeight,
        box_width: Number(node.box_width) || textWidth + boxPadX * 2,
        box_height: Number(node.box_height) || textHeight + boxPadY * 2,
        box_pad_x: boxPadX,
        box_pad_y: boxPadY,
        lod_score: Number(node.lod_score) || 0,
        lod_rank: Number.isFinite(Number(node.lod_rank)) ? Number(node.lod_rank) : 0,
        lod_tier: Number.isFinite(Number(node.lod_tier)) ? Number(node.lod_tier) : 5,
        min_visible_scale: Number.isFinite(Number(node.min_visible_scale)) ? Number(node.min_visible_scale) : 2,
        show_scale: Number.isFinite(Number(node.show_scale)) ? Number(node.show_scale) : Number(node.min_visible_scale) || 2,
        hide_scale: Number.isFinite(Number(node.hide_scale)) ? Number(node.hide_scale) : (Number(node.show_scale) || Number(node.min_visible_scale) || 2) * 0.92,
        selected_distance: Number.isFinite(Number(node.selected_distance)) ? Number(node.selected_distance) : null,
        selected_focus_score: Number.isFinite(Number(node.selected_focus_score)) ? Number(node.selected_focus_score) : null,
      };
    });
    return {
      ...data,
      nodes: nodesWithSize,
      stats: {
        ...(data?.stats || {}),
        bounds: data?.stats?.bounds || cloudBoundsForNodes(nodesWithSize),
      },
    };
  }

  const roots = [...new Set(rawNodes.map(node => node.semantic_root_title || "Other"))]
    .sort((a, b) => a.localeCompare(b));
  const rootAngles = new Map(roots.map((root, index) => [
    root,
    (-Math.PI / 2) + (index / Math.max(1, roots.length)) * Math.PI * 2,
  ]));
  const priorities = rawNodes.map(node => Number(node.priority) || Math.log((Number(node.monthly_views_p30) || 0) + 1));
  const maxPriority = Math.max(1, ...priorities);
  const minPriority = Math.min(...priorities, maxPriority);
  const prioritySpan = Math.max(1, maxPriority - minPriority);
  const nodesWithLayout = rawNodes.map((node, index) => {
    const label = node.label || labelFromTitle(node.wikipedia_title);
    const root = node.semantic_root_title || "Other";
    const priority = Number(node.priority) || Math.log((Number(node.monthly_views_p30) || 0) + 1);
    const priorityNorm = clamp((priority - minPriority) / prioritySpan, 0, 1);
    const depth = Math.max(1, Number(node.depth_from_music) || 5);
    const angle = (rootAngles.get(root) || 0) + (cloudStableUnit(`${node.id}:angle`) - 0.5) * 0.9 + (index % 7) * 0.012;
    const radius = 180 + depth * 175 + (1 - priorityNorm) * 460 + (cloudStableUnit(`${node.id}:radius`) - 0.5) * 170;
    return {
      ...node,
      label,
      priority,
      x: Math.cos(angle) * radius * 1.18,
      y: Math.sin(angle) * radius * 0.86,
      width: cloudFallbackTextWidth(label),
      height: cloudFallbackTextHeight(),
      text_width: cloudFallbackTextWidth(label),
      text_height: cloudFallbackTextHeight(),
      box_width: cloudFallbackTextWidth(label) + CLOUD_LABEL_PAD_PX * 2,
      box_height: cloudFallbackTextHeight() + CLOUD_LABEL_PAD_Y_PX * 2,
      box_pad_x: CLOUD_LABEL_PAD_PX,
      box_pad_y: CLOUD_LABEL_PAD_Y_PX,
      selected_distance: Number.isFinite(Number(node.selected_distance)) ? Number(node.selected_distance) : null,
      selected_focus_score: Number.isFinite(Number(node.selected_focus_score)) ? Number(node.selected_focus_score) : null,
    };
  });
  return {
    ...data,
    nodes: nodesWithLayout,
    stats: {
      ...(data?.stats || {}),
      bounds: cloudBoundsForNodes(nodesWithLayout),
    },
  };
}

function cloudStatsBounds(data = cloudData) {
  const bounds = data?.stats?.bounds;
  if (!bounds) return null;
  return {
    minX: Number(bounds.min_x),
    maxX: Number(bounds.max_x),
    minY: Number(bounds.min_y),
    maxY: Number(bounds.max_y),
  };
}

function createCloudScene(stats = {}) {
  return {
    nodesById: new Map(),
    layersByTier: new Map(),
    layerIdsByScale: new Map(),
    layerSpatialByScale: new Map(),
    layerTilesByScale: new Map(),
    layerScales: [],
    loadedLayers: new Set(),
    atlasSignature: "",
    pendingAtlasSignature: "",
    awaitingScaleLayer: false,
    stats: { ...stats },
    complete: false,
  };
}

function cloudAtlasSignature() {
  return [
    cloudRootGenreId || "",
    cloudRegionId || "",
    cloudSelectedGenreId || "",
    "atlas",
  ].join("|");
}

function prepareCloudSceneForReload(options = {}) {
  const atlasSignature = options.atlasSignature || cloudAtlasSignature();
  if (!options.preserveView || !cloudScene?.nodesById?.size) {
    resetCloudScene();
    if (cloudScene) cloudScene.atlasSignature = atlasSignature;
    return;
  }
  if (cloudScene.atlasSignature && cloudScene.atlasSignature !== atlasSignature) {
    resetCloudScaleLayersForSignature(atlasSignature);
  } else if (!cloudScene.atlasSignature) {
    cloudScene.atlasSignature = atlasSignature;
  }
  cloudScene.complete = false;
  cloudScene.stats = {
    ...(cloudScene.stats || {}),
    selected_genre_id: cloudSelectedGenreId || null,
  };
}

function resetCloudScaleLayersForSignature(atlasSignature = cloudAtlasSignature()) {
  if (!cloudScene) return;
  if (cloudScene.atlasSignature === atlasSignature && !cloudScene.pendingAtlasSignature) return;
  cloudScene.pendingAtlasSignature = atlasSignature;
  cloudScene.complete = false;
}

function activateCloudScaleLayersForSignature(atlasSignature = cloudAtlasSignature()) {
  if (!cloudScene) return;
  if (cloudScene.atlasSignature === atlasSignature && !cloudScene.pendingAtlasSignature) return;
  cloudScene.layersByTier = new Map();
  cloudScene.layerIdsByScale = new Map();
  cloudScene.layerSpatialByScale = new Map();
  cloudScene.layerTilesByScale = new Map();
  cloudScene.layerScales = [];
  cloudScene.loadedLayers = new Set();
  cloudScene.atlasSignature = atlasSignature;
  cloudScene.pendingAtlasSignature = "";
  cloudScene.awaitingScaleLayer = false;
  cloudRenderedLayerScale = null;
  cloudRenderedWindowSignature = "";
}

function resetCloudScene(stats = {}) {
  cloudScene = createCloudScene(stats);
  cloudVisibleNodeIds = new Set();
  cloudTextEls = new Map();
  cloudSceneDomPrepared = false;
  cloudRenderedLayerScale = null;
  cloudRenderedTextScale = 0;
  cloudRenderedWindowSignature = "";
  cloudNodeById = cloudScene.nodesById;
		    cloudCanvasNodes = [];
			    cloudCanvasHitNodes = [];
				    cloudCanvasVisibleIds = new Set();
				    cloudCanvasAlphaById = new Map();
				    cloudRenderSnapshot = null;
				    cloudRenderTransition = null;
				    cloudPresentationById = new Map();
				    cloudPresentationLastAt = 0;
				    cloudPresentationTargetSignature = "";
				    cloudSelectedLabelAlphaById = new Map();
			    cloudHoverUnderlineAlphaById = new Map();
			    cloudRelationshipAlphaById = new Map();
  cancelCloudFadeFrame();
  cloudBackgroundCache = null;
  cloudBackgroundBuildSignature = "";
  window.clearTimeout(cloudBackgroundBuildTimer);
  cloudBackgroundBuildTimer = 0;
  cloudLabelSpriteCache = new Map();
  cloudHoveredNodeId = null;
  cloudSelectedMarker = null;
  clearCloudSelectedMarkerAnimation();
  cloudClickEnabled = true;
  cloudClickEnableAt = 0;
  window.clearTimeout(cloudClickEnableTimer);
  cloudClickEnableTimer = 0;
  syncCloudClickAffordance();
	    if (cloudCanvasFadeFrame) {
	      cancelAnimationFrame(cloudCanvasFadeFrame);
	      cloudCanvasFadeFrame = 0;
	    }
		    if (cloudSelectedLabelFadeFrame) {
		      cancelAnimationFrame(cloudSelectedLabelFadeFrame);
		      cloudSelectedLabelFadeFrame = 0;
		    }
		    if (cloudHoverUnderlineFadeFrame) {
		      cancelAnimationFrame(cloudHoverUnderlineFadeFrame);
		      cloudHoverUnderlineFadeFrame = 0;
		    }
		    if (cloudRelationshipFadeFrame) {
		      cancelAnimationFrame(cloudRelationshipFadeFrame);
		      cloudRelationshipFadeFrame = 0;
		    }
  scheduleCloudCanvasRender();
  cloudData = { nodes: [], stats: cloudScene.stats };
}

function cloudViewportWorldBounds(marginPx = 160) {
  const scale = Math.max(0.001, viewScale);
  const margin = marginPx / scale;
  return {
    left: (0 - viewTx) / scale - margin,
    right: (vw() - viewTx) / scale + margin,
    top: (0 - viewTy) / scale - margin,
    bottom: (vh() - viewTy) / scale + margin,
  };
}

function cloudNodeIntersectsViewport(node, bounds = cloudViewportWorldBounds()) {
  if (node.id === ROOT_KEY) return true;
  const width = cloudBoxWidth(node);
  const height = cloudBoxHeight(node);
  return (
    node.x + width / 2 >= bounds.left &&
    node.x - width / 2 <= bounds.right &&
    node.y + height / 2 >= bounds.top &&
    node.y - height / 2 <= bounds.bottom
  );
}

function cloudNodeScreenIntersectsViewport(node, marginPx = 160) {
  if (node.id === ROOT_KEY) return true;
  const rect = cloudNodeScreenRect(node);
  return (
    rect.right >= -marginPx &&
    rect.left <= vw() + marginPx &&
    rect.bottom >= -marginPx &&
    rect.top <= vh() + marginPx
  );
}

function cloudLodBaselineScale(bounds = cloudStatsBounds(cloudData) || cloudBounds) {
  if (!bounds) return 1;
  const width = Math.max(1, Number(bounds.maxX) - Number(bounds.minX));
  const height = Math.max(1, Number(bounds.maxY) - Number(bounds.minY));
  const padding = isCompact() ? 28 : 48;
  const fitWidth = Math.max(220, vw() - padding * 2);
  const fitHeight = Math.max(220, vh() - padding * 2);
  return clamp(
    Math.min(fitWidth / width, fitHeight / height, 1),
    MIN_VIEW_SCALE,
    MAX_VIEW_SCALE
  );
}

function cloudEffectiveLodScale() {
  const baseline = Math.max(0.001, cloudLodBaselineScale());
  return Math.max(0.001, viewScale / baseline);
}

function cloudNodePassesLod(node, wasVisible = false) {
  if (node.id === ROOT_KEY) return true;
  const showScale = Number.isFinite(Number(node.show_scale))
    ? Number(node.show_scale)
    : Number.isFinite(Number(node.min_visible_scale))
      ? Number(node.min_visible_scale)
      : 2;
  const hideScale = Number.isFinite(Number(node.hide_scale)) ? Number(node.hide_scale) : showScale * 0.92;
  const effectiveScale = cloudEffectiveLodScale();
  return effectiveScale >= (wasVisible ? hideScale : showScale);
}

function cloudNodeScreenRect(node, options = {}) {
  const insetPx = Math.max(0, Number(options.insetPx) || 0);
  const scale = Math.max(0.001, viewScale);
  const x = Number(node.x) * scale + viewTx;
  const y = Number(node.y) * scale + viewTy;
  const width = cloudBoxWidth(node);
  const height = cloudBoxHeight(node);
  const halfWidth = Math.max(0, width / 2 - insetPx);
  const halfHeight = Math.max(0, height / 2 - insetPx);
  return {
    left: x - halfWidth,
    right: x + halfWidth,
    top: y - halfHeight,
    bottom: y + halfHeight,
  };
}

function cloudNodeLodScreenRect(node, options = {}) {
  const insetPx = Math.max(0, Number(options.insetPx) || 0);
  const scale = Math.max(0.001, viewScale);
  const x = Number(node.x) * scale + viewTx;
  const y = Number(node.y) * scale + viewTy;
  const width = cloudRenderedBoxWidth(node);
  const height = cloudBoxHeight(node);
  const halfWidth = Math.max(0, width / 2 - insetPx);
  const halfHeight = Math.max(0, height / 2 - insetPx);
  return {
    left: x - halfWidth,
    right: x + halfWidth,
    top: y - halfHeight,
    bottom: y + halfHeight,
  };
}

function cloudScreenRectsOverlap(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function cloudCollisionKey(x, y, cellSize = 96) {
  return `${Math.floor(x / cellSize)}:${Math.floor(y / cellSize)}`;
}

function cloudRectCollisionBuckets(rect, cellSize = 96) {
  const keys = [];
  const left = Math.floor(rect.left / cellSize);
  const right = Math.floor(rect.right / cellSize);
  const top = Math.floor(rect.top / cellSize);
  const bottom = Math.floor(rect.bottom / cellSize);
  for (let x = left; x <= right; x += 1) {
    for (let y = top; y <= bottom; y += 1) keys.push(`${x}:${y}`);
  }
  return keys;
}

function cloudRectOverlapsOccupied(rect, occupiedBuckets) {
  const tested = new Set();
  for (const key of cloudRectCollisionBuckets(rect)) {
    for (const existing of occupiedBuckets.get(key) || []) {
      if (tested.has(existing)) continue;
      tested.add(existing);
      if (cloudScreenRectsOverlap(rect, existing.rect)) return existing;
    }
  }
  return null;
}

function cloudOccupyRect(rect, occupiedBuckets, node) {
  const entry = { rect, node };
  for (const key of cloudRectCollisionBuckets(rect)) {
    if (!occupiedBuckets.has(key)) occupiedBuckets.set(key, []);
    occupiedBuckets.get(key).push(entry);
  }
}

function cloudSortedLayerScales(scene = cloudScene) {
  if (!scene) return [];
  if (scene.layerScales?.length) return scene.layerScales;
  const scales = Array.from(scene.layerIdsByScale?.keys?.() || [])
    .map(scale => Number(scale))
    .filter(scale => Number.isFinite(scale))
    .sort((a, b) => a - b);
  scene.layerScales = scales;
  return scales;
}

function cloudActiveLayerScale(scene = cloudScene) {
  const scales = cloudSortedLayerScales(scene);
  if (!scales.length) return null;
  const current = clampViewScale(viewScale);
  let active = scales[0];
  for (const scale of scales) {
    if (scale <= current + 0.0001) active = scale;
    else break;
  }
  return active;
}

function cloudActiveLayerCaughtUp(scene = cloudScene) {
  if (!scene?.layerIdsByScale?.size) return false;
  const activeScale = cloudActiveLayerScale(scene);
  if (activeScale == null) return false;
  return activeScale >= clampViewScale(viewScale) - CLOUD_LAYER_READY_EPSILON;
}

function cloudActiveLayerIds(scene = cloudScene, activeScale = null) {
  if (scene?.awaitingScaleLayer && !scene?.layerIdsByScale?.size) return new Set();
  if (!scene?.layerIdsByScale?.size) {
    const ids = Array.from(scene?.nodesById?.keys?.() || []);
    return new Set(scene?.complete ? ids : ids.slice(0, CLOUD_CATALOG_PREVIEW_NODE_LIMIT));
  }
  let scale = Number.isFinite(Number(activeScale)) ? Number(activeScale) : cloudActiveLayerScale(scene);
  if (scale == null) return new Set();
  let ids = scene.layerIdsByScale.get(scale);
  if (!ids?.size) {
    const scales = cloudSortedLayerScales(scene).filter(scale => scene.layerIdsByScale.get(scale)?.size);
    scale = scales.length ? scales[scales.length - 1] : null;
    ids = scale == null ? null : scene.layerIdsByScale.get(scale);
  }
  return ids || new Set();
}

function cloudSpatialKey(x, y, cellSize = CLOUD_SPATIAL_CELL_PX) {
  return `${Math.floor(x / cellSize)}:${Math.floor(y / cellSize)}`;
}

function cloudLayerSpatialIndex(scene = cloudScene, scale = cloudActiveLayerScale(scene)) {
  if (!scene || scale == null) return null;
  const cacheKey = Number(scale);
  const cached = scene.layerSpatialByScale?.get(cacheKey);
  if (cached) return cached;
  const layerIds = cloudActiveLayerIds(scene, cacheKey);
  const cells = new Map();
  for (const nodeId of layerIds) {
    const node = scene.nodesById.get(nodeId);
    if (!node) continue;
    const x = Number(node.x);
    const y = Number(node.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const key = cloudSpatialKey(x, y);
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(String(nodeId));
  }
  const index = { scale: cacheKey, cells, size: layerIds.size };
  scene.layerSpatialByScale?.set(cacheKey, index);
  return index;
}

function cloudViewportCandidateIds(scene = cloudScene, activeScale = cloudActiveLayerScale(scene)) {
  const layerIds = cloudActiveLayerIds(scene, activeScale);
  const index = cloudLayerSpatialIndex(scene, activeScale);
  if (!index?.cells?.size) return new Set(layerIds);
  const bounds = cloudViewportWorldBounds(CLOUD_DOM_WINDOW_MARGIN_PX + 220);
  const cellSize = CLOUD_SPATIAL_CELL_PX;
  const ids = new Set();
  const left = Math.floor(bounds.left / cellSize);
  const right = Math.floor(bounds.right / cellSize);
  const top = Math.floor(bounds.top / cellSize);
  const bottom = Math.floor(bounds.bottom / cellSize);
  for (let x = left; x <= right; x += 1) {
    for (let y = top; y <= bottom; y += 1) {
      for (const nodeId of index.cells.get(`${x}:${y}`) || []) ids.add(nodeId);
    }
  }
  return ids;
}

function cloudLayerTileIndex(scene = cloudScene, activeScale = cloudActiveLayerScale(scene)) {
  if (!scene || activeScale == null) return null;
  return scene.layerTilesByScale?.get(Number(activeScale)) || null;
}

function cloudTilePacketCandidateIds(scene = cloudScene, activeScale = cloudActiveLayerScale(scene)) {
  const packet = cloudLayerTileIndex(scene, activeScale);
  if (!packet?.cells?.size) return null;
  const scale = Math.max(0.001, viewScale);
  const margin = CLOUD_DOM_WINDOW_MARGIN_PX + 220;
  const tileSize = Math.max(1, Number(packet.tileSize) || CLOUD_DOM_WINDOW_TILE_PX);
  const left = (0 - viewTx - margin) / scale;
  const right = (vw() - viewTx + margin) / scale;
  const top = (0 - viewTy - margin) / scale;
  const bottom = (vh() - viewTy + margin) / scale;
  const minX = Math.floor((left * Number(activeScale || scale)) / tileSize);
  const maxX = Math.floor((right * Number(activeScale || scale)) / tileSize);
  const minY = Math.floor((top * Number(activeScale || scale)) / tileSize);
  const maxY = Math.floor((bottom * Number(activeScale || scale)) / tileSize);
  const ids = new Set();
  for (let tileX = minX; tileX <= maxX; tileX += 1) {
    for (let tileY = minY; tileY <= maxY; tileY += 1) {
      for (const nodeId of packet.cells.get(`${tileX}:${tileY}`) || []) ids.add(nodeId);
    }
  }
  return ids;
}

function cloudPacketLodTarget(scene = cloudScene, activeScale = cloudActiveLayerScale(scene)) {
  const packetCandidateIds = cloudTilePacketCandidateIds(scene, activeScale);
  if (!packetCandidateIds) return null;
  const layerIds = cloudActiveLayerIds(scene, activeScale);
  const nextNodeIds = new Set();
  let hiddenForViewport = 0;
  let missingCandidates = 0;
  for (const nodeId of packetCandidateIds) {
    const node = scene?.nodesById?.get(nodeId);
    if (!node) {
      missingCandidates += 1;
      continue;
    }
    if (!cloudNodeScreenIntersectsViewport(node, CLOUD_DOM_WINDOW_MARGIN_PX)) {
      hiddenForViewport += 1;
      continue;
    }
    nextNodeIds.add(node.id);
  }
  if (cloudSelectedGenreId && scene?.nodesById?.has(cloudSelectedGenreId)) {
    nextNodeIds.add(cloudSelectedGenreId);
  } else {
    nextNodeIds.add(ROOT_KEY);
  }
  return {
    nextNodeIds,
    candidateIds: packetCandidateIds,
    layerIds,
    hiddenForViewport,
    hiddenForOverlap: 0,
    missingCandidates,
    source: "packet_tiles",
  };
}

function cloudClientLodTarget(scene = cloudScene, activeScale = cloudActiveLayerScale(scene)) {
  const packetTarget = cloudPacketLodTarget(scene, activeScale);
  if (packetTarget) return packetTarget;
  const layerIds = cloudActiveLayerIds(scene, activeScale);
  const candidateIds = cloudViewportCandidateIds(scene, activeScale);
  candidateIds.add(ROOT_KEY);
  if (cloudSelectedGenreId && scene?.nodesById?.has(cloudSelectedGenreId)) {
    candidateIds.add(cloudSelectedGenreId);
  }

  const orderedIds = [];
  const queuedIds = new Set();
  const addOrderedId = nodeId => {
    if (!nodeId || queuedIds.has(nodeId)) return;
    queuedIds.add(nodeId);
    orderedIds.push(nodeId);
  };
  if (cloudSelectedGenreId && scene?.nodesById?.has(cloudSelectedGenreId)) {
    addOrderedId(cloudSelectedGenreId);
  }
  addOrderedId(ROOT_KEY);
  for (const nodeId of layerIds) {
    if (candidateIds.has(nodeId)) addOrderedId(nodeId);
  }
  for (const nodeId of candidateIds) addOrderedId(nodeId);

  const nextNodeIds = new Set();
  const occupiedBuckets = new Map();
  let hiddenForViewport = 0;
  let hiddenForOverlap = 0;
  let missingCandidates = 0;
  for (const nodeId of orderedIds) {
    const node = scene?.nodesById?.get(nodeId);
    if (!node) {
      missingCandidates += 1;
      continue;
    }
    if (!cloudNodeScreenIntersectsViewport(node, CLOUD_DOM_WINDOW_MARGIN_PX)) {
      hiddenForViewport += 1;
      continue;
    }
    const forceVisible = node.id === cloudSelectedGenreId || (node.id === ROOT_KEY && !cloudSelectedGenreId);
    const rect = cloudNodeLodScreenRect(node);
    if (!forceVisible && cloudRectOverlapsOccupied(rect, occupiedBuckets)) {
      hiddenForOverlap += 1;
      continue;
    }
    nextNodeIds.add(node.id);
    cloudOccupyRect(rect, occupiedBuckets, node);
  }

  return {
    nextNodeIds,
    candidateIds,
    layerIds,
    hiddenForViewport,
    hiddenForOverlap,
    missingCandidates,
    source: "client_overlap",
  };
}

function cloudBackgroundNodeColor(node) {
  return node?.similarity_color || node?.color || null;
}

function cloudBackgroundTheme() {
  const styles = getComputedStyle(document.documentElement);
  const colorScheme = styles.getPropertyValue("color-scheme").trim().toLowerCase();
  const bg = parseCssColor(styles.getPropertyValue("--bg")) || { r: 13, g: 13, b: 13 };
  const perceivedLightness = (0.2126 * bg.r + 0.7152 * bg.g + 0.0722 * bg.b) / 255;
  return colorScheme.includes("light") || perceivedLightness > 0.55 ? "light" : "dark";
}

function cloudBackgroundNodes(nodes = []) {
  return nodes
    .filter(node => {
      if (!node || node.id === ROOT_KEY) return false;
      if (!Number.isFinite(Number(node.x)) || !Number.isFinite(Number(node.y))) return false;
      return Boolean(parseColorToRgb(cloudBackgroundNodeColor(node)));
    })
    .map(node => ({
      ...node,
      x: Number(node.x),
      y: Number(node.y),
    }));
}

function cloudBackgroundBounds(nodes = []) {
  const bounds = cloudStatsBounds(cloudData) || cloudBoundsForNodes(nodes);
  if (!bounds) return null;
  const minX = Number(bounds.minX ?? bounds.min_x);
  const maxX = Number(bounds.maxX ?? bounds.max_x);
  const minY = Number(bounds.minY ?? bounds.min_y);
  const maxY = Number(bounds.maxY ?? bounds.max_y);
  if (![minX, maxX, minY, maxY].every(Number.isFinite) || minX === maxX || minY === maxY) return null;
  const width = maxX - minX;
  const height = maxY - minY;
  const pad = Math.max(width, height) * 0.08;
  return {
    minX: minX - pad,
    maxX: maxX + pad,
    minY: minY - pad,
    maxY: maxY + pad,
  };
}

function cloudBackgroundSignature(nodes, bounds, theme, width, height) {
  let hash = 2166136261;
  const write = value => {
    const text = String(value ?? "");
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
  };
  write(theme);
  write(Math.round(width));
  write(Math.round(height));
  write(Math.round(bounds.minX));
  write(Math.round(bounds.maxX));
  write(Math.round(bounds.minY));
  write(Math.round(bounds.maxY));
  write(nodes.length);
  for (const node of nodes) {
    write(node.id);
    write(Math.round(Number(node.x) * 10));
    write(Math.round(Number(node.y) * 10));
    write(cloudBackgroundNodeColor(node));
    write(Math.round(Number(node.monthly_views_p30 ?? node.popularity ?? 1)));
    write(Math.round(Number(node.color_confidence ?? node.colorConfidence ?? 1) * 1000));
  }
  return `${nodes.length}:${hash >>> 0}`;
}

function addOklab(a, b, weight = 1) {
  a.L += b.L * weight;
  a.a += b.a * weight;
  a.b += b.b * weight;
  return a;
}

function scaleOklab(color, weight) {
  return {
    L: color.L * weight,
    a: color.a * weight,
    b: color.b * weight,
  };
}

function nodeColorOklab(node) {
  const rgb = parseColorToRgb(cloudBackgroundNodeColor(node));
  return rgb ? rgbToOklab(rgb) : null;
}

function computeGraphSmoothedColors(nodes, nodeById, options) {
  const rawColors = new Map();
  for (const node of nodes) {
    const color = nodeColorOklab(node);
    if (color) rawColors.set(node.id, color);
  }
  const result = new Map();
  for (const node of nodes) {
    const self = rawColors.get(node.id);
    if (!self) continue;
    let accum = scaleOklab(self, options.selfWeight);
    let total = options.selfWeight;
    const neighbors = Array.isArray(node.neighbors) ? node.neighbors : [];
    const sortedNeighbors = neighbors
      .slice()
      .sort((a, b) => {
        const aScore = Number.isFinite(Number(a?.similarity)) ? Number(a.similarity) : -Number(a?.distance ?? Infinity);
        const bScore = Number.isFinite(Number(b?.similarity)) ? Number(b.similarity) : -Number(b?.distance ?? Infinity);
        return bScore - aScore;
      })
      .slice(0, options.graphNeighborLimit);
    for (const edge of sortedNeighbors) {
      const other = nodeById.get(edge?.id);
      const color = other ? rawColors.get(other.id) : null;
      if (!color) continue;
      let edgeWeight = 0;
      if (Number.isFinite(Number(edge.similarity))) {
        edgeWeight = options.graphWeight * clamp(Number(edge.similarity), 0, 1);
      } else if (Number.isFinite(Number(edge.distance))) {
        const sigmaGraph = Math.max(0.001, Number(options.sigmaGraph) || 1);
        const distance = Number(edge.distance);
        edgeWeight = options.graphWeight * Math.exp(-(distance * distance) / (2 * sigmaGraph * sigmaGraph));
      }
      if (edgeWeight <= 0) continue;
      addOklab(accum, color, edgeWeight);
      total += edgeWeight;
    }
    result.set(node.id, scaleOklab(accum, 1 / total));
  }
  return result;
}

function buildSpatialBuckets(nodes, cellSize) {
  const buckets = new Map();
  for (const node of nodes) {
    const key = `${Math.floor(node.x / cellSize)}:${Math.floor(node.y / cellSize)}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(node);
  }
  return { buckets, cellSize };
}

function nearbyBackgroundNodes(index, x, y, radius) {
  const { buckets, cellSize } = index;
  const minX = Math.floor((x - radius) / cellSize);
  const maxX = Math.floor((x + radius) / cellSize);
  const minY = Math.floor((y - radius) / cellSize);
  const maxY = Math.floor((y + radius) / cellSize);
  const result = [];
  for (let bx = minX; bx <= maxX; bx += 1) {
    for (let by = minY; by <= maxY; by += 1) {
      for (const node of buckets.get(`${bx}:${by}`) || []) result.push(node);
    }
  }
  return result;
}

function predominantContributorColor(contributors, limit, bucketCount) {
  const top = contributors
    .filter(contributor => contributor.weight > 0 && contributor.color)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, limit);
  if (!top.length) return { color: null, dominant: null, colorWeight: 0, dominance: 0 };
  const buckets = new Map();
  let totalWeight = 0;
  for (const contributor of top) {
    const oklch = oklabToOklch(contributor.color);
    const hue = ((oklch.h % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    const bucket = oklch.C < 0.012 ? "neutral" : Math.floor((hue / (Math.PI * 2)) * bucketCount);
    const entry = buckets.get(bucket) || { weight: 0, contributors: [] };
    entry.weight += contributor.weight;
    entry.contributors.push(contributor);
    buckets.set(bucket, entry);
    totalWeight += contributor.weight;
  }
  let winner = null;
  for (const entry of buckets.values()) {
    if (!winner || entry.weight > winner.weight) winner = entry;
  }
  const selected = winner?.contributors?.length ? winner.contributors : top.slice(0, 1);
  const accum = { L: 0, a: 0, b: 0 };
  let colorWeight = 0;
  for (const contributor of selected) {
    addOklab(accum, contributor.color, contributor.weight);
    colorWeight += contributor.weight;
  }
  return {
    color: colorWeight > 0 ? scaleOklab(accum, 1 / colorWeight) : top[0].color,
    dominant: top[0].color,
    hueBucket: winner ? [...buckets.entries()].find(([, entry]) => entry === winner)?.[0] : null,
    colorWeight,
    dominance: totalWeight > 0 ? (winner?.weight || top[0].weight) / totalWeight : 1,
  };
}

function computeSpatialField(nodes, smoothedColors, width, height, bounds, sigma, contributorLimit = 24, hueBucketCount = 18) {
  const cells = new Array(width * height);
  const radius = sigma * 3;
  const index = buildSpatialBuckets(nodes, Math.max(64, radius / 2));
  const worldWidth = bounds.maxX - bounds.minX;
  const worldHeight = bounds.maxY - bounds.minY;
  for (let gy = 0; gy < height; gy += 1) {
    const y = bounds.minY + ((gy + 0.5) / height) * worldHeight;
    for (let gx = 0; gx < width; gx += 1) {
      const x = bounds.minX + ((gx + 0.5) / width) * worldWidth;
      const contributors = [];
      let density = 0;
      for (const node of nearbyBackgroundNodes(index, x, y, radius)) {
        const dx = x - node.x;
        const dy = y - node.y;
        const d2 = dx * dx + dy * dy;
        if (d2 > radius * radius) continue;
        const spatialWeight = Math.exp(-d2 / (2 * sigma * sigma));
        const popularity = Number(node.popularity ?? node.monthly_views_p30 ?? 1);
        const popularityWeight = clamp(Math.sqrt(Math.log10(Math.max(0, Number.isFinite(popularity) ? popularity : 1) + 10)), 0.65, 2.1);
        const rawConfidence = node.colorConfidence ?? node.color_confidence;
        const confidence = Number(rawConfidence);
        const confidenceWeight = rawConfidence == null ? 0.42 : clamp(Number.isFinite(confidence) ? confidence : 1, 0.25, 1.5);
        const localWeight = Math.pow(spatialWeight, 1.18);
        const weight = localWeight * popularityWeight * confidenceWeight;
        const color = smoothedColors.get(node.id);
        if (!color) continue;
        contributors.push({ color, weight });
        density += localWeight;
      }
      contributors.sort((a, b) => b.weight - a.weight);
      const predominant = predominantContributorColor(contributors, contributorLimit, hueBucketCount);
      cells[gy * width + gx] = {
        color: predominant.color,
        dominant: predominant.dominant,
        hueBucket: predominant.hueBucket,
        dominance: predominant.dominance,
        density,
      };
    }
  }
  return { width, height, cells };
}

function blendSpatialFields(largeField, mediumField, largeWeight, mediumWeight) {
  const cells = new Array(largeField.cells.length);
  const totalBlendWeight = Math.max(0.001, largeWeight + mediumWeight);
  const lw = largeWeight / totalBlendWeight;
  const mw = mediumWeight / totalBlendWeight;
  for (let index = 0; index < cells.length; index += 1) {
    const large = largeField.cells[index];
    const medium = mediumField.cells[index];
    const localColor = medium?.color || large?.color || null;
    const broadColor = large?.color || localColor;
    let color = null;
    if (localColor) {
      color = broadColor
        ? {
            L: localColor.L + (broadColor.L - localColor.L) * lw,
            a: localColor.a + (broadColor.a - localColor.a) * lw * 0.9,
            b: localColor.b + (broadColor.b - localColor.b) * lw * 0.9,
          }
        : localColor;
    }
    cells[index] = {
      color,
      hueBucket: medium?.hueBucket ?? large?.hueBucket ?? null,
      dominance: medium?.dominance ?? large?.dominance ?? 0,
      density: (large?.density || 0) * lw + (medium?.density || 0) * mw,
    };
  }
  return { width: largeField.width, height: largeField.height, cells };
}

function smoothstep(edge0, edge1, value) {
  const t = clamp((value - edge0) / Math.max(0.0001, edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

function sameHueBucket(a, b, bucketCount) {
  if (a == null || b == null) return false;
  if (a === "neutral" || b === "neutral") return a === b;
  const ai = Number(a);
  const bi = Number(b);
  if (!Number.isFinite(ai) || !Number.isFinite(bi)) return false;
  const delta = Math.abs(ai - bi);
  return Math.min(delta, bucketCount - delta) <= 1;
}

function hueBucketBlendWeight(a, b, bucketCount) {
  if (a == null || b == null) return 0.72;
  if (a === "neutral" || b === "neutral") return a === b ? 1 : 0.56;
  const ai = Number(a);
  const bi = Number(b);
  if (!Number.isFinite(ai) || !Number.isFinite(bi)) return 0.72;
  const delta = Math.abs(ai - bi);
  const ringDelta = Math.min(delta, bucketCount - delta);
  if (ringDelta <= 1) return 1;
  if (ringDelta <= 3) return 0.86;
  if (ringDelta <= 6) return 0.64;
  return 0.48;
}

function percentile(sortedValues, ratio) {
  if (!sortedValues.length) return 0;
  const index = clamp(Math.round((sortedValues.length - 1) * ratio), 0, sortedValues.length - 1);
  return sortedValues[index];
}

function muteForBackground(oklab, theme, options) {
  const oklch = oklabToOklch(oklab);
  if (theme === "light") {
    oklch.L = oklch.L + (options.lightTargetLightness - oklch.L) * 0.60;
    oklch.C = Math.min(oklch.C * options.lightChromaScale, options.lightChromaMax);
  } else {
    oklch.L = oklch.L + (options.darkTargetLightness - oklch.L) * 0.45;
    oklch.C = Math.min(oklch.C * options.darkChromaScale, options.darkChromaMax);
  }
  return oklchToOklab(oklch);
}

function hashNoise2d(ix, iy, seed) {
  let h = Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263) ^ Math.imul(seed, 1442695041);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

function valueNoise2d(x, y, seed) {
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const tx = x - x0;
  const ty = y - y0;
  const sx = tx * tx * (3 - 2 * tx);
  const sy = ty * ty * (3 - 2 * ty);
  const n00 = hashNoise2d(x0, y0, seed);
  const n10 = hashNoise2d(x0 + 1, y0, seed);
  const n01 = hashNoise2d(x0, y0 + 1, seed);
  const n11 = hashNoise2d(x0 + 1, y0 + 1, seed);
  const nx0 = n00 + (n10 - n00) * sx;
  const nx1 = n01 + (n11 - n01) * sx;
  return (nx0 + (nx1 - nx0) * sy) * 2 - 1;
}

function sampleSpatialField(field, x, y, options = {}) {
  const clampedX = clamp(x, 0, field.width - 1);
  const clampedY = clamp(y, 0, field.height - 1);
  const x0 = Math.floor(clampedX);
  const y0 = Math.floor(clampedY);
  const x1 = Math.min(field.width - 1, x0 + 1);
  const y1 = Math.min(field.height - 1, y0 + 1);
  const tx = clampedX - x0;
  const ty = clampedY - y0;
  const samples = [
    { cell: field.cells[y0 * field.width + x0], weight: (1 - tx) * (1 - ty) },
    { cell: field.cells[y0 * field.width + x1], weight: tx * (1 - ty) },
    { cell: field.cells[y1 * field.width + x0], weight: (1 - tx) * ty },
    { cell: field.cells[y1 * field.width + x1], weight: tx * ty },
  ];
  let anchor = null;
  let bestColorScore = 0;
  let density = 0;
  for (const sample of samples) {
    density += (sample.cell?.density || 0) * sample.weight;
    if (!sample.cell?.color || sample.weight <= 0) continue;
    const colorScore = sample.weight * (sample.cell.density || 0) * (0.35 + (sample.cell.dominance || 0));
    if (colorScore > bestColorScore) {
      bestColorScore = colorScore;
      anchor = sample.cell;
    }
  }
  const color = { L: 0, a: 0, b: 0 };
  let colorWeight = 0;
  for (const sample of samples) {
    if (!sample.cell?.color || sample.weight <= 0 || !anchor) continue;
    const hueWeight = hueBucketBlendWeight(
      sample.cell.hueBucket,
      anchor.hueBucket,
      options.hueBucketCount || 18
    );
    const weight = sample.weight * hueWeight * (0.45 + (sample.cell.dominance || 0));
    addOklab(color, sample.cell.color, weight);
    colorWeight += weight;
  }
  return {
    color: colorWeight > 0 ? scaleOklab(color, 1 / colorWeight) : anchor?.color || null,
    density,
  };
}

function generateGenreBackgroundField(nodes, canvasWidth, canvasHeight, options = {}) {
  const mergedOptions = { ...CLOUD_BACKGROUND_OPTIONS, ...options };
  const theme = mergedOptions.theme || "dark";
  const bounds = mergedOptions.bounds || cloudBackgroundBounds(nodes);
  if (!bounds || !nodes.length) return null;
  const fieldWidth = Math.max(32, Math.round(mergedOptions.fieldWidth));
  const worldAspect = Math.max(0.2, Math.min(5, canvasHeight / Math.max(1, canvasWidth)));
  const fieldHeight = Math.max(24, Math.round(fieldWidth * worldAspect));
  const worldWidth = Math.max(1, bounds.maxX - bounds.minX);
  const spatialSigmaLarge = mergedOptions.spatialSigmaLarge || worldWidth * mergedOptions.spatialSigmaLargeRatio;
  const spatialSigmaMedium = mergedOptions.spatialSigmaMedium || worldWidth * mergedOptions.spatialSigmaMediumRatio;
  const nodeById = new Map(nodes.map(node => [node.id, node]));
  const smoothedColors = computeGraphSmoothedColors(nodes, nodeById, mergedOptions);
  const largeField = computeSpatialField(
    nodes,
    smoothedColors,
    fieldWidth,
    fieldHeight,
    bounds,
    spatialSigmaLarge,
    mergedOptions.largeContributorLimit,
    mergedOptions.hueBucketCount
  );
  const mediumField = computeSpatialField(
    nodes,
    smoothedColors,
    fieldWidth,
    fieldHeight,
    bounds,
    spatialSigmaMedium,
    mergedOptions.mediumContributorLimit,
    mergedOptions.hueBucketCount
  );
  const field = blendSpatialFields(
    largeField,
    mediumField,
    mergedOptions.largeFieldWeight,
    mergedOptions.mediumFieldWeight
  );
  const canvas = document.createElement("canvas");
  canvas.width = fieldWidth;
  canvas.height = fieldHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const image = ctx.createImageData(fieldWidth, fieldHeight);
  const data = image.data;
  const baseAlpha = theme === "light" ? mergedOptions.lightBaseAlpha : mergedOptions.darkBaseAlpha;
  const densityValues = field.cells
    .map(cell => cell?.density || 0)
    .filter(value => value > 0)
    .sort((a, b) => a - b);
  const densityLow = densityValues.length
    ? Math.max(mergedOptions.densityLow, percentile(densityValues, 0.42))
    : mergedOptions.densityLow;
  const densityHigh = densityValues.length
    ? Math.max(densityLow + 0.001, percentile(densityValues, 0.90))
    : mergedOptions.densityHigh;
  for (let gy = 0; gy < fieldHeight; gy += 1) {
    for (let gx = 0; gx < fieldWidth; gx += 1) {
      const noiseX = valueNoise2d(gx * mergedOptions.noiseScale, gy * mergedOptions.noiseScale, mergedOptions.noiseSeed);
      const noiseY = valueNoise2d(gx * mergedOptions.noiseScale, gy * mergedOptions.noiseScale, mergedOptions.noiseSeed + 1);
      const sample = sampleSpatialField(
        field,
        gx + noiseX * mergedOptions.warpStrength,
        gy + noiseY * mergedOptions.warpStrength,
        mergedOptions
      );
      const offset = (gy * fieldWidth + gx) * 4;
      if (!sample.color) {
        data[offset + 3] = 0;
        continue;
      }
      const densityNorm = Math.pow(
        smoothstep(densityLow, densityHigh, sample.density),
        1.35
      );
      const alpha = clamp(baseAlpha * densityNorm, 0, 0.16);
      if (alpha <= 0.002) {
        data[offset + 3] = 0;
        continue;
      }
      const rgb = oklabToRgb(muteForBackground(sample.color, theme, mergedOptions));
      data[offset] = clamp(rgb.r, 0, 255);
      data[offset + 1] = clamp(rgb.g, 0, 255);
      data[offset + 2] = clamp(rgb.b, 0, 255);
      data[offset + 3] = Math.round(alpha * 255);
    }
  }
  ctx.putImageData(image, 0, 0);
  const sourceCanvas = document.createElement("canvas");
  sourceCanvas.width = fieldWidth;
  sourceCanvas.height = fieldHeight;
  const sourceCtx = sourceCanvas.getContext("2d");
  if (sourceCtx) sourceCtx.putImageData(image, 0, 0);
  ctx.clearRect(0, 0, fieldWidth, fieldHeight);
  ctx.globalAlpha = 1;
  ctx.filter = "blur(7px)";
  ctx.drawImage(sourceCanvas, 0, 0);
  ctx.filter = "none";
  ctx.globalAlpha = 0.12;
  ctx.drawImage(sourceCanvas, 0, 0);
  ctx.filter = "none";
  ctx.globalAlpha = 1;
  canvas.__genreBackgroundBounds = bounds;
  canvas.__genreBackgroundDensity = { densityLow, densityHigh };
  return canvas;
}

function ensureCloudBackgroundField(width, height, options = {}) {
  if (!cloudMode || !cloudScene?.nodesById?.size) return null;
  const nodes = cloudBackgroundNodes(Array.from(cloudScene.nodesById.values()));
  if (nodes.length < 3) return null;
  const totalNodes = Number(cloudScene.stats?.total_nodes || nodes.length);
  const warmupNodeCount = Math.min(260, Math.max(3, Math.floor(totalNodes * 0.16)));
  if (!cloudScene.complete && nodes.length < warmupNodeCount) return cloudBackgroundCache;
  if (!cloudScene.complete && cloudBackgroundCache?.createdAt && Date.now() - cloudBackgroundCache.createdAt < 900) {
    return cloudBackgroundCache;
  }
  const bounds = cloudBackgroundBounds(nodes);
  if (!bounds) return null;
  const theme = cloudBackgroundTheme();
  const signature = cloudBackgroundSignature(nodes, bounds, theme, width, height);
  if (cloudBackgroundCache?.signature === signature) return cloudBackgroundCache;
  if (!options.allowBuild) {
    scheduleCloudBackgroundBuild(width, height, signature);
    return cloudBackgroundCache;
  }
  const canvas = generateGenreBackgroundField(nodes, bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, {
    ...CLOUD_BACKGROUND_OPTIONS,
    bounds,
    theme,
  });
  cloudBackgroundCache = canvas ? {
    signature,
    canvas,
    bounds,
    theme,
    density: canvas.__genreBackgroundDensity || null,
    createdAt: Date.now(),
  } : null;
  return cloudBackgroundCache;
}

function scheduleCloudBackgroundBuild(width, height, signature = "") {
  if (!cloudMode || cloudBackgroundBuildSignature === signature) return;
  cloudBackgroundBuildSignature = signature;
  window.clearTimeout(cloudBackgroundBuildTimer);
  cloudBackgroundBuildTimer = window.setTimeout(() => {
    cloudBackgroundBuildTimer = 0;
    if (!cloudMode) return;
    if (cloudFadeFrame || cloudCanvasFrame || cloudRenderFrame) {
      cloudBackgroundBuildSignature = "";
      scheduleCloudBackgroundBuild(width, height, signature);
      return;
    }
    ensureCloudBackgroundField(width, height, { allowBuild: true });
    scheduleCloudCanvasRender();
  }, cloudScene?.complete ? 70 : 140);
}

function cloudBackgroundZoomOpacity() {
  const effectiveScale = cloudEffectiveLodScale();
  return clamp(0.18 + smoothstep(0.92, 2.3, effectiveScale) * 0.82, 0.18, 1);
}

function drawCloudBackgroundField(ctx, width, height) {
  const background = ensureCloudBackgroundField(width, height);
  if (!background?.canvas || !background.bounds) return;
  const { bounds, canvas } = background;
  const x = bounds.minX * viewScale + viewTx;
  const y = bounds.minY * viewScale + viewTy;
  const drawWidth = (bounds.maxX - bounds.minX) * viewScale;
  const drawHeight = (bounds.maxY - bounds.minY) * viewScale;
  if (x > width || y > height || x + drawWidth < 0 || y + drawHeight < 0) return;
  const previousAlpha = ctx.globalAlpha;
  const previousFilter = ctx.filter;
  const previousSmoothing = ctx.imageSmoothingEnabled;
  const previousSmoothingQuality = ctx.imageSmoothingQuality;
  ctx.imageSmoothingEnabled = true;
  if ("imageSmoothingQuality" in ctx) ctx.imageSmoothingQuality = "high";
  ctx.globalAlpha = cloudBackgroundZoomOpacity();
  ctx.filter = "blur(4px)";
  ctx.drawImage(canvas, x, y, drawWidth, drawHeight);
  ctx.filter = previousFilter;
  ctx.globalAlpha = previousAlpha;
  ctx.imageSmoothingEnabled = previousSmoothing;
  if ("imageSmoothingQuality" in ctx) ctx.imageSmoothingQuality = previousSmoothingQuality;
}

function cloudCanvasTextColor(node, fallbackColor = "") {
  if (node.similarity_color) return node.similarity_color;
  return fallbackColor || "#777";
}

function cloudCanvasRenderStyles() {
  if (cloudCanvasStyleCache) return cloudCanvasStyleCache;
  const styles = getComputedStyle(document.documentElement);
  cloudCanvasStyleCache = {
    fontFamily: styles.getPropertyValue("--font").trim() || "system-ui, sans-serif",
    fallbackTextColor: styles.getPropertyValue("--text-muted").trim() || "#777",
  };
  return cloudCanvasStyleCache;
}

function cloudNodeRelationshipTargetAlpha(node) {
  const relationshipGenreId = cloudRelationshipSelectedGenreId();
  if (!relationshipGenreId || relationshipGenreId === ROOT_KEY) return 1;
  if (!node?.id || node.id === relationshipGenreId) return 1;
  const distance = Number(node.selected_distance);
  if (!Number.isFinite(distance)) return CLOUD_RELATIONSHIP_ALPHA_FLOOR;
  const progress = clamp(distance / CLOUD_RELATIONSHIP_ALPHA_DISTANCE_STEPS, 0, 1);
  const fadeOut = easeOutCubic(progress);
  return clamp(
    CLOUD_RELATIONSHIP_ALPHA_FLOOR
      + (1 - CLOUD_RELATIONSHIP_ALPHA_FLOOR) * (1 - fadeOut),
    CLOUD_RELATIONSHIP_ALPHA_FLOOR,
    1,
  );
}

function cloudRelationshipSelectedGenreId() {
  if (cloudRelationshipSwitchPending()) {
    return cloudScene?.stats?.selected_genre_id || null;
  }
  return cloudScene?.stats?.selected_genre_id || cloudSelectedGenreId || null;
}

function cloudRelationshipSwitchPending() {
  return Boolean(
    cloudScene?.pendingAtlasSignature &&
    cloudScene.pendingAtlasSignature !== cloudScene.atlasSignature
  );
}

function cloudNodeRelationshipAlpha(node, now = performance.now()) {
  const fade = cloudRelationshipAlphaById.get(String(node?.id || ""));
  if (!fade) return cloudNodeRelationshipTargetAlpha(node);
  return clamp(cloudCanvasFadeAlpha(fade, now), 0, 1);
}

function cloudSelectedMarkerColor(node, fallbackColor = "") {
  const baseColor = cloudCanvasTextColor(node, fallbackColor);
  const rgb = parseCssColor(baseColor);
  if (!rgb) return baseColor;
  const hsl = rgbToHsl(rgb);
  return rgbToHex(hslToRgb({
    ...hsl,
    s: clamp(hsl.s * 0.22, 0, 1),
    l: clamp(0.94 + hsl.l * 0.03, 0, 0.975),
  }));
}

function cloudSelectedPillFillColor(node, fallbackColor = "") {
  const baseColor = cloudCanvasTextColor(node, fallbackColor);
  const rgb = parseCssColor(baseColor);
  if (!rgb) return baseColor || "#f2f2f2";
  const hsl = rgbToHsl(rgb);
  return rgbToHex(hslToRgb({
    ...hsl,
    s: clamp(hsl.s * 0.72, 0.08, 0.72),
    l: clamp(Math.max(hsl.l, 0.72), 0.72, 0.88),
  }));
}

function drawRoundRectPath(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function cloudCanClickNodes() {
  return cloudMode &&
    cloudClickEnabled &&
    Date.now() >= cloudClickEnableAt &&
    !document.body.classList.contains("is-panning-canvas");
}

function syncCloudClickAffordance() {
  const enabled = cloudCanClickNodes();
  document.body.classList.toggle("cloud-click-enabled", enabled);
  svg.classList.toggle("cloud-node-hit", enabled && Boolean(cloudHoveredNodeId));
  if (window.__wikiGenresCloudCullDebug) {
    window.__wikiGenresCloudCullDebug.clickEnabled = enabled;
    window.__wikiGenresCloudCullDebug.hoveredNodeId = cloudHoveredNodeId;
  }
}

function clearCloudHover() {
  if (!cloudHoveredNodeId) {
    clearScheduledCloudHoverCard();
    syncCloudClickAffordance();
    return;
  }
  cloudHoveredNodeId = null;
  clearScheduledCloudHoverCard();
  syncCloudClickAffordance();
  scheduleCloudCanvasRender();
}

function setCloudClickEnabled(enabled) {
  window.clearTimeout(cloudClickEnableTimer);
  cloudClickEnableTimer = 0;
  cloudClickEnabled = Boolean(enabled);
  if (enabled) cloudClickEnableAt = 0;
  else clearCloudHover();
  syncCloudClickAffordance();
}

function scheduleCloudClickEnable(delay = CLOUD_CLICK_IDLE_ENABLE_MS) {
  window.clearTimeout(cloudClickEnableTimer);
  cloudClickEnabled = false;
  cloudClickEnableAt = Date.now() + delay;
  clearCloudHover();
  cloudClickEnableTimer = window.setTimeout(() => {
    cloudClickEnableTimer = 0;
    cloudClickEnabled = true;
    cloudClickEnableAt = 0;
    updateCloudHoverFromPoint(lastPointerClientX, lastPointerClientY);
    syncCloudClickAffordance();
  }, delay);
}

function updateCloudHoverFromPoint(clientX, clientY) {
  if (!cloudMode || !Number.isFinite(clientX) || !Number.isFinite(clientY) || !cloudCanClickNodes()) {
    clearCloudHover();
    return null;
  }
  const hitNode = cloudCanvasHitTest(clientX, clientY);
  const nextId = hitNode?.id || null;
  if (nextId !== cloudHoveredNodeId) {
    cloudHoveredNodeId = nextId;
    syncCloudClickAffordance();
    scheduleCloudCanvasRender();
    if (nextId) scheduleCloudHoverCard(nextId);
    else clearScheduledCloudHoverCard();
  }
  return hitNode;
}

function cloudLabelSprite(node, selected, fontFamily, fallbackColor) {
  const label = node.label || node.wikipedia_title || "";
  const color = selected ? "#050505" : cloudCanvasTextColor(node, fallbackColor);
  const pillFill = selected ? cloudSelectedPillFillColor(node, fallbackColor) : "";
  const weight = selected ? 760 : 650;
  const widthPx = selected ? cloudSelectedPillWidth(node) : cloudBoxWidth(node);
  const heightPx = cloudBoxHeight(node);
  const cssWidth = Math.max(1, Math.ceil(widthPx + CLOUD_CANVAS_HIT_PAD_PX * 2));
  const cssHeight = Math.max(1, Math.ceil(heightPx + 4));
  const dpr = Math.max(1, cloudCanvasDpr || 1);
  const key = [
    node.id,
    label,
    color,
    pillFill,
    weight,
    CLOUD_FONT_SIZE,
    fontFamily,
    dpr,
    cssWidth,
    cssHeight,
  ].join("|");
  const cached = cloudLabelSpriteCache.get(key);
  if (cached) return cached;
  const canvas = typeof OffscreenCanvas === "function"
    ? new OffscreenCanvas(Math.ceil(cssWidth * dpr), Math.ceil(cssHeight * dpr))
    : document.createElement("canvas");
  canvas.width = Math.ceil(cssWidth * dpr);
  canvas.height = Math.ceil(cssHeight * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = `${weight} ${CLOUD_FONT_SIZE}px ${fontFamily}`;
  if (selected) {
    const pillX = Math.max(1, (cssWidth - widthPx) / 2);
    const pillY = Math.max(1, (cssHeight - heightPx) / 2);
    drawRoundRectPath(ctx, pillX, pillY, widthPx, heightPx, Math.min(7, heightPx / 2));
    ctx.fillStyle = pillFill;
    ctx.fill();
  }
  ctx.fillStyle = color;
  ctx.fillText(label, cssWidth / 2, cssHeight / 2);
  const sprite = { canvas, width: cssWidth, height: cssHeight };
  cloudLabelSpriteCache.set(key, sprite);
  return sprite;
}

function cloudScreenRectForNode(node, padPx = 0) {
  const x = Number(node.x) * viewScale + viewTx;
  const y = Number(node.y) * viewScale + viewTy;
  const widthPx = cloudRenderedBoxWidth(node);
  const heightPx = cloudBoxHeight(node);
  return {
    left: x - widthPx / 2 - padPx,
    right: x + widthPx / 2 + padPx,
    top: y - heightPx / 2 - padPx,
    bottom: y + heightPx / 2 + padPx,
  };
}

function screenRectsOverlap(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function clampScreenPoint(x, y, margin = 14) {
  return {
    x: Math.max(margin, Math.min(vw() - margin, x)),
    y: Math.max(margin, Math.min(vh() - margin, y)),
  };
}

function cloudSelectedMarkerCandidate(node, occupiedRects) {
  if (!node) return null;
  const projected = clampScreenPoint(
    Number(node.x) * viewScale + viewTx,
    Number(node.y) * viewScale + viewTy,
    CLOUD_SELECTED_MARKER_RADIUS_PX + CLOUD_SELECTED_MARKER_VIEWPORT_MARGIN_PX
  );
  const radius = CLOUD_SELECTED_MARKER_RADIUS_PX;
  const fits = point => {
    const rect = {
      left: point.x - radius - CLOUD_SELECTED_MARKER_CLEARANCE_PX,
      right: point.x + radius + CLOUD_SELECTED_MARKER_CLEARANCE_PX,
      top: point.y - radius - CLOUD_SELECTED_MARKER_CLEARANCE_PX,
      bottom: point.y + radius + CLOUD_SELECTED_MARKER_CLEARANCE_PX,
    };
    return !occupiedRects.some(existing => screenRectsOverlap(rect, existing));
  };
  if (fits(projected)) return projected;
  const steps = [4, 6, 8, 10, 14, 18, 24, 32, 44, 60];
  for (const distance of steps) {
    const samples = Math.max(8, Math.ceil(distance / 4));
    for (let index = 0; index < samples; index += 1) {
      const angle = (Math.PI * 2 * index) / samples;
      const point = clampScreenPoint(
        projected.x + Math.cos(angle) * distance,
        projected.y + Math.sin(angle) * distance,
        radius + CLOUD_SELECTED_MARKER_VIEWPORT_MARGIN_PX
      );
      if (fits(point)) return point;
    }
  }
  return projected;
}

function clearCloudSelectedMarkerAnimation() {
  if (cloudSelectedMarkerFrame) {
    cancelAnimationFrame(cloudSelectedMarkerFrame);
    cloudSelectedMarkerFrame = 0;
  }
}

function scheduleCloudSelectedMarkerAnimation() {
  if (cloudSelectedMarkerFrame || prefersReducedMotion()) return;
  cloudSelectedMarkerFrame = requestAnimationFrame(() => {
    cloudSelectedMarkerFrame = 0;
    scheduleCloudCanvasRender();
    if (cloudSelectedMarker?.transition) {
      scheduleCloudSelectedMarkerAnimation();
    }
  });
}

function stepCloudSelectedMarker(now = performance.now()) {
  if (!cloudSelectedMarker?.transition) return;
  const transition = cloudSelectedMarker.transition;
  const duration = Math.max(1, Number(transition.duration) || 1);
  const progress = clamp((now - Number(transition.startedAt || 0)) / duration, 0, 1);
  const eased = 1 - Math.pow(1 - progress, 3);
  cloudSelectedMarker.alpha = Number(transition.fromAlpha || 0) +
    (Number(transition.toAlpha || 0) - Number(transition.fromAlpha || 0)) * eased;
  if (progress < 1) return;
  cloudSelectedMarker.alpha = transition.toAlpha;
  if (transition.next) {
    cloudSelectedMarker = {
      ...transition.next,
      alpha: 0,
      transition: {
        fromAlpha: 0,
        toAlpha: 1,
        startedAt: now,
        duration: CLOUD_SELECTED_MARKER_FADE_IN_MS,
        next: null,
      },
    };
    return;
  }
  if (cloudSelectedMarker.alpha <= 0.01) {
    cloudSelectedMarker = null;
    return;
  }
  cloudSelectedMarker.transition = null;
}

function startCloudSelectedMarkerTransition(toAlpha, duration, next = null, now = performance.now()) {
  if (!cloudSelectedMarker) return;
  const alpha = Number(cloudSelectedMarker.alpha);
  cloudSelectedMarker.transition = {
    fromAlpha: Number.isFinite(alpha) ? alpha : 1,
    toAlpha,
    startedAt: now,
    duration,
    next,
  };
  scheduleCloudSelectedMarkerAnimation();
}

function cloudSelectedMarkerMatches(a, b) {
  return Boolean(
    a &&
    b &&
    a.id === b.id &&
    Math.abs(Number(a.x) - Number(b.x)) <= 0.5 &&
    Math.abs(Number(a.y) - Number(b.y)) <= 0.5
  );
}

function syncCloudSelectedMarker(desiredMarker, now = performance.now()) {
  if (prefersReducedMotion()) {
    cloudSelectedMarker = desiredMarker ? { ...desiredMarker, alpha: 1, transition: null } : null;
    clearCloudSelectedMarkerAnimation();
    return;
  }
  const zoomChanged = cloudSelectedMarker
    ? Math.abs(Number(desiredMarker?.scale ?? viewScale) - Number(cloudSelectedMarker.scale ?? viewScale)) > 0.0005
    : false;
  if (!desiredMarker) {
    if (cloudSelectedMarker && !zoomChanged) {
      cloudSelectedMarker = null;
      clearCloudSelectedMarkerAnimation();
      return;
    }
    if (cloudSelectedMarker && !(cloudSelectedMarker.transition?.toAlpha === 0 && !cloudSelectedMarker.transition?.next)) {
      startCloudSelectedMarkerTransition(0, CLOUD_SELECTED_MARKER_FADE_OUT_MS, null, now);
    }
    return;
  }
  if (!cloudSelectedMarker) {
    cloudSelectedMarker = {
      ...desiredMarker,
      alpha: 0,
      transition: null,
    };
    startCloudSelectedMarkerTransition(1, CLOUD_SELECTED_MARKER_FADE_IN_MS, null, now);
    return;
  }
  if (cloudSelectedMarkerMatches(cloudSelectedMarker, desiredMarker)) {
    cloudSelectedMarker.id = desiredMarker.id;
    cloudSelectedMarker.x = desiredMarker.x;
    cloudSelectedMarker.y = desiredMarker.y;
    cloudSelectedMarker.radius = desiredMarker.radius;
    cloudSelectedMarker.color = desiredMarker.color;
    cloudSelectedMarker.scale = desiredMarker.scale;
    if (cloudSelectedMarker.transition?.toAlpha === 0) {
      startCloudSelectedMarkerTransition(1, CLOUD_SELECTED_MARKER_FADE_IN_MS, null, now);
    }
    return;
  }
  if (!zoomChanged) {
    cloudSelectedMarker = {
      ...desiredMarker,
      alpha: 1,
      transition: null,
    };
    clearCloudSelectedMarkerAnimation();
    return;
  }
  const nextMarker = { ...desiredMarker };
  if (cloudSelectedMarker.transition?.toAlpha === 0) {
    cloudSelectedMarker.transition.next = nextMarker;
    scheduleCloudSelectedMarkerAnimation();
    return;
  }
  startCloudSelectedMarkerTransition(0, CLOUD_SELECTED_MARKER_FADE_OUT_MS, nextMarker, now);
}

function resizeCloudCanvas() {
  if (!cloudLabelCanvas || !cloudLabelCtx) return false;
  const width = Math.max(1, Math.ceil(vw()));
  const height = Math.max(1, Math.ceil(vh()));
  const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  const dprChanged = Math.abs(dpr - cloudCanvasDpr) > 0.001;
  const pixelWidth = Math.ceil(width * dpr);
  const pixelHeight = Math.ceil(height * dpr);
  const changed = cloudLabelCanvas.width !== pixelWidth || cloudLabelCanvas.height !== pixelHeight;
  if (changed) {
    cloudLabelCanvas.width = pixelWidth;
    cloudLabelCanvas.height = pixelHeight;
    cloudLabelCanvas.style.width = `${width}px`;
      cloudLabelCanvas.style.height = `${height}px`;
  }
  cloudCanvasDpr = dpr;
  if (dprChanged) cloudLabelSpriteCache = new Map();
  cloudLabelCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return changed;
}

function updateCloudCanvasFadeTargets(nodes, options = {}) {
  const now = Number.isFinite(Number(options.now)) ? Number(options.now) : performance.now();
  const noFade = Boolean(options.noFade) || prefersReducedMotion();
  const targetIds = new Set(nodes.map(node => String(node.id)));
  const signature = cloudRenderTargetSignature(nodes);
  cloudCanvasAlphaById.clear();
  cloudCanvasVisibleIds = targetIds;
  applyCloudPresentationTargets(nodes, {
    noFade,
    hydrateNew: Boolean(options.hydrateNew),
    now,
    signature,
  });
}

function cloudPresentationSelectedTarget(nodeId) {
  return nodeId === String(cloudSelectedGenreId || "") ? 1 : 0;
}

function cloudPresentationRecordEntry(record) {
  if (!record?.node) return null;
  return {
    node: record.node,
    alpha: clamp(Number(record.alpha) || 0, 0, 1),
    relationshipAlpha: clamp(Number(record.relationshipAlpha ?? cloudNodeRelationshipTargetAlpha(record.node)), 0, 1),
    selectedAlpha: clamp(Number(record.selectedAlpha) || 0, 0, 1),
    active: record.active !== false,
    exiting: record.active === false,
  };
}

function cloudPresentationMaxDelta() {
  let maxDelta = 0;
  for (const record of cloudPresentationById.values()) {
    maxDelta = Math.max(
      maxDelta,
      Math.abs(Number(record.alpha || 0) - Number(record.targetAlpha || 0)),
      Math.abs(Number(record.selectedAlpha || 0) - Number(record.targetSelectedAlpha || 0)),
      Math.abs(Number(record.relationshipAlpha || 0) - Number(record.targetRelationshipAlpha || 0)),
    );
  }
  return maxDelta;
}

function cloudPresentationAnimating() {
  return cloudPresentationMaxDelta() > CLOUD_PRESENTATION_EPSILON;
}

function applyCloudPresentationTargets(nodes, options = {}) {
  const now = Number(options.now) || performance.now();
  const noFade = Boolean(options.noFade);
  const hydrateNew = Boolean(options.hydrateNew);
  const targetIds = new Set();
  let needsFrame = false;
  if (!cloudPresentationLastAt) cloudPresentationLastAt = now;

  for (const node of nodes || []) {
    if (!node?.id) continue;
    const nodeId = String(node.id);
    targetIds.add(nodeId);
    const targetSelectedAlpha = cloudPresentationSelectedTarget(nodeId);
    const targetRelationshipAlpha = cloudNodeRelationshipTargetAlpha(node);
    let record = cloudPresentationById.get(nodeId);
    if (!record) {
      const initialAlpha = noFade || hydrateNew ? 1 : 0;
      record = {
        node,
        alpha: initialAlpha,
        targetAlpha: 1,
        selectedAlpha: noFade ? targetSelectedAlpha : 0,
        targetSelectedAlpha,
        relationshipAlpha: noFade ? targetRelationshipAlpha : targetRelationshipAlpha,
        targetRelationshipAlpha,
        fadeInMs: CLOUD_CANVAS_FADE_IN_MS,
        fadeOutMs: CLOUD_CANVAS_FADE_OUT_MS,
        active: true,
      };
      cloudPresentationById.set(nodeId, record);
      if (!noFade) needsFrame = true;
      continue;
    }
    record.node = node;
    record.active = true;
    record.targetAlpha = 1;
    record.targetSelectedAlpha = targetSelectedAlpha;
    record.targetRelationshipAlpha = targetRelationshipAlpha;
    record.fadeInMs = CLOUD_CANVAS_FADE_IN_MS;
    record.fadeOutMs = CLOUD_CANVAS_FADE_OUT_MS;
    if (noFade) {
      record.alpha = record.targetAlpha;
      record.selectedAlpha = record.targetSelectedAlpha;
      record.relationshipAlpha = record.targetRelationshipAlpha;
    }
    if (
      Math.abs(Number(record.alpha || 0) - record.targetAlpha) > CLOUD_PRESENTATION_EPSILON ||
      Math.abs(Number(record.selectedAlpha || 0) - record.targetSelectedAlpha) > CLOUD_PRESENTATION_EPSILON ||
      Math.abs(Number(record.relationshipAlpha || 0) - record.targetRelationshipAlpha) > CLOUD_PRESENTATION_EPSILON
    ) {
      needsFrame = true;
    }
  }

  for (const [nodeId, record] of cloudPresentationById.entries()) {
    if (targetIds.has(nodeId)) continue;
    record.active = false;
    record.targetAlpha = 0;
    record.targetSelectedAlpha = 0;
    record.targetRelationshipAlpha = Number(record.relationshipAlpha ?? record.targetRelationshipAlpha ?? 1);
    record.fadeOutMs = CLOUD_CANVAS_FADE_OUT_MS;
    if (noFade) {
      cloudPresentationById.delete(nodeId);
      continue;
    }
    if (
      Math.abs(Number(record.alpha || 0)) > CLOUD_PRESENTATION_EPSILON ||
      Math.abs(Number(record.selectedAlpha || 0)) > CLOUD_PRESENTATION_EPSILON
    ) {
      needsFrame = true;
    } else {
      cloudPresentationById.delete(nodeId);
    }
  }

  cloudPresentationTargetSignature = options.signature || "";
  cloudRenderTransition = null;
  cloudRenderSnapshot = null;
  if (needsFrame && !noFade) scheduleCloudFade();
}

function cloudPresentationApproach(current, target, maxStep) {
  const value = Number(current) || 0;
  const next = Number(target) || 0;
  const delta = next - value;
  if (Math.abs(delta) <= CLOUD_PRESENTATION_EPSILON) return next;
  return value + Math.sign(delta) * Math.min(Math.abs(delta), maxStep);
}

function stepCloudPresentation(now = performance.now()) {
  if (!cloudPresentationById.size) {
    cloudPresentationLastAt = now;
    return false;
  }
  const previousAt = cloudPresentationLastAt || now;
  const dt = Math.min(64, Math.max(0, now - previousAt || 16));
  cloudPresentationLastAt = now;
  let active = false;
  for (const [nodeId, record] of cloudPresentationById.entries()) {
    const alphaDuration = Number(record.targetAlpha || 0) < Number(record.alpha || 0)
      ? Number(record.fadeOutMs || CLOUD_CANVAS_FADE_OUT_MS)
      : Number(record.fadeInMs || CLOUD_CANVAS_FADE_IN_MS);
    const alphaStep = clamp(dt / Math.max(1, alphaDuration), 0, 1);
    const selectedStep = clamp(dt / Math.max(1, CLOUD_CANVAS_TRANSITION_MS), 0, 1);
    const relationshipStep = clamp(dt / Math.max(1, CLOUD_RELATIONSHIP_ALPHA_FADE_MS), 0, 1);
    record.alpha = cloudPresentationApproach(record.alpha, record.targetAlpha, alphaStep);
    record.selectedAlpha = cloudPresentationApproach(record.selectedAlpha, record.targetSelectedAlpha, selectedStep);
    record.relationshipAlpha = cloudPresentationApproach(record.relationshipAlpha, record.targetRelationshipAlpha, relationshipStep);
    const isAnimating =
      Math.abs(Number(record.alpha || 0) - Number(record.targetAlpha || 0)) > CLOUD_PRESENTATION_EPSILON ||
      Math.abs(Number(record.selectedAlpha || 0) - Number(record.targetSelectedAlpha || 0)) > CLOUD_PRESENTATION_EPSILON ||
      Math.abs(Number(record.relationshipAlpha || 0) - Number(record.targetRelationshipAlpha || 0)) > CLOUD_PRESENTATION_EPSILON;
    active = active || isAnimating;
    if (
      !record.active &&
      !isAnimating &&
      Number(record.alpha || 0) <= CLOUD_PRESENTATION_EPSILON &&
      Number(record.selectedAlpha || 0) <= CLOUD_PRESENTATION_EPSILON
    ) {
      cloudPresentationById.delete(nodeId);
    }
  }
  cloudRenderSnapshot = null;
  return active;
}

function cloudCanvasFadeAlpha(fade, now = performance.now()) {
  if (!fade) return 0;
  const duration = Math.max(1, Number(fade.duration) || 1);
  const progress = clamp((now - Number(fade.startedAt || 0)) / duration, 0, 1);
  const eased = 1 - Math.pow(1 - progress, 3);
  return Number(fade.from || 0) + (Number(fade.target || 0) - Number(fade.from || 0)) * eased;
}

function cloudRenderTargetSignature(nodes) {
  const relationshipGenreId = cloudRelationshipSelectedGenreId() || "";
  const selectedGenreId = cloudSelectedGenreId || "";
  const nodeIds = nodes.map(node => String(node.id)).sort();
  return [
    relationshipGenreId,
    selectedGenreId,
    nodeIds.join(","),
  ].join("|");
}

function cloudBuildRenderSnapshot(nodes, signature = cloudRenderTargetSignature(nodes), alpha = 1) {
  const entriesById = new Map();
  for (const node of nodes) {
    if (!node?.id) continue;
    const nodeId = String(node.id);
    entriesById.set(nodeId, {
      node,
      alpha,
      relationshipAlpha: cloudNodeRelationshipTargetAlpha(node),
      selectedAlpha: nodeId === String(cloudSelectedGenreId || "") ? 1 : 0,
    });
  }
  return {
    signature,
    entriesById,
  };
}

function cloudBuildLodRenderTargetSnapshot(nodes, signature, fromSnapshot) {
  const snapshot = cloudBuildRenderSnapshot(nodes, signature, 1);
  const targetIds = new Set(nodes.map(node => String(node.id)));
  for (const [nodeId, entry] of fromSnapshot?.entriesById?.entries?.() || []) {
    if (targetIds.has(nodeId)) continue;
    snapshot.entriesById.set(nodeId, {
      node: entry.node,
      alpha: 0,
      relationshipAlpha: entry.relationshipAlpha,
      selectedAlpha: 0,
      fadingOut: true,
    });
  }
  return snapshot;
}

function cloudPrunedRenderSnapshot(snapshot) {
  if (!snapshot?.entriesById) return snapshot;
  const entriesById = new Map();
  for (const [nodeId, entry] of snapshot.entriesById.entries()) {
    if (Number(entry.alpha) <= 0.01 && Number(entry.selectedAlpha || 0) <= 0.01) continue;
    entriesById.set(nodeId, entry);
  }
  return {
    ...snapshot,
    entriesById,
  };
}

function cloudRenderTransitionProgress(now = performance.now()) {
  if (!cloudRenderTransition) return 1;
  const duration = Math.max(1, Number(cloudRenderTransition.duration) || 1);
  const progress = clamp((now - Number(cloudRenderTransition.startedAt || 0)) / duration, 0, 1);
  return easeInOutCubic(progress);
}

function cloudResolvedRenderEntry(nodeId, now = performance.now()) {
  const id = String(nodeId);
  if (!cloudRenderTransition) {
    return cloudRenderSnapshot?.entriesById?.get(id) || null;
  }
  const progress = cloudRenderTransitionProgress(now);
  const fromEntry = cloudRenderTransition.from.entriesById.get(id);
  const toEntry = cloudRenderTransition.to.entriesById.get(id);
  if (!fromEntry && !toEntry) return null;
  const fromAlpha = Number(fromEntry?.alpha ?? 0);
  const toAlpha = Number(toEntry?.alpha ?? 0);
  const fromRelationshipAlpha = Number(fromEntry?.relationshipAlpha ?? toEntry?.relationshipAlpha ?? 1);
  const toRelationshipAlpha = Number(toEntry?.relationshipAlpha ?? fromEntry?.relationshipAlpha ?? 1);
  const fromSelectedAlpha = Number(fromEntry?.selectedAlpha ?? 0);
  const toSelectedAlpha = Number(toEntry?.selectedAlpha ?? 0);
  return {
    node: toEntry?.node || fromEntry?.node,
    alpha: fromAlpha + (toAlpha - fromAlpha) * progress,
    relationshipAlpha: fromRelationshipAlpha + (toRelationshipAlpha - fromRelationshipAlpha) * progress,
    selectedAlpha: fromSelectedAlpha + (toSelectedAlpha - fromSelectedAlpha) * progress,
  };
}

function cloudCurrentRenderEntries(now = performance.now()) {
  if (cloudPresentationById.size) {
    const exitingEntries = [];
    const activeEntries = [];
    for (const record of cloudPresentationById.values()) {
      const entry = cloudPresentationRecordEntry(record);
      if (!entry || (entry.alpha <= 0.01 && entry.selectedAlpha <= 0.01)) continue;
      if (entry.active) activeEntries.push(entry);
      else exitingEntries.push(entry);
    }
    return [...exitingEntries, ...activeEntries];
  }
  if (!cloudRenderTransition) {
    return Array.from(cloudRenderSnapshot?.entriesById?.values?.() || []);
  }
  const ids = new Set([
    ...cloudRenderTransition.from.entriesById.keys(),
    ...cloudRenderTransition.to.entriesById.keys(),
  ]);
  const entries = [];
  for (const nodeId of ids) {
    const entry = cloudResolvedRenderEntry(nodeId, now);
    if (entry && (entry.alpha > 0.01 || entry.selectedAlpha > 0.01)) entries.push(entry);
  }
  return entries;
}

function cloudMaterializedRenderSnapshot(now = performance.now()) {
  const entriesById = new Map();
  for (const entry of cloudCurrentRenderEntries(now)) {
    entriesById.set(String(entry.node.id), {
      node: entry.node,
      alpha: entry.alpha,
      relationshipAlpha: entry.relationshipAlpha,
      selectedAlpha: entry.selectedAlpha,
    });
  }
  return {
    signature: `materialized:${now}`,
    entriesById,
  };
}

function stepCloudRenderTransition(now = performance.now()) {
  if (!cloudRenderTransition) return false;
  const progress = cloudRenderTransitionProgress(now);
  if (progress < 0.999) return true;
  cloudRenderSnapshot = cloudPrunedRenderSnapshot(cloudRenderTransition.to);
  cloudRenderTransition = null;
  return false;
}

function cloudCanvasNodeAlpha(nodeId, now = performance.now()) {
  const record = cloudPresentationById.get(String(nodeId));
  if (record) return clamp(Number(record.alpha) || 0, 0, 1);
  const entry = cloudResolvedRenderEntry(String(nodeId), now);
  return entry ? entry.alpha : 0;
}

function updateCloudSelectedLabelFadeTargets(nodes) {
  cloudSelectedLabelAlphaById.clear();
}

function startCloudSelectedLabelFade(nodeId, now = performance.now()) {
  scheduleCloudCanvasRender();
}

function updateCloudHoverUnderlineAlphaTargets(nodes) {
  const hoverKey = detailIndicatorPreviewKey && String(detailIndicatorPreviewKey).startsWith("cloud-")
    ? detailIndicatorPreviewKey
    : null;
  const now = performance.now();
  const activeIds = new Set(nodes.map(node => String(node.id)));
  let needsFrame = false;
  for (const node of nodes) {
    const nodeId = String(node.id);
    const target = hoverKey === detailKeyForCloudNodeId(nodeId) ? 1 : 0;
    const existing = cloudHoverUnderlineAlphaById.get(nodeId);
    const current = existing ? cloudCanvasFadeAlpha(existing, now) : 0;
    if (!existing && target <= 0) continue;
    if (existing?.target === target) {
      existing.alpha = Math.abs(current - target) <= 0.01 ? target : current;
      if (existing.alpha !== target) needsFrame = true;
      continue;
    }
    cloudHoverUnderlineAlphaById.set(nodeId, {
      alpha: prefersReducedMotion() ? target : current,
      from: prefersReducedMotion() ? target : current,
      target,
      startedAt: now,
      duration: prefersReducedMotion()
        ? 1
        : target > 0
          ? CLOUD_HOVER_UNDERLINE_FADE_IN_MS
          : CLOUD_HOVER_UNDERLINE_FADE_OUT_MS,
    });
    if (!prefersReducedMotion()) needsFrame = true;
  }
  for (const [nodeId, fade] of cloudHoverUnderlineAlphaById.entries()) {
    if (activeIds.has(nodeId) || fade.target === 0) continue;
    const alpha = cloudCanvasFadeAlpha(fade, now);
    cloudHoverUnderlineAlphaById.set(nodeId, {
      alpha,
      from: alpha,
      target: 0,
      startedAt: now,
      duration: prefersReducedMotion() ? 1 : CLOUD_HOVER_UNDERLINE_FADE_OUT_MS,
    });
    if (!prefersReducedMotion()) needsFrame = true;
  }
  if (needsFrame) scheduleCloudHoverUnderlineFade();
}

function cloudHoverUnderlineAlpha(nodeId, now = performance.now()) {
  const fade = cloudHoverUnderlineAlphaById.get(String(nodeId));
  if (!fade) return 0;
  return clamp(cloudCanvasFadeAlpha(fade, now), 0, 1);
}

function stepCloudFadeMap(map, now, shouldDeleteSettled = () => false) {
  let active = false;
  for (const [nodeId, fade] of map.entries()) {
    const alpha = cloudCanvasFadeAlpha(fade, now);
    fade.alpha = alpha;
    if (Math.abs(alpha - fade.target) > 0.01) {
      active = true;
      continue;
    }
    fade.alpha = fade.target;
    fade.from = fade.target;
    if (shouldDeleteSettled(fade, nodeId)) map.delete(nodeId);
  }
  return active;
}

function stepCloudFades() {
  cloudFadeFrame = 0;
  cloudCanvasFadeFrame = 0;
  cloudSelectedLabelFadeFrame = 0;
  cloudHoverUnderlineFadeFrame = 0;
  cloudRelationshipFadeFrame = 0;
  if (!cloudMode) return;
  const now = performance.now();
  const activePresentation = cloudPresentationAnimating();
  const activeRenderTransition = stepCloudRenderTransition(now);
  const activeCanvas = stepCloudFadeMap(
    cloudCanvasAlphaById,
    now,
    () => true
  );
  const activeSelected = stepCloudFadeMap(
    cloudSelectedLabelAlphaById,
    now,
    fade => fade.target <= 0
  );
  const activeHover = stepCloudFadeMap(
    cloudHoverUnderlineAlphaById,
    now,
    fade => fade.target <= 0
  );
  const activeRelationship = stepCloudFadeMap(
    cloudRelationshipAlphaById,
    now,
    fade => fade.target >= 0.995 && (!cloudSelectedGenreId || cloudSelectedGenreId === ROOT_KEY)
  );
  const hasFadeState =
    cloudPresentationById.size ||
    Boolean(cloudRenderTransition) ||
    cloudCanvasAlphaById.size ||
    cloudSelectedLabelAlphaById.size ||
    cloudHoverUnderlineAlphaById.size ||
    cloudRelationshipAlphaById.size;
  if (hasFadeState || activePresentation || activeRenderTransition || activeCanvas || activeSelected || activeHover || activeRelationship) {
    scheduleCloudCanvasRender();
  }
  if (activePresentation || activeRenderTransition || activeCanvas || activeSelected || activeHover || activeRelationship) {
    scheduleCloudFade();
  }
}

function scheduleCloudFade() {
  if (cloudFadeFrame || prefersReducedMotion()) return;
  cloudFadeFrame = requestAnimationFrame(stepCloudFades);
  cloudCanvasFadeFrame = cloudFadeFrame;
  cloudSelectedLabelFadeFrame = cloudFadeFrame;
  cloudHoverUnderlineFadeFrame = cloudFadeFrame;
  cloudRelationshipFadeFrame = cloudFadeFrame;
}

function cancelCloudFadeFrame() {
  if (!cloudFadeFrame) return;
  cancelAnimationFrame(cloudFadeFrame);
  cloudFadeFrame = 0;
  cloudCanvasFadeFrame = 0;
  cloudSelectedLabelFadeFrame = 0;
  cloudHoverUnderlineFadeFrame = 0;
  cloudRelationshipFadeFrame = 0;
}

function stepCloudHoverUnderlineFades() {
  stepCloudFades();
}

function scheduleCloudHoverUnderlineFade() {
  scheduleCloudFade();
}

function updateCloudRelationshipAlphaTargets(nodes) {
  cloudRelationshipAlphaById.clear();
}

function cloudSelectedLabelAlpha(nodeId, now = performance.now()) {
  const fade = cloudSelectedLabelAlphaById.get(String(nodeId));
  if (!fade) return 0;
  return clamp(cloudCanvasFadeAlpha(fade, now), 0, 1);
}

function stepCloudSelectedLabelFades() {
  stepCloudFades();
}

function scheduleCloudSelectedLabelFade() {
  scheduleCloudFade();
}

function stepCloudRelationshipFades() {
  stepCloudFades();
}

function scheduleCloudRelationshipFade() {
  scheduleCloudFade();
}

function stepCloudCanvasFades() {
  stepCloudFades();
}

function scheduleCloudCanvasFade() {
  scheduleCloudFade();
}

function cloudDrawableNodes(now = performance.now()) {
  return cloudDrawableEntries(now).map(entry => entry.node);
}

function cloudDrawableEntries(now = performance.now()) {
  const entries = [];
  const seen = new Set();
  const addEntry = entry => {
    const node = entry?.node;
    if (!node?.id) return;
    const nodeId = String(node.id);
    if (seen.has(nodeId)) return;
    const selectedAlpha = clamp(Number(entry.selectedAlpha) || 0, 0, 1);
    const hoverAlpha = cloudHoverUnderlineAlpha(nodeId, now);
    if (entry.alpha <= 0.01 && selectedAlpha <= 0.01 && hoverAlpha <= 0.01) return;
    seen.add(nodeId);
    entries.push(entry);
  };
  for (const entry of cloudCurrentRenderEntries(now)) addEntry(entry);
  if (cloudSelectedGenreId && !seen.has(String(cloudSelectedGenreId))) {
    const node = cloudScene?.nodesById?.get(cloudSelectedGenreId);
    if (node) {
      addEntry({
        node,
        alpha: 0,
        relationshipAlpha: cloudNodeRelationshipTargetAlpha(node),
        selectedAlpha: 1,
      });
    }
  }
  return entries;
}

function renderCloudCanvasNow(frameNow = performance.now()) {
  const now = Number.isFinite(Number(frameNow)) ? Number(frameNow) : performance.now();
  const renderStartedAt = performance.now();
  cloudCanvasFrame = 0;
  if (!cloudLabelCanvas || !cloudLabelCtx) return;
  resizeCloudCanvas();
  const activePresentation = stepCloudPresentation(now);
  if (activePresentation) scheduleCloudFade();
  stepCloudSelectedMarker(now);
  const ctx = cloudLabelCtx;
  const width = vw();
  const height = vh();
  ctx.clearRect(0, 0, width, height);
  if (!cloudMode) {
    if (cloudInitialRenderPending) setCloudInitialLoading(false);
    cloudCanvasHitNodes = [];
    cloudSelectedMarker = null;
    clearCloudSelectedMarkerAnimation();
    return;
  }
  drawCloudBackgroundField(ctx, width, height);
  const selectedSceneNode = cloudSelectedGenreId ? cloudScene?.nodesById?.get(cloudSelectedGenreId) : null;
  if (
    !cloudCanvasNodes.length &&
    !cloudPresentationById.size &&
    !cloudRenderSnapshot?.entriesById?.size &&
    !cloudRenderTransition &&
    !selectedSceneNode
  ) {
    cloudCanvasHitNodes = [];
    cloudSelectedMarker = null;
    clearCloudSelectedMarkerAnimation();
    return;
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const { fontFamily, fallbackTextColor } = cloudCanvasRenderStyles();
  ctx.font = `650 ${CLOUD_FONT_SIZE}px ${fontFamily}`;
  const drawableEntries = cloudDrawableEntries(now);
  const occupiedRects = [];
  const drawEntry = entry => {
    const node = entry?.node;
    if (!node) return false;
    const alpha = clamp(Number(entry.alpha) || 0, 0, 1);
    const selectedAlpha = clamp(Number(entry.selectedAlpha) || 0, 0, 1);
    if (alpha <= 0.01 && selectedAlpha <= 0.01) return false;
    const x = Number(node.x) * viewScale + viewTx;
    const y = Number(node.y) * viewScale + viewTy;
    const widthPx = cloudRenderedBoxWidth(node);
    const heightPx = cloudBoxHeight(node);
    const halfWidth = widthPx / 2;
    const halfHeight = heightPx / 2;
    if (
      x + halfWidth < -CLOUD_CANVAS_HIT_PAD_PX ||
      x - halfWidth > width + CLOUD_CANVAS_HIT_PAD_PX ||
      y + halfHeight < -CLOUD_CANVAS_HIT_PAD_PX ||
      y - halfHeight > height + CLOUD_CANVAS_HIT_PAD_PX
    ) {
      return false;
    }
    occupiedRects.push({
      left: x - halfWidth,
      right: x + halfWidth,
      top: y - halfHeight,
      bottom: y + halfHeight,
    });
    const hoverUnderlineAlpha = cloudHoverUnderlineAlpha(node.id, now);
    const relationshipAlpha = clamp(Number(entry.relationshipAlpha) || 0, 0, 1);
    const normalAlpha = 0.94 * alpha * relationshipAlpha * Math.max(0, 1 - selectedAlpha);
    const textColor = cloudCanvasTextColor(node, fallbackTextColor);
    if (normalAlpha > 0.01) {
      ctx.globalAlpha = normalAlpha;
      const sprite = cloudLabelSprite(node, false, fontFamily, fallbackTextColor);
      if (sprite) {
        ctx.drawImage(sprite.canvas, x - sprite.width / 2, y - sprite.height / 2, sprite.width, sprite.height);
      } else {
        ctx.font = `650 ${CLOUD_FONT_SIZE}px ${fontFamily}`;
        ctx.fillStyle = textColor;
        ctx.fillText(node.label || node.wikipedia_title || "", x, y);
      }
    }
    if (hoverUnderlineAlpha > 0.01 && node.id !== cloudSelectedGenreId) {
      const underlineWidth = Math.max(12, cloudTextWidth(node) - 2);
      ctx.save();
      ctx.globalAlpha = 0.96 * alpha * relationshipAlpha * hoverUnderlineAlpha;
      ctx.strokeStyle = textColor;
      ctx.lineWidth = 1.15;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x - underlineWidth / 2, y + cloudTextHeight(node) * 0.35);
      ctx.lineTo(x + underlineWidth / 2, y + cloudTextHeight(node) * 0.35);
      ctx.stroke();
      ctx.restore();
    }
    if (selectedAlpha > 0.01) {
      ctx.globalAlpha = selectedAlpha;
      const selectedSprite = cloudLabelSprite(node, true, fontFamily, fallbackTextColor);
      if (selectedSprite) {
        ctx.drawImage(
          selectedSprite.canvas,
          x - selectedSprite.width / 2,
          y - selectedSprite.height / 2,
          selectedSprite.width,
          selectedSprite.height
        );
      }
    }
    return true;
  };
  let selectedLabelDrawn = false;
  for (const entry of drawableEntries) {
    const drew = drawEntry(entry);
    const node = entry.node;
    if (drew && node.id === cloudSelectedGenreId) selectedLabelDrawn = true;
  }
  const selectedNode = selectedSceneNode;
  if (selectedNode && !selectedLabelDrawn && !drawableEntries.some(entry => entry.node.id === cloudSelectedGenreId)) {
    selectedLabelDrawn = drawEntry({
      node: selectedNode,
      alpha: 0,
      relationshipAlpha: cloudNodeRelationshipTargetAlpha(selectedNode),
    });
  }
  cloudSelectedMarker = null;
  clearCloudSelectedMarkerAnimation();
  ctx.globalAlpha = 1;
	  const activeDrawableEntries = drawableEntries.filter(entry => entry?.active !== false);
	  cloudCanvasHitNodes = activeDrawableEntries;
	  if (window.__wikiGenresCloudCullDebug) {
	    const presentationDelta = cloudPresentationMaxDelta();
	    const exitingPresentationNodes = drawableEntries.length - activeDrawableEntries.length;
	    window.__wikiGenresCloudCullDebug.canvasFadeNodes = cloudCanvasAlphaById.size;
	    window.__wikiGenresCloudCullDebug.presentationNodes = cloudPresentationById.size;
	    window.__wikiGenresCloudCullDebug.exitingPresentationNodes = exitingPresentationNodes;
	    window.__wikiGenresCloudCullDebug.presentationDelta = presentationDelta;
	    window.__wikiGenresCloudCullDebug.drawableNodes = drawableEntries.length;
    window.__wikiGenresCloudCullDebug.canvasHitNodes = cloudCanvasHitNodes.length;
    window.__wikiGenresCloudCullDebug.clickEnabled = cloudCanClickNodes();
    window.__wikiGenresCloudCullDebug.hoveredNodeId = cloudHoveredNodeId;
    window.__wikiGenresCloudCullDebug.selectedMarker = null;
    window.__wikiGenresCloudCullDebug.renderTransitionActive = presentationDelta > CLOUD_PRESENTATION_EPSILON || Boolean(cloudRenderTransition);
    window.__wikiGenresCloudCullDebug.renderTransitionProgress = cloudRenderTransition
      ? cloudRenderTransitionProgress(now)
      : 1 - clamp(presentationDelta, 0, 1);
    window.__wikiGenresCloudCullDebug.renderMs = performance.now() - renderStartedAt;
  }
}

function scheduleCloudCanvasRender() {
  if (cloudCanvasFrame) return;
  cloudCanvasFrame = requestAnimationFrame(renderCloudCanvasNow);
}

function cloudCanvasHitTest(clientX, clientY) {
  if (!cloudMode || !cloudCanvasHitNodes.length) return null;
  const rect = svg.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
	  for (let index = cloudCanvasHitNodes.length - 1; index >= 0; index -= 1) {
	    const entry = cloudCanvasHitNodes[index];
	    const node = entry?.node || entry;
	    if (!node?.id) continue;
	    const visualAlpha = Number(entry?.alpha ?? cloudCanvasNodeAlpha(node.id));
	    if (visualAlpha <= 0.45 && node.id !== cloudSelectedGenreId) continue;
    const screenX = Number(node.x) * viewScale + viewTx;
    const screenY = Number(node.y) * viewScale + viewTy;
    const widthPx = cloudRenderedBoxWidth(node);
    const heightPx = cloudBoxHeight(node);
    const halfWidth = widthPx / 2 + CLOUD_CANVAS_HIT_PAD_PX;
    const halfHeight = heightPx / 2 + CLOUD_CANVAS_HIT_PAD_PX;
    if (
      x >= screenX - halfWidth &&
      x <= screenX + halfWidth &&
      y >= screenY - halfHeight &&
      y <= screenY + halfHeight
    ) {
      return node;
    }
  }
  return null;
}

function cloudSelectedMarkerHit(clientX, clientY) {
  return false;
}

function cloudDomWindowSignature(activeLayerScale = cloudActiveLayerScale()) {
  const scale = Math.max(0.001, viewScale);
  const tileWorld = CLOUD_DOM_WINDOW_TILE_PX / scale;
  const left = (0 - viewTx) / scale;
  const top = (0 - viewTy) / scale;
  const scaleBucket = Math.round(Math.log(scale) / Math.log(1.035));
  return [
    activeLayerScale ?? "",
    scaleBucket,
    Math.floor(left / tileWorld),
    Math.floor(top / tileWorld),
    Math.ceil(vw() / CLOUD_DOM_WINDOW_TILE_PX),
    Math.ceil(vh() / CLOUD_DOM_WINDOW_TILE_PX),
  ].join("|");
}

function mergeCloudLayerSnapshot(snapshot, options = {}) {
  const data = normalizedCloudData(snapshot);
  if (!cloudScene) resetCloudScene(data.stats || {});
  const snapshotSignature = options.atlasSignature || cloudLastFetchSignature || cloudAtlasSignature();
  if (
    data.stream?.kind === "scale_layer" &&
    snapshotSignature &&
    cloudScene.atlasSignature !== snapshotSignature
  ) {
    activateCloudScaleLayersForSignature(snapshotSignature);
  }
  cloudScene.stats = {
    ...cloudScene.stats,
    ...(data.stats || {}),
  };
  const layer = data.stream?.layer || `tier:${data.stream?.lod_tier ?? "unknown"}`;
  const tier = Number.isFinite(Number(data.stream?.lod_tier)) ? Number(data.stream.lod_tier) : 0;
  const layerIds = cloudScene.layersByTier.get(tier) || new Set();
  for (const node of data.nodes || []) {
    cloudScene.nodesById.set(node.id, node);
    layerIds.add(node.id);
  }
  cloudScene.layersByTier.set(tier, layerIds);
  if (data.stream?.kind === "scale_layer") {
    const scale = Number(data.stream.scale);
    if (Number.isFinite(scale)) {
      let ids = cloudScene.layerIdsByScale.get(scale);
      if (!ids) {
        const previousScales = cloudSortedLayerScales(cloudScene).filter(existingScale => existingScale < scale);
        const previousScale = previousScales.length ? previousScales[previousScales.length - 1] : null;
        ids = new Set(previousScale == null ? [] : cloudScene.layerIdsByScale.get(previousScale) || []);
      }
	      const addIds = data.stream.delta
	        ? data.stream.add_node_ids || data.stream.visible_node_ids || []
	        : data.stream.visible_node_ids || [];
	      for (const nodeId of addIds) ids.add(String(nodeId));
	      for (const nodeId of data.stream.remove_node_ids || []) ids.delete(String(nodeId));
	      for (const node of data.nodes || []) ids.add(String(node.id));
	      cloudScene.layerIdsByScale.set(scale, ids);
	      cloudScene.layerSpatialByScale?.delete(scale);
	      if (Array.isArray(data.stream.tiles) && data.stream.tiles.length) {
	        const cells = new Map();
	        for (const tile of data.stream.tiles) {
	          const tileX = Number(tile?.x);
	          const tileY = Number(tile?.y);
	          if (!Number.isFinite(tileX) || !Number.isFinite(tileY)) continue;
	          const nodeIds = Array.isArray(tile?.node_ids)
	            ? tile.node_ids.map(nodeId => String(nodeId))
	            : [];
	          cells.set(`${tileX}:${tileY}`, nodeIds);
	        }
	        cloudScene.layerTilesByScale?.set(scale, {
	          scale,
	          tileSize: Number(data.stream.tile_size) || CLOUD_DOM_WINDOW_TILE_PX,
	          cells,
	        });
	      }
	      cloudScene.layerScales = [];
      cloudScene.layerScales = cloudSortedLayerScales(cloudScene);
      cloudScene.awaitingScaleLayer = false;
    }
  }
  cloudScene.loadedLayers.add(layer);
  cloudScene.complete = Boolean(data.stream?.complete);
  cloudNodeById = cloudScene.nodesById;
  cloudData = {
    ...data,
    nodes: Array.from(cloudScene.nodesById.values()),
    stats: cloudScene.stats,
  };
  cloudBounds = cloudStatsBounds(cloudData) || cloudBounds;
  return data;
}

function cloudNodeFromData(data, genreId) {
  if (!genreId) return null;
  return cloudScene?.nodesById?.get?.(genreId) ||
    (data?.nodes || []).find(node => node.id === genreId) ||
    null;
}

function fitCloudView(data = cloudData, options = {}) {
  const bounds = cloudStatsBounds(data);
  if (!bounds) return;
  cloudBounds = bounds;
  const selectedId = options.selectedGenreId && options.selectedGenreId !== ROOT_KEY
    ? options.selectedGenreId
    : null;
  const focusNode = cloudNodeFromData(data, selectedId) ||
    cloudNodeFromData(data, cloudRootGenreId) ||
    cloudNodeFromData(data, ROOT_KEY);
  const baselineScale = cloudLodBaselineScale(bounds);
  viewScale = selectedId
    ? clampViewScale(Math.max(0.92, baselineScale * 3.2))
    : clampViewScale(baselineScale);
  if (focusNode) {
    viewTx = focusX() - Number(focusNode.x || 0) * viewScale;
    viewTy = focusY() - Number(focusNode.y || 0) * viewScale;
  } else {
    viewTx = focusX() - ((Number(bounds.minX) + Number(bounds.maxX)) / 2) * viewScale;
    viewTy = focusY() - ((Number(bounds.minY) + Number(bounds.maxY)) / 2) * viewScale;
  }
  writeWorldTransform();
}

function removeNonCloudSceneNodes() {
  for (const child of Array.from(nodesG.children)) {
    if (!child.classList?.contains("cloud-node")) child.remove();
  }
}

function prepareCloudSceneDom() {
  if (cloudSceneDomPrepared) return;
  edgesG.innerHTML = "";
  removeNonCloudSceneNodes();
  for (const el of cloudNodeEls.values()) el.remove();
  cloudNodeEls = new Map();
  cloudTextEls = new Map();
  nodeEls = new Map();
  edgeEls = new Map();
  edgeGradientEls = new Map();
  ensureEdgeGradientDefs().innerHTML = "";
  cloudSceneDomPrepared = true;
}

function buildCloudNodeEl(node, inverseScale, isEntering = false) {
  const isSelected = node.id === cloudSelectedGenreId;
  const group = svgEl("g", {
    class: `cloud-node${isEntering ? "" : " cloud-node-visible"}${isSelected ? " cloud-node-selected" : ""}${detailKeyForCloudNodeId(node.id) === cloudDetailIndicatorKey() ? " cloud-node-detail-preview" : ""}`,
    transform: `translate(${node.x} ${node.y})`,
    tabindex: "0",
    role: "button",
    "aria-label": node.label,
  });
  group.dataset.genreId = node.id;
  const readableColor = node.similarity_color;
  if (readableColor) group.style.setProperty("--genre-color", readableColor);
  if (node.id === ROOT_KEY) group.classList.add("cloud-node-root");
  const textWidth = cloudTextWidth(node);
  const underline = svgEl("line", {
    class: "cloud-node-underline",
    x1: -(textWidth / 2) + 1,
    x2: (textWidth / 2) - 1,
    y1: CLOUD_FONT_SIZE * 0.58,
    y2: CLOUD_FONT_SIZE * 0.58,
  });
  const text = svgEl("text", {
    class: "cloud-node-label",
    "font-size": CLOUD_FONT_SIZE,
    transform: `scale(${inverseScale})`,
    x: 0,
    y: 0,
    "dominant-baseline": "central",
  });
  text.textContent = node.label;
  group.append(underline);
  group.append(text);
  group.__cloudTextEl = text;
  group.addEventListener("pointerenter", () => {
    if (!cloudMode || !cloudCanClickNodes()) return;
    scheduleCloudHoverCard(node.id);
  });
  group.addEventListener("pointerleave", () => {
    if (!cloudMode) return;
    clearScheduledCloudHoverCard(detailKeyForCloudNodeId(node.id));
  });
  group.addEventListener("click", () => {
    void openCloudGenre(node.id);
  });
  group.addEventListener("keydown", event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    void openCloudGenre(node.id);
  });
  return group;
}

function retireCloudNodeAfterFade(nodeId, el) {
  window.setTimeout(() => {
    if (cloudNodeEls.get(nodeId) !== el) return;
    if (!el.classList.contains("cloud-node-exiting")) return;
    if (el.parentNode) el.remove();
    cloudNodeEls.delete(nodeId);
    cloudTextEls.delete(nodeId);
  }, prefersReducedMotion() ? 0 : 160);
}

function renderCloud(data = cloudData, options = {}) {
  if (!data) return;
  data = normalizedCloudData(data);
  cloudData = data;
  cloudBounds = cloudStatsBounds(data) || cloudBounds;
  cloudNodeById = new Map((data.nodes || []).map(node => [node.id, node]));
  edgesG.innerHTML = "";
  removeNonCloudSceneNodes();
  nodeEls = new Map();
  edgeEls = new Map();
  edgeGradientEls = new Map();
  ensureEdgeGradientDefs().innerHTML = "";

  const inverseScale = 1 / Math.max(0.001, viewScale);
  const nextNodeIds = new Set();
  const enteringNodes = [];
  for (const node of data.nodes || []) {
    nextNodeIds.add(node.id);
    const existing = cloudNodeEls.get(node.id);
    if (existing) {
      existing.setAttribute("transform", `translate(${node.x} ${node.y})`);
      const isSelected = node.id === cloudSelectedGenreId;
      existing.classList.toggle("cloud-node-selected", isSelected);
      existing.classList.toggle("cloud-node-detail-preview", detailKeyForCloudNodeId(node.id) === cloudDetailIndicatorKey());
      existing.classList.toggle("cloud-node-root", node.id === ROOT_KEY);
      existing.classList.remove("cloud-node-exiting");
      existing.classList.add("cloud-node-visible");
      existing.setAttribute("aria-label", node.label);
      if (node.similarity_color) existing.style.setProperty("--genre-color", node.similarity_color);
      else existing.style.removeProperty("--genre-color");
      const text = existing.querySelector(".cloud-node-label");
      if (text) {
        text.setAttribute("transform", `scale(${inverseScale})`);
        if (text.textContent !== node.label) text.textContent = node.label;
        cloudTextEls.set(node.id, text);
      }
      continue;
    }

    const group = buildCloudNodeEl(node, inverseScale, !options.noFade);
    nodesG.appendChild(group);
    cloudNodeEls.set(node.id, group);
    if (group.__cloudTextEl) cloudTextEls.set(node.id, group.__cloudTextEl);
    if (!options.noFade) enteringNodes.push(group);
  }

  for (const [nodeId, el] of cloudNodeEls.entries()) {
    if (nextNodeIds.has(nodeId)) continue;
    if (el.classList.contains("cloud-node-exiting")) continue;
    el.classList.remove("cloud-node-visible");
    el.classList.add("cloud-node-exiting");
    retireCloudNodeAfterFade(nodeId, el);
  }

  if (!prefersReducedMotion() && enteringNodes.length) {
    requestAnimationFrame(() => {
      for (const el of enteringNodes) el.classList.add("cloud-node-visible");
    });
  } else {
    for (const el of enteringNodes) el.classList.add("cloud-node-visible");
  }
  const visible = data.nodes?.length || 0;
  const total = data.stats?.total_nodes || visible;
  setStatus(`${visible} visible of ${total} cloud genres`);
  updateTargetButtonVisibility();
}

function updateCloudLodVisibility(options = {}) {
  if (!cloudMode || !cloudScene) {
    updateCloudNodeScale();
    return;
  }
  if (options.immediate && cloudRenderFrame) {
    cancelAnimationFrame(cloudRenderFrame);
    cloudRenderFrame = null;
  }
  if (cloudRenderFrame && !options.immediate) return;
  const run = frameNow => {
    const now = Number.isFinite(Number(frameNow)) ? Number(frameNow) : performance.now();
    cloudRenderFrame = null;
    if (!cloudMode || !cloudScene) return;
    prepareCloudSceneDom();

    const inverseScale = 1 / Math.max(0.001, viewScale);
    let nextNodeIds = new Set();
    const enteringNodes = [];
    const activeLayerScale = cloudActiveLayerScale(cloudScene);
    const windowSignature = cloudDomWindowSignature(activeLayerScale);
    const lodTarget = cloudClientLodTarget(cloudScene, activeLayerScale);
    nextNodeIds = lodTarget.nextNodeIds;
    const layerIds = lodTarget.layerIds;
    let hiddenForLayer = Math.max(0, cloudScene.nodesById.size - layerIds.size);
    let hiddenForViewport = lodTarget.hiddenForViewport;
    const hiddenForOverlap = lodTarget.hiddenForOverlap;
    const candidateIds = lodTarget.candidateIds;
    hiddenForLayer += lodTarget.missingCandidates;

    for (const [nodeId, el] of cloudNodeEls.entries()) {
      if (nextNodeIds.has(nodeId)) continue;
      if (el.classList.contains("cloud-node-exiting")) continue;
      el.classList.remove("cloud-node-visible");
      el.classList.add("cloud-node-exiting");
      retireCloudNodeAfterFade(nodeId, el);
    }
    cloudVisibleNodeIds = nextNodeIds;
    if (!prefersReducedMotion() && enteringNodes.length) {
      requestAnimationFrame(() => {
        for (const el of enteringNodes) el.classList.add("cloud-node-visible");
      });
    } else {
      for (const el of enteringNodes) el.classList.add("cloud-node-visible");
    }
	    const total = cloudScene.stats?.total_nodes || cloudScene.nodesById.size;
	    const loaded = cloudScene.nodesById.size;
	    const activeLayerReady = cloudActiveLayerCaughtUp(cloudScene);
	    window.__wikiGenresCloudCullDebug = {
      visible: nextNodeIds.size,
      total,
      loaded,
      spatialCandidates: candidateIds.size,
      hiddenForLayer,
      hiddenForViewport,
      hiddenForOverlap,
      blockers: [],
      zoom: viewScale,
      activeLayerScale,
      windowSignature,
      renderBackend: "canvas",
	      canvasNodes: nextNodeIds.size,
	      canvasFadeNodes: cloudCanvasAlphaById.size,
	      loadedLayerScales: cloudSortedLayerScales(cloudScene),
	      lodBaselineScale: cloudLodBaselineScale(),
	      activeLayerReady,
	      cloudLoading: cloudInitialRenderPending,
	      lodTargetSource: lodTarget.source,
	    };
    cloudCanvasNodes = Array.from(nextNodeIds)
      .map(nodeId => cloudScene.nodesById.get(nodeId))
      .filter(Boolean);
    updateCloudCanvasFadeTargets(cloudCanvasNodes, {
      noFade: options.noFade || cloudInitialRenderPending,
      hydrateNew: options.hydrateNew,
      now,
    });
    const drawableNodes = cloudDrawableNodes();
    updateCloudSelectedLabelFadeTargets(drawableNodes);
    updateCloudHoverUnderlineAlphaTargets(drawableNodes);
    updateCloudRelationshipAlphaTargets(drawableNodes);
    cloudRenderedLayerScale = activeLayerScale;
    cloudRenderedTextScale = viewScale;
    cloudRenderedWindowSignature = windowSignature;
    scheduleCloudCanvasRender();
    if (cloudInitialRenderPending && cloudActiveLayerCaughtUp(cloudScene)) {
      finishCloudInitialLoadingAfterPaint();
    }
    setStatus(`${nextNodeIds.size} visible of ${total} cloud genres${loaded < total ? ` (${loaded} preloaded)` : ""}`);
    updateTargetButtonVisibility();
  };
  if (options.immediate) run();
  else cloudRenderFrame = requestAnimationFrame(run);
}

function updateCloudNodeScale() {
  if (!cloudMode) return;
  if (Math.abs(cloudRenderedTextScale - viewScale) < 0.0005) return;
  cloudRenderedTextScale = viewScale;
	  if (cloudCanvasNodes.length) {
	    updateCloudSelectedLabelFadeTargets(cloudCanvasNodes);
	    updateCloudHoverUnderlineAlphaTargets(cloudCanvasNodes);
	    updateCloudRelationshipAlphaTargets(cloudCanvasNodes);
	  }
  scheduleCloudCanvasRender();
}

async function loadCloudMode(options = {}) {
  const token = ++cloudRequestToken;
  if (options.initial) {
    viewScale = 1;
    viewTx = focusX();
    viewTy = focusY();
    writeWorldTransform();
    setCloudInitialLoading(true);
  } else if (!cloudInitialRenderPending) {
    setCloudInitialLoading(false);
  }
  setStatus("Loading cloud...");
  cloudLastFetchAt = Date.now();
  const atlasSignature = cloudAtlasSignature();
  cloudLastFetchSignature = atlasSignature;
  if (cloudStreamController) cloudStreamController.abort();
  const controller = new AbortController();
  cloudStreamController = controller;
  let fittedInitialView = false;
  let renderedInitialSnapshot = false;
  prepareCloudSceneForReload({ ...options, atlasSignature });
  try {
    await streamNdjson(cloudStreamUrl(), {
      signal: controller.signal,
      onSnapshot: snapshot => {
        if (token !== cloudRequestToken || !cloudMode) return;
        const data = mergeCloudLayerSnapshot(snapshot, { atlasSignature });
        if (options.initial && !fittedInitialView) {
          fitCloudView(cloudData, {
            selectedGenreId: cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY
              ? cloudSelectedGenreId
              : null,
          });
          fittedInitialView = true;
        }
        updateCloudLodVisibility({
          noFade: options.noFade,
          hydrateNew: options.preserveView && !options.initial,
          immediate: !renderedInitialSnapshot,
        });
        renderedInitialSnapshot = true;
      },
    });
  } catch (err) {
    if (err?.name === "AbortError") return;
    setCloudInitialLoading(false);
    cloudStreamRetryAfter = Date.now() + 1200;
    if (cloudScene?.nodesById?.size) {
      console.warn("[wiki-genres] cloud stream ended after partial atlas; keeping loaded layers", err);
      cloudScene.complete = false;
      updateCloudLodVisibility({
        noFade: options.noFade,
        hydrateNew: options.preserveView && !options.initial,
        immediate: true,
      });
      return;
    }
    console.warn("[wiki-genres] cloud stream failed; falling back to JSON", err);
    try {
      const data = normalizedCloudData(await getCloudData({ atlas: true }));
      if (token !== cloudRequestToken || !cloudMode) return;
      resetCloudScene(data.stats || {});
      cloudScene.atlasSignature = atlasSignature;
      cloudScene.pendingAtlasSignature = "";
      for (const node of data.nodes || []) cloudScene.nodesById.set(node.id, node);
      cloudScene.complete = true;
      cloudNodeById = cloudScene.nodesById;
      cloudData = data;
      if (options.initial && !fittedInitialView) {
        fitCloudView(data, {
          selectedGenreId: cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY
            ? cloudSelectedGenreId
            : null,
        });
      }
      finishCloudInitialLoadingAfterPaint();
      updateCloudLodVisibility({
        noFade: options.noFade,
        hydrateNew: options.preserveView && !options.initial,
        immediate: true,
      });
    } catch (fallbackErr) {
      if (cloudScene?.nodesById?.size) {
        console.warn("[wiki-genres] cloud fallback failed; keeping partial atlas", fallbackErr);
        updateCloudLodVisibility({
          noFade: options.noFade,
          hydrateNew: options.preserveView && !options.initial,
          immediate: true,
        });
        return;
      }
      throw fallbackErr;
    }
    return;
  } finally {
    if (cloudStreamController === controller) cloudStreamController = null;
    if (
      cloudQueuedFetch &&
      token === cloudRequestToken &&
      cloudMode &&
      cloudQueuedFetchSignature &&
      cloudQueuedFetchSignature !== cloudLastFetchSignature
    ) {
      cloudQueuedFetch = false;
      cloudQueuedFetchSignature = "";
      scheduleCloudFetch(0);
    }
  }
  if (token !== cloudRequestToken || !cloudMode || !cloudScene) return;
  finishCloudInitialLoadingAfterPaint();
  cloudData = {
    nodes: Array.from(cloudScene.nodesById.values()),
    stats: cloudScene.stats,
  };
}

function scheduleCloudFetch(delay = 90) {
  if (!cloudMode) return;
  const signature = cloudAtlasSignature();
  if (cloudScene?.complete && signature === cloudLastFetchSignature) {
    updateCloudLodVisibility();
    return;
  }
  if (signature === cloudLastFetchSignature && cloudScene?.nodesById?.size) return;
  if (Date.now() < cloudStreamRetryAfter) delay = Math.max(delay, cloudStreamRetryAfter - Date.now());
  if (cloudStreamController) {
    cloudQueuedFetch = true;
    cloudQueuedFetchSignature = signature;
    return;
  }
  if (cloudFetchTimer) return;
  const elapsed = Date.now() - cloudLastFetchAt;
  const wait = Math.max(delay, 280 - elapsed, 0);
  cloudFetchTimer = window.setTimeout(() => {
    cloudFetchTimer = 0;
    void loadCloudMode({ preserveView: true }).catch(err => {
      console.error("[wiki-genres] cloud refresh failed", err);
      setStatus("Cloud unavailable.");
    });
  }, wait);
}

async function openCloudGenre(genreId, options = {}) {
  if (!genreId) return;
  if (cloudSelectedGenreId === genreId && genreId !== ROOT_KEY && !options.forceOpen) {
    cloudSelectedGenreId = null;
    resetCloudScaleLayersForSignature();
    setDetailCardNodeKey(null);
    hoverCardToken++;
    setStatus("");
    updateDetailCardVisibility();
    updateUrlState({ push: true });
    updateCloudLodVisibility({ immediate: true });
    scheduleCloudFetch(0);
    void updateMapCard(nodes.get(ROOT_KEY));
    return;
  }
  allowDetailCardForManualSelection();
  cloudSelectedGenreId = genreId;
  startCloudSelectedLabelFade(genreId);
  resetCloudScaleLayersForSignature();
  setDetailCardNodeKey(detailKeyForCloudNodeId(genreId));
  updateDetailCardVisibility();
  updateUrlState({ push: true });
  updateCloudLodVisibility({ immediate: true });
  const cloudNode = cloudNodeById.get(genreId);
  if (cloudNode) {
    updateCard(cloudNodeFromPayload(cloudNode));
    updateYoutubeCardForSelection(cloudNodeFromPayload(cloudNode));
  }
  panToSelectedCenterTarget({ holdDetailCard: true });
  scheduleCloudFetch(0);
  if (genreId === ROOT_KEY) {
    void updateMapCard(nodes.get(ROOT_KEY));
    return;
  }
  if (cloudNode) void updateMapCard(cloudNodeFromPayload(cloudNode));
  try {
    const detail = await getGenreDetail(genreId);
    if (!cloudMode || cloudSelectedGenreId !== genreId) return;
    setDetailCardNodeKey(detailKeyForCloudNodeId(genreId));
    updateCard(detail);
    updateYoutubeCardForSelection(detail);
    void updateMapCard(detail);
    updateCloudLodVisibility({ immediate: true });
    panToSelectedCenterTarget({ holdDetailCard: true });
  } catch (err) {
    console.error("[wiki-genres] cloud genre open failed", err);
    setStatus("Could not open that cloud genre.");
  }
}

function openRegionalCloud(item) {
  if (!item?.genre_id || !item?.region_id) return;
  allowDetailCardForManualSelection();
  cloudRootGenreId = null;
  cloudRegionId = item.region_id;
  cloudSelectedGenreId = item.genre_id;
  startCloudSelectedLabelFade(item.genre_id);
  setDetailCardNodeKey(detailKeyForCloudNodeId(item.genre_id));
  updateUrlState({ push: true });
  void loadCloudMode({ initial: true }).then(() => {
    if (!cloudMode || cloudRegionId !== item.region_id) return;
    return openCloudGenre(item.genre_id, { forceOpen: true });
  }).catch(err => {
    console.error("[wiki-genres] regional cloud failed", err);
    setStatus("Cloud unavailable.");
  });
}

function panToCloudSelection() {
  const node = cloudSelectedGenreId ? cloudNodeById.get(cloudSelectedGenreId) : null;
  if (!node) return;
  tweenPanTo(
    focusX() - node.x * viewScale,
    focusY() - node.y * viewScale,
    520
  );
}

function focusCloudSelectedMarker() {
  const node = cloudSelectedGenreId ? cloudNodeById.get(cloudSelectedGenreId) : null;
  if (!node) return;
  const targetScale = Math.max(viewScale, 1);
  tweenPanTo(
    focusX() - node.x * targetScale,
    focusY() - node.y * targetScale,
    520,
    null,
    targetScale
  );
}

function setCloudMode(enabled, options = {}) {
  const wantsCloud = Boolean(enabled);
  const selectedBeforeSwap = selectedGenreIdForModeTransfer();
  const realSelectedBeforeSwap = selectedBeforeSwap && selectedBeforeSwap !== ROOT_KEY ? selectedBeforeSwap : null;
  if (wantsCloud && timelineMode) {
    historyNavigating = true;
    setTimelineMode(false, { skipGraphRestore: true });
    historyNavigating = false;
  }
  cloudMode = wantsCloud;
  document.body.classList.toggle("cloud-mode", cloudMode);
  updateManualUiDimClass();
  cloudToggleButton?.classList.remove("active");
  setModeButtonState(cloudToggleButton, cloudMode
    ? { icon: "polyline", label: "Graph", ariaLabel: "Return to graph" }
    : { icon: "mist", label: "Cloud", ariaLabel: "Open word cloud" }
  );
  if (cloudMode) {
    if (panAnimTimer) {
      clearInterval(panAnimTimer);
      panAnimTimer = null;
    }
    stopPanInertia();
    followMode = false;
    if (sim) sim.stop();
    if (tickTimer) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
    nodeEls = new Map();
    edgeEls = new Map();
    edgeGradientEls = new Map();
    cloudRootGenreId = null;
    cloudRegionId = null;
    cloudSelectedGenreId = realSelectedBeforeSwap;
    clearScheduledCloudHoverCard();
    cloudHoverCardDelayTimer = 0;
    pendingCloudHoverCardKey = null;
    cloudHoverUnderlineAlphaById = new Map();
    if (realSelectedBeforeSwap) {
      setDetailCardNodeKey(detailKeyForCloudNodeId(realSelectedBeforeSwap));
      const maybeDetail = detailCache.get(realSelectedBeforeSwap) || nodes.get(activeLeafKey) || nodes.get(currentKey) || null;
      if (maybeDetail) {
        updateCard(maybeDetail);
        updateYoutubeCardForSelection(maybeDetail);
        void updateMapCard(maybeDetail);
      }
    }
    updateUrlState({ push: true });
    if (!options.deferLoad) {
      void loadCloudMode({ initial: true }).then(() => {
        if (!cloudMode || !cloudSelectedGenreId || cloudSelectedGenreId === ROOT_KEY) {
          updateDetailCardVisibility();
          void updateMapCard(nodes.get(ROOT_KEY));
          return;
        }
        return openCloudGenre(cloudSelectedGenreId, { forceOpen: true });
      }).catch(err => {
        console.error("[wiki-genres] cloud mode failed", err);
        setStatus("Cloud unavailable.");
      });
    }
  } else {
    setCloudInitialLoading(false);
    const cloudSelectedBeforeExit = (cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY)
      ? cloudSelectedGenreId
      : realSelectedBeforeSwap;
	    cloudRootGenreId = null;
	    cloudRegionId = null;
	    cloudSelectedGenreId = null;
	    clearScheduledCloudHoverCard();
	    cloudHoverCardDelayTimer = 0;
	    pendingCloudHoverCardKey = null;
	    setDetailCardNodeKey(null);
	    cloudNodeEls = new Map();
	    cloudTextEls = new Map();
	    cloudScene = null;
	    cloudVisibleNodeIds = new Set();
	    cloudSceneDomPrepared = false;
	    cloudRenderedLayerScale = null;
	    cloudRenderedTextScale = 0;
	    cloudRenderedWindowSignature = "";
		    cloudCanvasNodes = [];
			    cloudCanvasHitNodes = [];
			    cloudCanvasVisibleIds = new Set();
			    cloudCanvasAlphaById = new Map();
			    cloudRenderSnapshot = null;
			    cloudRenderTransition = null;
			    cloudPresentationById = new Map();
			    cloudPresentationLastAt = 0;
			    cloudPresentationTargetSignature = "";
				    cloudSelectedLabelAlphaById = new Map();
			    cloudHoverUnderlineAlphaById = new Map();
			    cloudRelationshipAlphaById = new Map();
	    cancelCloudFadeFrame();
		    cloudBackgroundCache = null;
	    cloudBackgroundBuildSignature = "";
	    window.clearTimeout(cloudBackgroundBuildTimer);
	    cloudBackgroundBuildTimer = 0;
	    cloudLabelSpriteCache = new Map();
	    cloudHoveredNodeId = null;
	    cloudSelectedMarker = null;
	    clearCloudSelectedMarkerAnimation();
	    cloudClickEnabled = true;
	    cloudClickEnableAt = 0;
	    window.clearTimeout(cloudClickEnableTimer);
	    cloudClickEnableTimer = 0;
	    syncCloudClickAffordance();
	    if (cloudCanvasFadeFrame) {
	      cancelAnimationFrame(cloudCanvasFadeFrame);
	      cloudCanvasFadeFrame = 0;
	    }
		    if (cloudSelectedLabelFadeFrame) {
		      cancelAnimationFrame(cloudSelectedLabelFadeFrame);
		      cloudSelectedLabelFadeFrame = 0;
		    }
		    if (cloudHoverUnderlineFadeFrame) {
		      cancelAnimationFrame(cloudHoverUnderlineFadeFrame);
		      cloudHoverUnderlineFadeFrame = 0;
		    }
		    if (cloudRelationshipFadeFrame) {
		      cancelAnimationFrame(cloudRelationshipFadeFrame);
		      cloudRelationshipFadeFrame = 0;
		    }
	    scheduleCloudCanvasRender();
	    window.clearTimeout(cloudFetchTimer);
	    cloudFetchTimer = 0;
	    cloudQueuedFetch = false;
	    cloudQueuedFetchSignature = "";
	    cloudRequestToken += 1;
	    if (cloudStreamController) {
	      cloudStreamController.abort();
	      cloudStreamController = null;
	    }
	    if (cloudRenderFrame) {
	      cancelAnimationFrame(cloudRenderFrame);
	      cloudRenderFrame = null;
	    }
	    document.body.classList.remove("cloud-mode");
	    restoreGraphLayoutForModeExit();
	    viewScale = defaultScale();
	    const cur = nodes.get(currentKey) || nodes.get(ROOT_KEY);
	    if (cur) {
	      viewTx = focusX() - cur.homeX * viewScale;
	      viewTy = focusY() - cur.homeY * viewScale;
	    }
    writeWorldTransform();
    fullRender();
    rebuildSim();
    bumpSim(0.18);
    updateDetailCardVisibility();
    updateFooter(nodes.get(currentKey));
    updateUrlState({ push: true });
    if (cloudSelectedBeforeExit) {
      void ensureGraphSelectionByGenreId(cloudSelectedBeforeExit).then(() => {
        if (!cloudMode && !timelineMode) updateUrlState({ push: false });
      });
    }
  }
}

function setTimelineMode(enabled, options = {}) {
  const selectedBeforeSwap = selectedGenreIdForModeTransfer();
  if (enabled && cloudMode) {
    setCloudInitialLoading(false);
    cloudMode = false;
    cloudRootGenreId = null;
    cloudRegionId = null;
    cloudSelectedGenreId = null;
    cloudNodeEls = new Map();
    cloudTextEls = new Map();
    cloudScene = null;
    cloudVisibleNodeIds = new Set();
    cloudSceneDomPrepared = false;
    cloudRenderedLayerScale = null;
    cloudRenderedTextScale = 0;
    cloudRenderedWindowSignature = "";
	    cloudCanvasNodes = [];
	    cloudCanvasHitNodes = [];
	    cloudCanvasVisibleIds = new Set();
	    cloudCanvasAlphaById = new Map();
	    cloudRenderSnapshot = null;
	    cloudRenderTransition = null;
	    cloudPresentationById = new Map();
	    cloudPresentationLastAt = 0;
	    cloudPresentationTargetSignature = "";
	    cloudSelectedLabelAlphaById = new Map();
	    cloudRelationshipAlphaById = new Map();
    cancelCloudFadeFrame();
    cloudBackgroundCache = null;
    cloudBackgroundBuildSignature = "";
    window.clearTimeout(cloudBackgroundBuildTimer);
    cloudBackgroundBuildTimer = 0;
    cloudLabelSpriteCache = new Map();
    cloudHoveredNodeId = null;
    cloudSelectedMarker = null;
    clearCloudSelectedMarkerAnimation();
    cloudClickEnabled = true;
    cloudClickEnableAt = 0;
    window.clearTimeout(cloudClickEnableTimer);
    cloudClickEnableTimer = 0;
    syncCloudClickAffordance();
    if (cloudCanvasFadeFrame) {
      cancelAnimationFrame(cloudCanvasFadeFrame);
      cloudCanvasFadeFrame = 0;
    }
    if (cloudSelectedLabelFadeFrame) {
      cancelAnimationFrame(cloudSelectedLabelFadeFrame);
      cloudSelectedLabelFadeFrame = 0;
    }
    if (cloudRelationshipFadeFrame) {
      cancelAnimationFrame(cloudRelationshipFadeFrame);
      cloudRelationshipFadeFrame = 0;
    }
    scheduleCloudCanvasRender();
    window.clearTimeout(cloudFetchTimer);
    cloudFetchTimer = 0;
    cloudQueuedFetch = false;
    cloudQueuedFetchSignature = "";
    if (cloudStreamController) {
      cloudStreamController.abort();
      cloudStreamController = null;
    }
    document.body.classList.remove("cloud-mode");
    cloudToggleButton?.classList.remove("active");
  }
  const timelineSelectedBeforeExit = timelineSelectedGenreId || selectedBeforeSwap || null;

  timelineMode = Boolean(enabled);
  document.body.classList.toggle("timeline-mode", timelineMode);
  if (timelinePanel) timelinePanel.hidden = true;
  timelineToggleButton?.classList.remove("active");
  setModeButtonState(timelineToggleButton, timelineMode
    ? { icon: "scatterPlot", label: "Graph", ariaLabel: "Return to graph" }
    : { icon: "clockArrowDown", label: "Timeline", ariaLabel: "Open timeline map" }
  );
  if (timelineMode) {
    // Stop any in-flight camera motion from graph mode so timeline opens at
    // a stable default.
    if (panAnimTimer) {
      clearInterval(panAnimTimer);
      panAnimTimer = null;
    }
    stopPanInertia();
    followMode = false;
    if (sim) sim.stop();
    if (tickTimer) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
    timelineNeedsRender = false;
    timelineInteractUntil = 0;
    timelineNoFadeNextRender = false;
    timelineLastStreamRenderAt = 0;
    if (timelineInteractTimer) {
      window.clearTimeout(timelineInteractTimer);
      timelineInteractTimer = null;
    }
    clearTimelineLayersImmediate();
    nodeEls = new Map();
    edgeEls = new Map();
    edgeGradientEls = new Map();
    ensureEdgeGradientDefs().innerHTML = "";
    // Persist current selection into timeline mode when possible.
    timelineSelectedGenreId = selectedBeforeSwap;
    timelineDetailCardOpen = Boolean(selectedBeforeSwap);
    if (selectedBeforeSwap) {
      setDetailCardNodeKey(detailKeyForTimelineNodeId(selectedBeforeSwap));
      // Keep playback continuous by reusing the same selection key where possible.
      const maybeDetail = detailCache.get(selectedBeforeSwap) || nodes.get(activeLeafKey) || nodes.get(currentKey) || null;
      if (maybeDetail) {
        updateCard(maybeDetail);
        updateYoutubeCardForSelection(maybeDetail);
        void updateMapCard(maybeDetail);
      }
    }
    updateUrlState({ push: true });
    void loadTimelineForSelection().then(() => {
      if (timelineMode && timelineSelectedGenreId) {
        panToSelectedCenterTarget({ holdDetailCard: true });
      }
    });
  } else {
    // Stop any timeline-mode camera motion before returning to graph.
    if (panAnimTimer) {
      clearInterval(panAnimTimer);
      panAnimTimer = null;
    }
    stopPanInertia();
    timelineToken += 1;
    timelineDataRequestToken += 1;
    if (timelineStreamController) {
      timelineStreamController.abort();
      timelineStreamController = null;
    }
    timelineData = null;
    timelineSelectedGenreId = null;
    timelineDetailCardOpen = false;
    timelineYearRows = [];
    timelineNodePositions = new Map();
    timelinePlacedPositions = new Map();
    timelineLoadedRank = 0;
    timelineLoadingRank = 0;
    timelineQueuedRank = 0;
    timelineLastDataSignature = "";
    timelineRenderedSignature = "";
    timelineRenderedNodeIds = new Set();
    timelineRenderedEdgeKeys = new Set();
    timelineNodeDetailSignature = "";
    timelineYearMarkerSignature = "";
    timelineYearMarkerEls = new Map();
    if (timelineViewportFrame) {
      cancelAnimationFrame(timelineViewportFrame);
      timelineViewportFrame = null;
    }
    timelineNeedsRender = false;
    timelineInteractUntil = 0;
    timelineNoFadeNextRender = false;
    timelineLastStreamRenderAt = 0;
    if (timelineInteractTimer) {
      window.clearTimeout(timelineInteractTimer);
      timelineInteractTimer = null;
    }
    if (timelineRenderFrame) {
      cancelAnimationFrame(timelineRenderFrame);
      timelineRenderFrame = null;
    }
    if (timelineRenderTimer) {
      window.clearTimeout(timelineRenderTimer);
      timelineRenderTimer = null;
    }
	    timelineVisibility = {
	      nodeRanks: new Map(),
	      nodeScores: new Map(),
	      nodeWidths: new Map(),
	      edgeRanks: new Map(),
	      edgesByNode: new Map(),
	      focusNodeIds: new Set(),
	      focusDistances: new Map(),
	      sortedNodeIds: [],
	      clusters: [],
	    };
	    if (timelineYearRail) timelineYearRail.innerHTML = "";
	    clearTimelineLayersImmediate();
	    restoreGraphLayoutForModeExit();
	    // Reset camera for graph mode so it opens centered at a sane scale.
	    viewScale = defaultScale();
    const cur = nodes.get(currentKey) || nodes.get(ROOT_KEY);
    if (cur) {
      viewTx = focusX() - cur.homeX * viewScale;
      viewTy = focusY() - cur.homeY * viewScale;
    }
    writeWorldTransform();
    fullRender();
    rebuildSim();
    bumpSim(0.18);
    updateFooter(nodes.get(currentKey));
    updateUrlState({ push: true });

    // Restore timeline selection into graph mode.
    if (timelineSelectedBeforeExit && !options.skipGraphRestore) {
      void ensureGraphSelectionByGenreId(timelineSelectedBeforeExit).then(() => {
        if (!cloudMode && !timelineMode) updateUrlState({ push: false });
      });
    }
  }
}

function scheduleTimelineRefresh(options = {}) {
  if (!timelineMode) return;
  if (timelineRefreshTimer) window.clearTimeout(timelineRefreshTimer);
  const delay = options.delay ?? 120;
  if (delay <= 0) {
    timelineRefreshTimer = null;
    void loadTimelineForSelection({ preserveView: true, ...options });
    return;
  }
  timelineRefreshTimer = window.setTimeout(() => {
    timelineRefreshTimer = null;
    void loadTimelineForSelection({ preserveView: true, ...options });
  }, delay);
}

async function loadTimelineForSelection(options = {}) {
  const hasSelectedOverride = Object.prototype.hasOwnProperty.call(options, "selectedGenreId");
  const selectedOverride = hasSelectedOverride ? options.selectedGenreId : undefined;
  const confidence = timelineConfidence?.value || "low";
  const requestedRank = Math.max(
    TIMELINE_MIN_SERVER_RANK,
    Math.min(1, options.requestedRank ?? timelineDesiredServerRankForScale())
  );
  const selectedGenreId = hasSelectedOverride
    ? (selectedOverride || null)
    : (timelineSelectedGenreId || null);
  const selectedTimelinePayload = selectedGenreId
    ? timelineData?.nodes?.find(item => item.id === selectedGenreId)
    : null;
  const node = selectedGenreId
    ? (
        detailCache.get(selectedGenreId) ||
        (selectedTimelinePayload ? timelineNodeFromPayload(selectedTimelinePayload) : null) ||
        null
      )
    : null;
  if (
    !options.force &&
    !options.forceViewport &&
    timelineData &&
    selectedGenreId === timelineSelectedGenreId &&
    requestedRank <= timelineLoadedRank + TIMELINE_RANK_RELOAD_EPSILON
  ) {
    return;
  }
  if (
    !options.force &&
    !options.forceViewport &&
    timelineLoadingRank &&
    selectedGenreId === timelineSelectedGenreId &&
    requestedRank <= timelineLoadingRank + TIMELINE_RANK_RELOAD_EPSILON
  ) {
    return;
  }
  if (options.force) timelineQueuedRank = 0;

  const modeToken = timelineToken;
  const requestToken = ++timelineDataRequestToken;
  if (timelineStreamController) timelineStreamController.abort();
  const controller = new AbortController();
  timelineStreamController = controller;
  timelineLastDataSignature = timelineDataSignature(requestedRank);
  timelineLoadingRank = requestedRank;
  if (!options.quiet) {
    setStatus(node?.genreId ? `Loading ${node.label} timeline...` : "Loading timeline...");
  }

  try {
    const previousSelected = timelineSelectedGenreId || null;
    let snapshotCount = 0;
    const data = await streamNdjson(timelineStreamUrl(selectedGenreId, confidence, requestedRank), {
      signal: controller.signal,
      onSnapshot: snapshot => {
        if (modeToken !== timelineToken || requestToken !== timelineDataRequestToken || !timelineMode) return;
        timelineData = snapshot;
        timelineSelectedGenreId = selectedGenreId;
        const selectionChanging = previousSelected !== (selectedGenreId || null);
        renderTimeline(snapshot, {
          preserveView: snapshotCount > 0 || Boolean(options.preserveView),
          // Avoid flashing the initial selection swap, but let streamed-in detail fade.
          noFade: snapshotCount === 0 && (selectionChanging || Boolean(options.noFade)),
        });
        snapshotCount += 1;
      },
    });
    if (modeToken !== timelineToken || requestToken !== timelineDataRequestToken || !timelineMode) return;
    timelineData = data;
    timelineLoadedRank = requestedRank;
    timelineLoadingRank = 0;
    timelineSelectedGenreId = selectedGenreId;
  } catch (err) {
    if (err?.name === "AbortError") return;
    timelineStreamRetryAfter = Date.now() + 1200;
    console.warn("[wiki-genres] timeline stream failed; falling back to JSON", err);
    try {
      const previousSelected = timelineSelectedGenreId || null;
      const data = await getTimelineData(selectedGenreId, confidence, requestedRank);
      if (modeToken !== timelineToken || requestToken !== timelineDataRequestToken || !timelineMode) return;
      timelineData = data;
      timelineLoadedRank = requestedRank;
      timelineLoadingRank = 0;
      timelineSelectedGenreId = selectedGenreId;
      const selectionChanging = previousSelected !== (selectedGenreId || null);
      renderTimeline(data, {
        preserveView: Boolean(options.preserveView),
        noFade: selectionChanging || Boolean(options.noFade),
      });
    } catch (fallbackErr) {
      if (modeToken !== timelineToken || requestToken !== timelineDataRequestToken) return;
      timelineLoadingRank = 0;
      console.error("[wiki-genres] timeline failed", fallbackErr);
      edgesG.innerHTML = "";
      nodesG.innerHTML = "";
      setStatus("Timeline unavailable.");
    }
  } finally {
    if (timelineStreamController === controller) timelineStreamController = null;
    if (requestToken === timelineDataRequestToken) {
      timelineLoadingRank = 0;
      if (
        timelineMode &&
        timelineData &&
        timelineQueuedRank > timelineLoadedRank + TIMELINE_RANK_RELOAD_EPSILON
      ) {
        const queuedRank = timelineQueuedRank;
        timelineQueuedRank = 0;
        void loadTimelineForSelection({
          preserveView: true,
          requestedRank: queuedRank,
          quiet: true,
        });
      }
    }
  }
}

function timelinePath(route) {
  if (!Array.isArray(route) || route.length < 2) return "";
  const [start, c1, c2, end] = route;
  if (route.length >= 4) {
    return `M ${start[0]} ${start[1]} C ${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${end[0]} ${end[1]}`;
  }
  return route.map((point, index) => `${index ? "L" : "M"} ${point[0]} ${point[1]}`).join(" ");
}

function timelineYearLabel(node) {
  if (!node.year_start) return "undated";
  if (node.year_end && node.year_end !== node.year_start) {
    if (node.year_start % 10 === 0 && node.year_end === node.year_start + 9) {
      return `${node.year_start}s`;
    }
    return `${node.year_start}-${node.year_end}`;
  }
  return String(node.year_start);
}

function timelineTickStep(yearMin, yearMax) {
  const span = Math.max(1, yearMax - yearMin);
  if (span > 420) return 100;
  if (span > 180) return 50;
  if (span > 80) return 20;
  return 10;
}

function updateTimelineYearMarkers() {
  if (!timelineYearRail) return;
  if (!timelineMode || !timelineYearRows.length) {
    if (timelineYearMarkerSignature || timelineYearMarkerEls.size || timelineYearRail.childNodes.length) {
      timelineYearRail.innerHTML = "";
      timelineYearMarkerEls = new Map();
      timelineYearMarkerSignature = "";
    }
    return;
  }
  const viewportHeight = vh();
  const minGap = 34;
  let lastY = -Infinity;
  const markers = [];
  for (const row of timelineYearRows) {
    const screenY = row.y * viewScale + viewTy;
    if (screenY < -24 || screenY > viewportHeight + 24) continue;
    if (screenY - lastY < minGap) continue;
    markers.push({ label: `${row.decade}s`, y: screenY });
    lastY = screenY;
  }
  const signature = markers.map(marker => marker.label).join("|");
  if (signature !== timelineYearMarkerSignature) {
    timelineYearRail.innerHTML = "";
    timelineYearMarkerEls = new Map();
    for (const marker of markers) {
      const el = document.createElement("div");
      el.className = "timeline-year-marker";
      el.textContent = marker.label;
      timelineYearRail.appendChild(el);
      timelineYearMarkerEls.set(marker.label, el);
    }
    timelineYearMarkerSignature = signature;
  }
  for (const marker of markers) {
    const el = timelineYearMarkerEls.get(marker.label);
    if (el) el.style.top = `${marker.y.toFixed(1)}px`;
  }
}

function timelineDetailAmount() {
  return timelineDetailForScale(viewScale);
}

function timelineNodeVisibleAtRank(rank, detail = timelineDetailAmount()) {
  return rank <= timelineVisibleRankCutoff(detail);
}

function timelineEdgeKey(edge) {
  return `${edge.from_genre_id}->${edge.to_genre_id}:${edge.relation || ""}:${edge.source || ""}`;
}

function timelineEdgePathForNodes(fromId, toId) {
  const start = timelineNodePositions.get(fromId);
  const end = timelineNodePositions.get(toId);
  if (!start || !end) return "";
  const startY = start.y;
  const endY = end.y;
  const direction = endY >= startY ? 1 : -1;
  const controlGap = Math.max(34, Math.abs(endY - startY) * 0.42);
  return [
    `M ${start.x} ${startY}`,
    `C ${start.x} ${startY + controlGap * direction}`,
    `${end.x} ${endY - controlGap * direction}`,
    `${end.x} ${endY}`,
  ].join(" ");
}

function buildTimelineVisibilityModel(nodesData, edgesData) {
  const nodeRanks = new Map();
  const nodeScores = new Map();
  const nodeWidths = new Map();
  const edgesByNode = new Map();
  const focusNodeIds = new Set();
  const focusDistances = new Map();
  const focusScores = new Map();
  const sortedNodeIds = nodesData
    .slice()
    .sort((a, b) => (
      (a.timeline_rank ?? 1) - (b.timeline_rank ?? 1)
      || (a.label || a.wikipedia_title || "").localeCompare(b.label || b.wikipedia_title || "")
      || a.id.localeCompare(b.id)
    ))
    .map(node => node.id);
  nodesData.forEach(node => {
    const label = displayLabel(node.label || node.wikipedia_title);
    const selectedDistance = Number.isFinite(node.selected_distance) ? node.selected_distance : null;
    if (selectedDistance !== null) {
      focusNodeIds.add(node.id);
      focusDistances.set(node.id, selectedDistance);
      focusScores.set(node.id, Math.max(0, Math.min(1, Number(node.selected_focus_score) || 0)));
    }
    const focusScore = focusScores.get(node.id) || 0;
    const focusRank = selectedDistance === null
      ? 1
      : Math.min(0.14, Math.max(0.001, 0.006 + selectedDistance * 0.014 - focusScore * 0.008));
    nodeRanks.set(node.id, Math.min(node.timeline_rank ?? 1, focusRank));
    nodeScores.set(node.id, node.timeline_importance ?? 0);
    nodeWidths.set(node.id, Math.max(72, Math.min(230, label.length * 7.5 + 28)));
  });

  const edgeRanks = new Map();
  for (const edge of edgesData) {
    const fromRank = nodeRanks.get(edge.from_genre_id) ?? 1;
    const toRank = nodeRanks.get(edge.to_genre_id) ?? 1;
    const relationBoost = edge.relation === "subgenre" ? -0.04 : edge.relation === "derivative" ? 0.02 : 0.06;
    const key = timelineEdgeKey(edge);
    edgeRanks.set(key, Math.max(fromRank, toRank) + relationBoost);
    if (!edgesByNode.has(edge.from_genre_id)) edgesByNode.set(edge.from_genre_id, []);
    if (!edgesByNode.has(edge.to_genre_id)) edgesByNode.set(edge.to_genre_id, []);
    edgesByNode.get(edge.from_genre_id).push(edge);
    edgesByNode.get(edge.to_genre_id).push(edge);
  }

  return { nodeRanks, nodeScores, nodeWidths, edgeRanks, edgesByNode, focusNodeIds, focusDistances, focusScores, sortedNodeIds, clusters: [] };
}

function timelineSelectedFocusActive() {
  return Boolean(timelineSelectedGenreId && timelineVisibility.focusNodeIds?.has(timelineSelectedGenreId));
}

function timelineNodeInSelectedFocus(nodeId) {
  return !timelineSelectedFocusActive() || timelineVisibility.focusNodeIds.has(nodeId);
}

function timelineFocusDistanceCutoff(detail = timelineDetailAmount()) {
  // In selected-focus mode, mid zoom levels (0.2-0.3) should reveal
  // more connected context to avoid empty space, without changing the
  // default unselected timeline density.
  const base = Math.floor(1 + detail * 4.2);
  if (!timelineSelectedFocusActive()) {
    return Math.max(1, Math.min(4, base));
  }
  const scale = viewScale;
  const boosted = Math.floor(2 + Math.max(0, scale - 0.18) * 15);
  // A little extra tolerance in selected-node mode so active connections don't
  // disappear too aggressively at zoomed-out scales.
  const tolerant = Math.floor(Math.max(base, boosted) + (scale <= 0.26 ? 1 : 0));
  return Math.max(1, Math.min(4, tolerant));
}

function timelineSelectedBackgroundRankCutoff(detail = timelineDetailAmount()) {
  // Selected-node mode should keep some "background" context at mid zooms so
  // the canvas doesn't become mostly empty. Background nodes remain unfocused
  // (faded) and we avoid rendering their unrelated edges for performance.
  const base = timelineVisibleRankCutoff(detail);
  if (!timelineSelectedFocusActive()) return base;
  const scale = viewScale;
  if (scale < 0.18) return base;
  const t = Math.max(0, Math.min(1, (scale - 0.18) / 0.18));
  const floor = 0.05 + t * 0.06; // ~0.05 at 0.18 -> ~0.11 at 0.36
  return Math.max(base, floor);
}

function timelineVisibleNodeIds() {
  const ids = new Set();
  const detail = timelineDetailAmount();
  const rankCutoff = timelineVisibleRankCutoff(detail);
  for (const nodeId of timelineVisibility.sortedNodeIds) {
    const rank = timelineVisibility.nodeRanks.get(nodeId) ?? 1;
    const selected = nodeId === timelineSelectedGenreId;
    if (!selected && rank > rankCutoff) continue;
    ids.add(nodeId);
  }
  return ids;
}

function timelineViewportBounds(marginPx = TIMELINE_VIEWPORT_MARGIN_PX) {
  const margin = marginPx / Math.max(0.001, viewScale);
  return {
    left: (0 - viewTx) / viewScale - margin,
    right: (vw() - viewTx) / viewScale + margin,
    top: (0 - viewTy) / viewScale - margin,
    bottom: (vh() - viewTy) / viewScale + margin,
  };
}

function shouldCullTimelineToViewport() {
  return timelineMode;
}

function timelineNodeInViewport(node, bounds = timelineViewportBounds()) {
  if (!shouldCullTimelineToViewport()) return true;
  const width = timelineVisibility.nodeWidths.get(node.id) || 120;
  return (
    (node.x || 0) + width / 2 >= bounds.left &&
    (node.x || 0) - width / 2 <= bounds.right &&
    (node.y || 0) + 32 >= bounds.top &&
    (node.y || 0) - 32 <= bounds.bottom
  );
}

function timelineNodePriority(node) {
  if (node.id === timelineSelectedGenreId) return -2;
  if (timelineSelectedFocusActive() && timelineVisibility.focusNodeIds.has(node.id)) {
    const distance = timelineVisibility.focusDistances.get(node.id) ?? 4;
    const score = timelineVisibility.focusScores.get(node.id) || 0;
    return -1.5 + distance * 0.05 - score * 0.08;
  }
  const rank = timelineVisibility.nodeRanks.get(node.id) ?? 1;
  const importance = timelineVisibility.nodeScores.get(node.id) || 0;
  return rank - importance * 0.035;
}

function timelineNodeRenderScale(nodeId) {
  const importance = Math.max(0, Math.min(1, timelineVisibility.nodeScores.get(nodeId) || 0));
  const focusScore = Math.max(0, Math.min(1, timelineVisibility.focusScores.get(nodeId) || 0));
  const focusBoost = timelineSelectedFocusActive() && timelineVisibility.focusNodeIds.has(nodeId)
    ? focusScore * 0.12
    : 0;
  return 1 + importance * 0.1 + focusBoost;
}

function timelineNodeWorldBounds(node, x = node.renderX ?? node.x ?? 0, y = node.renderY ?? node.y ?? 0) {
  const scale = Math.max(0.001, viewScale);
  const nodeScale = Number.isFinite(node.node_scale) ? Number(node.node_scale) : timelineNodeRenderScale(node.id);
  const width = ((timelineVisibility.nodeWidths.get(node.id) || 120) * nodeScale) / scale;
  const height = (36 * nodeScale) / scale;
  let pad = TIMELINE_NODE_OVERLAP_PAD_PX / scale;
  // Slightly increase overlap culling for inactive nodes in selected-node mode,
  // so they disappear a bit earlier rather than packing into noisy overlaps.
  if (timelineSelectedFocusActive() && !timelineVisibility.focusNodeIds.has(node.id) && node.id !== timelineSelectedGenreId) {
    pad *= 1.35;
  }
  return {
    left: x - width / 2 - pad,
    right: x + width / 2 + pad,
    top: y - height / 2 - pad,
    bottom: y + height / 2 + pad,
  };
}

function timelineBoundsOverlap(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function timelinePlacementOffsets() {
  const values = [{ dx: 0, dy: 0, distance: 0 }];
  const steps = [34, 58, 88, 122, 160, TIMELINE_PLACEMENT_MAX_SCREEN_OFFSET];
  const directions = [
    [1, 0], [-1, 0],
    [0, 1], [0, -1],
    [1, 0.52], [-1, 0.52],
    [1, -0.52], [-1, -0.52],
    [0.55, 1], [-0.55, 1],
    [0.55, -1], [-0.55, -1],
  ];
  for (const step of steps) {
    for (const [dx, dy] of directions) {
      values.push({
        dx: dx * step,
        dy: dy * step,
        distance: step * Math.hypot(dx, dy),
      });
    }
  }
  return values;
}

const TIMELINE_PLACEMENT_OFFSETS = timelinePlacementOffsets();

function timelinePlacementInBounds(bounds, viewportBounds) {
  if (!shouldCullTimelineToViewport()) return true;
  return (
    bounds.right >= viewportBounds.left &&
    bounds.left <= viewportBounds.right &&
    bounds.bottom >= viewportBounds.top &&
    bounds.top <= viewportBounds.bottom
  );
}

function timelineStoredPlacement(node) {
  const saved = timelinePlacedPositions.get(node.id);
  if (!saved || !Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return null;
  return saved;
}

function timelinePlacementCandidate(node, x, y, keptBounds, viewportBounds) {
  const bounds = timelineNodeWorldBounds(node, x, y);
  if (!timelinePlacementInBounds(bounds, viewportBounds)) return null;
  if (keptBounds.some(existing => timelineBoundsOverlap(bounds, existing))) return null;
  return { x, y, bounds };
}

function timelinePlaceNode(node, keptBounds, viewportBounds) {
  const scale = Math.max(0.001, viewScale);
  const originX = node.x || 0;
  const originY = node.y || 0;
  let best = null;

  for (const offset of TIMELINE_PLACEMENT_OFFSETS) {
    const x = originX + offset.dx / scale;
    const y = originY + offset.dy / scale;
    const candidate = timelinePlacementCandidate(node, x, y, keptBounds, viewportBounds);
    if (!candidate) continue;
    const yPenalty = Math.abs(offset.dy) * 1.45;
    const score = offset.distance + yPenalty;
    if (!best || score < best.score) best = { ...candidate, score };
  }

  return best;
}

function timelineCullOverlappingNodes(candidates, viewportBounds = timelineViewportBounds()) {
  const ordered = candidates
    .slice()
    .sort((a, b) => (
      timelineNodePriority(a) - timelineNodePriority(b)
      || (timelineRenderedNodeIds.has(a.id) ? 0 : 1) - (timelineRenderedNodeIds.has(b.id) ? 0 : 1)
      || (a.y || 0) - (b.y || 0)
      || (a.x || 0) - (b.x || 0)
      || (a.label || a.wikipedia_title || "").localeCompare(b.label || b.wikipedia_title || "")
      || a.id.localeCompare(b.id)
    ));
  const kept = [];
  const keptBounds = [];
  for (const node of ordered) {
    const saved = timelineStoredPlacement(node);
    const focusActive = timelineSelectedFocusActive();
    const staticX = saved?.x ?? node.x;
    const staticY = saved?.y ?? node.y;
    // In selected-node mode we do not "move nodes" to resolve overlap. We keep
    // static/stored positions and cull lower-priority overlaps instead.
    const placement = focusActive
      ? timelinePlacementCandidate(node, staticX, staticY, keptBounds, viewportBounds)
      : (
          (saved && timelinePlacementCandidate(node, saved.x, saved.y, keptBounds, viewportBounds)) ||
          timelinePlaceNode(node, keptBounds, viewportBounds)
        );
    if (!placement && node.id !== timelineSelectedGenreId) {
      continue;
    }
    const placed = {
      ...node,
      renderX: placement?.x ?? node.x,
      renderY: placement?.y ?? node.y,
    };
    timelinePlacedPositions.set(node.id, { x: placed.renderX, y: placed.renderY });
    kept.push(placed);
    keptBounds.push(placement?.bounds ?? timelineNodeWorldBounds(placed));
  }
  return kept.sort((a, b) => (a.renderY || a.y || 0) - (b.renderY || b.y || 0) || (a.renderX || a.x || 0) - (b.renderX || b.x || 0));
}

function timelineEdgePriority(edge) {
  return (
    (timelineVisibility.edgeRanks.get(timelineEdgeKey(edge)) ?? 1) * 10 +
    (RELATION_RANK.get(edge.relation) ?? 9)
  );
}

function timelineHasAlternatePath(fromId, toId, skipKey, adjacency) {
  const queue = [{ id: fromId, depth: 0 }];
  const seen = new Set([fromId]);
  while (queue.length) {
    const current = queue.shift();
    if (!current || current.depth >= 5) continue;
    for (const edge of adjacency.get(current.id) || []) {
      const key = timelineEdgeKey(edge);
      if (key === skipKey) continue;
      if (edge.to_genre_id === toId) return true;
      if (seen.has(edge.to_genre_id)) continue;
      seen.add(edge.to_genre_id);
      queue.push({ id: edge.to_genre_id, depth: current.depth + 1 });
    }
  }
  return false;
}

function timelineExtraEdgeAllowance(nodeId, candidateDegree, nodeById) {
  const node = nodeById.get(nodeId);
  const views = Math.max(0, node?.monthly_views_p30 || 0);
  const degree = candidateDegree.get(nodeId) || 0;
  if (degree <= 2) return 0;
  const viewFactor = Math.max(0.18, Math.min(1.35, Math.log10(views + 10) / 3.35));
  const connectionFactor = Math.sqrt(Math.max(0, degree - 2));
  return Math.max(0, Math.min(
    TIMELINE_EXTRA_EDGE_MAX,
    Math.round(connectionFactor * viewFactor)
  ));
}

function timelineCanKeepExtraEdge(edge, extraUsage, extraAllowance) {
  const fromUsed = extraUsage.get(edge.from_genre_id) || 0;
  const toUsed = extraUsage.get(edge.to_genre_id) || 0;
  const fromAllowance = extraAllowance.get(edge.from_genre_id) || 0;
  const toAllowance = extraAllowance.get(edge.to_genre_id) || 0;
  return fromUsed < fromAllowance || toUsed < toAllowance;
}

function timelineRecordExtraEdge(edge, extraUsage) {
  extraUsage.set(edge.from_genre_id, (extraUsage.get(edge.from_genre_id) || 0) + 1);
  extraUsage.set(edge.to_genre_id, (extraUsage.get(edge.to_genre_id) || 0) + 1);
}

function timelineNodeIsCore(nodeId) {
  if (nodeId === timelineSelectedGenreId) return true;
  if (timelineSelectedFocusActive() && timelineVisibility.focusNodeIds.has(nodeId)) return true;
  return (timelineVisibility.nodeRanks.get(nodeId) ?? 1) <= timelineCoreRankCutoff();
}

function timelineEdgeSideForNode(edge, nodeId) {
  const self = timelineNodePositions.get(nodeId);
  const otherId = edge.from_genre_id === nodeId ? edge.to_genre_id : edge.from_genre_id;
  const other = timelineNodePositions.get(otherId);
  if (!self || !other) return edge.from_genre_id === nodeId ? "bottom" : "top";
  return other.y < self.y ? "top" : "bottom";
}

function timelineSideUsageKey(nodeId, side) {
  return `${nodeId}:${side}`;
}

function timelineNodeSideLimit(nodeId, nodeById) {
  if (nodeId === timelineSelectedGenreId) return Number.POSITIVE_INFINITY;
  if (timelineSelectedFocusActive() && timelineVisibility.focusNodeIds.has(nodeId)) {
    const distance = timelineVisibility.focusDistances.get(nodeId) ?? 4;
    if (distance <= 1) return Number.POSITIVE_INFINITY;
    if (distance === 2) return 10;
    if (distance === 3) return 5;
  }
  if (!timelineNodeIsCore(nodeId)) return TIMELINE_NON_CORE_SIDE_EDGE_LIMIT;
  const views = Math.max(0, nodeById.get(nodeId)?.monthly_views_p30 || 0);
  return Math.max(2, Math.min(7, Math.round(Math.log10(views + 10) * 1.8)));
}

function timelineCanUseSideBudget(edge, sideUsage, nodeById) {
  for (const nodeId of [edge.from_genre_id, edge.to_genre_id]) {
    const side = timelineEdgeSideForNode(edge, nodeId);
    const key = timelineSideUsageKey(nodeId, side);
    if ((sideUsage.get(key) || 0) >= timelineNodeSideLimit(nodeId, nodeById)) return false;
  }
  return true;
}

function timelineRecordSideUsage(edge, sideUsage, incidentCounts) {
  for (const nodeId of [edge.from_genre_id, edge.to_genre_id]) {
    const side = timelineEdgeSideForNode(edge, nodeId);
    const key = timelineSideUsageKey(nodeId, side);
    sideUsage.set(key, (sideUsage.get(key) || 0) + 1);
    incidentCounts.set(nodeId, (incidentCounts.get(nodeId) || 0) + 1);
  }
}

function timelineTrimEdgeSides(candidates, renderedNodeIds, nodeById, fallbackCandidates = candidates) {
  const result = [];
  const resultKeys = new Set();
  const sideUsage = new Map();
  const incidentCounts = new Map([...renderedNodeIds].map(nodeId => [nodeId, 0]));

  for (const edge of candidates) {
    if (!timelineCanUseSideBudget(edge, sideUsage, nodeById)) continue;
    result.push(edge);
    resultKeys.add(timelineEdgeKey(edge));
    timelineRecordSideUsage(edge, sideUsage, incidentCounts);
  }

  for (const nodeId of renderedNodeIds) {
    if ((incidentCounts.get(nodeId) || 0) > 0) continue;
    const edge = fallbackCandidates.find(candidate =>
      !resultKeys.has(timelineEdgeKey(candidate)) &&
      (candidate.from_genre_id === nodeId || candidate.to_genre_id === nodeId)
    );
    if (!edge) continue;
    result.push(edge);
    resultKeys.add(timelineEdgeKey(edge));
    timelineRecordSideUsage(edge, sideUsage, incidentCounts);
  }

  return result;
}

function timelineCandidateEdgesForRenderedNodes(renderedNodeIds) {
  const result = [];
  const seen = new Set();
  for (const nodeId of renderedNodeIds) {
    for (const edge of timelineVisibility.edgesByNode.get(nodeId) || []) {
      const key = timelineEdgeKey(edge);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(edge);
    }
  }
  return result;
}

function timelineConsolidatedEdges(edgesData, renderedNodeIds, edgeEndpointNodeIds, edgeRankCutoff, nodeById) {
  const fallbackByPair = new Map();
  const bestByPair = new Map();
  for (const edge of edgesData) {
    const fromRendered = renderedNodeIds.has(edge.from_genre_id);
    const toRendered = renderedNodeIds.has(edge.to_genre_id);
    if (!fromRendered && !toRendered) continue;
    if (!edgeEndpointNodeIds.has(edge.from_genre_id) || !edgeEndpointNodeIds.has(edge.to_genre_id)) continue;
    const pairKey = `${edge.from_genre_id}->${edge.to_genre_id}`;
    const fallbackCurrent = fallbackByPair.get(pairKey);
    if (!fallbackCurrent || timelineEdgePriority(edge) < timelineEdgePriority(fallbackCurrent)) {
      fallbackByPair.set(pairKey, edge);
    }
    if ((timelineVisibility.edgeRanks.get(timelineEdgeKey(edge)) ?? 1) > edgeRankCutoff) continue;
    const current = bestByPair.get(pairKey);
    if (!current || timelineEdgePriority(edge) < timelineEdgePriority(current)) {
      bestByPair.set(pairKey, edge);
    }
  }

  const candidates = [...bestByPair.values()].sort((a, b) => timelineEdgePriority(a) - timelineEdgePriority(b));
  const candidateDegree = new Map();
  for (const edge of candidates) {
    candidateDegree.set(edge.from_genre_id, (candidateDegree.get(edge.from_genre_id) || 0) + 1);
    candidateDegree.set(edge.to_genre_id, (candidateDegree.get(edge.to_genre_id) || 0) + 1);
  }
  const extraAllowance = new Map(
    [...renderedNodeIds].map(nodeId => [
      nodeId,
      timelineExtraEdgeAllowance(nodeId, candidateDegree, nodeById),
    ])
  );
  const extraUsage = new Map();
  const adjacency = new Map();
  for (const edge of candidates) {
    if (!adjacency.has(edge.from_genre_id)) adjacency.set(edge.from_genre_id, []);
    adjacency.get(edge.from_genre_id).push(edge);
  }

  const result = [];
  for (const edge of candidates) {
    const hasAlternate = timelineHasAlternatePath(
      edge.from_genre_id,
      edge.to_genre_id,
      timelineEdgeKey(edge),
      adjacency
    );
    if (!hasAlternate) {
      result.push(edge);
      continue;
    }
    if (!timelineCanKeepExtraEdge(edge, extraUsage, extraAllowance)) continue;
    timelineRecordExtraEdge(edge, extraUsage);
    result.push(edge);
  }
  const fallbackCandidates = [...fallbackByPair.values()].sort((a, b) => timelineEdgePriority(a) - timelineEdgePriority(b));
  return timelineTrimEdgeSides(result, renderedNodeIds, nodeById, fallbackCandidates);
}

function timelineRenderSignatureFor(cutoff = timelineVisibleRankCutoff()) {
  const bounds = timelineViewportBounds();
  return [
    `rank:${Math.round(cutoff / TIMELINE_RENDER_RANK_EPSILON)}`,
    `x:${Math.floor(bounds.left / TIMELINE_VIEWPORT_TILE)}:${Math.ceil(bounds.right / TIMELINE_VIEWPORT_TILE)}`,
    `y:${Math.floor(bounds.top / TIMELINE_VIEWPORT_TILE)}:${Math.ceil(bounds.bottom / TIMELINE_VIEWPORT_TILE)}`,
  ].join("|");
}

function timelineRenderRankSignature(cutoff = timelineVisibleRankCutoff()) {
  return `rank:${Math.round(cutoff / TIMELINE_RENDER_RANK_EPSILON)}`;
}

function timelineRenderedRankSignature() {
  return timelineRenderedSignature.split("|")[0] || "";
}

function scheduleTimelineRender(options = {}) {
  if (!timelineMode || !timelineData) return;
  const delay = Math.max(0, options.delay ?? 0);
  if (delay > 0 && !options.urgent) {
    if (timelineRenderFrame) return;
    if (timelineRenderTimer) return;
    timelineRenderTimer = window.setTimeout(() => {
      timelineRenderTimer = null;
      scheduleTimelineRender({ urgent: true, noFade: options.noFade });
    }, delay);
    return;
  }
  if (timelineRenderTimer) {
    window.clearTimeout(timelineRenderTimer);
    timelineRenderTimer = null;
  }
  if (timelineRenderFrame) return;
  const noFade = Boolean(options.noFade || timelineNoFadeNextRender);
  timelineRenderFrame = requestAnimationFrame(() => {
    timelineRenderFrame = null;
    if (noFade) timelineNoFadeNextRender = false;
    if (timelineMode && timelineData) renderTimeline(timelineData, { preserveView: true, noFade });
  });
}

function scheduleTimelineDataWindowRefresh(options = {}) {
  if (!timelineMode || !timelineData) return;
  const now = Date.now();
  if (now < timelineStreamRetryAfter) return;
  if (options.allowDuringInteraction && now - timelineLastDataRefreshAt < 320) return;
  const desiredRank = timelineDesiredServerRankForScale();
  const signature = timelineDataSignature(desiredRank);
  if (!options.forceViewport && signature === timelineLastDataSignature) return;
  if (
    !options.forceViewport &&
    desiredRank <= timelineLoadedRank + TIMELINE_RANK_RELOAD_EPSILON
  ) return;
  if (timelineLoadingRank) {
    timelineQueuedRank = Math.max(timelineQueuedRank, desiredRank);
    return;
  }
  timelineLastDataRefreshAt = now;
  timelineLastDataSignature = signature;
  const quiet = true;
  void loadTimelineForSelection({
    preserveView: true,
    requestedRank: desiredRank,
    quiet,
    forceViewport: Boolean(options.forceViewport),
  });
}

function clearTimelineSelectionMode() {
  if (!timelineMode) return;
  timelineSelectedGenreId = null;
  timelineDetailCardOpen = false;
  setDetailCardNodeKey(null);
  hoverCardToken++;
  timelineDataRequestToken += 1;
  timelineLoadingRank = 0;
  timelineQueuedRank = 0;
  timelineLastDataSignature = "";
  timelineRenderedSignature = "";
  timelineRenderedNodeIds = new Set();
  timelineRenderedEdgeKeys = new Set();
  timelineNodeDetailSignature = "";
  timelinePlacedPositions = new Map();
  updateDetailCardVisibility();
  updateUrlState({ push: true });
  if (timelineData) renderTimeline(timelineData, { preserveView: true });
  void loadTimelineForSelection({
    force: true,
    preserveView: true,
    selectedGenreId: null,
    requestedRank: Math.max(timelineLoadedRank, timelineDesiredServerRankForScale()),
    quiet: true,
  });
}

function updateTimelineZoomDetail() {
  if (!timelineMode || !timelineData) return;
  const detail = timelineDetailAmount();
  const cutoff = timelineVisibleRankCutoff(detail);
  const signature = timelineRenderSignatureFor(cutoff);
  if (signature !== timelineRenderedSignature) {
    // While panning/zooming we avoid rebuilding all SVG layers; we queue a render
    // for shortly after interaction so transforms remain smooth.
    if (timelineIsInteracting()) {
      timelineNeedsRender = true;
    } else {
      const rankChanged = timelineRenderRankSignature(cutoff) !== timelineRenderedRankSignature();
      scheduleTimelineRender({ urgent: rankChanged, delay: rankChanged ? 0 : 70 });
    }
  }
  scheduleTimelineDataWindowRefresh({
    allowDuringInteraction: timelineIsInteracting(),
    forceViewport: timelineIsInteracting(),
  });
  updateTimelineNodeZoomDetail(detail);
}

function updateTimelineNodeZoomDetail(detail = timelineDetailAmount(), options = {}) {
  if (!timelineMode || !timelineData) return;
  const inverseScale = 1 / Math.max(0.001, viewScale);
  const labelRankCutoff = 0.18 + detail * 0.44;
  const signature = [
    Math.round(inverseScale * 1000),
    Math.round(labelRankCutoff / TIMELINE_RENDER_RANK_EPSILON),
  ].join("|");
  const shouldUpdateLabels = Boolean(options.force || signature !== timelineNodeDetailSignature);
  if (shouldUpdateLabels) timelineNodeDetailSignature = signature;
  for (const el of nodesG.querySelectorAll(".timeline-node-layer:not(.timeline-layer-exiting) .timeline-node")) {
    const rank = timelineVisibility.nodeRanks.get(el.dataset.genreId) ?? 1;
    const labelVisible = rank <= labelRankCutoff;
    const inner = el.querySelector(".timeline-node-inner");
    const nodeScale = Number(el.dataset.nodeScale) || 1;
    if (inner) inner.setAttribute("transform", `scale(${inverseScale * nodeScale})`);
    if (shouldUpdateLabels) el.classList.toggle("timeline-node-label-hidden", !labelVisible);
  }
}

function ensureTimelineLayers() {
  if (!timelineMode) return;
  if (!timelineGridLayerEl) {
    timelineGridLayerEl = svgEl("g", { class: "timeline-grid" });
    edgesG.appendChild(timelineGridLayerEl);
  }
  if (!timelineEdgeLayerEl) {
    timelineEdgeLayerEl = svgEl("g", { class: "timeline-edge-layer" });
    edgesG.appendChild(timelineEdgeLayerEl);
  }
  if (!timelineNodeLayerEl) {
    timelineNodeLayerEl = svgEl("g", { class: "timeline-node-layer" });
    nodesG.appendChild(timelineNodeLayerEl);
  }
}

function clearTimelineLayersImmediate() {
  if (timelineGridLayerEl) timelineGridLayerEl.remove();
  if (timelineEdgeLayerEl) timelineEdgeLayerEl.remove();
  if (timelineNodeLayerEl) timelineNodeLayerEl.remove();
  timelineGridLayerEl = null;
  timelineEdgeLayerEl = null;
  timelineNodeLayerEl = null;
  timelineEdgeElByKey = new Map();
  timelineNodeElById = new Map();
  timelineVisibilityCache = null;
  timelineVisibilityCacheData = null;
  timelineNodeByIdCache = null;
  timelineNodeByIdCacheData = null;
  timelineDecadeCache = null;
  timelineDecadeCacheData = null;
}

function timelineVisibilityFromPreparedScene(data, scene) {
  const nodeRanks = new Map();
  const nodeScores = new Map();
  const nodeWidths = new Map();
  const edgeRanks = new Map();
  const edgesByNode = new Map();
  const focusNodeIds = new Set(scene.focus_node_ids || []);
  const focusDistances = new Map();
  const focusScores = new Map();
  const nodesData = data.nodes || [];
  for (const node of nodesData) {
    const nodeId = node.id;
    if (!nodeId) continue;
    const label = displayLabel(node.label || node.wikipedia_title);
    const rank = Number.isFinite(node.timeline_render_rank)
      ? node.timeline_render_rank
      : Number.isFinite(node.timeline_rank)
        ? node.timeline_rank
        : 1;
    nodeRanks.set(nodeId, rank);
    nodeScores.set(nodeId, Number.isFinite(node.timeline_importance) ? node.timeline_importance : 0);
    nodeWidths.set(nodeId, Math.max(72, Math.min(230, label.length * 7.5 + 28)));
    if (Number.isFinite(node.selected_distance)) {
      focusNodeIds.add(nodeId);
      focusDistances.set(nodeId, node.selected_distance);
      focusScores.set(nodeId, Math.max(0, Math.min(1, Number(node.selected_focus_score) || 0)));
    }
  }
  for (const node of scene.nodes || []) {
    if (!node.id) continue;
    if (Number.isFinite(node.timeline_render_rank)) nodeRanks.set(node.id, node.timeline_render_rank);
    if (Number.isFinite(node.node_scale)) nodeScores.set(node.id, Math.max(0, (Number(node.node_scale) - 1) / 0.1));
    if (node.timeline_focus) focusNodeIds.add(node.id);
  }
  for (const edge of scene.edges || []) {
    const key = edge.key || timelineEdgeKey(edge);
    edgeRanks.set(key, 0);
    if (!edgesByNode.has(edge.from_genre_id)) edgesByNode.set(edge.from_genre_id, []);
    if (!edgesByNode.has(edge.to_genre_id)) edgesByNode.set(edge.to_genre_id, []);
    edgesByNode.get(edge.from_genre_id).push(edge);
    edgesByNode.get(edge.to_genre_id).push(edge);
  }
  const sortedNodeIds = nodesData
    .map(node => node.id)
    .filter(Boolean)
    .sort((a, b) => (nodeRanks.get(a) ?? 1) - (nodeRanks.get(b) ?? 1) || a.localeCompare(b));
  return { nodeRanks, nodeScores, nodeWidths, edgeRanks, edgesByNode, focusNodeIds, focusDistances, focusScores, sortedNodeIds, clusters: [] };
}

function renderPreparedTimeline(data, scene, options = {}) {
  const previousRenderedNodeIds = new Set(timelineRenderedNodeIds);
  const previousRenderedEdgeKeys = new Set(timelineRenderedEdgeKeys);
  const enteringNodes = [];
  const enteringEdges = [];
  ensureTimelineLayers();
  ensureEdgeGradientDefs().innerHTML = "";

  const sceneNodes = scene.nodes || [];
  const sceneEdges = scene.edges || [];
  timelineVisibility = timelineVisibilityFromPreparedScene(data, scene);
  timelineNodePositions = new Map((data.nodes || []).map(node => [node.id, { x: node.x || 0, y: node.y || 0 }]));
  for (const node of sceneNodes) {
    timelineNodePositions.set(node.id, {
      x: node.renderX ?? node.x ?? 0,
      y: node.renderY ?? node.y ?? 0,
    });
  }
  timelineYearRows = Array.isArray(scene.year_rows) ? scene.year_rows : [];
  timelineRenderedSignature = scene.render_signature || timelineRenderSignatureFor(timelineVisibleRankCutoff());

  const viewportBounds = timelineViewportBounds();
  const grid = timelineGridLayerEl;
  grid.innerHTML = "";
  for (const row of timelineYearRows) {
    const y = Number(row.y);
    if (!Number.isFinite(y) || y < viewportBounds.top || y > viewportBounds.bottom) continue;
    grid.appendChild(svgEl("line", {
      x1: -1_000_000,
      y1: y,
      x2: 1_000_000,
      y2: y,
      class: "timeline-tick",
    }));
  }

  const edgeLayer = timelineEdgeLayerEl;
  const nextEdgeKeys = new Set();
  for (const edge of sceneEdges) {
    const edgeKey = edge.key || timelineEdgeKey(edge);
    nextEdgeKeys.add(edgeKey);
    const isEntering = !options.noFade && !previousRenderedEdgeKeys.has(edgeKey);
    const existing = timelineEdgeElByKey.get(edgeKey);
    const d = edge.path || timelinePath(edge.route);
    if (existing) {
      if (existing.getAttribute("d") !== d) existing.setAttribute("d", d);
      existing.classList.remove("timeline-edge-exiting");
      existing.dataset.fromGenreId = edge.from_genre_id;
      existing.dataset.toGenreId = edge.to_genre_id;
      existing.dataset.edgeKey = edgeKey;
    } else {
      const edgeEl = svgEl("path", {
        d,
        class: `timeline-edge timeline-edge-${edge.relation}${isEntering ? " timeline-edge-entering" : ""}`,
      });
      edgeEl.dataset.fromGenreId = edge.from_genre_id;
      edgeEl.dataset.toGenreId = edge.to_genre_id;
      edgeEl.dataset.edgeKey = edgeKey;
      edgeLayer.appendChild(edgeEl);
      timelineEdgeElByKey.set(edgeKey, edgeEl);
      if (isEntering) enteringEdges.push(edgeEl);
    }
  }
  for (const [key, el] of timelineEdgeElByKey.entries()) {
    if (nextEdgeKeys.has(key)) continue;
    if (el.classList.contains("timeline-edge-exiting")) continue;
    el.classList.add("timeline-edge-exiting");
    window.setTimeout(() => {
      if (el.parentNode) el.remove();
      timelineEdgeElByKey.delete(key);
    }, prefersReducedMotion() ? 0 : 180);
  }

  const nodeLayer = timelineNodeLayerEl;
  for (const node of sceneNodes) {
    const isEntering = !options.noFade && !previousRenderedNodeIds.has(node.id);
    const existing = timelineNodeElById.get(node.id);
    const isSelected = node.id === timelineSelectedGenreId;
    const detail = detailCache.get(node.id);
    const color = detail?.color || node.similarity_color || (isSelected ? "var(--accent)" : null);
    if (existing) {
      existing.setAttribute("transform", `translate(${node.renderX ?? node.x}, ${node.renderY ?? node.y})`);
      existing.dataset.nodeScale = Number.isFinite(node.node_scale) ? Number(node.node_scale).toFixed(3) : existing.dataset.nodeScale;
      const className = timelineNodeClassName(node, color, false);
      if (existing.dataset.className !== className) {
        existing.setAttribute("class", className);
        existing.dataset.className = className;
      }
      existing.classList.remove("timeline-node-exiting");
      if (color) existing.style.setProperty("--genre-color", color);
      else existing.style.removeProperty("--genre-color");
      const labelEl = existing.querySelector(".timeline-node-label");
      if (labelEl) {
        if (!isSelected && color) labelEl.style.fill = color;
        else labelEl.style.removeProperty("fill");
      }
    } else {
      const nodeEl = buildTimelineNodeEl(node, isEntering);
      nodeLayer.appendChild(nodeEl);
      nodeEl.dataset.className = nodeEl.getAttribute("class") || "";
      timelineNodeElById.set(node.id, nodeEl);
      if (isEntering) enteringNodes.push(nodeEl);
    }
  }
  const nextNodeIds = new Set(sceneNodes.map(node => node.id));
  for (const [nodeId, el] of timelineNodeElById.entries()) {
    if (nextNodeIds.has(nodeId)) continue;
    if (el.classList.contains("timeline-node-exiting")) continue;
    el.classList.add("timeline-node-exiting");
    window.setTimeout(() => {
      if (el.parentNode) el.remove();
      timelineNodeElById.delete(nodeId);
    }, prefersReducedMotion() ? 0 : 180);
  }
  timelineRenderedNodeIds = nextNodeIds;
  timelineRenderedEdgeKeys = new Set(sceneEdges.map(edge => edge.key || timelineEdgeKey(edge)));
  updateTimelineNodeZoomDetail(timelineDetailAmount(), { force: true });
  if (!prefersReducedMotion() && (enteringNodes.length || enteringEdges.length)) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        for (const el of enteringNodes) el.classList.remove("timeline-node-entering");
        for (const el of enteringEdges) el.classList.remove("timeline-edge-entering");
      });
    });
  } else {
    for (const el of enteringNodes) el.classList.remove("timeline-node-entering");
    for (const el of enteringEdges) el.classList.remove("timeline-edge-entering");
  }

  const totalNodes = data.stats?.total_nodes || data.stats?.nodes || (data.nodes || []).length;
  setStatus(`${sceneNodes.length} visible of ${totalNodes} timeline genres`);

  if (!options.preserveView) {
    const streamBounds = data.stats?.bounds;
    const bounds = streamBounds
      ? {
          minX: Number(streamBounds.min_x),
          maxX: Number(streamBounds.max_x),
          minY: Number(streamBounds.min_y),
          maxY: Number(streamBounds.max_y),
        }
      : (data.nodes || []).reduce((acc, node) => {
          const x = node.x || 0;
          const y = node.y || 0;
          acc.minX = Math.min(acc.minX, x);
          acc.maxX = Math.max(acc.maxX, x);
          acc.minY = Math.min(acc.minY, y);
          acc.maxY = Math.max(acc.maxY, y);
          return acc;
        }, { minX: Number.POSITIVE_INFINITY, maxX: Number.NEGATIVE_INFINITY, minY: Number.POSITIVE_INFINITY, maxY: Number.NEGATIVE_INFINITY });
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    viewScale = MIN_VIEW_SCALE;
    viewTx = focusX() - centerX * viewScale;
    viewTy = focusY() - centerY * viewScale;
    writeWorldTransform();
  } else {
    updateTimelineYearMarkers();
  }
  if (!timelineIsInteracting()) setGraphStill(true);
}

function renderTimeline(data, options = {}) {
  if (data?.render_scene?.nodes && data?.render_scene?.edges) {
    renderPreparedTimeline(data, data.render_scene, options);
    return;
  }
  const previousRenderedNodeIds = new Set(timelineRenderedNodeIds);
  const previousRenderedEdgeKeys = new Set(timelineRenderedEdgeKeys);
  const enteringNodes = [];
  const enteringEdges = [];
  ensureTimelineLayers();
  ensureEdgeGradientDefs().innerHTML = "";
  const nodesData = data.nodes || [];
  const edgesData = data.edges || [];
  const nodeById = (timelineNodeByIdCacheData === data && timelineNodeByIdCache)
    ? timelineNodeByIdCache
    : new Map(nodesData.map(node => [node.id, node]));
  timelineNodeByIdCache = nodeById;
  timelineNodeByIdCacheData = data;

  timelineVisibility = (timelineVisibilityCacheData === data && timelineVisibilityCache)
    ? timelineVisibilityCache
    : buildTimelineVisibilityModel(nodesData, edgesData);
  timelineVisibilityCache = timelineVisibility;
  timelineVisibilityCacheData = data;
  if (!nodesData.length) {
    timelineYearRows = [];
    timelineVisibility = {
      nodeRanks: new Map(),
      nodeScores: new Map(),
      nodeWidths: new Map(),
      edgeRanks: new Map(),
      edgesByNode: new Map(),
      focusNodeIds: new Set(),
      focusDistances: new Map(),
      sortedNodeIds: [],
      clusters: [],
    };
    timelineNodePositions = new Map();
    timelinePlacedPositions = new Map();
    timelineRenderedNodeIds = new Set();
    timelineRenderedEdgeKeys = new Set();
    timelineNodeDetailSignature = "";
    updateTimelineYearMarkers();
    setStatus("No timeline nodes found.");
    return;
  }
  timelineNodePositions = new Map(nodesData.map(node => [node.id, { x: node.x || 0, y: node.y || 0 }]));
  const renderCutoff = timelineVisibleRankCutoff();
  const selectedBackgroundCutoff = timelineSelectedBackgroundRankCutoff();
  const detail = timelineDetailAmount();
  const focusActive = timelineSelectedFocusActive();
  const focusDistanceCutoff = timelineFocusDistanceCutoff(detail);
  const viewportBounds = timelineViewportBounds();
  const renderCandidates = nodesData.filter(node => {
    const rank = timelineVisibility.nodeRanks.get(node.id) ?? 1;
    if (focusActive && timelineVisibility.focusNodeIds.has(node.id)) {
      const distance = timelineVisibility.focusDistances.get(node.id) ?? 99;
      if (distance > focusDistanceCutoff && node.id !== timelineSelectedGenreId) return false;
    } else if (node.id !== timelineSelectedGenreId) {
      const cutoff = focusActive ? selectedBackgroundCutoff : renderCutoff;
      if (rank > cutoff) return false;
    }
    return timelineNodeInViewport(node, viewportBounds);
  });
  const renderedNodesData = timelineCullOverlappingNodes(renderCandidates, viewportBounds);
  const renderedNodeIds = new Set(renderedNodesData.map(node => node.id));
  for (const node of renderedNodesData) {
    timelineNodePositions.set(node.id, {
      x: node.renderX ?? node.x ?? 0,
      y: node.renderY ?? node.y ?? 0,
    });
  }
  timelineRenderedSignature = timelineRenderSignatureFor(renderCutoff);

  const width = Math.max(1000, Math.ceil(Math.max(...nodesData.map(n => n.x || 0)) + 260));
  const height = Math.max(900, Math.ceil(Math.max(...nodesData.map(n => n.y || 0)) + 160));

  const grid = timelineGridLayerEl;
  grid.innerHTML = "";
  let yByDecade = null;
  if (timelineDecadeCacheData === data && timelineDecadeCache) {
    yByDecade = timelineDecadeCache;
  } else {
    const decadeRows = [...new Set(nodesData
      .filter(node => node.year_start)
      .map(node => Math.floor(node.year_start / 10) * 10))]
      .sort((a, b) => a - b);
    yByDecade = new Map();
    for (const decade of decadeRows) {
      const decadeNodes = nodesData.filter(node => Math.floor((node.year_start || 0) / 10) * 10 === decade);
      const avgY = decadeNodes.reduce((sum, node) => sum + node.y, 0) / Math.max(1, decadeNodes.length);
      yByDecade.set(decade, avgY);
    }
    timelineDecadeCache = yByDecade;
    timelineDecadeCacheData = data;
  }
  timelineYearRows = Array.from(yByDecade, ([decade, y]) => ({ decade, y }))
    .sort((a, b) => a.y - b.y);
  for (const y of yByDecade.values()) {
    if (y < viewportBounds.top || y > viewportBounds.bottom) continue;
    grid.appendChild(svgEl("line", {
      x1: -1_000_000,
      y1: y,
      x2: 1_000_000,
      y2: y,
      class: "timeline-tick",
    }));
  }
  const edgeLayer = timelineEdgeLayerEl;
  const nextEdgeKeys = new Set();
  const edgeRankCutoff = focusActive ? 1.05 : 0.10 + detail * 0.34;
  const edgeEndpointNodeIds = focusActive
    ? new Set([...timelineVisibility.focusNodeIds].filter(nodeId => nodeById.has(nodeId)))
    : new Set(nodesData
        .filter(node => node.id === timelineSelectedGenreId || (timelineVisibility.nodeRanks.get(node.id) ?? 1) <= renderCutoff)
        .map(node => node.id));
  const candidateRenderedEdgesData = timelineConsolidatedEdges(
    timelineCandidateEdgesForRenderedNodes(renderedNodeIds),
    renderedNodeIds,
    edgeEndpointNodeIds,
    edgeRankCutoff,
    nodeById
  );
  const renderedEdgesData = focusActive
    ? candidateRenderedEdgesData.filter(edge => {
        if (!renderedNodeIds.has(edge.from_genre_id) || !renderedNodeIds.has(edge.to_genre_id)) return false;
        // In selected-node mode we keep edges only for the focus subgraph so we
        // can include faded background nodes without paying for background paths.
        return (
          timelineVisibility.focusNodeIds.has(edge.from_genre_id) ||
          timelineVisibility.focusNodeIds.has(edge.to_genre_id)
        );
      })
    : candidateRenderedEdgesData;
  const connectedRenderedNodeIds = new Set();
  for (const edge of renderedEdgesData) {
    connectedRenderedNodeIds.add(edge.from_genre_id);
    connectedRenderedNodeIds.add(edge.to_genre_id);
    const edgeKey = timelineEdgeKey(edge);
    nextEdgeKeys.add(edgeKey);
    const isEntering = !options.noFade && !previousRenderedEdgeKeys.has(edgeKey);
    const existing = timelineEdgeElByKey.get(edgeKey);
    const d = timelineEdgePathForNodes(edge.from_genre_id, edge.to_genre_id) || timelinePath(edge.route);
    if (existing) {
      if (existing.getAttribute("d") !== d) existing.setAttribute("d", d);
      existing.classList.remove("timeline-edge-exiting");
      existing.dataset.fromGenreId = edge.from_genre_id;
      existing.dataset.toGenreId = edge.to_genre_id;
      existing.dataset.edgeKey = edgeKey;
    } else {
      const edgeEl = svgEl("path", {
        d,
        class: `timeline-edge timeline-edge-${edge.relation}${isEntering ? " timeline-edge-entering" : ""}`,
      });
      edgeEl.dataset.fromGenreId = edge.from_genre_id;
      edgeEl.dataset.toGenreId = edge.to_genre_id;
      edgeEl.dataset.edgeKey = edgeKey;
      edgeLayer.appendChild(edgeEl);
      timelineEdgeElByKey.set(edgeKey, edgeEl);
      if (isEntering) enteringEdges.push(edgeEl);
    }
  }
  // Remove edges that are no longer rendered (fade out per-edge).
  for (const [key, el] of timelineEdgeElByKey.entries()) {
    if (nextEdgeKeys.has(key)) continue;
    if (el.classList.contains("timeline-edge-exiting")) continue;
    el.classList.add("timeline-edge-exiting");
    window.setTimeout(() => {
      if (el.parentNode) el.remove();
      timelineEdgeElByKey.delete(key);
    }, prefersReducedMotion() ? 0 : 180);
  }

  const nodeLayer = timelineNodeLayerEl;
  const finalRenderedNodesData = renderedEdgesData.length
    ? (focusActive
        ? renderedNodesData
        : renderedNodesData.filter(node => connectedRenderedNodeIds.has(node.id)))
    : renderedNodesData;
  for (const node of finalRenderedNodesData) {
    const isEntering = !options.noFade && !previousRenderedNodeIds.has(node.id);
    const existing = timelineNodeElById.get(node.id);
    const isSelected = node.id === timelineSelectedGenreId;
    const detail = detailCache.get(node.id);
    const color = detail?.color || node.similarity_color || (isSelected ? "var(--accent)" : null);
    if (existing) {
      // Update position + classes in-place.
      existing.setAttribute("transform", `translate(${node.renderX ?? node.x}, ${node.renderY ?? node.y})`);
      const className = timelineNodeClassName(node, color, false);
      if (existing.dataset.className !== className) {
        existing.setAttribute("class", className);
        existing.dataset.className = className;
      }
      existing.classList.remove("timeline-node-exiting");
      if (color) existing.style.setProperty("--genre-color", color);
      else existing.style.removeProperty("--genre-color");
      const labelEl = existing.querySelector(".timeline-node-label");
      if (labelEl) {
        if (!isSelected && color) labelEl.style.fill = color;
        else labelEl.style.removeProperty("fill");
      }
      // Rebuild if "entering" is needed (rare).
    } else {
      const nodeEl = buildTimelineNodeEl(node, isEntering);
      nodeLayer.appendChild(nodeEl);
      nodeEl.dataset.className = nodeEl.getAttribute("class") || "";
      timelineNodeElById.set(node.id, nodeEl);
      if (isEntering) enteringNodes.push(nodeEl);
    }
  }
  // Fade out nodes that are no longer rendered (per-node).
  const nextNodeIds = new Set(finalRenderedNodesData.map(node => node.id));
  for (const [nodeId, el] of timelineNodeElById.entries()) {
    if (nextNodeIds.has(nodeId)) continue;
    if (el.classList.contains("timeline-node-exiting")) continue;
    el.classList.add("timeline-node-exiting");
    window.setTimeout(() => {
      if (el.parentNode) el.remove();
      timelineNodeElById.delete(nodeId);
    }, prefersReducedMotion() ? 0 : 180);
  }
  timelineRenderedNodeIds = new Set(finalRenderedNodesData.map(node => node.id));
  timelineRenderedEdgeKeys = new Set(renderedEdgesData.map(edge => timelineEdgeKey(edge)));
  updateTimelineNodeZoomDetail(detail, { force: true });
  if (!prefersReducedMotion() && (enteringNodes.length || enteringEdges.length)) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        for (const el of enteringNodes) el.classList.remove("timeline-node-entering");
        for (const el of enteringEdges) el.classList.remove("timeline-edge-entering");
      });
    });
  } else {
    for (const el of enteringNodes) el.classList.remove("timeline-node-entering");
    for (const el of enteringEdges) el.classList.remove("timeline-edge-entering");
  }

  const totalNodes = data.stats?.total_nodes || data.stats?.nodes || nodesData.length;
  setStatus(`${finalRenderedNodesData.length} visible of ${totalNodes} timeline genres`);

  if (!options.preserveView) {
    const streamBounds = data.stats?.bounds;
    const bounds = streamBounds
      ? {
          minX: Number(streamBounds.min_x),
          maxX: Number(streamBounds.max_x),
          minY: Number(streamBounds.min_y),
          maxY: Number(streamBounds.max_y),
        }
      : nodesData.reduce((acc, node) => {
          const x = node.x || 0;
          const y = node.y || 0;
          acc.minX = Math.min(acc.minX, x);
          acc.maxX = Math.max(acc.maxX, x);
          acc.minY = Math.min(acc.minY, y);
          acc.maxY = Math.max(acc.maxY, y);
          return acc;
        }, { minX: Number.POSITIVE_INFINITY, maxX: Number.NEGATIVE_INFINITY, minY: Number.POSITIVE_INFINITY, maxY: Number.NEGATIVE_INFINITY });
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    viewScale = MIN_VIEW_SCALE;
    viewTx = focusX() - centerX * viewScale;
    viewTy = focusY() - centerY * viewScale;
  }
  writeWorldTransform();
  setGraphStill(true);
}

function timelineNodeFromPayload(node) {
  return {
    key: `timeline-${node.id}`,
    genreId: node.id,
    label: node.label || labelFromTitle(node.wikipedia_title),
    title: normalizeLabel(node.wikipedia_title),
    qid: null,
    color: node.similarity_color || null,
    colorConfidence: null,
    hasPlaylist: typeof node.has_playlist === "boolean" ? node.has_playlist : node.hasPlaylist,
    summary: null,
    wikipedia_url: null,
    aliases: [],
    origins: [],
    instruments: [],
    categories: [],
    monthlyViews: node.monthly_views_p30,
    ...textMetricsFromPayload(node),
    x: node.x,
    y: node.y,
    homeX: node.x,
    homeY: node.y,
    isUnresolved: false,
  };
}

function timelinePillWidth(node, label) {
  return pillWidthFromPretext(node, label, 15, 500, 14, 1, 230);
}

function buildTimelineNodeEl(node, isEntering = false) {
  const label = displayLabel(node.label || node.wikipedia_title);
  const year = timelineYearLabel(node);
  const widthEstimate = timelinePillWidth(node, label);
  const isSelected = node.id === timelineSelectedGenreId;
  const detail = detailCache.get(node.id);
    const color = detail?.color || node.similarity_color || (isSelected ? "var(--accent)" : null);
  const classes = [
    "node",
    "timeline-node",
    node.is_inferred_year ? "timeline-node-inferred" : "timeline-node-dated",
  ];
  if (isSelected) classes.push("node-active-leaf", "timeline-node-selected");
  if (color) classes.push("has-color");
  if (isEntering) classes.push("timeline-node-entering");
  if (detailKeyForTimelineNodeId(node.id) === detailCardIndicatorKey()) classes.push("timeline-node-detail-preview");
  if (timelineSelectedFocusActive()) {
    if (timelineVisibility.focusNodeIds.has(node.id)) classes.push("timeline-node-focus");
    else classes.push("timeline-node-unfocused");
  }
  const group = svgEl("g", {
    class: classes.join(" "),
    transform: `translate(${node.renderX ?? node.x}, ${node.renderY ?? node.y})`,
    tabindex: "0",
    role: "button",
    "aria-label": `${node.wikipedia_title}, ${year}`,
  });
  group.dataset.genreId = node.id;
  if (Number.isFinite(node.selected_distance)) group.dataset.selectedDistance = String(node.selected_distance);
  const nodeScale = Number.isFinite(node.node_scale) ? Number(node.node_scale) : timelineNodeRenderScale(node.id);
  group.dataset.nodeScale = nodeScale.toFixed(3);
  if (Number.isFinite(node.selected_focus_score)) {
    const focusScore = Math.max(0, Math.min(1, Number(node.selected_focus_score) || 0));
    group.dataset.focusScale = focusScore.toFixed(3);
    group.dataset.selectedConnections = String(node.selected_connection_count || 0);
  }
  if (color) group.style.setProperty("--genre-color", color);

  const inner = svgEl("g", { class: "node-inner timeline-node-inner" });
  group.appendChild(inner);
  inner.appendChild(svgEl("rect", {
    x: -widthEstimate / 2,
    y: -18,
    width: widthEstimate,
    height: 36,
    rx: 18,
    ry: 18,
    class: "node-pill timeline-node-pill",
  }));
  const text = svgEl("text", {
    y: TIMELINE_LABEL_Y,
    class: "node-label timeline-node-label",
    "dominant-baseline": "central",
    "text-anchor": "middle",
  });
  if (!isSelected && color) text.style.fill = color;
  text.textContent = label;
  inner.appendChild(text);
  inner.appendChild(svgEl("rect", {
    x: -widthEstimate / 2,
    y: -18,
    width: widthEstimate,
    height: 36,
    rx: 18,
    ry: 18,
    class: "node-hit-area timeline-node-hit-area",
  }));
  group.addEventListener("pointerenter", () => {
    if (!timelineNodeAllowsHoverDetail(group)) return;
    scheduleTimelineHoverCard(node);
  });
  group.addEventListener("pointerleave", () => {
    if (!timelineNodeAllowsHoverDetail(group)) return;
    cancelScheduledHoverCard(detailKeyForTimelineNodeId(node.id));
  });
  group.addEventListener("click", () => {
    void openTimelineNode(node);
  });
  group.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      void openTimelineNode(node);
    }
  });
  return group;
}

function timelineNodeAllowsHoverDetail(el) {
  if (!el) return false;
  return !(
    el.classList.contains("timeline-node-unfocused") ||
    el.classList.contains("timeline-node-hidden-detail") ||
    el.classList.contains("timeline-node-entering") ||
    el.classList.contains("timeline-node-exiting")
  );
}

function timelineNodeClassName(node, color, isEntering = false) {
  const classes = [
    "node",
    "timeline-node",
    node.is_inferred_year ? "timeline-node-inferred" : "timeline-node-dated",
  ];
  const isSelected = node.id === timelineSelectedGenreId;
  if (isSelected) classes.push("node-active-leaf", "timeline-node-selected");
  if (color) classes.push("has-color");
  if (isEntering) classes.push("timeline-node-entering");
  if (detailKeyForTimelineNodeId(node.id) === detailCardIndicatorKey()) classes.push("timeline-node-detail-preview");
  if (timelineSelectedFocusActive()) {
    if (timelineVisibility.focusNodeIds.has(node.id)) classes.push("timeline-node-focus");
    else classes.push("timeline-node-unfocused");
  }
  return classes.join(" ");
}

async function showTimelineHoverCard(node) {
  if (!timelineMode || !node?.id) return;
  if (node.id !== timelineSelectedGenreId || !timelineDetailCardOpen) return;
  const token = ++hoverCardToken;
  setDetailCardNodeKey(detailKeyForTimelineNodeId(node.id));
  try {
    const detail = await getGenreDetail(node.id);
    if (token !== hoverCardToken || !timelineMode) return;
    setDetailCardNodeKey(detailKeyForTimelineNodeId(node.id));
    updateCard(detail, { hoverSwap: true });
  } catch (err) {
    console.error("[wiki-genres] timeline hover detail failed", err);
    if (token === hoverCardToken && timelineMode) {
      updateCard(timelineNodeFromPayload(node), { hoverSwap: true });
    }
  }
}

async function openTimelineNode(node) {
  if (!node?.id) return;
  if (timelineSelectedGenreId === node.id) {
    timelineSelectedGenreId = null;
    timelineDetailCardOpen = false;
    setDetailCardNodeKey(null);
    hoverCardToken++;
    setStatus("");
    updateDetailCardVisibility();
    updateUrlState({ push: true });
    if (timelineData) renderTimeline(timelineData, { preserveView: true, noFade: true });
    void loadTimelineForSelection({
      selectedGenreId: null,
      force: true,
      preserveView: true,
      requestedRank: Math.max(timelineLoadedRank, timelineDesiredServerRankForScale()),
      quiet: true,
      noFade: true,
    });
    return;
  }
  allowDetailCardForManualSelection();
  timelineSelectedGenreId = node.id;
  timelineDetailCardOpen = true;
  updateDetailCardVisibility();
  setStatus(`Opening ${node.label || node.wikipedia_title} timeline...`);
  updateUrlState({ push: true });
  // Avoid flashing the whole canvas on click; selection swaps should not fade.
  if (timelineData) renderTimeline(timelineData, { preserveView: true, noFade: true });
  const timelineLoad = loadTimelineForSelection({
    force: true,
    preserveView: true,
    requestedRank: Math.max(timelineLoadedRank, timelineDesiredServerRankForScale()),
    quiet: true,
  });
  const detailLoad = getGenreDetail(node.id);
  try {
    await timelineLoad;
    if (!timelineMode || timelineSelectedGenreId !== node.id) return;
    panToSelectedCenterTarget({ holdDetailCard: true });
    const detail = await detailLoad;
    if (!timelineMode || timelineSelectedGenreId !== node.id) return;
    setDetailCardNodeKey(detailKeyForTimelineNodeId(node.id));
    updateCard(detail);
    updateYoutubeCardForSelection(detail);
    void updateMapCard(detail);
    if (timelineData) renderTimeline(timelineData, { preserveView: true, noFade: true });
    panToSelectedCenterTarget({ holdDetailCard: true });
  } catch (err) {
    console.error("[wiki-genres] timeline node open failed", err);
    setStatus("Could not open that timeline node.");
  }
}

function renderSearchResults(hits, query) {
  if (!searchResults || !searchInput) return;
  searchResults.innerHTML = "";

  if (!query.trim()) {
    setSearchExpanded(false);
    return;
  }

  if (!hits.length) {
    const empty = document.createElement("div");
    empty.className = "search-empty";
    empty.textContent = searchBusy ? "Searching..." : "No traversable matches";
    searchResults.appendChild(empty);
    setSearchExpanded(true);
    return;
  }

  hits.forEach((hit, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result";
    button.setAttribute("role", "option");
    button.dataset.index = String(index);

    const title = document.createElement("span");
    title.className = "search-result-title";
    title.textContent = labelFromTitle(hit.wikipedia_title);

    const path = document.createElement("span");
    path.className = "search-result-path";
    path.textContent = pathPreview(hit);

    button.append(title, path);
    button.addEventListener("click", () => {
      void openTraversableSearchHit(hit);
    });
    searchResults.appendChild(button);
  });

  setSearchExpanded(true);
}

function scheduleTraversableSearch() {
  if (!searchInput) return;
  const query = searchInput.value.trim();
  searchToken += 1;
  const token = searchToken;
  if (searchTimer) clearTimeout(searchTimer);

  if (query.length < 2) {
    searchBusy = false;
    clearSearchResults();
    return;
  }

  searchBusy = true;
  renderSearchResults([], query);
  searchTimer = setTimeout(async () => {
    try {
      const data = await searchTraversableGenres(query);
      if (token !== searchToken) return;
      searchBusy = false;
      renderSearchResults(data.hits || [], query);
    } catch (err) {
      if (token !== searchToken) return;
      searchBusy = false;
      console.error("[wiki-genres] search failed", err);
      if (searchResults) {
        searchResults.innerHTML = "";
        const empty = document.createElement("div");
        empty.className = "search-empty";
        empty.textContent = "Search unavailable";
        searchResults.appendChild(empty);
        setSearchExpanded(true);
      }
    }
  }, SEARCH_DEBOUNCE_MS);
}

async function openRandomTraversableGenre() {
  if (!randomGenreButton) return;
  searchToken += 1;
  if (searchTimer) clearTimeout(searchTimer);
  searchBusy = false;
  clearSearchResults();
  randomGenreButton.disabled = true;
  setStatus("Opening random genre...");

  try {
    const hit = await randomTraversableGenre();
    await openTraversableSearchHit(hit);
  } catch (err) {
    console.error("[wiki-genres] random genre failed", err);
    setStatus("Could not open a random genre");
  } finally {
    randomGenreButton.disabled = false;
  }
}

async function ensureGraphSelectionByGenreId(genreId) {
  if (!genreId) return;
  if (cloudMode) return;
  if (timelineMode) return;

  const existing = findVisibleGenreNode(genreId);
  if (existing) {
    // Avoid forcing a camera move on mode swap.
    try {
      await focusOn(existing.key, { noFollow: true });
    } catch (err) {
      console.error("[wiki-genres] focus existing failed", err);
    }
    return;
  }

  // Use the exact indexed Music path. Search is intentionally avoided here:
  // persistence across modes must not select a nearby-but-wrong result.
  try {
    setBusy(true);
    setStatus("Restoring selection...");
    const rows = await getReachableParents(genreId).catch(() => []);
    const best = rows
      .filter(row => Array.isArray(row.path_genre_ids) && row.path_genre_ids.includes(genreId))
      .sort((a, b) => (
        (a.depth_from_music ?? 99) - (b.depth_from_music ?? 99) ||
        (b.genre_monthly_views_p30 ?? 0) - (a.genre_monthly_views_p30 ?? 0)
      ))[0];
    if (!best) return;
    const pathIds = best.path_genre_ids.filter(Boolean);
    if (!pathIds.length || pathIds[pathIds.length - 1] !== genreId) return;
    const hit = {
      id: genreId,
      wikipedia_title: best.path_titles?.[best.path_titles.length - 1] || "",
      path_genre_ids: pathIds,
      path_titles: best.path_titles || [],
    };
    await openTraversableSearchHit(hit);
  } catch (err) {
    console.error("[wiki-genres] restore selection failed", err);
  } finally {
    setBusy(false);
    setStatus("");
  }
}

async function ensurePathChild(parent, wantedId) {
  if (!parent || !wantedId) return null;
  await expand(parent.key);
  let child = [...nodes.values()].find(n => n.parentKey === parent.key && n.genreId === wantedId);
  if (child) return child;

  const detail = await getGenreDetail(wantedId).catch(() => null);
  if (!detail) return null;
  child = createRegionalNode(parent, {
    genre_id: detail.genreId,
    wikipedia_title: detail.title,
    monthly_views_p30: detail.monthlyViews,
    similarity_color: detail.color,
    color_confidence: detail.colorConfidence,
  });
  if (child) await hydrateNodeDetail(child);
  return child;
}

async function openTraversableSearchHit(hit) {
  if (timelineMode) {
    const genreId = hit?.id || hit?.genre_id || hit?.path_genre_ids?.at?.(-1);
    if (!genreId) return;
    searchToken += 1;
    if (searchTimer) clearTimeout(searchTimer);
    clearSearchResults();
    if (searchInput) searchInput.blur();
    await openTimelineNode({
      id: genreId,
      label: labelFromTitle(hit?.wikipedia_title || hit?.title || hit?.label || ""),
      wikipedia_title: hit?.wikipedia_title || hit?.title || hit?.label || "",
    });
    return;
  }
  if (cloudMode) {
    const genreId = hit?.id || hit?.genre_id || hit?.path_genre_ids?.at?.(-1);
    if (!genreId) return;
    searchToken += 1;
    if (searchTimer) clearTimeout(searchTimer);
    clearSearchResults();
    if (searchInput) searchInput.blur();
    await openCloudGenre(genreId);
    return;
  }
  const ids = hit?.path_genre_ids || [];
  if (!ids.length) return;

  const openToken = ++focusToken;
  searchToken += 1;
  if (searchTimer) clearTimeout(searchTimer);
  clearSearchResults();
  if (searchInput) searchInput.blur();
  setBusy(true);
  setStatus("Opening search path...");

  try {
    activeLeafKey = null;
    for (const item of nodes.values()) item.isActiveLeaf = false;

    let parent = nodes.get(ROOT_KEY);
    currentKey = ROOT_KEY;
    pruneToActivePath({ animate: true });
    recomputeLayout();
    fullRender();
    rebuildSim();

    let target = null;
    for (let i = 0; i < ids.length; i++) {
      const child = await ensurePathChild(parent, ids[i]);
      if (openToken !== focusToken) return;
      if (!child) break;
      if (i === ids.length - 1) {
        target = child;
        break;
      }
      currentKey = child.key;
      parent = child;
      recomputeLayout();
      fullRender();
      rebuildSim();
      bumpSim(0.22);
      await sleep(80);
    }

    if (!target) {
      setStatus("Could not open that path");
      return;
    }

    currentKey = target.parentKey || ROOT_KEY;
    await activateNode(target.key);
    panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
  } catch (err) {
    console.error("[wiki-genres] search path failed", err);
    setStatus("Could not open that path");
  } finally {
    setBusy(false);
  }
}

function refreshGraphAfterSelectionChange(node, { push = true, follow = true } = {}) {
  clearInactiveTraceDistanceAccounting();
  pruneToActivePath({ animate: true, preserveParentContext: true });
  recomputeLayout();
  if (nodeEls.size) {
    updateClasses();
    renderTick();
  } else {
    fullRender();
  }
  rebuildSim();
  bumpSim(0.36);
  setDetailCardNodeKey(node?.key || null);
  if (node) {
    updateCard(node);
    scheduleMapCardUpdate(node);
    updateFooter(node);
  }
  scheduleTimelineRefresh();
  updateUrlState({ push });
  if (follow) {
    panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
  }
}

function deselectGraphNode(nodeKey) {
  if (cloudMode || timelineMode) return false;
  const node = nodes.get(nodeKey);
  if (!node || node.key === ROOT_KEY) return false;

  if (activeLeafKey && node.key === activeLeafKey) {
    focusToken += 1;
    const parent = node.parentKey ? nodes.get(node.parentKey) : nodes.get(currentKey);
    activeLeafKey = null;
    node.isActiveLeaf = false;
    clearClearingState(node);
    setBusy(false);
    setStatus("");
    refreshGraphAfterSelectionChange(parent || nodes.get(currentKey) || nodes.get(ROOT_KEY));
    return true;
  }

  if (node.key === currentKey) {
    focusToken += 1;
    const parent = node.parentKey ? nodes.get(node.parentKey) : nodes.get(ROOT_KEY);
    activeLeafKey = null;
    for (const item of nodes.values()) item.isActiveLeaf = false;
    clearClearingState(node);
    currentKey = parent?.key || ROOT_KEY;
    setBusy(false);
    setStatus("");
    refreshGraphAfterSelectionChange(parent || nodes.get(ROOT_KEY));
    return true;
  }

  return false;
}

async function activateNode(nodeKey) {
  const node = nodes.get(nodeKey);
  if (!node) return;
  if (Boolean(node.isUnresolved)) {
    setStatus(`${node.label} is not yet in the graph`);
    return;
  }
  if (deselectGraphNode(nodeKey)) return;
  allowDetailCardForManualSelection();

  if (node.key !== currentKey && node.parentKey === currentKey) {
    if (node.childCount === 0) {
      await focusLeafNode(nodeKey);
      return;
    }

    if (node.childCount === null) {
      const token = ++focusToken;
      setBusy(true);
      setStatus("Checking child genres...");
      try {
        const children = await getChildren(node);
        if (token !== focusToken) return;
        node.childCount = children.length;
        if (children.length === 0) {
          await focusLeafNode(nodeKey, { keepToken: true });
          return;
        }
        await focusOn(nodeKey, { preloadedChildren: children });
        return;
      } catch (err) {
        console.error("[wiki-genres] child check failed", err);
      } finally {
        if (token === focusToken) setBusy(false);
      }
    }
  }

  await focusOn(nodeKey);
}

async function focusLeafNode(nodeKey, options = {}) {
  const leaf = nodes.get(nodeKey);
  const parent = leaf?.parentKey ? nodes.get(leaf.parentKey) : null;
  if (!leaf || !parent) return;
  if (Boolean(leaf.isUnresolved)) {
    setStatus(`${leaf.label} is not yet in the graph`);
    return;
  }
  allowDetailCardForManualSelection();

  const token = options.keepToken ? focusToken : ++focusToken;
  activeLeafKey = leaf.key;
  leaf.isActiveLeaf = true;
  leaf.childCount = 0;
  setBusy(true);
  setStatus("Loading leaf relationships...");

  try {
    pruneToActivePath({ animate: true });
    const traceRowsPromise = reachableParentTraceRows(leaf);
    const detailPromise = hydrateNodeDetail(leaf);
    const traceRows = await traceRowsPromise;
    if (token !== focusToken || activeLeafKey !== leaf.key) return;
    leaf.parentRelationshipRows = reachableParentsCache.get(leaf.genreId) || traceRows;
    precomputeSelectedTraceDistance(leaf, traceRows);
    leaf.edgeLengthAnim = null;
    recomputeLayout();
    if (nodeEls.size) {
      updateClasses();
      renderTick();
    } else {
      fullRender();
    }
    rebuildSim();
    bumpSim(0.48);

    const hydrated = await detailPromise;
    if (token !== focusToken || activeLeafKey !== leaf.key) return;
    setDetailCardNodeKey(hydrated.key);
    updateCard(hydrated);
    updateYoutubeCardForSelection(hydrated);
    scheduleMapCardUpdate(hydrated);
    scheduleTimelineRefresh();
    updateFooter(parent);
    updateUrlState({ push: true });

    await revealReachableParentTraces(hydrated, token, traceRows);
    if (token === focusToken && !options.noFollow) {
      panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
    }
  } finally {
    if (token === focusToken) {
      setBusy(false);
      setStatus("");
    }
  }
}

async function focusOn(nodeKey, options = {}) {
  const node = nodes.get(nodeKey);
  if (!node) return;
  if (Boolean(node.isUnresolved)) {
    setStatus(`${node.label} is not yet in the graph`);
    return;
  }
  allowDetailCardForManualSelection();

  const token = ++focusToken;
  activeLeafKey = null;
  for (const item of nodes.values()) item.isActiveLeaf = false;
  setBusy(true);
  setStatus("Loading graph data...");

  try {
    currentKey = nodeKey;
    pruneToActivePath({ animate: true, preserveParentContext: true });
    let focusedNode = nodes.get(nodeKey);
    const traceRowsPromise = reachableParentTraceRows(focusedNode);
    const childrenPromise = options.preloadedChildren
      ? Promise.resolve(options.preloadedChildren)
      : getChildren(focusedNode);
    const traceRows = await traceRowsPromise;
    if (token !== focusToken) return;
    focusedNode.parentRelationshipRows = reachableParentsCache.get(focusedNode.genreId) || traceRows;
    precomputeSelectedTraceDistance(focusedNode, traceRows);
    recomputeLayout();
    if (nodeEls.size) {
      updateClasses();
      renderTick();
    } else {
      fullRender();
    }
    rebuildSim();
    bumpSim(0.45);
    setDetailCardNodeKey(focusedNode?.key || null);
    updateCard(focusedNode);
    updateYoutubeCardForSelection(focusedNode);
    scheduleMapCardUpdate(focusedNode);
    scheduleTimelineRefresh();
    updateUrlState({ push: true });
    if (!options.noFollow) startFollow();

    const children = await childrenPromise;
    if (token !== focusToken) return;
    const isLeafSelection = children.length === 0;
    focusedNode.childCount = children.length;
    focusedNode.isClearingCluster = !isLeafSelection && shouldUseClearingCluster(focusedNode, children.length);
    pruneToActivePath({ animate: true, preserveParentContext: isLeafSelection });
    focusedNode = nodes.get(nodeKey);
    if (focusedNode) {
      focusedNode.isClearingCluster = !isLeafSelection && shouldUseClearingCluster(focusedNode, children.length);
    }
    await hydrateNodeDetail(focusedNode);
    if (token !== focusToken) return;

    if (!isLeafSelection) {
      captureClearingSiblingCaps(focusedNode);
    }
    recomputeLayout();
    if (nodeEls.size) {
      updateClasses();
      renderTick();
    } else {
      fullRender();
    }
    rebuildSim();
    bumpSim(children.length ? 0.62 : 0.35);
    setDetailCardNodeKey(focusedNode?.key || null);
    updateCard(focusedNode);
    updateYoutubeCardForSelection(focusedNode);
    scheduleMapCardUpdate(focusedNode);
    scheduleTimelineRefresh();
    updateFooter(focusedNode);
    updateUrl();

    if (!focusedNode.childCount && !options.noFollow) {
      followMode = false;
    }

    let traceRevealStarted = false;
    const startParentTraceReveal = () => {
      if (traceRevealStarted || token !== focusToken || !focusedNode?.genreId) return;
      traceRevealStarted = true;
      window.setTimeout(() => {
        if (token !== focusToken || !nodes.has(focusedNode.key)) return;
        void revealReachableParentTraces(focusedNode, token, traceRows).catch(err => {
          console.error("[wiki-genres] parent trace failed", err);
        });
      }, PARENT_TRACE_AFTER_CHILD_REVEAL_MS);
    };

    if (children.length) {
      await waitForSelectedChildClearance(nodeKey, token);
      if (token !== focusToken) return;
      await expand(nodeKey, {
        children,
        stagger: true,
        prewarmMs: CHILD_PREWARM_MS,
        token,
        onRevealStart: startParentTraceReveal,
      });
      if (token !== focusToken) return;
      startParentTraceReveal();
      clearClearingState(focusedNode);
      recomputeLayout();
      updateClasses();
      updateFooter(focusedNode);
    } else {
      clearClearingState(focusedNode);
      startParentTraceReveal();
    }
    if (token === focusToken && !options.noFollow && !children.length) {
      panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
    }
  } catch (err) {
    console.error("[wiki-genres] focus failed", err);
    setStatus("Could not load this part of the graph");
    updateCard({
      ...node,
      summary: node.summary || "The API did not return graph data for this selection.",
    });
    updateYoutubeCardForSelection(node);
    scheduleMapCardUpdate(node);
  } finally {
    if (token === focusToken) setBusy(false);
  }
}

function detailCardIdentity(g) {
  return String(g?.genreId || g?.id || g?.title || g?.label || g?.key || "");
}

function renderCardContent(g, options = {}) {
  if (!options.preserveRelation) {
    const relationText = relationshipLine(g) || "Genre";
    cardRelation.textContent = relationText;
    cardRelation.style.display = "";
    cardRelation.toggleAttribute("aria-hidden", !relationText);
  }
  cardTitle.textContent = g.label || "";
  cardSummary.textContent = g.summary || "";

  const aliases = displayAliasesForCard(g);
  detailCard?.classList.toggle("card-aliases-empty", !aliases.length);
  if (aliases.length) {
    cardSynonyms.textContent = aliases.join(", ");
    cardSynonyms.hidden = false;
    cardSynonyms.style.display = "";
  } else {
    cardSynonyms.textContent = "";
    cardSynonyms.hidden = true;
    cardSynonyms.style.display = "none";
  }

  const metadata = metadataItems(g);
  cardMeta.innerHTML = "";
  if (metadata.length) {
    for (const item of metadata) {
      const chip = document.createElement("span");
      chip.className = `metadata-chip metadata-${item.kind}`;
      const icon = document.createElement("span");
      icon.className = "material-symbols-rounded metadata-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = metadataIcon(item.kind);
      const text = document.createElement("span");
      text.textContent = item.value;
      chip.append(icon, text);
      cardMeta.appendChild(chip);
    }
    cardMeta.style.display = "";
  } else {
    cardMeta.style.display = "none";
  }

  cardWikiLink.href =
    g.wikipedia_url ||
    `https://en.wikipedia.org/wiki/${encodeURIComponent(g.title || g.label || "")}`;
  updateTargetButtonVisibility();
}

function cancelDetailCardContentSwap() {
  window.clearTimeout(detailCardContentSwapTimer);
  window.clearTimeout(detailCardHeightResetTimer);
  window.clearTimeout(detailCardTransitionCleanupTimer);
  detailCardContentSwapTimer = 0;
  detailCardHeightResetTimer = 0;
  detailCardTransitionCleanupTimer = 0;
  detailCardContentSwapToken++;
  detailCard?.classList.remove("card-content-fading");
  detailCard?.classList.remove("detail-card-entering");
  detailCard?.classList.remove("detail-card-height-animating");
  detailCardSlot?.classList.remove("detail-card-swap-transitioning");
  detailCardTransitionClone?.remove();
  detailCardTransitionClone = null;
  if (detailCard) {
    detailCard.style.height = "";
    detailCard.style.minHeight = "";
  }
}

function commitCardContent(g, options, nextKey) {
  renderCardContent(g, options);
  detailCardRenderedKey = nextKey || detailCardRenderedKey;
  syncDetailNodeIndicators();
}

function shouldAnimateDetailCardHeight() {
  return Boolean(
    detailCard &&
    window.matchMedia("(max-width: 899px)").matches &&
    document.body.classList.contains("detail-card-visible") &&
    !document.body.classList.contains("mobile-cards-hidden")
  );
}

function measuredDetailCardAutoHeight() {
  if (!detailCard) return 0;
  const previousHeight = detailCard.style.height;
  detailCard.style.height = "auto";
  const height = Math.ceil(detailCard.getBoundingClientRect().height || 0);
  detailCard.style.height = previousHeight;
  return height;
}

function cleanupDetailCardTransition(token = detailCardContentSwapToken) {
  if (token !== detailCardContentSwapToken) return;
  window.clearTimeout(detailCardTransitionCleanupTimer);
  detailCardTransitionCleanupTimer = 0;
  detailCardTransitionClone?.remove();
  detailCardTransitionClone = null;
  detailCard?.classList.remove("detail-card-entering");
  detailCardSlot?.classList.remove("detail-card-swap-transitioning");
}

const DETAIL_CARD_SNAPSHOT_CLASSES = {
  "card-title": "detail-card-snapshot-title",
  "card-target-button": "detail-card-snapshot-target-button",
  "card-close-button": "detail-card-snapshot-close-button",
  "card-summary": "detail-card-snapshot-summary",
};

function sanitizeDetailCardTransitionClone(clone) {
  if (!clone) return;
  for (const el of clone.querySelectorAll("[id]")) {
    const snapshotClass = DETAIL_CARD_SNAPSHOT_CLASSES[el.id];
    if (snapshotClass) el.classList.add(snapshotClass);
    el.removeAttribute("id");
  }
  clone.querySelectorAll("button, a, input, textarea, select").forEach(el => {
    el.tabIndex = -1;
  });
}

function beginDetailCardTransition(token) {
  if (!detailCard || !detailCardSlot) return;
  window.clearTimeout(detailCardTransitionCleanupTimer);
  detailCardTransitionClone?.remove();
  detailCardTransitionClone = detailCard.cloneNode(true);
  detailCardTransitionClone.removeAttribute("id");
  detailCardTransitionClone.classList.add("detail-card-transition-clone");
  detailCardTransitionClone.dataset.detailCardKey = detailCardRenderedKey || "";
  detailCardTransitionClone.setAttribute("aria-hidden", "true");
  detailCardTransitionClone.inert = true;
  sanitizeDetailCardTransitionClone(detailCardTransitionClone);
  detailCardSlot.appendChild(detailCardTransitionClone);
  detailCardSlot.classList.add("detail-card-swap-transitioning");
  detailCard.classList.remove("detail-card-entering");
  detailCard.getBoundingClientRect();
  detailCard.classList.add("detail-card-entering");
  detailCardTransitionCleanupTimer = window.setTimeout(() => {
    cleanupDetailCardTransition(token);
  }, 220);
}

function swapCardContent(g, options, nextKey, shouldFade) {
  if (!shouldFade || prefersReducedMotion() || !document.body.classList.contains("detail-card-visible")) {
    cancelDetailCardContentSwap();
    commitCardContent(g, options, nextKey);
    return;
  }

  const token = ++detailCardContentSwapToken;
  window.clearTimeout(detailCardContentSwapTimer);
  window.clearTimeout(detailCardHeightResetTimer);
  detailCardContentSwapTimer = 0;
  detailCardHeightResetTimer = 0;

  const previousHeight = detailCard?.getBoundingClientRect().height || 0;
  const animateHeight = shouldAnimateDetailCardHeight() && previousHeight > 0;
  if (animateHeight) {
    detailCard.classList.add("detail-card-height-animating");
    detailCard.style.minHeight = "";
    detailCard.style.height = `${Math.ceil(previousHeight)}px`;
    detailCard.getBoundingClientRect();
  }
  beginDetailCardTransition(token);
  commitCardContent(g, options, nextKey);

  if (detailCard && animateHeight) {
    const nextHeight = measuredDetailCardAutoHeight();
    detailCard.style.height = `${Math.ceil(previousHeight)}px`;
    requestAnimationFrame(() => {
      if (token !== detailCardContentSwapToken) return;
      detailCard.style.height = `${Math.max(1, nextHeight)}px`;
    });
    detailCardHeightResetTimer = window.setTimeout(() => {
      if (token !== detailCardContentSwapToken) return;
      detailCardHeightResetTimer = 0;
      detailCard.classList.remove("detail-card-height-animating");
      detailCard.style.height = "";
    }, DETAIL_CARD_HEIGHT_ANIMATION_MS + 40);
  } else if (detailCard && previousHeight > 0) {
    detailCard.style.minHeight = `${Math.ceil(previousHeight)}px`;
    detailCardHeightResetTimer = window.setTimeout(() => {
      if (token !== detailCardContentSwapToken) return;
      detailCardHeightResetTimer = 0;
      detailCard.style.minHeight = "";
    }, DETAIL_CARD_HEIGHT_STABILIZE_MS);
  }
  window.requestAnimationFrame(() => {
    if (token !== detailCardContentSwapToken) return;
    detailCard?.classList.remove("card-content-fading");
  });
}

function updateCard(g, options = {}) {
  if (!g) return;
  if (!options.preserveRelation && g.key) {
    setDetailCardNodeKey(g.key);
  }
  const nextKey = detailCardIdentity(g);
  const isContentSwap = Boolean(detailCardRenderedKey && nextKey && nextKey !== detailCardRenderedKey);
  setDetailCardHoverSwapActive(Boolean(
    options.hoverSwap &&
    document.body.classList.contains("ui-manual-moving") &&
    (isContentSwap || detailCardHoverSwapActive)
  ));
  swapCardContent(g, options, nextKey, isContentSwap);
  if (options.idleReturn) clearDetailCardIdleTimer();
  else scheduleDetailCardIdleReturn(nextKey);
}

function updateFooter(node) {
  const children = childrenCache.get(node.key === ROOT_KEY ? ROOT_KEY : node.genreId) || [];
  footerDepth.textContent = node.key === ROOT_KEY ? "Root" : `Depth ${node.depth}`;
  if (node.childCount === 0) {
    setStatus(`${node.label} has no child genres in this graph`);
  } else if (children.length) {
    setStatus(relationSummary(children));
  } else {
    setStatus("");
  }
}

async function restorePathFromUrl(rawPath = null) {
  rawPath = rawPath ?? new URL(window.location.href).searchParams.get("path");
  if (!rawPath) return false;
  const ids = rawPath.split(",").map(v => v.trim()).filter(Boolean);
  if (!ids.length) return false;

  restoringUrl = true;
  try {
    let node = nodes.get(ROOT_KEY);
    for (const wantedId of ids) {
      await expand(node.key);
      let child = [...nodes.values()].find(n => n.parentKey === node.key && n.genreId === wantedId);
      if (!child) {
        const detail = await getGenreDetail(wantedId).catch(() => null);
        if (!detail) break;
        child = createRegionalNode(node, {
          genre_id: detail.genreId,
          wikipedia_title: detail.title,
          monthly_views_p30: detail.monthlyViews,
        });
      }
      if (!child) break;
      await hydrateNodeDetail(child);
      currentKey = child.key;
      node = child;
    }

    const restoredNode = nodes.get(currentKey);
    let traceRows = [];
    if (restoredNode && restoredNode.key !== ROOT_KEY) {
      traceRows = await reachableParentTraceRows(restoredNode);
      precomputeSelectedTraceDistance(restoredNode, traceRows);
      const children = await getChildren(restoredNode);
      restoredNode.childCount = children.length;
      if (children.length && !restoredNode.isExpanded) {
        await expand(restoredNode.key, { children });
      }
    }

    pruneToActivePath();
    recomputeLayout();
    fullRender();
    rebuildSim();
    bumpSim(0.5);
    const currentNode = nodes.get(currentKey);
    setDetailCardNodeKey(currentNode?.key || null);
    updateCard(currentNode);
    updateYoutubeCardForSelection(currentNode);
    void updateMapCard(currentNode);
    updateFooter(currentNode);
    startFollow();
    panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
    const restoredKey = currentKey;
    void revealReachableParentTraces(nodes.get(currentKey), focusToken, traceRows).then(() => {
      if (!cloudMode && !timelineMode && currentKey === restoredKey) {
        startFollow();
        panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
      }
    }).catch(err => {
      console.error("[wiki-genres] parent trace failed", err);
    });
    return currentKey !== ROOT_KEY;
  } finally {
    restoringUrl = false;
  }
}

function renderRootState() {
  currentKey = ROOT_KEY;
  initializeGraphLayoutForRender();
  fullRender();
  rebuildSim();
  bumpSim(1.0);
  const root = nodes.get(ROOT_KEY);
  if (!root) return;
  setDetailCardNodeKey(root.key);
  updateCard(root);
  updateYoutubeCardForSelection(root);
  void updateMapCard(root);
  updateFooter(root);
  panToCurrent();
}

function initializeGraphLayoutForRender() {
  recomputeLayout();
  if (nodeEls.size) return;
  for (const node of nodes.values()) {
    node.x = node.homeX;
    node.y = node.homeY;
    node.vx = 0;
    node.vy = 0;
  }
}

function restoreGraphLayoutForModeExit() {
  recomputeLayout();
  for (const node of nodes.values()) {
    node.x = node.homeX;
    node.y = node.homeY;
    node.vx = 0;
    node.vy = 0;
  }
}

async function init() {
  try {
    focusToken += 1;
    activeLeafKey = null;
    setDetailCardNodeKey(null);
    if (panAnimTimer) {
      clearInterval(panAnimTimer);
      panAnimTimer = null;
    }
    stopPanInertia();
    setBusy(true);
    setStatus("Loading graph data...");
    const resolvedState = resolvedExplorerUrlState();
    const wantsTimeline = resolvedState.mode === "timeline";
    const wantsCloud = resolvedState.mode === "cloud";
    if (sim) sim.stop();
    nodes.clear();
    edges.length = 0;
    currentKey = ROOT_KEY;
    followMode = false;
    viewScale = defaultScale();
    placeRoot();
    setModeButtonState(cloudToggleButton, { icon: "mist", label: "Cloud", ariaLabel: "Open word cloud" });
    setModeButtonState(timelineToggleButton, { icon: "clockArrowDown", label: "Timeline", ariaLabel: "Open timeline map" });
    await expand(ROOT_KEY);
    let restored = false;
    if (!wantsTimeline && !wantsCloud) {
      try {
        restored = await restorePathFromUrl(resolvedState.rawPath);
      } catch (err) {
        console.error("[wiki-genres] path restore failed", err);
        setStatus("Could not restore the requested path");
      }
    }
    if (!wantsTimeline && !wantsCloud && !restored) {
      renderRootState();
    }
    window.__wikiGenresExplorer = {
      nodes,
      edges,
      detailCache,
      childrenCache,
      reachableParentsCache,
      layoutPressureDebug,
      activateNode,
      searchTraversableGenres,
      randomTraversableGenre,
      openTraversableSearchHit,
      async openSearchResult(query, exactLabel = null) {
        const data = await searchTraversableGenres(query);
        const hits = data?.hits || data?.results || [];
        const wanted = exactLabel ? String(exactLabel).trim().toLowerCase() : null;
        const hit = wanted
          ? hits.find(item =>
              String(item.label || item.title || item.wikipedia_title || "").trim().toLowerCase() === wanted
            )
          : hits[0];
        if (!hit) return null;
        await openTraversableSearchHit(hit);
        return hit;
      },
      findNodesByLabel: findDebugNodes,
      nodeSnapshot: debugNodeSnapshot,
      monitorNodeMotion,
      get currentKey() { return currentKey; },
      get activeLeafKey() { return activeLeafKey; },
    };
    recordAppHistory(window.location.href, { push: false });
    void applyModeFromUrl(resolvedState);
  } catch (err) {
    console.error("[wiki-genres] init failed", err);
    updateCard({
      label: "Music",
      summary: "The explorer could not load graph data from the API.",
      qid: null,
      color: null,
      aliases: [],
      origins: [],
      wikipedia_url: "https://en.wikipedia.org/wiki/Music",
    });
    updateYoutubeCardForSelection({ label: "Music", key: ROOT_KEY });
    footerDepth.textContent = "Offline";
    setStatus("API data unavailable");
  } finally {
    setBusy(false);
    if (window.__wikiGenresBootWatchdog) {
      window.clearTimeout(window.__wikiGenresBootWatchdog);
      window.__wikiGenresBootWatchdog = 0;
    }
    document.body.classList.remove("app-booting");
  }
}

async function applyModeFromUrl(resolvedState = resolvedExplorerUrlState()) {
  const wantsTimeline = resolvedState.mode === "timeline";
  const wantsCloud = resolvedState.mode === "cloud";
  const selectedTimeline = resolvedState.selectedTimeline;
  const cloudRoot = resolvedState.cloudRoot;
  const cloudRegion = resolvedState.cloudRegion;
  const selectedCloud = resolvedState.selectedCloud;

  if (wantsCloud) {
    if (!cloudMode) {
      historyNavigating = true;
      setCloudMode(true, { deferLoad: true });
      historyNavigating = false;
    }
    cloudRootGenreId = cloudRoot;
    cloudRegionId = cloudRegion;
    cloudSelectedGenreId = selectedCloud || cloudRoot || null;
    if (cloudSelectedGenreId && cloudSelectedGenreId !== ROOT_KEY) startCloudSelectedLabelFade(cloudSelectedGenreId);
    void loadCloudMode({ initial: true }).then(() => {
      if (!cloudMode) return;
      if (cloudSelectedGenreId) {
        void openCloudGenre(cloudSelectedGenreId, { forceOpen: true });
      } else {
        updateDetailCardVisibility();
        void updateMapCard(nodes.get(ROOT_KEY));
      }
    }).catch(err => {
      console.error("[wiki-genres] cloud mode failed", err);
      setStatus("Cloud unavailable.");
    });
  } else if (wantsTimeline) {
    if (!timelineMode) {
      historyNavigating = true;
      setTimelineMode(true);
      historyNavigating = false;
    }
    if (selectedTimeline) {
      timelineSelectedGenreId = selectedTimeline;
      timelineDetailCardOpen = true;
      updateDetailCardVisibility();
      const timelineLoad = loadTimelineForSelection({
        force: true,
        // No persisted timeline camera in the URL, so always open on a sane
        // default view (max zoomed out + centered) even when restoring selection.
        preserveView: false,
        selectedGenreId: selectedTimeline,
        requestedRank: Math.max(timelineLoadedRank, timelineDesiredServerRankForScale()),
        quiet: true,
      });
      void timelineLoad.then(() => {
        if (timelineMode && timelineSelectedGenreId === selectedTimeline) {
          panToSelectedCenterTarget({ holdDetailCard: true });
        }
      });
      void getGenreDetail(selectedTimeline).then(detail => {
        if (!timelineMode || timelineSelectedGenreId !== selectedTimeline) return;
        setDetailCardNodeKey(detailKeyForTimelineNodeId(selectedTimeline));
        updateCard(detail);
        updateYoutubeCardForSelection(detail);
        void updateMapCard(detail);
        if (timelineData) renderTimeline(timelineData, { preserveView: true, noFade: true });
        panToSelectedCenterTarget({ holdDetailCard: true });
      }).catch(() => {});
    }
  } else if (timelineMode) {
    historyNavigating = true;
    setTimelineMode(false);
    historyNavigating = false;
  } else if (cloudMode) {
    historyNavigating = true;
    setCloudMode(false);
    historyNavigating = false;
  }

  // Ensure a sane camera even when no path was restored.
  if (!wantsTimeline && !wantsCloud && !timelineMode && !cloudMode) {
    panToSelectedCenterTarget({ normalizeZoom: true });
  }
}

window.addEventListener("resize", () => {
  resizeCloudCanvas();
  refitMapAutoView({ animate: false });
  if (cloudMode) {
    cloudRenderedWindowSignature = "";
    updateCloudLodVisibility();
    syncYoutubeVolumePanelPosition();
    return;
  }
  recomputeLayout();
  fullRender();
  rebuildSim();
  panToCurrent();
  syncYoutubeVolumePanelPosition();
  if (mapListMode) {
    updateMapListCardHeight(mapListViewState?.totalHeight || 0);
    renderVisibleMapListRows();
  }
  fitMapLabelMeta();
});

footerZoom?.addEventListener("pointerdown", event => {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  footerZoomDragging = true;
  footerZoom.classList.add("zoom-progress-active");
  footerZoom.setPointerCapture?.(event.pointerId);
  beginManualMovementGesture(event.clientX, event.clientY);
  setZoomFromFooterClientX(event.clientX);
});

footerZoom?.addEventListener("pointermove", event => {
  if (!footerZoomDragging) return;
  event.preventDefault();
  event.stopPropagation();
  markManualUiMovingAfterGestureThreshold(event.clientX, event.clientY, 360);
  setZoomFromFooterClientX(event.clientX);
});

function stopFooterZoomDrag(event = null) {
  if (!footerZoomDragging) return;
  if (event?.pointerId != null && event.type !== "lostpointercapture") {
    try {
      footerZoom?.releasePointerCapture?.(event.pointerId);
    } catch {}
  }
  footerZoomDragging = false;
  footerZoom?.classList.remove("zoom-progress-active");
  clearManualMovementGesture();
}

footerZoom?.addEventListener("pointerup", stopFooterZoomDrag);
footerZoom?.addEventListener("pointercancel", stopFooterZoomDrag);
footerZoom?.addEventListener("lostpointercapture", stopFooterZoomDrag);

footerZoom?.addEventListener("keydown", event => {
  const step = event.shiftKey ? 0.1 : 0.04;
  let nextProgress = null;
  if (event.key === "ArrowLeft" || event.key === "ArrowDown") nextProgress = currentZoomProgress() - step;
  else if (event.key === "ArrowRight" || event.key === "ArrowUp") nextProgress = currentZoomProgress() + step;
  else if (event.key === "Home") nextProgress = 0;
  else if (event.key === "End") nextProgress = 1;
  if (nextProgress == null) return;
  event.preventDefault();
  setZoomFromFooterProgress(nextProgress);
});

document.addEventListener("pointermove", event => {
  setActivePointerButtons(event.buttons);
  updateLastPointerPosition(event.clientX, event.clientY);
  if (activePointerButtons > 0 && manualMovementGesture) {
    markManualUiMovingAfterGestureThreshold(event.clientX, event.clientY);
  }
  uiHovering = isUiHoverTarget(event.target) || Boolean(liveUiHoverRoot());
  if (uiHovering) triggerUiHoverRestoreHold();
  if (manualUiDimPending) updateManualUiDimClass();
}, { passive: true });

document.addEventListener("pointerdown", event => {
  setActivePointerButtons(event.buttons || 1);
  if ((event.buttons || 1) > 0 && isManualGraphDragTarget(event.target)) {
    beginManualMovementGesture(event.clientX, event.clientY);
  }
  updateManualUiDimClass();
}, true);

function clearActivePointerButtons() {
  setActivePointerButtons(0);
  clearManualMovementGesture();
  updateManualUiDimClass();
}

window.addEventListener("pointerup", clearActivePointerButtons, true);
window.addEventListener("pointercancel", clearActivePointerButtons, true);
window.addEventListener("blur", clearActivePointerButtons);

document.addEventListener("pointerover", event => {
  if (!isUiHoverTarget(event.target)) return;
  uiHovering = true;
  triggerUiHoverRestoreHold();
  updateManualUiDimClass();
}, true);

document.addEventListener("pointerout", event => {
  if (!isUiHoverTarget(event.target)) return;
  if (isUiHoverTarget(event.relatedTarget)) return;
  uiHovering = false;
  triggerUiHoverRestoreHold();
  updateManualUiDimClass();
}, true);

window.addEventListener("popstate", () => {
  historyNavigating = true;
  void init().finally(() => {
    historyNavigating = false;
    void applyModeFromUrl();
  });
});

function setMobileCardsHidden(hidden) {
  document.body.classList.toggle("mobile-cards-hidden", hidden);
  updateDetailCardVisibility();
}

function setMobilePanel(panel) {
  const showRadio = panel === "radio";
  const isSmallMobile = window.matchMedia("(max-width: 599px)").matches;
  const isAlreadyActive = document.body.classList.contains("mobile-radio-active") === showRadio;
  if (isSmallMobile && isAlreadyActive && !document.body.classList.contains("mobile-cards-hidden")) {
    setMobileCardsHidden(true);
    return;
  }
  setMobileCardsHidden(false);
  document.body.classList.toggle("mobile-radio-active", showRadio);
  document.body.classList.remove("mobile-map-active");
  mobileDetailTab?.classList.toggle("active", !showRadio);
  mobileMapTab?.classList.toggle("active", showRadio);
  updateDetailCardVisibility();
}

function setMapExpanded(isExpanded) {
  mapCard?.classList.toggle("map-expanded", isExpanded);
  document.body.classList.toggle("map-expanded-active", Boolean(isExpanded));
  mapExpandButton?.setAttribute("aria-expanded", String(isExpanded));
  mapExpandButton?.setAttribute("aria-label", isExpanded ? "Collapse map" : "Expand map");
  if (mapExpandButton) mapExpandButton.dataset.tooltip = isExpanded ? "Collapse map" : "Expand map";
  mapGesturePointers.clear();
  mapGestureLast = null;
  mapGestureMoved = false;
  clearMapHoveredCountry();
  refitMapAutoView({ animate: true });
  requestAnimationFrame(() => refitMapAutoView({ animate: true }));
  syncMapCountryInteractivity();
  fitMapLabelMeta();
  window.setTimeout(fitMapLabelMeta, 560);
}

const TOOLTIP_SELECTOR = "[data-tooltip]";
let activeTooltipTarget = null;
let tooltipTimer = 0;
let tooltipEl = null;

function tooltipTargetFromEvent(event) {
  const target = event.target;
  if (!(target instanceof Element)) return null;
  const tooltipTarget = target.closest(TOOLTIP_SELECTOR);
  if (!tooltipTarget || !tooltipTarget.isConnected) return null;
  return tooltipTarget;
}

function tooltipTextForTarget(target) {
  return String(target?.getAttribute("data-tooltip") || "").trim();
}

function ensureTooltipEl() {
  if (tooltipEl) return tooltipEl;
  tooltipEl = document.createElement("div");
  tooltipEl.className = "ui-tooltip";
  tooltipEl.hidden = true;
  document.body.appendChild(tooltipEl);
  return tooltipEl;
}

function positionTooltip(target) {
  const el = ensureTooltipEl();
  const rect = target.getBoundingClientRect();
  const tooltipRect = el.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - tooltipRect.width / 2;
  left = clamp(left, 12, Math.max(12, vw() - tooltipRect.width - 12));
  let top = rect.bottom + UI_TOOLTIP_GAP_PX;
  if (top + tooltipRect.height > vh() - 12) {
    top = rect.top - tooltipRect.height - UI_TOOLTIP_GAP_PX;
  }
  top = clamp(top, 12, Math.max(12, vh() - tooltipRect.height - 12));
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

function showTooltip(target) {
  const text = tooltipTextForTarget(target);
  if (!text) return;
  const el = ensureTooltipEl();
  activeTooltipTarget = target;
  el.textContent = text;
  el.hidden = false;
  positionTooltip(target);
  requestAnimationFrame(() => {
    if (activeTooltipTarget === target) el.classList.add("is-visible");
  });
}

function scheduleTooltip(target, delay = UI_TOOLTIP_DELAY_MS) {
  const text = tooltipTextForTarget(target);
  if (!text) return;
  window.clearTimeout(tooltipTimer);
  activeTooltipTarget = target;
  tooltipTimer = window.setTimeout(() => {
    tooltipTimer = 0;
    if (activeTooltipTarget === target) showTooltip(target);
  }, delay);
}

function hideTooltip(target = null) {
  if (target && activeTooltipTarget && activeTooltipTarget !== target) return;
  window.clearTimeout(tooltipTimer);
  tooltipTimer = 0;
  activeTooltipTarget = null;
  if (!tooltipEl) return;
  tooltipEl.classList.remove("is-visible");
  tooltipEl.hidden = true;
}

document.addEventListener("pointerover", event => {
  const target = tooltipTargetFromEvent(event);
  if (!target) return;
  scheduleTooltip(target);
}, true);

document.addEventListener("pointerout", event => {
  const target = tooltipTargetFromEvent(event);
  if (!target) return;
  if (event.relatedTarget instanceof Element && target.contains(event.relatedTarget)) return;
  hideTooltip(target);
}, true);

document.addEventListener("focusin", event => {
  const target = tooltipTargetFromEvent(event);
  if (!target) return;
  scheduleTooltip(target, 220);
}, true);

document.addEventListener("focusout", event => {
  const target = tooltipTargetFromEvent(event);
  if (target) hideTooltip(target);
}, true);

document.addEventListener("click", () => hideTooltip(), true);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") hideTooltip();
}, true);

mobileDetailTab?.addEventListener("click", () => setMobilePanel("detail"));
mobileMapTab?.addEventListener("click", () => setMobilePanel("radio"));
youtubeCloseButton?.addEventListener("click", () => {
  if (window.matchMedia("(max-width: 599px)").matches) setMobileCardsHidden(true);
});
randomGenreButton?.addEventListener("click", () => {
  void openRandomTraversableGenre();
});
cloudToggleButton?.addEventListener("click", () => {
  setCloudMode(!cloudMode);
});
setYoutubeVolume(youtubeVolume, { persist: false });
youtubeVolumeControl?.addEventListener("pointerenter", openYoutubeVolumePanel);
youtubeVolumeControl?.addEventListener("pointerleave", closeYoutubeVolumePanel);
youtubeVolumeControl?.addEventListener("focusin", openYoutubeVolumePanel);
youtubeVolumeControl?.addEventListener("focusout", closeYoutubeVolumePanel);
youtubeVolumePanel?.addEventListener("pointerenter", openYoutubeVolumePanel);
youtubeVolumePanel?.addEventListener("pointerleave", closeYoutubeVolumePanel);
youtubeVolumePanel?.addEventListener("focusin", openYoutubeVolumePanel);
youtubeVolumePanel?.addEventListener("focusout", closeYoutubeVolumePanel);
youtubeVolumeInput?.addEventListener("input", event => {
  setYoutubeVolume(event.target?.value);
});
[
  navControls,
  mapCard,
  rightPanel,
  timelinePanel,
  mobilePanelTabs,
].filter(Boolean).forEach(root => {
  root.addEventListener("pointerenter", () => setUiHover(root, true));
  root.addEventListener("pointerleave", () => setUiHover(root, false));
});
youtubeCard?.addEventListener("pointerenter", () => {
  void showPlaybackDetailCard();
});
youtubeCard?.addEventListener("pointerleave", restoreDetailCardAfterPlaybackHover);
youtubeCard?.addEventListener("focusin", () => {
  void showPlaybackDetailCard();
});
youtubeCard?.addEventListener("focusout", event => {
  if (event.relatedTarget && youtubeCard.contains(event.relatedTarget)) return;
  restoreDetailCardAfterPlaybackHover();
});
youtubeGenreTitle?.addEventListener("click", () => {
  void selectPlaybackGenreInCurrentGraph();
});
youtubeGenreTitle?.addEventListener("keydown", event => {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  void selectPlaybackGenreInCurrentGraph();
});
detailRestoreButton?.addEventListener("click", restoreDetailCardFromButton);
youtubePauseButton?.addEventListener("click", () => {
  if (!youtubeItems.length) return;
  persistYoutubePlayback();
  const shouldPlay = youtubeUserPaused || youtubePaused || !youtubeIsPlaying || youtubeAutoplayBlocked;
  youtubeAutoplayBlocked = false;
  setYoutubeUserPaused(!shouldPlay);
  youtubePaused = !shouldPlay;
  youtubePlayRequested = shouldPlay;
  if (shouldPlay) {
    youtubeTrackLoading = true;
    youtubeTrackStartedAt = Date.now() - (youtubeLastKnownSeconds * 1000);
  }
  youtubeCommand(shouldPlay ? "playVideo" : "pauseVideo");
  if (shouldPlay) {
    startYoutubeStatePolling();
    scheduleYoutubeReadyTimeout(6500);
    void fadeYoutubeVolume(youtubeVolume, 1500);
  }
  updateYoutubeTrackText();
  updateYoutubeControls();
});
youtubeSongTitle?.addEventListener("click", openCurrentYoutubeTrack);
youtubeSongTitle?.addEventListener("keydown", event => {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  openCurrentYoutubeTrack();
});
youtubeSkipButton?.addEventListener("click", () => {
  if (youtubeItems.length < 2) return;
  loadNextYoutubeIndex();
});
youtubePinIndicator?.addEventListener("click", () => {
  setYoutubeMenuOpen(false);
  toggleYoutubePin();
});
youtubeMenuButton?.addEventListener("click", event => {
  event.stopPropagation();
  setYoutubeMenuOpen(youtubeContextMenu?.hidden !== false);
  updateYoutubePinUi();
});
youtubePinButton?.addEventListener("click", () => {
  setYoutubeMenuOpen(false);
  toggleYoutubePin();
});
youtubeOpenButton?.addEventListener("click", () => {
  setYoutubeMenuOpen(false);
  openCurrentYoutubeTrack();
});
youtubeFeedbackButton?.addEventListener("click", () => {
  setYoutubeMenuOpen(false);
  openFeedbackModal("youtube");
});
document.addEventListener("click", event => {
  if (!youtubeContextMenu || youtubeContextMenu.hidden) return;
  if (
    event.target instanceof Node &&
    (youtubeContextMenu.contains(event.target) || youtubeMenuButton?.contains(event.target))
  ) {
    return;
  }
  setYoutubeMenuOpen(false);
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  setYoutubeMenuOpen(false);
});
window.addEventListener("resize", () => {
  if (!youtubeContextMenu || youtubeContextMenu.hidden) return;
  setYoutubeMenuOpen(true);
});
mapList?.addEventListener("scroll", () => {
  if (!mapListMode || mapListScrollFrame) return;
  mapListScrollFrame = requestAnimationFrame(() => {
    mapListScrollFrame = 0;
    renderVisibleMapListRows();
  });
});
document.addEventListener("scroll", () => {
  if (!youtubeContextMenu || youtubeContextMenu.hidden) return;
  setYoutubeMenuOpen(true);
}, true);
youtubeSubmitButton?.addEventListener("click", () => {
  openFeedbackModal("music");
});
window.addEventListener("beforeunload", persistYoutubePlayback);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) persistYoutubePlayback();
});
detailFeedbackButton?.addEventListener("click", () => {
  openFeedbackModal("relationship");
});
feedbackCloseButton?.addEventListener("click", closeFeedbackModal);
feedbackForm?.addEventListener("submit", event => {
  event.preventDefault();
  void submitFeedback();
});
feedbackModal?.addEventListener("click", event => {
  if (event.target instanceof HTMLElement && event.target.hasAttribute("data-feedback-close")) {
    closeFeedbackModal();
  }
});
feedbackModal?.addEventListener("keydown", event => {
  if (event.key === "Escape") closeFeedbackModal();
});
searchInput?.addEventListener("input", scheduleTraversableSearch);
mapListSearchInput?.addEventListener("input", event => {
  mapListSearchQuery = event.target?.value || "";
  if (mapListMode) {
    void renderMapList(mapListViewState?.items || [], { rootMode: Boolean(mapListViewState?.rootMode) });
  }
});
mapListSearchInput?.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  event.stopPropagation();
  if (mapListSearchQuery) {
    mapListSearchInput.value = "";
    mapListSearchQuery = "";
  } else {
    mapListSearchOpen = false;
  }
  if (mapListMode) {
    void renderMapList(mapListViewState?.items || [], { rootMode: Boolean(mapListViewState?.rootMode) });
  }
});
mapListSearchButton?.addEventListener("click", event => {
  event.preventDefault();
  event.stopPropagation();
  if (!mapListMode || !mapListViewState?.searchAvailable) return;
  mapListSearchOpen = true;
  updateMapListSearchVisibility(Boolean(mapListViewState.rootMode), true);
  requestAnimationFrame(() => mapListSearchInput?.focus());
});
searchInput?.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    searchInput.value = "";
    searchToken += 1;
    if (searchTimer) clearTimeout(searchTimer);
    searchBusy = false;
    clearSearchResults();
    searchInput.blur();
    return;
  }
  if (event.key === "Enter") {
    const first = searchResults?.querySelector(".search-result");
    if (first instanceof HTMLButtonElement) {
      event.preventDefault();
      first.click();
    }
  }
});
document.addEventListener("pointerdown", event => {
  updateLastPointerPosition(event.clientX, event.clientY);
  if (!searchCard || searchCard.contains(event.target)) return;
  clearSearchResults();
});
regionMap?.addEventListener("pointermove", updateResolvedMapHover);
regionMap?.addEventListener("pointerleave", () => clearMapHoveredCountry());
mapHitLayer?.addEventListener("click", selectResolvedMapCountry);
regionMap?.addEventListener("click", selectResolvedMapCountry);
regionMap?.addEventListener("wheel", event => {
  if (!isMapExpanded()) return;
  event.preventDefault();
  event.stopPropagation();

  if (event.ctrlKey || event.metaKey) {
    zoomMapAt(event.clientX, event.clientY, Math.exp(-event.deltaY * 0.012));
    return;
  }

  const rect = regionMap.getBoundingClientRect();
  setMapViewManuallyAdjusted(true);
  mapViewBox = clampMapViewBox({
    ...mapViewBox,
    x: mapViewBox.x + (event.deltaX / Math.max(1, rect.width)) * mapViewBox.w,
    y: mapViewBox.y + (event.deltaY / Math.max(1, rect.height)) * mapViewBox.h,
  }, { softFocus: true });
  applyMapViewBox({ softFocus: true });
  scheduleMapPanSettle();
}, { passive: false });
regionMap?.addEventListener("pointerdown", event => {
  if (!isMapExpanded()) return;
  if (event.pointerType === "mouse" && event.button !== 0) return;
  if (event.target?.closest?.(".map-country-hit-active") && resolvedMapCountryAtPointer(event)) return;
  mapGesturePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  mapGestureLast = null;
  mapGestureMoved = false;
  regionMap.setPointerCapture?.(event.pointerId);
});
regionMap?.addEventListener("pointermove", event => {
  if (!isMapExpanded() || !mapGesturePointers.has(event.pointerId)) return;
  mapGesturePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  const points = [...mapGesturePointers.values()];

  if (points.length >= 2) {
    const [a, b] = points;
    const center = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const distance = Math.hypot(b.x - a.x, b.y - a.y);
    if (mapGestureLast?.type === "pinch") {
      const lastDistance = Math.max(1, mapGestureLast.distance);
      zoomMapAt(center.x, center.y, clamp(distance / lastDistance, 0.68, 1.48));
      panMapByClientDelta(center.x - mapGestureLast.center.x, center.y - mapGestureLast.center.y);
      mapGestureMoved = true;
    }
    mapGestureLast = { type: "pinch", center, distance };
    return;
  }

  const point = points[0];
  if (mapGestureLast?.type === "pan") {
    const dx = point.x - mapGestureLast.x;
    const dy = point.y - mapGestureLast.y;
    if (Math.hypot(dx, dy) > 0.4) {
      panMapByClientDelta(dx, dy);
      mapGestureMoved = true;
    }
  }
  mapGestureLast = { type: "pan", x: point.x, y: point.y };
});
function endMapPointer(event) {
  if (!mapGesturePointers.has(event.pointerId)) return;
  mapGesturePointers.delete(event.pointerId);
  mapGestureLast = null;
  if (!mapGesturePointers.size) settleMapViewBox();
}
regionMap?.addEventListener("pointerup", endMapPointer);
regionMap?.addEventListener("pointercancel", endMapPointer);
regionMap?.addEventListener("lostpointercapture", endMapPointer);
regionMap?.addEventListener("click", event => {
  if (!mapGestureMoved) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  mapGestureMoved = false;
}, true);
regionMap?.addEventListener("click", event => {
  if (isMapExpanded() || mapListMode) return;
  event.preventDefault();
  event.stopPropagation();
  setMapExpanded(true);
});
mapWorldButton?.addEventListener("click", event => {
  event.preventDefault();
  event.stopPropagation();
  if (!isMapExpanded()) {
    setMapExpanded(true);
    return;
  }
  mapDisplayedWorldOverride = true;
  const node = currentMapNodeForMode();
  void updateMapCard(node);
});
mapListButton?.addEventListener("click", event => {
  event.preventDefault();
  event.stopPropagation();
  setMapListMode(!mapListMode);
  const node = currentMapNodeForMode();
  void updateMapCard(node);
});
mapExpandButton?.addEventListener("click", event => {
  event.stopPropagation();
  setMapExpanded(!mapCard?.classList.contains("map-expanded"));
});
mapResetButton?.addEventListener("click", event => {
  event.stopPropagation();
  resetMapViewBox();
});
mapCard?.addEventListener("click", event => {
  if (isMapExpanded() || mapListMode) return;
  if (event.target?.closest?.("button, input")) return;
  setMapExpanded(true);
});
mapCard?.addEventListener("keydown", event => {
  if (event.key === "Escape") setMapExpanded(false);
});
mapParentLabel?.addEventListener("click", event => {
  event.preventDefault();
  event.stopPropagation();
  void returnToMapParent();
});
cardTargetButton?.addEventListener("click", () => {
  panToSelectedCenterTarget({ holdDetailCard: true, normalizeZoom: true });
});
function closeDetailFromButton(event = null) {
  if (window.matchMedia("(max-width: 899px)").matches) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    setMobileCardsHidden(true);
    return;
  }
  suppressDetailCardUntilSelection();
  if (timelineMode) timelineDetailCardOpen = false;
}

cardCloseButton?.addEventListener("pointerdown", event => {
  if (!window.matchMedia("(max-width: 899px)").matches) return;
  closeDetailFromButton(event);
});
cardCloseButton?.addEventListener("click", closeDetailFromButton);
timelineToggleButton?.addEventListener("click", () => {
  setTimelineMode(!timelineMode);
});
timelineCloseButton?.addEventListener("click", () => {
  setTimelineMode(false);
});
timelineConfidence?.addEventListener("change", () => {
  if (timelineMode) void loadTimelineForSelection({ force: true });
});
document.addEventListener("pointerdown", event => {
  if (!isMapExpanded()) return;
  if (mapCard?.contains(event.target)) return;
  setMapExpanded(false);
});

navBackButton?.addEventListener("click", () => {
  void navigateAppHistory(-1);
});
navForwardButton?.addEventListener("click", () => {
  void navigateAppHistory(1);
});

updateDetailCardVisibility();
updateAppHistoryButtons();
setMapListMode(false);
ensureYoutubeApi();

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
