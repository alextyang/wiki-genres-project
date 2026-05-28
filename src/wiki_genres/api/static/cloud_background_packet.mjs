#!/usr/bin/env node

const CLOUD_BACKGROUND_FIELD_WIDTH = 420;
const CLOUD_BACKGROUND_OPTIONS = {
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
  darkTargetLightness: 0.34,
  darkChromaScale: 0.44,
  darkChromaMax: 0.09,
  noiseScale: 0.006,
  warpStrength: 3.0,
  noiseSeed: 1337,
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
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

function addOklab(a, b, weight = 1) {
  a.L += b.L * weight;
  a.a += b.a * weight;
  a.b += b.b * weight;
  return a;
}

function scaleOklab(color, weight) {
  return { L: color.L * weight, a: color.a * weight, b: color.b * weight };
}

function cloudBackgroundNodeColor(node) {
  return node?.similarity_color || node?.color || null;
}

function cloudBoxWidth(node) {
  return Number(node.box_width ?? node.width ?? 0);
}

function cloudBoxHeight(node) {
  return Number(node.box_height ?? node.height ?? 0);
}

function cloudBackgroundNodes(nodes = []) {
  return nodes
    .filter(node => {
      if (!node || node.id === "__music_root__") return false;
      if (!Number.isFinite(Number(node.x)) || !Number.isFinite(Number(node.y))) return false;
      return Boolean(parseCssColor(cloudBackgroundNodeColor(node)));
    })
    .map(node => ({ ...node, x: Number(node.x), y: Number(node.y) }));
}

function cloudBackgroundBounds(data, nodes) {
  const raw = data?.stats?.bounds;
  let minX;
  let maxX;
  let minY;
  let maxY;
  if (raw) {
    minX = Number(raw.minX ?? raw.min_x);
    maxX = Number(raw.maxX ?? raw.max_x);
    minY = Number(raw.minY ?? raw.min_y);
    maxY = Number(raw.maxY ?? raw.max_y);
  } else if (nodes.length) {
    minX = Math.min(...nodes.map(node => node.x - cloudBoxWidth(node) / 2));
    maxX = Math.max(...nodes.map(node => node.x + cloudBoxWidth(node) / 2));
    minY = Math.min(...nodes.map(node => node.y - cloudBoxHeight(node) / 2));
    maxY = Math.max(...nodes.map(node => node.y + cloudBoxHeight(node) / 2));
  }
  if (![minX, maxX, minY, maxY].every(Number.isFinite) || minX === maxX || minY === maxY) return null;
  const pad = Math.max(maxX - minX, maxY - minY) * 0.08;
  return { minX: minX - pad, maxX: maxX + pad, minY: minY - pad, maxY: maxY + pad };
}

function cloudBackgroundSignature(nodes, bounds, width, height) {
  let hash = 2166136261;
  const write = value => {
    const text = String(value ?? "");
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
  };
  write("dark");
  write(width);
  write(height);
  write(Math.round(bounds.minX));
  write(Math.round(bounds.maxX));
  write(Math.round(bounds.minY));
  write(Math.round(bounds.maxY));
  write(nodes.length);
  for (const node of nodes) {
    write(node.id);
    write(Math.round(node.x * 10));
    write(Math.round(node.y * 10));
    write(cloudBackgroundNodeColor(node));
    write(Math.round(Number(node.monthly_views_p30 ?? node.popularity ?? 1)));
    write(Math.round(Number(node.color_confidence ?? node.colorConfidence ?? 1) * 1000));
  }
  return `${nodes.length}:${hash >>> 0}`;
}

function computeGraphSmoothedColors(nodes, options) {
  const rawColors = new Map();
  for (const node of nodes) {
    const rgb = parseCssColor(cloudBackgroundNodeColor(node));
    if (rgb) rawColors.set(node.id, rgbToOklab(rgb));
  }
  const nodeById = new Map(nodes.map(node => [String(node.id), node]));
  const result = new Map();
  for (const node of nodes) {
    const self = rawColors.get(node.id);
    if (!self) continue;
    const accum = scaleOklab(self, options.selfWeight);
    let total = options.selfWeight;
    const sortedNeighbors = (Array.isArray(node.neighbors) ? node.neighbors : [])
      .slice()
      .sort((a, b) => {
        const aScore = Number.isFinite(Number(a?.similarity)) ? Number(a.similarity) : -Number(a?.distance ?? Infinity);
        const bScore = Number.isFinite(Number(b?.similarity)) ? Number(b.similarity) : -Number(b?.distance ?? Infinity);
        return bScore - aScore;
      })
      .slice(0, options.graphNeighborLimit);
    for (const edge of sortedNeighbors) {
      const other = nodeById.get(String(edge?.id));
      const color = other ? rawColors.get(other.id) : null;
      if (!color) continue;
      let edgeWeight = 0;
      if (Number.isFinite(Number(edge.similarity))) {
        edgeWeight = options.graphWeight * clamp(Number(edge.similarity), 0, 1);
      } else if (Number.isFinite(Number(edge.distance))) {
        const distance = Number(edge.distance);
        edgeWeight = options.graphWeight * Math.exp(-(distance * distance) / 2);
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
      const bucket = buckets.get(`${bx}:${by}`);
      if (bucket) result.push(...bucket);
    }
  }
  return result;
}

function predominantContributorColor(contributors, limit, bucketCount) {
  const top = contributors
    .filter(contributor => contributor.weight > 0 && contributor.color)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, limit);
  if (!top.length) return { color: null, hueBucket: null, dominance: 0 };
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
  let winnerKey = null;
  let winner = null;
  for (const [key, entry] of buckets.entries()) {
    if (!winner || entry.weight > winner.weight) {
      winnerKey = key;
      winner = entry;
    }
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
    hueBucket: winnerKey,
    dominance: totalWeight > 0 ? (winner?.weight || top[0].weight) / totalWeight : 1,
  };
}

function computeSpatialField(nodes, smoothedColors, width, height, bounds, sigma, contributorLimit, hueBucketCount) {
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
      const predominant = predominantContributorColor(contributors, contributorLimit, hueBucketCount);
      cells[gy * width + gx] = {
        color: predominant.color,
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

function muteForBackground(oklab, options) {
  const oklch = oklabToOklch(oklab);
  oklch.L = oklch.L + (options.darkTargetLightness - oklch.L) * 0.45;
  oklch.C = Math.min(oklch.C * options.darkChromaScale, options.darkChromaMax);
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

function sampleSpatialField(field, x, y, options) {
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
    const weight = sample.weight
      * hueBucketBlendWeight(sample.cell.hueBucket, anchor.hueBucket, options.hueBucketCount)
      * (0.45 + (sample.cell.dominance || 0));
    addOklab(color, sample.cell.color, weight);
    colorWeight += weight;
  }
  return {
    color: colorWeight > 0 ? scaleOklab(color, 1 / colorWeight) : anchor?.color || null,
    density,
  };
}

function createPacket(payload) {
  const data = payload.data || {};
  const nodes = cloudBackgroundNodes(data.nodes || []);
  if (nodes.length < 3) return null;
  const bounds = cloudBackgroundBounds(data, nodes);
  if (!bounds) return null;
  const options = CLOUD_BACKGROUND_OPTIONS;
  const fieldWidth = Math.max(32, Math.round(CLOUD_BACKGROUND_FIELD_WIDTH));
  const viewportWidth = Number(payload.viewport_width);
  const viewportHeight = Number(payload.viewport_height);
  const fieldAspect = viewportWidth > 0 && viewportHeight > 0
    ? clamp(viewportHeight / viewportWidth, 0.2, 5)
    : 0.62;
  const fieldHeight = Math.max(24, Math.round(fieldWidth * fieldAspect));
  const worldWidth = Math.max(1, bounds.maxX - bounds.minX);
  const smoothedColors = computeGraphSmoothedColors(nodes, options);
  const largeField = computeSpatialField(
    nodes,
    smoothedColors,
    fieldWidth,
    fieldHeight,
    bounds,
    worldWidth * options.spatialSigmaLargeRatio,
    options.largeContributorLimit,
    options.hueBucketCount
  );
  const mediumField = computeSpatialField(
    nodes,
    smoothedColors,
    fieldWidth,
    fieldHeight,
    bounds,
    worldWidth * options.spatialSigmaMediumRatio,
    options.mediumContributorLimit,
    options.hueBucketCount
  );
  const field = blendSpatialFields(largeField, mediumField, options.largeFieldWeight, options.mediumFieldWeight);
  const densityValues = field.cells
    .map(cell => cell?.density || 0)
    .filter(value => value > 0)
    .sort((a, b) => a - b);
  const densityLow = densityValues.length ? Math.max(options.densityLow, percentile(densityValues, 0.42)) : options.densityLow;
  const densityHigh = densityValues.length ? Math.max(densityLow + 0.001, percentile(densityValues, 0.90)) : options.densityHigh;
  const pixels = Buffer.alloc(fieldWidth * fieldHeight * 4);
  for (let gy = 0; gy < fieldHeight; gy += 1) {
    for (let gx = 0; gx < fieldWidth; gx += 1) {
      const noiseX = valueNoise2d(gx * options.noiseScale, gy * options.noiseScale, options.noiseSeed);
      const noiseY = valueNoise2d(gx * options.noiseScale, gy * options.noiseScale, options.noiseSeed + 1);
      const sample = sampleSpatialField(
        field,
        gx + noiseX * options.warpStrength,
        gy + noiseY * options.warpStrength,
        options
      );
      const offset = (gy * fieldWidth + gx) * 4;
      if (!sample.color) continue;
      const densityNorm = Math.pow(smoothstep(densityLow, densityHigh, sample.density), 1.35);
      const alpha = clamp(options.darkBaseAlpha * densityNorm, 0, 0.16);
      if (alpha <= 0.002) continue;
      const rgb = oklabToRgb(muteForBackground(sample.color, options));
      pixels[offset] = clamp(Math.round(rgb.r), 0, 255);
      pixels[offset + 1] = clamp(Math.round(rgb.g), 0, 255);
      pixels[offset + 2] = clamp(Math.round(rgb.b), 0, 255);
      pixels[offset + 3] = Math.round(alpha * 255);
    }
  }
  return {
    version: "cloud-background-v1",
    encoding: "rgba-base64",
    postprocess: { blurPx: 7, overlayAlpha: 0.12 },
    width: fieldWidth,
    height: fieldHeight,
    bounds: {
      min_x: bounds.minX,
      max_x: bounds.maxX,
      min_y: bounds.minY,
      max_y: bounds.maxY,
    },
    density: { densityLow, densityHigh },
    signature: cloudBackgroundSignature(nodes, bounds, fieldWidth, fieldHeight),
    rgba: pixels.toString("base64"),
  };
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => {
  input += chunk;
});
process.stdin.on("end", () => {
  const payload = JSON.parse(input || "{}");
  const packet = createPacket(payload);
  process.stdout.write(JSON.stringify(packet));
});
