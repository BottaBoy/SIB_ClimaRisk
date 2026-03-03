#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const inputPath = process.argv[2] || 'web/data/sib-thesis-demo.json';
const resolved = path.resolve(process.cwd(), inputPath);

const fail = (msg) => {
  console.error(`ERROR: ${msg}`);
  process.exitCode = 1;
};

const isFiniteNumber = (v) => typeof v === 'number' && Number.isFinite(v);

let data;
try {
  data = JSON.parse(fs.readFileSync(resolved, 'utf8'));
} catch (err) {
  console.error(`ERROR: cannot parse ${resolved}`);
  console.error(err.message);
  process.exit(1);
}

if (!data || typeof data !== 'object') fail('root must be an object');
if (!data.meta || typeof data.meta !== 'object') fail('meta is required');
if (typeof data.meta?.title !== 'string' || !data.meta.title.trim()) fail('meta.title is required');
if (typeof data.meta?.updated_at !== 'string' || Number.isNaN(new Date(data.meta.updated_at).getTime())) fail('meta.updated_at must be ISO date string');
if (typeof data.meta?.source !== 'string' || !data.meta.source.trim()) fail('meta.source is required');
if (typeof data.meta?.impact_function !== 'string' || !data.meta.impact_function.trim()) fail('meta.impact_function is required');
if (!Array.isArray(data.meta?.hazards) || data.meta.hazards.length < 2) fail('meta.hazards must be an array of hazards');
if (data.meta?.modeling != null && typeof data.meta.modeling !== 'object') fail('meta.modeling must be an object when provided');

if (!data.exposure_summary || typeof data.exposure_summary !== 'object') fail('exposure_summary is required');
['asset_count_original', 'asset_count_points', 'total_exposure_eur'].forEach((key) => {
  if (!isFiniteNumber(data.exposure_summary[key])) fail(`exposure_summary.${key} must be numeric`);
});

if (!Array.isArray(data.territory_results) || data.territory_results.length === 0) {
  fail('territory_results must be a non-empty array');
} else {
  const ids = new Set();
  data.territory_results.forEach((row, idx) => {
    if (!row || typeof row !== 'object') return fail(`territory_results[${idx}] must be an object`);
    ['territory_id', 'territory_label'].forEach((k) => {
      if (typeof row[k] !== 'string' || !row[k].trim()) fail(`territory_results[${idx}].${k} must be non-empty string`);
    });
    ['exposure_eur', 'eai_storm_eur', 'eai_cmcc_eur', 'risk_index_storm', 'risk_index_cmcc'].forEach((k) => {
      if (!isFiniteNumber(row[k])) fail(`territory_results[${idx}].${k} must be numeric`);
    });
    ['eai_storm_direct_eur', 'eai_storm_indirect_eur', 'eai_cmcc_direct_eur', 'eai_cmcc_indirect_eur'].forEach((k) => {
      if (row[k] != null && !isFiniteNumber(row[k])) fail(`territory_results[${idx}].${k} must be numeric when provided`);
    });
    if (row.lat != null && !isFiniteNumber(row.lat)) fail(`territory_results[${idx}].lat must be number|null`);
    if (row.lon != null && !isFiniteNumber(row.lon)) fail(`territory_results[${idx}].lon must be number|null`);
    if (ids.has(row.territory_id)) fail(`duplicate territory_id ${row.territory_id}`);
    ids.add(row.territory_id);
  });
}

if (!data.portfolio_results || typeof data.portfolio_results !== 'object') fail('portfolio_results is required');
['storm', 'storm_cmcc'].forEach((haz) => {
  if (!data.portfolio_results[haz]) return fail(`portfolio_results.${haz} is required`);
  ['eai_eur', 'aai_agg_eur', 'max_event_loss_eur'].forEach((k) => {
    if (!isFiniteNumber(data.portfolio_results[haz][k])) fail(`portfolio_results.${haz}.${k} must be numeric`);
  });
  ['eai_direct_eur', 'eai_indirect_eur', 'pml_10_eur', 'pml_20_eur', 'pml_50_eur', 'pml_100_eur', 'pml_200_eur', 'tvar_95_eur'].forEach((k) => {
    if (data.portfolio_results[haz][k] != null && !isFiniteNumber(data.portfolio_results[haz][k])) {
      fail(`portfolio_results.${haz}.${k} must be numeric when provided`);
    }
  });
});
if (!data.portfolio_results.delta || typeof data.portfolio_results.delta !== 'object') fail('portfolio_results.delta is required');
if (data.portfolio_results.event_summary != null && typeof data.portfolio_results.event_summary !== 'object') {
  fail('portfolio_results.event_summary must be an object when provided');
}
['storm_top_events', 'storm_cmcc_top_events'].forEach((k) => {
  const events = data.portfolio_results?.event_summary?.[k];
  if (events == null) return;
  if (!Array.isArray(events)) return fail(`portfolio_results.event_summary.${k} must be an array`);
  events.forEach((event, idx) => {
    if (!event || typeof event !== 'object') return fail(`portfolio_results.event_summary.${k}[${idx}] must be an object`);
    if (event.loss_eur != null && !isFiniteNumber(event.loss_eur)) fail(`portfolio_results.event_summary.${k}[${idx}].loss_eur must be numeric`);
    if (event.frequency_annual != null && !isFiniteNumber(event.frequency_annual)) fail(`portfolio_results.event_summary.${k}[${idx}].frequency_annual must be numeric`);
  });
});

if (!data.graphs || typeof data.graphs !== 'object') fail('graphs is required');
['storm', 'storm_cmcc', 'comparison'].forEach((k) => {
  if (!data.graphs[k] || typeof data.graphs[k] !== 'object') fail(`graphs.${k} is required`);
});

if (!data.artifacts || typeof data.artifacts !== 'object') fail('artifacts is required');
if (!Array.isArray(data.artifacts.plots_png)) fail('artifacts.plots_png must be array');
if (!Array.isArray(data.artifacts.downloads)) fail('artifacts.downloads must be array');

if (!Array.isArray(data.notes)) fail('notes must be array');
else data.notes.forEach((n, i) => { if (typeof n !== 'string' || !n.trim()) fail(`notes[${i}] must be non-empty string`); });

if (process.exitCode === 1) process.exit(1);
console.log(`OK: ${resolved}`);
console.log(`Territories: ${data.territory_results.length}`);
console.log(`Total exposure (EUR): ${data.exposure_summary.total_exposure_eur}`);
console.log(`Portfolio EAI STORM (EUR): ${data.portfolio_results.storm.eai_eur}`);
console.log(`Portfolio EAI STORM_CMCC (EUR): ${data.portfolio_results.storm_cmcc.eai_eur}`);
