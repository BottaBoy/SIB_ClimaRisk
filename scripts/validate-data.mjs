#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const inputPath = process.argv[2] || 'web/data/sib-demo.json';
const resolvedPath = path.resolve(process.cwd(), inputPath);

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exitCode = 1;
}

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

let raw;
try {
  raw = fs.readFileSync(resolvedPath, 'utf8');
} catch (error) {
  console.error(`ERROR: cannot read file ${resolvedPath}`);
  console.error(error.message);
  process.exit(1);
}

let data;
try {
  data = JSON.parse(raw);
} catch (error) {
  console.error('ERROR: invalid JSON syntax');
  console.error(error.message);
  process.exit(1);
}

if (!data || typeof data !== 'object') {
  fail('root JSON must be an object');
  process.exit(1);
}

if (!data.meta || typeof data.meta !== 'object') {
  fail('meta is required and must be an object');
}

if (typeof data.meta?.title !== 'string' || !data.meta.title.trim()) {
  fail('meta.title is required and must be a non-empty string');
}

if (typeof data.meta?.updated_at !== 'string' || Number.isNaN(new Date(data.meta.updated_at).getTime())) {
  fail('meta.updated_at is required and must be an ISO date string');
}

if (typeof data.meta?.source !== 'string' || !data.meta.source.trim()) {
  fail('meta.source is required and must be a non-empty string');
}

if (typeof data.meta?.unit_currency !== 'string' || !data.meta.unit_currency.trim()) {
  fail('meta.unit_currency is required and must be a non-empty string');
}

if (!Array.isArray(data.scenarios) || data.scenarios.length === 0) {
  fail('scenarios must be a non-empty array');
}

const scenarioIds = new Set();
for (const [idx, scenario] of (data.scenarios || []).entries()) {
  if (!scenario || typeof scenario !== 'object') {
    fail(`scenarios[${idx}] must be an object`);
    continue;
  }

  if (typeof scenario.id !== 'string' || !scenario.id.trim()) {
    fail(`scenarios[${idx}].id must be a non-empty string`);
  }

  if (typeof scenario.label !== 'string' || !scenario.label.trim()) {
    fail(`scenarios[${idx}].label must be a non-empty string`);
  }

  if (typeof scenario.technical_label !== 'string' || !scenario.technical_label.trim()) {
    fail(`scenarios[${idx}].technical_label must be a non-empty string`);
  }

  if (scenarioIds.has(scenario.id)) {
    fail(`duplicate scenario id: ${scenario.id}`);
  }
  scenarioIds.add(scenario.id);
}

if (!Array.isArray(data.horizons) || data.horizons.length === 0) {
  fail('horizons must be a non-empty array');
}

const horizonSet = new Set();
for (const [idx, horizon] of (data.horizons || []).entries()) {
  if (!Number.isInteger(horizon)) {
    fail(`horizons[${idx}] must be an integer`);
    continue;
  }
  if (horizonSet.has(horizon)) {
    fail(`duplicate horizon value: ${horizon}`);
  }
  horizonSet.add(horizon);
}

if (!Array.isArray(data.geographies) || data.geographies.length === 0) {
  fail('geographies must be a non-empty array');
}

const geographyIds = new Set();
for (const [idx, geography] of (data.geographies || []).entries()) {
  if (!geography || typeof geography !== 'object') {
    fail(`geographies[${idx}] must be an object`);
    continue;
  }

  if (typeof geography.id !== 'string' || !geography.id.trim()) {
    fail(`geographies[${idx}].id must be a non-empty string`);
  }

  if (typeof geography.label !== 'string' || !geography.label.trim()) {
    fail(`geographies[${idx}].label must be a non-empty string`);
  }

  if (!isFiniteNumber(geography.lat)) {
    fail(`geographies[${idx}].lat must be a finite number`);
  }

  if (!isFiniteNumber(geography.lon)) {
    fail(`geographies[${idx}].lon must be a finite number`);
  }

  if (isFiniteNumber(geography.lat) && (geography.lat < -90 || geography.lat > 90)) {
    fail(`geographies[${idx}].lat must be in [-90, 90]`);
  }

  if (isFiniteNumber(geography.lon) && (geography.lon < -180 || geography.lon > 180)) {
    fail(`geographies[${idx}].lon must be in [-180, 180]`);
  }

  if (geographyIds.has(geography.id)) {
    fail(`duplicate geography id: ${geography.id}`);
  }
  geographyIds.add(geography.id);
}

if (!Array.isArray(data.records) || data.records.length === 0) {
  fail('records must be a non-empty array');
}

const recordKeys = new Set();
const recordsByScenario = new Map();
const recordsByHorizon = new Map();

for (const [idx, record] of (data.records || []).entries()) {
  if (!record || typeof record !== 'object') {
    fail(`records[${idx}] must be an object`);
    continue;
  }

  const requiredStringFields = ['geography_id', 'geography_label', 'scenario_id'];
  for (const field of requiredStringFields) {
    if (typeof record[field] !== 'string' || !record[field].trim()) {
      fail(`records[${idx}].${field} must be a non-empty string`);
    }
  }

  if (!Number.isInteger(record.horizon)) {
    fail(`records[${idx}].horizon must be an integer`);
  }

  if (!isFiniteNumber(record.exposure_meur)) {
    fail(`records[${idx}].exposure_meur must be a finite number`);
  }

  if (!isFiniteNumber(record.expected_loss_meur)) {
    fail(`records[${idx}].expected_loss_meur must be a finite number`);
  }

  if (!isFiniteNumber(record.risk_index)) {
    fail(`records[${idx}].risk_index must be a finite number`);
  }

  if (record.exposure_meur < 0) {
    fail(`records[${idx}].exposure_meur cannot be negative`);
  }

  if (record.expected_loss_meur < 0) {
    fail(`records[${idx}].expected_loss_meur cannot be negative`);
  }

  if (record.risk_index < 0 || record.risk_index > 100) {
    fail(`records[${idx}].risk_index must be between 0 and 100`);
  }

  if (!scenarioIds.has(record.scenario_id)) {
    fail(`records[${idx}].scenario_id (${record.scenario_id}) is not declared in scenarios[]`);
  }

  if (!horizonSet.has(record.horizon)) {
    fail(`records[${idx}].horizon (${record.horizon}) is not declared in horizons[]`);
  }

  if (!geographyIds.has(record.geography_id)) {
    fail(`records[${idx}].geography_id (${record.geography_id}) is not declared in geographies[]`);
  }

  const key = `${record.geography_id}|${record.scenario_id}|${record.horizon}`;
  if (recordKeys.has(key)) {
    fail(`duplicate record key geography/scenario/horizon: ${key}`);
  }
  recordKeys.add(key);

  recordsByScenario.set(record.scenario_id, (recordsByScenario.get(record.scenario_id) || 0) + 1);
  recordsByHorizon.set(record.horizon, (recordsByHorizon.get(record.horizon) || 0) + 1);
}

if (!Array.isArray(data.insight_notes)) {
  fail('insight_notes must be an array');
} else {
  data.insight_notes.forEach((note, idx) => {
    if (typeof note !== 'string' || !note.trim()) {
      fail(`insight_notes[${idx}] must be a non-empty string`);
    }
  });
}

if (process.exitCode === 1) {
  process.exit(1);
}

console.log(`OK: ${resolvedPath}`);
console.log(`Scenarios: ${data.scenarios.length}`);
console.log(`Horizons: ${data.horizons.length}`);
console.log(`Geographies: ${data.geographies.length}`);
console.log(`Records: ${data.records.length}`);
console.log('Records by scenario:');
for (const scenario of data.scenarios) {
  console.log(`  - ${scenario.id}: ${recordsByScenario.get(scenario.id) || 0}`);
}
console.log('Records by horizon:');
for (const horizon of [...horizonSet].sort((a, b) => a - b)) {
  console.log(`  - ${horizon}: ${recordsByHorizon.get(horizon) || 0}`);
}
