const state = {
  demoResult: null,
  activeResult: null,
  selectedHazard: 'storm',
  selectedDatasetMode: 'demo',
  selectedTerritoryId: null,
  territorySearch: '',
  resultsByMode: {
    demo: null,
    uploaded: null,
    drawn: null
  },
  currentJobId: null,
  pollTimer: null,
  pollingModeTarget: null,
  currentPage: 'page1',
  mapReady: false,
  windMaps: null,
  windLayerOpacity: 0.82,
  waterInfra: null,
  waterLayerVisibility: {},
  page1Analysis: null,
  networkStates: null,
  networkStatesPromise: null,
  networkLayerVisibility: {},
  impactMapHazard: 'storm',
  impactMapScenario: 'event_max'
};

const mapRef = {
  instance: null,
  markersLayer: null,
  drawnItems: null,
  drawControl: null,
  markerByTerritoryId: new Map(),
  hasFitted: false
};

const windMapRef = {
  storm: { instance: null, cellsLayer: null, hasFitted: false, legendControl: null },
  storm_cmcc: { instance: null, cellsLayer: null, hasFitted: false, legendControl: null }
};

const waterMapRef = {
  instance: null,
  layersByType: new Map(),
  order: [],
  hasFitted: false
};

const networkMapRef = {
  instance: null,
  layersByType: new Map(),
  order: [],
  hasFitted: false
};

const WATER_LAYER_ORDER = [
  'aep_cana',
  'aep_ouvrage',
  'eu_cana',
  'eu_pr',
  'eu_step',
  'elec_bt_aerien',
  'elec_bt_souterrain',
  'elec_hta_aerien',
  'elec_hta_souterrain'
];
const WATER_LAYER_LABEL = {
  aep_cana: 'AEP canalisations',
  aep_ouvrage: 'AEP ouvrages',
  eu_cana: 'EU canalisations',
  eu_pr: 'EU postes de refoulement',
  eu_step: 'STEP',
  elec_bt_aerien: 'Basse tension aerien',
  elec_bt_souterrain: 'Basse tension souterrain',
  elec_hta_aerien: 'Haute tension aerien',
  elec_hta_souterrain: 'Haute tension souterrain'
};

const NETWORK_LAYER_ORDER = [
  'eau_aep',
  'eau_eu',
  'elec_bt_souterrain',
  'elec_bt_aerien',
  'elec_hta_souterrain',
  'elec_hta_aerien'
];

const NETWORK_LAYER_LABEL = {
  eau_aep: 'Reseau eau AEP',
  eau_eu: 'Reseau eau EU',
  elec_bt_souterrain: 'Reseau basse tension souterrain',
  elec_bt_aerien: 'Reseau basse tension aerien',
  elec_hta_souterrain: 'Reseau haute tension souterrain',
  elec_hta_aerien: 'Reseau haute tension aerien'
};

const STATE_COLORS = {
  S0: '#6AB96F',
  S1: '#f2b66f',
  S2: '#d94832',
  S3: '#111111'
};

const WIND_PADDING_CELLS = 6;

const GUA_VALUATION_RULES = [
  'Elec basse tension aerien: 180 kEUR/km',
  'Elec basse tension souterrain: 320 kEUR/km',
  'Elec haute tension aerien: 260 kEUR/km',
  'Elec haute tension souterrain: 520 kEUR/km',
  'AEP canalisations: 280 kEUR/km',
  'EU canalisations: 340 kEUR/km',
  'EU PR: 900 kEUR/unite',
  'EU STEP: 6 000 kEUR/unite',
  'AEP ouvrages: valeur fixe par ovrg_type (TRAIT/STPMP/CAP/CUV/autres)'
];

const chartRefs = {
  c1: null,
  c2: null,
  c3: null,
  c4: null,
  comparison: null,
  page1_year_compare: null,
  page1_track_compare: null,
  impact_eai: null,
  impact_evt: null
};

const els = {
  navPage1: document.getElementById('nav-page-1'),
  navPage2: document.getElementById('nav-page-2'),
  navPage3: document.getElementById('nav-page-3'),
  pageBlocks: Array.from(document.querySelectorAll('.page-block')),
  errorBanner: document.getElementById('error-banner'),
  badgeSource: document.getElementById('badge-source'),
  badgeUpdated: document.getElementById('badge-updated'),
  badgeEngine: document.getElementById('badge-engine'),
  hazardSelect: document.getElementById('hazard-select'),
  datasetSelect: document.getElementById('dataset-select'),
  resetDemoBtn: document.getElementById('reset-demo-btn'),
  pollJobId: document.getElementById('poll-job-id'),
  reloadJobBtn: document.getElementById('reload-job-btn'),
  uploadForm: document.getElementById('upload-form'),
  uploadFile: document.getElementById('upload-file'),
  valueField: document.getElementById('value-field'),
  idField: document.getElementById('id-field'),
  assetTypeField: document.getElementById('asset-type-field'),
  categoryField: document.getElementById('category-field'),
  defaultCategory: document.getElementById('default-category'),
  crsField: document.getElementById('crs-field'),
  spacingField: document.getElementById('spacing-field'),
  runLabel: document.getElementById('run-label'),
  drawCategory: document.getElementById('draw-category'),
  uploadSubmitBtn: document.getElementById('upload-submit-btn'),
  submitDrawingBtn: document.getElementById('submit-drawing-btn'),
  refreshPreviewBtn: document.getElementById('refresh-preview-btn'),
  clearDrawingsBtn: document.getElementById('clear-drawings-btn'),
  drawSummaryList: document.getElementById('draw-summary-list'),
  jobStatusBox: document.getElementById('job-status-box'),
  kpiGrid: document.getElementById('kpi-grid'),
  selectedTerritoryChip: document.getElementById('selected-territory-chip'),
  territorySearch: document.getElementById('territory-search'),
  clearTerritoryFilterBtn: document.getElementById('clear-territory-filter-btn'),
  territoryTableBody: document.getElementById('territory-table-body'),
  tableCaption: document.getElementById('table-caption'),
  mapCaption: document.getElementById('map-caption'),
  mapContainer: document.getElementById('territory-map'),
  mapFallback: document.getElementById('map-fallback'),
  chartsCaption: document.getElementById('charts-caption'),
  artifactLinks: document.getElementById('artifact-links'),
  chartTitle1: document.getElementById('chart-title-1'),
  chartTitle2: document.getElementById('chart-title-2'),
  chartTitle3: document.getElementById('chart-title-3'),
  chartTitle4: document.getElementById('chart-title-4'),
  notesBox: document.getElementById('notes-box'),
  windMapStorm: document.getElementById('wind-map-storm'),
  windMapCmcc: document.getElementById('wind-map-cmcc'),
  windStormCaption: document.getElementById('wind-storm-caption'),
  windCmccCaption: document.getElementById('wind-cmcc-caption'),
  windOpacitySlider: document.getElementById('wind-opacity-slider'),
  windOpacityValue: document.getElementById('wind-opacity-value'),
  hazardSummaryText: document.getElementById('hazard-summary-text'),
  waterInfraMap: document.getElementById('water-infra-map'),
  waterMapCaption: document.getElementById('water-map-caption'),
  waterLayerControls: document.getElementById('water-layer-controls'),
  infraSummary: document.getElementById('infra-summary'),
  expositionSummaryText: document.getElementById('exposition-summary-text'),
  expositionMetricsList: document.getElementById('exposition-metrics-list'),
  expositionValueTableBody: document.getElementById('exposition-value-table-body'),
  expositionTotalValue: document.getElementById('exposition-total-value'),
  page1ChartYearCompare: document.getElementById('page1-chart-year-compare'),
  page1ChartTrackCompare: document.getElementById('page1-chart-track-compare'),
  impactSummaryText: document.getElementById('impact-summary-text'),
  impactStateTableBody: document.getElementById('impact-state-table-body'),
  impactEaiChart: document.getElementById('impact-eai-chart'),
  impactEvtChart: document.getElementById('impact-evt-chart'),
  impactMapHazardSelect: document.getElementById('impact-map-hazard-select'),
  impactMapScenarioSelect: document.getElementById('impact-map-scenario-select'),
  networkLayerControls: document.getElementById('network-layer-controls'),
  networkStateMap: document.getElementById('network-state-map'),
  networkStateCaption: document.getElementById('network-state-caption'),
  conclusionText: document.getElementById('conclusion-text')
};

const numberFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const percentFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const moneyFmt = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dateFmt = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
});

function pageFromHash() {
  const hash = String(window.location.hash || '').replace('#', '').trim().toLowerCase();
  if (hash === 'page2') return 'page2';
  if (hash === 'page3') return 'page3';
  return 'page1';
}

function setActivePage(pageKey, { updateHash = true } = {}) {
  state.currentPage = pageKey;
  if (updateHash) {
    const nextHash = `#${pageKey}`;
    if (window.location.hash !== nextHash) window.history.replaceState(null, '', nextHash);
  }

  els.pageBlocks.forEach((el) => {
    if (!el.classList.contains(pageKey)) el.classList.add('hidden-page');
    else el.classList.remove('hidden-page');
  });

  const tabs = [
    [els.navPage1, 'page1'],
    [els.navPage2, 'page2'],
    [els.navPage3, 'page3']
  ];
  tabs.forEach(([btn, key]) => {
    if (!btn) return;
    if (pageKey === key) btn.classList.add('active');
    else btn.classList.remove('active');
  });

  if (pageKey === 'page2') {
    renderMap();
    renderDrawPreview();
    renderHazardCharts();
    setTimeout(() => {
      if (mapRef.instance) mapRef.instance.invalidateSize();
      if (chartRefs.c1) chartRefs.c1.resize();
      if (chartRefs.c2) chartRefs.c2.resize();
      if (chartRefs.c3) chartRefs.c3.resize();
      if (chartRefs.c4) chartRefs.c4.resize();
      if (chartRefs.comparison) chartRefs.comparison.resize();
    }, 80);
  }
  if (pageKey === 'page1') {
    setTimeout(() => {
      if (windMapRef.storm.instance) windMapRef.storm.instance.invalidateSize();
      if (windMapRef.storm_cmcc.instance) windMapRef.storm_cmcc.instance.invalidateSize();
      if (waterMapRef.instance) waterMapRef.instance.invalidateSize();
      if (networkMapRef.instance) networkMapRef.instance.invalidateSize();
      if (chartRefs.page1_year_compare) chartRefs.page1_year_compare.resize();
      if (chartRefs.page1_track_compare) chartRefs.page1_track_compare.resize();
      if (chartRefs.impact_eai) chartRefs.impact_eai.resize();
      if (chartRefs.impact_evt) chartRefs.impact_evt.resize();
    }, 80);
  }
}

function showError(message) {
  els.errorBanner.hidden = false;
  els.errorBanner.textContent = message;
}

function clearError() {
  els.errorBanner.hidden = true;
  els.errorBanner.textContent = '';
}

function setStatus(message, tone = 'info') {
  if (!message) {
    els.jobStatusBox.hidden = true;
    els.jobStatusBox.textContent = '';
    els.jobStatusBox.style.borderColor = '';
    els.jobStatusBox.style.background = '';
    return;
  }
  els.jobStatusBox.hidden = false;
  els.jobStatusBox.textContent = message;
  if (tone === 'error') {
    els.jobStatusBox.style.borderColor = 'rgba(255, 143, 115, 0.4)';
    els.jobStatusBox.style.background = 'rgba(255, 143, 115, 0.08)';
  } else if (tone === 'success') {
    els.jobStatusBox.style.borderColor = 'rgba(96, 193, 142, 0.4)';
    els.jobStatusBox.style.background = 'rgba(96, 193, 142, 0.08)';
  } else {
    els.jobStatusBox.style.borderColor = 'rgba(75, 177, 203, 0.35)';
    els.jobStatusBox.style.background = 'rgba(75, 177, 203, 0.08)';
  }
}

function formatMoneyMEUR(valueEur) {
  return `${moneyFmt.format((Number(valueEur) || 0) / 1_000_000)} M€`;
}

function formatMoneyEUR(valueEur) {
  return `${moneyFmt.format(Number(valueEur) || 0)} €`;
}

function formatRisk(value) {
  return numberFmt.format(Number(value) || 0);
}

function formatDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return dateFmt.format(d);
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function formatStateTuple(statePct) {
  const p = statePct || {};
  return `S0 ${percentFmt.format(Number(p.S0 || 0))} · S1 ${percentFmt.format(Number(p.S1 || 0))} · S2 ${percentFmt.format(Number(p.S2 || 0))} · S3 ${percentFmt.format(Number(p.S3 || 0))}`;
}

function ensureResultShape(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('Invalid result payload');
  if (!raw.meta || !raw.exposure_summary || !Array.isArray(raw.territory_results) || !raw.portfolio_results || !raw.graphs) {
    throw new Error('Result payload missing required sections');
  }
  return raw;
}

function currentHazardKey() {
  return state.selectedHazard;
}

function getActiveResult() {
  return state.activeResult;
}

function getHazardPortfolio(result, hazardKey) {
  return result?.portfolio_results?.[hazardKey] || { eai_eur: 0, aai_agg_eur: 0, max_event_loss_eur: 0 };
}

function getHazardLabel(hazardKey) {
  return hazardKey === 'storm_cmcc' ? 'STORM_CMCC' : 'STORM';
}

function updateMetaBadges() {
  const result = getActiveResult();
  if (!result) return;
  els.badgeSource.textContent = `Source: ${result.meta?.source || 'unknown'}`;
  els.badgeUpdated.textContent = `Updated: ${formatDate(result.meta?.updated_at)}`;
  els.badgeEngine.textContent = `Engine: ${result.meta?.engine || 'n/a'}`;
}

function renderKpis() {
  const result = getActiveResult();
  if (!result) {
    els.kpiGrid.innerHTML = '';
    return;
  }
  const hazardKey = currentHazardKey();
  const selectedRow = state.selectedTerritoryId
    ? (result.territory_results || []).find((x) => x.territory_id === state.selectedTerritoryId)
    : null;
  const p = selectedRow ? {
    eai_eur: eaiForHazard(selectedRow, hazardKey),
    aai_agg_eur: eaiForHazard(selectedRow, hazardKey),
    max_event_loss_eur: eaiForHazard(selectedRow, hazardKey) * (hazardKey === 'storm_cmcc' ? 4.2 : 4.0)
  } : getHazardPortfolio(result, hazardKey);
  const delta = result.portfolio_results?.delta || { eai_eur: 0, eai_pct: 0 };
  const summary = result.exposure_summary || {};
  const exposureForScope = selectedRow ? Number(selectedRow.exposure_eur || 0) : Number(summary.total_exposure_eur || 0);
  const assetCountForScope = selectedRow ? 1 : Number(summary.asset_count_original || 0);
  const pointCountForScope = selectedRow ? null : Number(summary.asset_count_points || 0);

  const cards = [
    {
      label: 'Selected Hazard EAI',
      value: formatMoneyMEUR(p.eai_eur),
      sub: `AAI agg ${formatMoneyMEUR(p.aai_agg_eur)} · ${getHazardLabel(hazardKey)}`
    },
    {
      label: 'Max Event Loss',
      value: formatMoneyMEUR(p.max_event_loss_eur),
      sub: 'Portfolio-level estimate from current result set'
    },
    {
      label: 'Total Exposure',
      value: formatMoneyMEUR(exposureForScope),
      sub: selectedRow
        ? `Selected territory: ${selectedRow.territory_label}`
        : `${numberFmt.format(assetCountForScope)} assets · ${numberFmt.format(pointCountForScope || 0)} disaggregated points`
    },
    {
      label: 'CMCC Delta vs STORM',
      value: formatMoneyMEUR(delta.eai_eur),
      sub: `${percentFmt.format(delta.eai_pct || 0)}% portfolio EAI change`
    }
  ];

  els.kpiGrid.innerHTML = cards.map((card) => `
    <article class="panel kpi-card">
      <div class="kpi-label">${escapeHtml(card.label)}</div>
      <div class="kpi-value">${escapeHtml(card.value)}</div>
      <div class="kpi-sub">${escapeHtml(card.sub)}</div>
    </article>
  `).join('');
}

function renderInfraSummary() {
  const analysis = state.page1Analysis;
  if (!analysis) {
    if (els.expositionSummaryText) els.expositionSummaryText.textContent = "Donnees d'exposition indisponibles.";
    if (els.hazardSummaryText) els.hazardSummaryText.textContent = "Donnees d'alea indisponibles.";
    if (els.impactSummaryText) els.impactSummaryText.textContent = "Donnees d'impact indisponibles.";
    if (els.conclusionText) els.conclusionText.textContent = "Conclusion indisponible.";
    return;
  }

  renderPage1Exposition(analysis);
  renderPage1Hazard(analysis);
  renderPage1Impact(analysis);
  renderPage1Conclusion(analysis);
}

function renderPage1Exposition(analysis) {
  const expo = analysis?.exposition || {};
  const lengths = expo.lengths_km || {};
  const counts = expo.counts || {};

  if (els.expositionSummaryText) {
    const linesElec = Number(counts.elec_lines_total || 0);
    const linesWater = Number(counts.water_lines_total || 0);
    const txt = [
      `Le jeu de reference comprend ${numberFmt.format(linesElec)} troncons electriques et ${numberFmt.format(linesWater)} troncons d'eau.`,
      `Longueurs reseaux: basse tension aerien ${numberFmt.format(Number(lengths.elec_bt_aerien || 0))} km, basse tension souterrain ${numberFmt.format(Number(lengths.elec_bt_souterrain || 0))} km, haute tension aerien ${numberFmt.format(Number(lengths.elec_hta_aerien || 0))} km, haute tension souterrain ${numberFmt.format(Number(lengths.elec_hta_souterrain || 0))} km, AEP ${numberFmt.format(Number(lengths.eau_aep || 0))} km, EU ${numberFmt.format(Number(lengths.eau_eu || 0))} km.`,
      `Ouvrages eau: ${numberFmt.format(Number(counts.aep_ouvrages_total || 0))} AEP, ${numberFmt.format(Number(counts.eu_pr_total || 0))} postes de refoulement, ${numberFmt.format(Number(counts.eu_step_total || 0))} STEP.`
    ];
    els.expositionSummaryText.textContent = txt.join(' ');
  }

  if (els.expositionMetricsList) {
    const items = [
      `Reseau basse tension aerien: ${numberFmt.format(Number(lengths.elec_bt_aerien || 0))} km`,
      `Reseau basse tension souterrain: ${numberFmt.format(Number(lengths.elec_bt_souterrain || 0))} km`,
      `Reseau haute tension aerien: ${numberFmt.format(Number(lengths.elec_hta_aerien || 0))} km`,
      `Reseau haute tension souterrain: ${numberFmt.format(Number(lengths.elec_hta_souterrain || 0))} km`,
      `Reseau eau AEP: ${numberFmt.format(Number(lengths.eau_aep || 0))} km`,
      `Reseau eau EU: ${numberFmt.format(Number(lengths.eau_eu || 0))} km`,
      `Ouvrages AEP: ${numberFmt.format(Number(counts.aep_ouvrages_total || 0))}`,
      `Postes de refoulement: ${numberFmt.format(Number(counts.eu_pr_total || 0))}`,
      `STEP: ${numberFmt.format(Number(counts.eu_step_total || 0))}`
    ];
    els.expositionMetricsList.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  }

  if (els.expositionValueTableBody) {
    const valuePerKm = expo.value_per_km_eur || {};
    const totals = expo.total_value_by_type_eur || {};

    const networkRows = NETWORK_LAYER_ORDER.map((key) => ({
      label: NETWORK_LAYER_LABEL[key] || key,
      lengthKm: Number(lengths[key] || 0),
      valuePerKm: Number(valuePerKm[key] || 0),
      total: Number(totals[key] || 0)
    }));
    const ouvrageRows = [
      { label: 'Ouvrages eau AEP', lengthKm: null, valuePerKm: null, total: Number(totals.eau_aep_ouvrages || 0) },
      { label: 'Postes de refoulement EU', lengthKm: null, valuePerKm: null, total: Number(totals.eau_eu_pr || 0) },
      { label: 'STEP', lengthKm: null, valuePerKm: null, total: Number(totals.eau_eu_step || 0) }
    ];
    const rows = [...networkRows, ...ouvrageRows];
    const totalValue = rows.reduce((acc, row) => acc + Number(row.total || 0), 0);
    els.expositionValueTableBody.innerHTML = rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.label)}</td>
        <td class="num">${row.lengthKm === null ? '—' : escapeHtml(numberFmt.format(row.lengthKm))}</td>
        <td class="num">${row.valuePerKm === null ? '—' : escapeHtml(numberFmt.format(row.valuePerKm))}</td>
        <td class="num">${escapeHtml(formatMoneyEUR(row.total))}</td>
      </tr>
    `).join('') + `
      <tr class="table-total-row">
        <td><strong>Total</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num"><strong>${escapeHtml(formatMoneyEUR(totalValue))}</strong></td>
      </tr>
    `;
  }

  if (els.expositionTotalValue) {
    els.expositionTotalValue.textContent = `Valeur totale des infrastructures: ${formatMoneyEUR(expo.total_value_all_eur || 0)}`;
  }
}

function renderPage1Hazard(analysis) {
  const hazard = analysis?.hazard || {};
  const hist = hazard.wind_histograms || {};
  if (els.hazardSummaryText) {
    const stormYears = Number(hist?.storm?.year_count || 0);
    const cmccYears = Number(hist?.storm_cmcc?.year_count || 0);
    els.hazardSummaryText.textContent = `${String(hazard.summary_text || '')} STORM: ${numberFmt.format(stormYears)} annees; STORM_CMCC: ${numberFmt.format(cmccYears)} annees.`;
  }

  renderHistogramComparisonChart(
    'page1_year_compare',
    'page1-chart-year-compare',
    hist?.storm?.year_max_hist,
    hist?.storm_cmcc?.year_max_hist,
    'STORM',
    'STORM_CMCC',
    '#0083CB',
    '#F39655'
  );
  renderHistogramComparisonChart(
    'page1_track_compare',
    'page1-chart-track-compare',
    hist?.storm?.track_max_hist,
    hist?.storm_cmcc?.track_max_hist,
    'STORM',
    'STORM_CMCC',
    '#00A6E2',
    '#A4A64B'
  );
}

function renderPage1Impact(analysis) {
  const impact = analysis?.impact || {};
  const summary = impact.summary_metrics || {};
  if (els.impactSummaryText) {
    const storm = summary.storm || {};
    const cmcc = summary.storm_cmcc || {};
    const directAnnualStorm = Number(storm.direct_hs_pct_annual || 0);
    const indirectAnnualStorm = Number(storm.indirect_hs_pct_annual || 0);
    const directAnnualCmcc = Number(cmcc.direct_hs_pct_annual || 0);
    const indirectAnnualCmcc = Number(cmcc.indirect_hs_pct_annual || 0);

    els.impactSummaryText.textContent = [
      `Pourcentage hors service annuel (S3) - dommages directs: STORM ${percentFmt.format(directAnnualStorm)} %, STORM_CMCC ${percentFmt.format(directAnnualCmcc)} %.`,
      `Pourcentage hors service annuel (S3) - dependance electrique: STORM ${percentFmt.format(indirectAnnualStorm)} %, STORM_CMCC ${percentFmt.format(indirectAnnualCmcc)} %.`,
      `Dommages annuels moyens: STORM ${formatMoneyEUR(storm.eai_total_eur || 0)}, STORM_CMCC ${formatMoneyEUR(cmcc.eai_total_eur || 0)}.`,
      `Evenement le plus fort: STORM ${formatMoneyEUR(storm.event_max_total_loss_eur || 0)}, STORM_CMCC ${formatMoneyEUR(cmcc.event_max_total_loss_eur || 0)}.`
    ].join(' ');
  }

  const rows = Array.isArray(impact.state_damage_table) ? impact.state_damage_table : [];
  if (els.impactStateTableBody) {
    if (!rows.length) {
      els.impactStateTableBody.innerHTML = '<tr><td colspan="9">Aucune donnee d\'impact disponible.</td></tr>';
    } else {
      els.impactStateTableBody.innerHTML = rows.map((row) => {
        const storm = row.storm || {};
        const cmcc = row.storm_cmcc || {};
        const rowLabel = NETWORK_LAYER_LABEL[String(row.class_key || '')] || row.class_label || row.class_key || 'Reseau';
        return `
          <tr>
            <td>${escapeHtml(String(rowLabel))}</td>
            <td class="num">${escapeHtml(formatStateTuple(storm.state_pct_annual))}</td>
            <td class="num">${escapeHtml(formatStateTuple(storm.state_pct_event_max))}</td>
            <td class="num">${escapeHtml(formatMoneyEUR(storm.eai_eur || 0))}</td>
            <td class="num">${escapeHtml(formatMoneyEUR(storm.event_max_loss_eur || 0))}</td>
            <td class="num">${escapeHtml(formatStateTuple(cmcc.state_pct_annual))}</td>
            <td class="num">${escapeHtml(formatStateTuple(cmcc.state_pct_event_max))}</td>
            <td class="num">${escapeHtml(formatMoneyEUR(cmcc.eai_eur || 0))}</td>
            <td class="num">${escapeHtml(formatMoneyEUR(cmcc.event_max_loss_eur || 0))}</td>
          </tr>
        `;
      }).join('');
    }
  }

  renderImpactBreakdownCharts(impact);
}

function renderPage1Conclusion(analysis) {
  if (!els.conclusionText) return;
  const expo = analysis?.exposition || {};
  const impact = analysis?.impact || {};
  const storm = impact?.summary_metrics?.storm || {};
  const cmcc = impact?.summary_metrics?.storm_cmcc || {};
  const totalValue = Number(expo.total_value_all_eur || 0);
  const stormEai = Number(storm.eai_total_eur || 0);
  const cmccEai = Number(cmcc.eai_total_eur || 0);
  const stormEvt = Number(storm.event_max_total_loss_eur || 0);
  const cmccEvt = Number(cmcc.event_max_total_loss_eur || 0);
  const stronger = cmccEai >= stormEai ? 'STORM_CMCC' : 'STORM';
  const ratioStorm = totalValue > 0 ? (stormEai / totalValue) * 100.0 : 0;
  const ratioCmcc = totalValue > 0 ? (cmccEai / totalValue) * 100.0 : 0;
  const txt = [
    `Le portefeuille d'infrastructures represente ${formatMoneyEUR(totalValue)}.`,
    `Les dommages annuels moyens restent limites (${percentFmt.format(ratioStorm)} % pour STORM et ${percentFmt.format(ratioCmcc)} % pour STORM_CMCC), mais l'evenement extrême atteint ${formatMoneyEUR(stormEvt)} (STORM) et ${formatMoneyEUR(cmccEvt)} (STORM_CMCC).`,
    `Le scenario le plus penalise en EAI est ${stronger}. Priorites recommandees: renforcer les troncons critiques, securiser l'alimentation electrique des ouvrages d'eau et prevoir des plans de continuité en cas de cyclone majeur.`
  ];
  els.conclusionText.textContent = txt.join(' ');
}

function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function filteredTerritories() {
  const result = getActiveResult();
  if (!result) return [];
  let rows = [...(result.territory_results || [])];
  if (state.territorySearch) {
    const q = state.territorySearch.toLowerCase();
    rows = rows.filter((r) => String(r.territory_label || '').toLowerCase().includes(q) || String(r.territory_id || '').toLowerCase().includes(q));
  }
  rows.sort((a, b) => {
    const key = currentHazardKey() === 'storm_cmcc' ? 'risk_index_cmcc' : 'risk_index_storm';
    return (Number(b[key]) || 0) - (Number(a[key]) || 0);
  });
  return rows;
}

function riskForHazard(row, hazardKey) {
  return hazardKey === 'storm_cmcc' ? Number(row.risk_index_cmcc || 0) : Number(row.risk_index_storm || 0);
}

function eaiForHazard(row, hazardKey) {
  return hazardKey === 'storm_cmcc' ? Number(row.eai_cmcc_eur || 0) : Number(row.eai_storm_eur || 0);
}

function renderTerritoryTable() {
  const result = getActiveResult();
  if (!result) {
    els.territoryTableBody.innerHTML = '<tr><td colspan="6">No data loaded.</td></tr>';
    return;
  }
  const rows = filteredTerritories();
  els.tableCaption.textContent = `${rows.length} territory row(s) · source ${result.meta?.source || 'unknown'} · hazard ${getHazardLabel(currentHazardKey())}`;

  if (!rows.length) {
    els.territoryTableBody.innerHTML = '<tr><td colspan="6">No territories match the filter.</td></tr>';
    return;
  }

  els.territoryTableBody.innerHTML = rows.map((row) => {
    const activeClass = state.selectedTerritoryId === row.territory_id ? 'active' : '';
    return `
      <tr class="${activeClass}" data-territory-id="${escapeHtml(row.territory_id)}">
        <td>${escapeHtml(row.territory_label)}</td>
        <td class="num">${escapeHtml(numberFmt.format((row.exposure_eur || 0) / 1_000_000))}</td>
        <td class="num">${escapeHtml(numberFmt.format((row.eai_storm_eur || 0) / 1_000_000))}</td>
        <td class="num">${escapeHtml(numberFmt.format((row.eai_cmcc_eur || 0) / 1_000_000))}</td>
        <td class="num">${escapeHtml(formatRisk(row.risk_index_storm))}</td>
        <td class="num">${escapeHtml(formatRisk(row.risk_index_cmcc))}</td>
      </tr>
    `;
  }).join('');

  Array.from(els.territoryTableBody.querySelectorAll('tr[data-territory-id]')).forEach((tr) => {
    tr.addEventListener('click', () => {
      const id = tr.getAttribute('data-territory-id');
      state.selectedTerritoryId = state.selectedTerritoryId === id ? null : id;
      renderTerritorySelectionState();
      renderKpis();
      renderMap();
      renderTerritoryTable();
    });
  });
}

function renderTerritorySelectionState() {
  if (!state.selectedTerritoryId) {
    els.selectedTerritoryChip.textContent = 'No territory selected';
    return;
  }
  const result = getActiveResult();
  const row = (result?.territory_results || []).find((x) => x.territory_id === state.selectedTerritoryId);
  els.selectedTerritoryChip.textContent = row ? `Selected: ${row.territory_label}` : 'No territory selected';
}

function getRiskColor(risk) {
  if (risk >= 80) return '#d94832';
  if (risk >= 70) return '#ea7b2f';
  if (risk >= 60) return '#d8ba5e';
  return '#45b493';
}

function getRadius(val, min, max) {
  if (!Number.isFinite(val)) return 8;
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return 12;
  return 7 + ((val - min) / (max - min)) * 18;
}

function ensureMap() {
  if (mapRef.instance) return true;
  if (!window.L) return false;

  mapRef.instance = L.map(els.mapContainer, { zoomControl: true }).setView([16.35, -61.55], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 12,
    minZoom: 2,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(mapRef.instance);

  mapRef.markersLayer = L.layerGroup().addTo(mapRef.instance);
  mapRef.drawnItems = L.featureGroup().addTo(mapRef.instance);

  if (window.L.Control && window.L.Control.Draw) {
    mapRef.drawControl = new L.Control.Draw({
      edit: { featureGroup: mapRef.drawnItems },
      draw: {
        polygon: { allowIntersection: false, shapeOptions: { color: '#4bb1cb', weight: 2, fillOpacity: 0.12 } },
        rectangle: { shapeOptions: { color: '#4bb1cb', weight: 2, fillOpacity: 0.12 } },
        polyline: { shapeOptions: { color: '#dfb85a', weight: 3, opacity: 0.9 } },
        marker: true,
        circle: { shapeOptions: { color: '#db6b48', weight: 2, fillOpacity: 0.1 } },
        circlemarker: false
      }
    });
    mapRef.instance.addControl(mapRef.drawControl);

    const onDrawChange = () => {
      renderDrawPreview();
      els.clearDrawingsBtn.disabled = mapRef.drawnItems.getLayers().length === 0;
      els.submitDrawingBtn.disabled = mapRef.drawnItems.getLayers().length === 0;
    };

    mapRef.instance.on(L.Draw.Event.CREATED, (evt) => {
      const drawCategory = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
      evt.layer.feature = evt.layer.feature || { type: 'Feature', properties: {} };
      evt.layer.feature.properties = {
        ...(evt.layer.feature.properties || {}),
        exposure_category: drawCategory
      };
      mapRef.drawnItems.addLayer(evt.layer);
      onDrawChange();
    });
    mapRef.instance.on(L.Draw.Event.EDITED, onDrawChange);
    mapRef.instance.on(L.Draw.Event.DELETED, onDrawChange);
  }

  state.mapReady = true;
  return true;
}

function renderMap() {
  const result = getActiveResult();
  if (!result) return;

  if (!window.L) {
    els.mapFallback.hidden = false;
    els.mapFallback.textContent = 'Leaflet could not be loaded. The map is unavailable.';
    return;
  }
  els.mapFallback.hidden = true;
  els.mapFallback.textContent = '';

  if (!ensureMap()) {
    els.mapFallback.hidden = false;
    els.mapFallback.textContent = 'Map initialization failed.';
    return;
  }

  const rows = (result.territory_results || []).filter((row) => Number.isFinite(row.lat) && Number.isFinite(row.lon));
  const hazardKey = currentHazardKey();
  els.mapCaption.textContent = `Marker size = exposure, color = risk index (${getHazardLabel(hazardKey)}). Click a marker to highlight a territory.`;

  mapRef.markerByTerritoryId.clear();
  mapRef.markersLayer.clearLayers();

  if (!rows.length) {
    els.mapFallback.hidden = false;
    els.mapFallback.textContent = 'No mappable centroids in this result set. Aggregate results remain available in the table and charts.';
    return;
  }

  const exposures = rows.map((r) => Number(r.exposure_eur || 0));
  const min = Math.min(...exposures);
  const max = Math.max(...exposures);
  const bounds = [];

  rows.forEach((row) => {
    const risk = riskForHazard(row, hazardKey);
    const marker = L.circleMarker([row.lat, row.lon], {
      radius: getRadius(Number(row.exposure_eur || 0), min, max),
      color: state.selectedTerritoryId === row.territory_id ? '#ffffff' : 'rgba(8, 16, 22, 0.75)',
      weight: state.selectedTerritoryId === row.territory_id ? 2.5 : 1.3,
      fillColor: getRiskColor(risk),
      fillOpacity: state.selectedTerritoryId === row.territory_id ? 0.95 : 0.84
    });
    marker.bindTooltip(
      [
        `<strong>${escapeHtml(row.territory_label)}</strong>`,
        `Exposure: ${escapeHtml(formatMoneyMEUR(row.exposure_eur))}`,
        `EAI (${escapeHtml(getHazardLabel(hazardKey))}): ${escapeHtml(formatMoneyMEUR(eaiForHazard(row, hazardKey)))}`,
        `Risk index: ${escapeHtml(formatRisk(risk))}`
      ].join('<br/>'),
      { sticky: true }
    );
    marker.on('click', () => {
      state.selectedTerritoryId = state.selectedTerritoryId === row.territory_id ? null : row.territory_id;
      renderTerritorySelectionState();
      renderKpis();
      renderMap();
      renderTerritoryTable();
    });
    marker.addTo(mapRef.markersLayer);
    mapRef.markerByTerritoryId.set(row.territory_id, marker);
    bounds.push([row.lat, row.lon]);
  });

  if (!mapRef.hasFitted && bounds.length) {
    mapRef.instance.fitBounds(bounds, { padding: [22, 22], maxZoom: 8 });
    mapRef.hasFitted = true;
  }

  setTimeout(() => mapRef.instance && mapRef.instance.invalidateSize(), 0);
}

function getWindColor(value, min, max) {
  const span = Math.max(0.0001, (max - min) || 1);
  const t = Math.max(0, Math.min(1, (value - min) / span));
  if (t >= 0.9) return '#b10026';
  if (t >= 0.75) return '#e31a1c';
  if (t >= 0.6) return '#fd8d3c';
  if (t >= 0.45) return '#feb24c';
  if (t >= 0.3) return '#fee391';
  return '#d9f0a3';
}

function clamp01(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(1, numeric));
}

function currentWindOpacityFactor() {
  return clamp01(state.windLayerOpacity ?? 0.82);
}

function updateWindOpacityUi() {
  const factor = currentWindOpacityFactor();
  if (els.windOpacitySlider) els.windOpacitySlider.value = String(Math.round(factor * 100));
  if (els.windOpacityValue) els.windOpacityValue.textContent = `${Math.round(factor * 100)}%`;
}

function syncWindOpacityFromSlider({ forceApply = false } = {}) {
  if (!els.windOpacitySlider) return;
  const pct = Number(els.windOpacitySlider.value);
  if (!Number.isFinite(pct)) return;
  const next = clamp01(pct / 100);
  const previous = currentWindOpacityFactor();
  const changed = Math.abs(next - previous) > 0.0001;
  if (changed) state.windLayerOpacity = next;
  updateWindOpacityUi();
  if (changed || forceApply) applyWindLayerOpacity();
}

function applyWindOpacityToMap(hazardKey) {
  const ref = windMapRef[hazardKey];
  if (!ref || !ref.cellsLayer) return;
  const factor = currentWindOpacityFactor();
  ref.cellsLayer.eachLayer((layer) => {
    if (!layer || typeof layer.setStyle !== 'function') return;
    const base = Number(layer.options?.baseFillOpacity);
    const finalOpacity = Number.isFinite(base) ? clamp01(base * factor) : factor;
    layer.setStyle({ fillOpacity: finalOpacity });
  });
}

function applyWindLayerOpacity() {
  applyWindOpacityToMap('storm');
  applyWindOpacityToMap('storm_cmcc');
}

function buildWindLegendHtml(min, max) {
  const steps = [0.95, 0.8, 0.65, 0.5, 0.35, 0.2];
  const rows = steps.map((s) => {
    const value = min + s * (max - min);
    const color = getWindColor(value, min, max);
    return `<div class="wind-legend-row"><span class="wind-legend-swatch" style="background:${color}"></span><span>${numberFmt.format(value)} m/s</span></div>`;
  });
  return [
    '<div class="wind-legend">',
    `<div class="wind-legend-title">Vent moyen</div>`,
    ...rows,
    `<div class="wind-legend-range">${numberFmt.format(min)} - ${numberFmt.format(max)} m/s</div>`,
    '</div>'
  ].join('');
}

function ensureWindLegend(hazardKey, min, max) {
  const ref = windMapRef[hazardKey];
  if (!ref || !ref.instance || !window.L) return;

  if (!ref.legendControl) {
    ref.legendControl = L.control({ position: 'bottomright' });
    ref.legendControl.onAdd = () => {
      const div = L.DomUtil.create('div');
      div.className = 'leaflet-control wind-legend-control';
      return div;
    };
    ref.legendControl.addTo(ref.instance);
  }

  const legendEl = ref.legendControl.getContainer();
  if (legendEl) legendEl.innerHTML = buildWindLegendHtml(min, max);
}

function ensureWindMap(hazardKey) {
  if (!window.L) return null;
  const ref = windMapRef[hazardKey];
  if (!ref) return null;
  if (ref.instance) return ref;

  const container = hazardKey === 'storm' ? els.windMapStorm : els.windMapCmcc;
  if (!container) return null;

  ref.instance = L.map(container, { zoomControl: true, attributionControl: true, preferCanvas: true }).setView([16.25, -61.5], 8);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 11,
    minZoom: 4,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(ref.instance);
  ref.cellsLayer = L.layerGroup().addTo(ref.instance);
  return ref;
}

function nearestWindCellValue(i, j, knownCells, fallbackValue) {
  if (!knownCells.length) return { mean_wind_mps: fallbackValue, sample_count: 0, extrapolated: true };
  let best = null;
  let bestDist = Number.POSITIVE_INFINITY;
  for (let idx = 0; idx < knownCells.length; idx += 1) {
    const cell = knownCells[idx];
    const di = cell.i - i;
    const dj = cell.j - j;
    const d2 = (di * di) + (dj * dj);
    if (d2 < bestDist) {
      bestDist = d2;
      best = cell;
    }
  }
  if (!best) return { mean_wind_mps: fallbackValue, sample_count: 0, extrapolated: true };
  return { mean_wind_mps: best.mean_wind_mps, sample_count: best.sample_count, extrapolated: true };
}

function buildSharedWindGridSpec(payload, meta) {
  const cellDeg = Number(meta?.grid_cell_deg || 0.05);
  const cells = Array.isArray(payload?.cells) ? payload.cells : [];
  if (!cells.length || !Number.isFinite(cellDeg) || cellDeg <= 0) return null;

  let minLat = Number.POSITIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;
  let minLon = Number.POSITIVE_INFINITY;
  let maxLon = Number.NEGATIVE_INFINITY;
  cells.forEach((cell) => {
    const lat = Number(cell.lat);
    const lon = Number(cell.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
    minLon = Math.min(minLon, lon);
    maxLon = Math.max(maxLon, lon);
  });
  if (!Number.isFinite(minLat) || !Number.isFinite(maxLat) || !Number.isFinite(minLon) || !Number.isFinite(maxLon)) {
    return null;
  }

  const half = cellDeg / 2.0;
  const south = minLat - half - (WIND_PADDING_CELLS * cellDeg);
  const north = maxLat + half + (WIND_PADDING_CELLS * cellDeg);
  const west = minLon - half - (WIND_PADDING_CELLS * cellDeg);
  const east = maxLon + half + (WIND_PADDING_CELLS * cellDeg);
  const nLat = Math.max(1, Math.round((north - south) / cellDeg));
  const nLon = Math.max(1, Math.round((east - west) / cellDeg));
  return { cellDeg, south, north, west, east, nLat, nLon };
}

function renderWindMap(hazardKey, payload, meta, options = {}) {
  if (!payload || !Array.isArray(payload.cells)) return;
  const ref = ensureWindMap(hazardKey);
  if (!ref || !ref.cellsLayer) return;

  ref.cellsLayer.clearLayers();
  const cells = payload.cells || [];
  if (!cells.length) return;

  const grid = options.gridSpec || buildSharedWindGridSpec(payload, meta);
  if (!grid) return;

  const min = Number.isFinite(options.colorMin) ? Number(options.colorMin) : Number(payload.mean_wind_min_mps || 0);
  const max = Number.isFinite(options.colorMax) ? Number(options.colorMax) : Number(payload.mean_wind_max_mps || 0);
  const knownCells = [];
  const knownByIndex = new Map();
  const cellDeg = grid.cellDeg;
  const latMin = grid.south;
  const latMax = grid.north;
  const lonMin = grid.west;
  const lonMax = grid.east;
  const nLat = grid.nLat;
  const nLon = grid.nLon;
  const centerLat0 = latMin + (cellDeg / 2.0);
  const centerLon0 = lonMin + (cellDeg / 2.0);

  if (
    !ref.hasFitted
    && Number.isFinite(latMin)
    && Number.isFinite(latMax)
    && Number.isFinite(lonMin)
    && Number.isFinite(lonMax)
  ) {
    ref.instance.fitBounds([[latMin, lonMin], [latMax, lonMax]], { padding: [0, 0], maxZoom: 9 });
    ref.hasFitted = true;
  }

  cells.forEach((cell) => {
    const lat = Number(cell.lat);
    const lon = Number(cell.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    if (!Number.isFinite(centerLat0) || !Number.isFinite(centerLon0) || !Number.isFinite(cellDeg)) return;
    const i = Math.round((lat - centerLat0) / cellDeg);
    const j = Math.round((lon - centerLon0) / cellDeg);
    const key = `${i}|${j}`;
    const observed = {
      i,
      j,
      mean_wind_mps: Number(cell.mean_wind_mps || min),
      sample_count: Number(cell.sample_count || 0)
    };
    knownCells.push(observed);
    if (!knownByIndex.has(key)) knownByIndex.set(key, observed);
  });

  if (
    Number.isFinite(latMin) && Number.isFinite(latMax) && Number.isFinite(lonMin) && Number.isFinite(lonMax) && Number.isFinite(cellDeg)
  ) {
    for (let i = 0; i < nLat; i += 1) {
      for (let j = 0; j < nLon; j += 1) {
        const south = latMin + i * cellDeg;
        const north = south + cellDeg;
        const west = lonMin + j * cellDeg;
        const east = west + cellDeg;
        const key = `${i}|${j}`;
        const observed = knownByIndex.get(key);
        const data = observed || nearestWindCellValue(i, j, knownCells, min);
        const meanWind = Number(data.mean_wind_mps ?? min);
        const sampleCount = Number(data.sample_count ?? 0);
        const extrapolated = !observed;
        const color = getWindColor(meanWind, min, max);
        const baseFillOpacity = extrapolated ? 0.86 : 0.97;
        const finalFillOpacity = clamp01(baseFillOpacity * currentWindOpacityFactor());
        const rect = L.rectangle([[south, west], [north, east]], {
          stroke: false,
          fillColor: color,
          fillOpacity: finalFillOpacity
        });
        rect.options.baseFillOpacity = baseFillOpacity;
        rect.bindTooltip(
          [
            `<strong>${escapeHtml(getHazardLabel(hazardKey))}</strong>`,
            `Mean max wind: ${escapeHtml(numberFmt.format(meanWind))} m/s`,
            `Samples: ${escapeHtml(numberFmt.format(sampleCount))}`,
            extrapolated ? 'Valeur: extrapolee (plus proche maille observee)' : 'Valeur: observee'
          ].join('<br/>'),
          { sticky: true }
        );
        rect.addTo(ref.cellsLayer);
      }
    }
  }

  ensureWindLegend(hazardKey, min, max);

  setTimeout(() => ref.instance && ref.instance.invalidateSize(), 0);
}

function renderWindMaps() {
  const payload = state.windMaps;
  if (!payload) return;
  const meta = payload.meta || {};
  const storm = payload.storm;
  const cmcc = payload.storm_cmcc;

  const sharedCells = [
    ...((storm && Array.isArray(storm.cells)) ? storm.cells : []),
    ...((cmcc && Array.isArray(cmcc.cells)) ? cmcc.cells : [])
  ];
  const sharedGrid = buildSharedWindGridSpec({ cells: sharedCells }, meta);
  const sharedMin = Math.min(
    Number(storm?.mean_wind_min_mps ?? Number.POSITIVE_INFINITY),
    Number(cmcc?.mean_wind_min_mps ?? Number.POSITIVE_INFINITY)
  );
  const sharedMax = Math.max(
    Number(storm?.mean_wind_max_mps ?? Number.NEGATIVE_INFINITY),
    Number(cmcc?.mean_wind_max_mps ?? Number.NEGATIVE_INFINITY)
  );
  const colorMin = Number.isFinite(sharedMin) ? sharedMin : 0;
  const colorMax = Number.isFinite(sharedMax) ? sharedMax : 1;

  if (storm && els.windStormCaption) {
    els.windStormCaption.textContent = `${numberFmt.format(storm.cell_count || 0)} cells observees · extrapolation spatiale active autour de la zone etudiee · ${numberFmt.format(storm.years_covered || 0)} years · echelle commune ${numberFmt.format(colorMin)}-${numberFmt.format(colorMax)} m/s`;
    renderWindMap('storm', storm, meta, { gridSpec: sharedGrid, colorMin, colorMax });
  }
  if (cmcc && els.windCmccCaption) {
    els.windCmccCaption.textContent = `${numberFmt.format(cmcc.cell_count || 0)} cells observees · extrapolation spatiale active autour de la zone etudiee · ${numberFmt.format(cmcc.years_covered || 0)} years · echelle commune ${numberFmt.format(colorMin)}-${numberFmt.format(colorMax)} m/s`;
    renderWindMap('storm_cmcc', cmcc, meta, { gridSpec: sharedGrid, colorMin, colorMax });
  }
  applyWindLayerOpacity();
}

function waterInfraStyle(feature) {
  const t = String(feature?.properties?.infra_type || '').toLowerCase();
  if (t === 'aep_cana') return { color: '#003A76', weight: 1.2, opacity: 0.85 };
  if (t === 'aep_ouvrage') return { color: '#5BC5F2', weight: 1.8, opacity: 0.95 };
  if (t === 'eu_cana') return { color: '#564949', weight: 1.2, opacity: 0.85 };
  if (t === 'eu_pr') return { color: '#9A7867', weight: 1.8, opacity: 0.95 };
  if (t === 'eu_step') return { color: '#CC9F72', weight: 2.2, opacity: 0.95 };
  if (t === 'elec_bt_aerien') return { color: '#6AB96F', weight: 1.2, opacity: 0.85 };
  if (t === 'elec_bt_souterrain') return { color: '#A4A64B', weight: 1.2, opacity: 0.85 };
  if (t === 'elec_hta_aerien') return { color: '#F39655', weight: 1.4, opacity: 0.9 };
  if (t === 'elec_hta_souterrain') return { color: '#FFD744', weight: 1.4, opacity: 0.9 };
  return { color: '#c7d0d8', weight: 1.0, opacity: 0.7 };
}

function ensureWaterLayerState(typeKey) {
  if (state.waterLayerVisibility[typeKey] === undefined) state.waterLayerVisibility[typeKey] = false;
}

function ensureWaterMap() {
  if (!window.L || !els.waterInfraMap) return null;
  if (waterMapRef.instance) return waterMapRef;

  waterMapRef.instance = L.map(els.waterInfraMap, { zoomControl: true, preferCanvas: true }).setView([16.25, -61.5], 8);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 13,
    minZoom: 4,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(waterMapRef.instance);
  return waterMapRef;
}

function buildWaterLayerControls(layerCounts) {
  if (!els.waterLayerControls) return;
  const types = [
    ...WATER_LAYER_ORDER.filter((k) => layerCounts[k] !== undefined),
    ...Object.keys(layerCounts).filter((k) => !WATER_LAYER_ORDER.includes(k)).sort()
  ];

  els.waterLayerControls.innerHTML = types.map((type) => {
    const style = waterInfraStyle({ properties: { infra_type: type } });
    const checked = state.waterLayerVisibility[type] !== false ? 'checked' : '';
    const label = WATER_LAYER_LABEL[type] || type;
    const count = layerCounts[type] || 0;
    return `
      <label class="layer-item">
        <input type="checkbox" data-water-layer="${escapeHtml(type)}" ${checked} />
        <span class="layer-dot" style="background:${escapeHtml(style.color)}"></span>
        <span>${escapeHtml(label)} (${escapeHtml(numberFmt.format(count))})</span>
      </label>
    `;
  }).join('');

  Array.from(els.waterLayerControls.querySelectorAll('input[data-water-layer]')).forEach((input) => {
    input.addEventListener('change', () => {
      const key = input.getAttribute('data-water-layer');
      if (!key) return;
      state.waterLayerVisibility[key] = input.checked;
      renderWaterInfraMap();
    });
  });
}

function ensureWaterLayers(payload) {
  const ref = ensureWaterMap();
  if (!ref || !ref.instance || !payload || !Array.isArray(payload.features)) return null;
  if (ref.layersByType.size > 0) return ref;

  const grouped = new Map();
  payload.features.forEach((feature) => {
    const type = String(feature?.properties?.infra_type || 'unknown');
    if (!grouped.has(type)) grouped.set(type, []);
    grouped.get(type).push(feature);
  });

  const orderedTypes = [
    ...WATER_LAYER_ORDER.filter((k) => grouped.has(k)),
    ...Array.from(grouped.keys()).filter((k) => !WATER_LAYER_ORDER.includes(k)).sort()
  ];
  ref.order = orderedTypes;
  orderedTypes.forEach((type) => {
    ensureWaterLayerState(type);
    const features = grouped.get(type) || [];
    const layer = L.geoJSON({ type: 'FeatureCollection', features }, {
      style: waterInfraStyle,
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        ...waterInfraStyle(feature),
        radius: String(feature?.properties?.infra_type || '') === 'eu_step' ? 4.5 : 3.2,
        fillColor: waterInfraStyle(feature).color,
        fillOpacity: 0.85
      }),
      onEachFeature: (feature, layerItem) => {
        const p = feature?.properties || {};
        layerItem.bindTooltip(
          [
            `<strong>${escapeHtml(String(p.infra_type || 'infra'))}</strong>`,
            `id: ${escapeHtml(String(p.feature_id || 'n/a'))}`,
            `groupe: ${escapeHtml(String(p.source_group || 'n/a'))}`
          ].join('<br/>'),
          { sticky: true }
        );
      }
    });
    ref.layersByType.set(type, { layer, count: features.length });
  });
  return ref;
}

function renderWaterInfraMap() {
  const payload = state.waterInfra;
  const ref = ensureWaterLayers(payload);
  if (!payload || !ref || !ref.instance || !window.L) return;

  const counts = {};
  ref.layersByType.forEach((entry, type) => {
    counts[type] = entry.count;
  });
  buildWaterLayerControls(counts);

  let visibleTotal = 0;
  let visibleTypes = 0;
  let bounds = null;
  ref.order.forEach((type) => {
    const entry = ref.layersByType.get(type);
    if (!entry) return;
    const visible = state.waterLayerVisibility[type] !== false;
    if (visible) {
      if (!ref.instance.hasLayer(entry.layer)) entry.layer.addTo(ref.instance);
      visibleTotal += Number(entry.count || 0);
      visibleTypes += 1;
      const layerBounds = entry.layer.getBounds();
      if (layerBounds && layerBounds.isValid()) {
        bounds = bounds ? bounds.extend(layerBounds) : layerBounds;
      }
    } else if (ref.instance.hasLayer(entry.layer)) {
      ref.instance.removeLayer(entry.layer);
    }
  });

  if (els.waterMapCaption) {
    const activeSummary = ref.order
      .filter((type) => state.waterLayerVisibility[type] !== false)
      .map((type) => `${WATER_LAYER_LABEL[type] || type}: ${numberFmt.format(counts[type] || 0)}`);
    if (!visibleTypes) {
      els.waterMapCaption.textContent = 'Aucune couche selectionnee. Activez au moins une couche pour afficher les infrastructures.';
    } else {
      els.waterMapCaption.textContent = `Visible ${numberFmt.format(visibleTotal)} infrastructures (eau + elec) sur ${numberFmt.format((payload.features || []).length)} (couches actives: ${numberFmt.format(visibleTypes)}). ${activeSummary.join(' · ')}`;
    }
  }

  if (!ref.hasFitted && bounds && bounds.isValid()) {
      ref.instance.fitBounds(bounds, { padding: [18, 18], maxZoom: 11 });
      ref.hasFitted = true;
  }
  setTimeout(() => ref.instance && ref.instance.invalidateSize(), 0);
}

function networkStatePropertyKey() {
  const hazard = state.impactMapHazard === 'storm_cmcc' ? 'storm_cmcc' : 'storm';
  const scenario = state.impactMapScenario === 'annual' ? 'annual' : 'event_max';
  if (hazard === 'storm') return scenario === 'annual' ? 'state_annual_storm' : 'state_event_max_storm';
  return scenario === 'annual' ? 'state_annual_storm_cmcc' : 'state_event_max_storm_cmcc';
}

function networkFeatureState(feature) {
  const key = networkStatePropertyKey();
  const raw = String(feature?.properties?.[key] || 'S0').toUpperCase();
  if (!Object.prototype.hasOwnProperty.call(STATE_COLORS, raw)) return 'S0';
  return raw;
}

function networkStateStyle(feature) {
  const layerKey = String(feature?.properties?.layer_key || '');
  const stateCode = networkFeatureState(feature);
  const weight = layerKey.startsWith('eau_') ? 1.4 : 1.1;
  return {
    color: STATE_COLORS[stateCode] || STATE_COLORS.S0,
    weight,
    opacity: 0.92
  };
}

function ensureNetworkLayerState(typeKey) {
  if (state.networkLayerVisibility[typeKey] === undefined) state.networkLayerVisibility[typeKey] = true;
}

function ensureNetworkMap() {
  if (!window.L || !els.networkStateMap) return null;
  if (networkMapRef.instance) return networkMapRef;

  networkMapRef.instance = L.map(els.networkStateMap, { zoomControl: true, preferCanvas: true }).setView([16.25, -61.5], 8);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 13,
    minZoom: 4,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(networkMapRef.instance);
  return networkMapRef;
}

function buildNetworkLayerControls(layerCounts) {
  if (!els.networkLayerControls) return;
  const types = [
    ...NETWORK_LAYER_ORDER.filter((k) => layerCounts[k] !== undefined),
    ...Object.keys(layerCounts).filter((k) => !NETWORK_LAYER_ORDER.includes(k)).sort()
  ];

  els.networkLayerControls.innerHTML = types.map((type) => {
    const checked = state.networkLayerVisibility[type] !== false ? 'checked' : '';
    const label = NETWORK_LAYER_LABEL[type] || type;
    const count = layerCounts[type] || 0;
    return `
      <label class="layer-item">
        <input type="checkbox" data-network-layer="${escapeHtml(type)}" ${checked} />
        <span class="layer-dot" style="background:${escapeHtml(STATE_COLORS.S0)}"></span>
        <span>${escapeHtml(label)} (${escapeHtml(numberFmt.format(count))})</span>
      </label>
    `;
  }).join('');

  Array.from(els.networkLayerControls.querySelectorAll('input[data-network-layer]')).forEach((input) => {
    input.addEventListener('change', () => {
      const key = input.getAttribute('data-network-layer');
      if (!key) return;
      state.networkLayerVisibility[key] = input.checked;
      renderNetworkStateMap();
    });
  });
}

function ensureNetworkLayers(payload) {
  const ref = ensureNetworkMap();
  if (!ref || !ref.instance || !payload || !Array.isArray(payload.features)) return null;
  if (ref.layersByType.size > 0) return ref;

  const grouped = new Map();
  payload.features.forEach((feature) => {
    const type = String(feature?.properties?.layer_key || 'unknown');
    if (!grouped.has(type)) grouped.set(type, []);
    grouped.get(type).push(feature);
  });

  ref.order = [
    ...NETWORK_LAYER_ORDER.filter((k) => grouped.has(k)),
    ...Array.from(grouped.keys()).filter((k) => !NETWORK_LAYER_ORDER.includes(k)).sort()
  ];

  ref.order.forEach((type) => {
    ensureNetworkLayerState(type);
    const features = grouped.get(type) || [];
    const layer = L.geoJSON({ type: 'FeatureCollection', features }, {
      style: networkStateStyle
    });
    ref.layersByType.set(type, { layer, count: features.length });
  });
  return ref;
}

function refreshNetworkLayerStyles() {
  const ref = networkMapRef;
  ref.layersByType.forEach((entry) => {
    entry.layer.eachLayer((layerItem) => {
      if (!layerItem || typeof layerItem.setStyle !== 'function') return;
      const style = networkStateStyle(layerItem.feature);
      layerItem.setStyle(style);
    });
  });
}

function renderNetworkStateMap() {
  if (!state.networkStates) {
    if (els.networkStateCaption) els.networkStateCaption.textContent = 'Chargement de la carte d etat des reseaux...';
    return;
  }
  const ref = ensureNetworkLayers(state.networkStates);
  if (!ref || !ref.instance || !window.L) return;

  const counts = {};
  ref.layersByType.forEach((entry, type) => {
    counts[type] = entry.count;
  });
  buildNetworkLayerControls(counts);
  refreshNetworkLayerStyles();

  let visibleTotal = 0;
  let visibleTypes = 0;
  let bounds = null;
  ref.order.forEach((type) => {
    const entry = ref.layersByType.get(type);
    if (!entry) return;
    const visible = state.networkLayerVisibility[type] !== false;
    if (visible) {
      if (!ref.instance.hasLayer(entry.layer)) entry.layer.addTo(ref.instance);
      visibleTotal += Number(entry.count || 0);
      visibleTypes += 1;
      const layerBounds = entry.layer.getBounds();
      if (layerBounds && layerBounds.isValid()) {
        bounds = bounds ? bounds.extend(layerBounds) : layerBounds;
      }
    } else if (ref.instance.hasLayer(entry.layer)) {
      ref.instance.removeLayer(entry.layer);
    }
  });

  if (els.networkStateCaption) {
    const hz = getHazardLabel(state.impactMapHazard);
    const sc = state.impactMapScenario === 'annual' ? 'moyenne annuelle' : 'evenement le plus fort';
    if (!visibleTypes) {
      els.networkStateCaption.textContent = 'Aucune couche selectionnee.';
    } else {
      els.networkStateCaption.textContent = `Affichage ${hz} (${sc}) - ${numberFmt.format(visibleTotal)} segments visibles sur ${numberFmt.format((state.networkStates.features || []).length)}.`;
    }
  }

  if (!ref.hasFitted && bounds && bounds.isValid()) {
    ref.instance.fitBounds(bounds, { padding: [18, 18], maxZoom: 11 });
    ref.hasFitted = true;
  }
  setTimeout(() => ref.instance && ref.instance.invalidateSize(), 0);
}

function chartThemeCommon() {
  return {
    backgroundColor: 'transparent',
    grid: { left: 12, right: 16, top: 36, bottom: 28, containLabel: true },
    textStyle: { color: '#edf4f2', fontFamily: 'Marianne' },
    xAxis: {
      axisLine: { lineStyle: { color: 'rgba(177,208,203,0.25)' } },
      axisTick: { show: false },
      axisLabel: { color: '#abc0ba' }
    },
    yAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#abc0ba' },
      splitLine: { lineStyle: { color: 'rgba(177,208,203,0.12)' } }
    }
  };
}

function ensureChart(refKey, domId) {
  if (!window.echarts) return null;
  if (!chartRefs[refKey]) {
    const el = document.getElementById(domId);
    if (!el) return null;
    chartRefs[refKey] = echarts.init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => chartRefs[refKey] && chartRefs[refKey].resize());
  }
  return chartRefs[refKey];
}

function renderHistogramChart(refKey, domId, graph, color) {
  const chart = ensureChart(refKey, domId);
  if (!chart || !graph) return;
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: { trigger: 'axis' },
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: (graph.bins_mps || []).map(String), name: 'm/s' },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '%' },
    series: [{ type: 'bar', data: graph.percent || [], itemStyle: { color }, barMaxWidth: 26 }]
  }, true);
}

function renderHistogramComparisonChart(refKey, domId, graphA, graphB, labelA, labelB, colorA, colorB) {
  const chart = ensureChart(refKey, domId);
  if (!chart || !graphA || !graphB) return;
  const seriesA = (graphA.bins_mps || []).map((x, idx) => [Number(x), Number((graphA.percent || [])[idx] || 0)]);
  const seriesB = (graphB.bins_mps || []).map((x, idx) => [Number(x), Number((graphB.percent || [])[idx] || 0)]);
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: {
      trigger: 'axis',
      valueFormatter: (val) => `${numberFmt.format(Number(val || 0))}%`
    },
    legend: {
      top: 2,
      textStyle: { color: '#abc0ba' }
    },
    xAxis: { ...chartThemeCommon().xAxis, type: 'value', name: 'm/s' },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '%' },
    series: [
      {
        name: labelA,
        type: 'line',
        smooth: true,
        data: seriesA,
        lineStyle: { color: colorA, width: 2 },
        itemStyle: { color: colorA }
      },
      {
        name: labelB,
        type: 'line',
        smooth: true,
        data: seriesB,
        lineStyle: { color: colorB, width: 2 },
        itemStyle: { color: colorB }
      }
    ]
  }, true);
}

function renderAnnualFecChart(refKey, domId, graph, color) {
  const chart = ensureChart(refKey, domId);
  if (!chart || !graph) return;
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: { trigger: 'axis' },
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: (graph.return_period_years || []).map(String), name: 'Years' },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: 'EUR' },
    series: [{ type: 'line', smooth: true, data: graph.damage_eur || [], lineStyle: { color, width: 2 }, itemStyle: { color }, areaStyle: { color: `${color}22` } }]
  }, true);
}

function renderLifetimeFecChart(refKey, domId, graph) {
  const chart = ensureChart(refKey, domId);
  if (!chart || !graph) return;
  const palette = ['#4bb1cb', '#dfb85a', '#db6b48'];
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: { trigger: 'axis' },
    legend: { top: 2, textStyle: { color: '#abc0ba' } },
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: (graph.series?.[0]?.return_period_years || []).map(String), name: 'Years' },
    yAxis: { ...chartThemeCommon().yAxis, type: 'log', name: 'EUR' },
    series: (graph.series || []).map((s, i) => ({
      name: s.name,
      type: 'line',
      step: 'end',
      data: s.damage_eur || [],
      lineStyle: { color: palette[i % palette.length], width: 2 },
      itemStyle: { color: palette[i % palette.length] }
    }))
  }, true);
}

function renderComparisonChart() {
  const result = getActiveResult();
  const comparison = result?.graphs?.comparison?.side_by_side;
  const chart = ensureChart('comparison', 'chart-comparison');
  if (!chart || !comparison) return;
  const hazards = comparison.hazards || ['STORM', 'STORM_CMCC'];
  const annual = comparison.values?.annual_eai || [];
  const maxEvent = comparison.values?.max_event_loss || [];
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 2, textStyle: { color: '#abc0ba' } },
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: hazards },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: 'EUR' },
    series: [
      { name: 'Annual EAI', type: 'bar', data: annual, itemStyle: { color: '#4bb1cb' }, barMaxWidth: 30 },
      { name: 'Max Event Loss', type: 'bar', data: maxEvent, itemStyle: { color: '#dfb85a' }, barMaxWidth: 30 }
    ]
  }, true);
}

function renderImpactBreakdownCharts(impactPayload) {
  const breakdown = impactPayload?.damage_breakdown || null;
  let labels = [];
  let stormEai = [];
  let cmccEai = [];
  let stormEvt = [];
  let cmccEvt = [];

  if (breakdown?.storm && breakdown?.storm_cmcc) {
    const byStorm = new Map((breakdown.storm || []).map((r) => [String(r.class_key), r]));
    const byCmcc = new Map((breakdown.storm_cmcc || []).map((r) => [String(r.class_key), r]));
    const ordered = Array.from(new Set([...byStorm.keys(), ...byCmcc.keys()]));
    ordered.forEach((key) => {
      const s = byStorm.get(key) || {};
      const c = byCmcc.get(key) || {};
      labels.push(String(s.class_label || c.class_label || key));
      stormEai.push(Number(s.eai_eur || 0));
      cmccEai.push(Number(c.eai_eur || 0));
      stormEvt.push(Number(s.event_max_loss_eur || 0));
      cmccEvt.push(Number(c.event_max_loss_eur || 0));
    });
  } else {
    const rows = Array.isArray(impactPayload?.state_damage_table) ? impactPayload.state_damage_table : [];
    rows.forEach((row) => {
      labels.push(String(row.class_label || row.class_key || 'type'));
      stormEai.push(Number(row?.storm?.eai_eur || 0));
      cmccEai.push(Number(row?.storm_cmcc?.eai_eur || 0));
      stormEvt.push(Number(row?.storm?.event_max_loss_eur || 0));
      cmccEvt.push(Number(row?.storm_cmcc?.event_max_loss_eur || 0));
    });
  }

  const eaiChart = ensureChart('impact_eai', 'impact-eai-chart');
  if (eaiChart && labels.length) {
    eaiChart.setOption({
      ...chartThemeCommon(),
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (value) => formatMoneyEUR(value)
      },
      legend: { top: 2, textStyle: { color: '#abc0ba' } },
      xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: labels, axisLabel: { color: '#abc0ba', rotate: 20 } },
      yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '€' },
      series: [
        { name: 'STORM', type: 'bar', data: stormEai, itemStyle: { color: '#0083CB' }, barMaxWidth: 30 },
        { name: 'STORM_CMCC', type: 'bar', data: cmccEai, itemStyle: { color: '#F39655' }, barMaxWidth: 30 }
      ]
    }, true);
  }

  const evtChart = ensureChart('impact_evt', 'impact-evt-chart');
  if (evtChart && labels.length) {
    evtChart.setOption({
      ...chartThemeCommon(),
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (value) => formatMoneyEUR(value)
      },
      legend: { top: 2, textStyle: { color: '#abc0ba' } },
      xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: labels, axisLabel: { color: '#abc0ba', rotate: 20 } },
      yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '€' },
      series: [
        { name: 'STORM', type: 'bar', data: stormEvt, itemStyle: { color: '#00A6E2' }, barMaxWidth: 30 },
        { name: 'STORM_CMCC', type: 'bar', data: cmccEvt, itemStyle: { color: '#A4A64B' }, barMaxWidth: 30 }
      ]
    }, true);
  }
}

function renderHazardCharts() {
  const result = getActiveResult();
  if (!result) return;
  const hazardKey = currentHazardKey();
  const hazardGraphs = result.graphs?.[hazardKey];
  if (!hazardGraphs) return;

  els.chartsCaption.textContent = `Interactive web replica for ${getHazardLabel(hazardKey)} plus a side-by-side comparison. Charts are generated from backend risk outputs (CLIMADA in production mode when available).`;
  els.chartTitle1.textContent = hazardGraphs.wind_year_hist?.title || 'Max wind per year';
  els.chartTitle2.textContent = hazardGraphs.wind_track_hist?.title || 'Max wind per track';
  els.chartTitle3.textContent = hazardGraphs.annual_fec?.title || 'Annual FEC';
  els.chartTitle4.textContent = hazardGraphs.lifetime_fec?.title || 'Lifetime FEC';

  const color = hazardKey === 'storm_cmcc' ? '#db6b48' : '#4bb1cb';
  renderHistogramChart('c1', 'chart-1', hazardGraphs.wind_year_hist, color);
  renderHistogramChart('c2', 'chart-2', hazardGraphs.wind_track_hist, '#dfb85a');
  renderAnnualFecChart('c3', 'chart-3', hazardGraphs.annual_fec, color);
  renderLifetimeFecChart('c4', 'chart-4', hazardGraphs.lifetime_fec);
  renderComparisonChart();
}

function renderArtifactLinks() {
  const result = getActiveResult();
  const downloads = result?.artifacts?.downloads || [];
  const plots = result?.artifacts?.plots_png || [];
  const all = [...downloads, ...plots];
  if (!all.length) {
    els.artifactLinks.innerHTML = '<span class="muted">No downloadable artifacts attached to this result.</span>';
    return;
  }
  els.artifactLinks.innerHTML = all.map((a) => `<a href="${escapeHtml(a.url)}" target="_blank" rel="noopener">${escapeHtml(a.name)}</a>`).join('');
}

function renderNotes() {
  const result = getActiveResult();
  const notes = Array.isArray(result?.notes) ? result.notes : [];
  if (!notes.length) {
    els.notesBox.textContent = 'No notes available for this result.';
    return;
  }
  els.notesBox.innerHTML = `<ul>${notes.slice(0, 8).map((n) => `<li>${escapeHtml(n)}</li>`).join('')}</ul>`;
}

function renderDrawPreview() {
  if (!mapRef.drawnItems) {
    els.drawSummaryList.innerHTML = '<li>Map drawing tools not available.</li>';
    return;
  }
  const layers = mapRef.drawnItems.getLayers();
  if (!layers.length) {
    els.drawSummaryList.innerHTML = '<li>No drawings yet.</li>';
    els.submitDrawingBtn.disabled = true;
    return;
  }
  const counts = { marker: 0, circle: 0, polyline: 0, polygon: 0, rectangle: 0 };
  const categoryCounts = { habitation: 0, ouvrage_eau: 0, ouvrage_electrique: 0 };
  layers.forEach((layer) => {
    if (!window.L) return;
    if (layer instanceof L.Circle) counts.circle += 1;
    else if (layer instanceof L.Marker) counts.marker += 1;
    else if (layer instanceof L.Polygon) counts.polygon += 1;
    else if (layer instanceof L.Polyline) counts.polyline += 1;
    const category = String(layer?.feature?.properties?.exposure_category || els.drawCategory?.value || 'habitation');
    if (Object.prototype.hasOwnProperty.call(categoryCounts, category)) {
      categoryCounts[category] += 1;
    }
  });
  const lines = [`${layers.length} drawing(s) ready for submission.`];
  Object.entries(counts).forEach(([k, v]) => {
    if (v > 0) lines.push(`${k}: ${v}`);
  });
  lines.push(`categories: habitation=${categoryCounts.habitation}, ouvrage_eau=${categoryCounts.ouvrage_eau}, ouvrage_electrique=${categoryCounts.ouvrage_electrique}`);
  lines.push(`MVP backend fallback uses default value per drawn feature and returns an ephemeral job result.`);
  els.drawSummaryList.innerHTML = lines.map((l) => `<li>${escapeHtml(l)}</li>`).join('');
  els.submitDrawingBtn.disabled = layers.length === 0;
}

function filterResultToSelectedTerritory(result) {
  if (!result || !state.selectedTerritoryId) return result;
  const row = (result.territory_results || []).find((x) => x.territory_id === state.selectedTerritoryId);
  if (!row) return result;

  const clone = deepClone(result);
  clone.territory_results = [row];
  const storm = {
    eai_eur: row.eai_storm_eur,
    aai_agg_eur: row.eai_storm_eur,
    max_event_loss_eur: row.eai_storm_eur * 4.0
  };
  const cmcc = {
    eai_eur: row.eai_cmcc_eur,
    aai_agg_eur: row.eai_cmcc_eur,
    max_event_loss_eur: row.eai_cmcc_eur * 4.2
  };
  clone.portfolio_results = {
    storm,
    storm_cmcc: cmcc,
    delta: {
      eai_eur: cmcc.eai_eur - storm.eai_eur,
      eai_pct: storm.eai_eur ? ((cmcc.eai_eur / storm.eai_eur) - 1) * 100 : 0
    }
  };
  clone.exposure_summary.total_exposure_eur = row.exposure_eur;
  clone.exposure_summary.asset_count_original = 1;
  return clone;
}

function renderAll() {
  renderWindMaps();
  renderWaterInfraMap();
  renderInfraSummary();
  if (state.currentPage === 'page1') {
    ensureNetworkStatesLoaded();
  }
  renderNetworkStateMap();

  if (!state.activeResult) {
    return;
  }
  if (state.selectedTerritoryId && !(state.activeResult.territory_results || []).some((x) => x.territory_id === state.selectedTerritoryId)) {
    state.selectedTerritoryId = null;
  }
  updateMetaBadges();
  renderNotes();

  if (state.currentPage === 'page2') {
    renderTerritorySelectionState();
    renderKpis();
    renderMap();
    renderTerritoryTable();
    renderHazardCharts();
    renderArtifactLinks();
  }
}

function setActiveResult(result, mode = state.selectedDatasetMode) {
  ensureResultShape(result);
  state.activeResult = result;
  if (mode) state.resultsByMode[mode] = result;
  renderAll();
}

async function fetchDemoResult() {
  const urls = [
    new URL('/data/guadeloupe-complete-analysis.json', window.location.origin).toString(),
    new URL('/data/sib-thesis-demo.json', window.location.origin).toString()
  ];
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return ensureResultShape(await res.json());
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error('Unable to load demo result');
}

async function fetchWindMaps() {
  const urls = [new URL('/data/guadeloupe-wind-maps.json', window.location.origin).toString()];
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      if (!payload || !payload.storm || !payload.storm_cmcc) {
        throw new Error('Invalid wind map payload');
      }
      return payload;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error('Unable to load wind map payload');
}

async function fetchWaterInfra() {
  const url = new URL('/data/guadeloupe-water-infra.geojson', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    throw new Error('Invalid water infrastructure payload');
  }
  return payload;
}

async function fetchPage1Analysis() {
  const url = new URL('/data/guadeloupe-page1-analysis.json', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || !payload.exposition || !payload.hazard || !payload.impact || !payload.conclusion) {
    throw new Error('Invalid page1 analysis payload');
  }
  return payload;
}

async function fetchNetworkStates() {
  const url = new URL('/data/guadeloupe-network-states.geojson', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    throw new Error('Invalid network state payload');
  }
  return payload;
}

function ensureNetworkStatesLoaded() {
  if (state.networkStates) return;
  if (state.networkStatesPromise) return;
  state.networkStatesPromise = fetchNetworkStates()
    .then((payload) => {
      state.networkStates = payload;
    })
    .catch((err) => {
      console.warn('Network states could not be loaded', err);
      if (els.networkStateCaption) {
        els.networkStateCaption.textContent = 'Donnees d etat des reseaux indisponibles.';
      }
    })
    .finally(() => {
      state.networkStatesPromise = null;
      renderNetworkStateMap();
    });
}

function stopPolling() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollJob(jobId, { modeTarget = 'uploaded', immediate = false } = {}) {
  stopPolling();
  state.currentJobId = jobId;
  state.pollingModeTarget = modeTarget;
  if (els.pollJobId && !els.pollJobId.value) els.pollJobId.value = jobId;

  const runOnce = async () => {
    try {
      const res = await fetch(`/api/v1/runs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const job = await res.json();
      const msg = `${job.job_id} · ${job.status} · ${job.stage} · ${Math.round((job.progress || 0) * 100)}%${job.message ? ` · ${job.message}` : ''}`;
      setStatus(msg, job.status === 'failed' ? 'error' : (job.status === 'completed' ? 'success' : 'info'));

      if (job.status === 'completed') {
        const resultRes = await fetch(`/api/v1/runs/${encodeURIComponent(jobId)}/result`, { cache: 'no-store' });
        if (!resultRes.ok) throw new Error(`Result HTTP ${resultRes.status}`);
        const payload = ensureResultShape(await resultRes.json());
        state.resultsByMode[modeTarget] = payload;
        state.selectedDatasetMode = modeTarget;
        els.datasetSelect.value = modeTarget;
        setActiveResult(payload, modeTarget);
        stopPolling();
        return;
      }

      if (job.status === 'failed' || job.status === 'expired') {
        stopPolling();
        return;
      }

      state.pollTimer = setTimeout(runOnce, 1800);
    } catch (err) {
      setStatus(`Polling error for ${jobId}: ${err.message}`, 'error');
      stopPolling();
    }
  };

  if (immediate) {
    await runOnce();
  } else {
    state.pollTimer = setTimeout(runOnce, 300);
  }
}

async function submitUpload(event) {
  event.preventDefault();
  clearError();
  const file = els.uploadFile.files?.[0];
  if (!file) {
    showError('Select a file before submitting an uploaded exposure run.');
    return;
  }

  const form = new FormData();
  form.append('input_mode', 'file');
  form.append('exposure_file', file);
  if (els.valueField.value.trim()) form.append('value_field', els.valueField.value.trim());
  if (els.idField.value.trim()) form.append('id_field', els.idField.value.trim());
  if (els.assetTypeField.value.trim()) form.append('asset_type_field', els.assetTypeField.value.trim());
  if (els.categoryField.value.trim()) form.append('exposure_category_field', els.categoryField.value.trim());
  form.append('default_exposure_category', (els.defaultCategory?.value || 'habitation').trim() || 'habitation');
  if (els.crsField.value.trim()) form.append('crs', els.crsField.value.trim());
  if (els.spacingField.value) form.append('sampling_spacing_m', els.spacingField.value);
  if (els.runLabel.value.trim()) form.append('run_label', els.runLabel.value.trim());

  els.uploadSubmitBtn.disabled = true;
  setStatus('Submitting uploaded exposure run…', 'info');
  try {
    const res = await fetch('/api/v1/runs', { method: 'POST', body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    setStatus(`Job accepted: ${payload.job_id}. Queueing upload run.`, 'info');
    state.selectedDatasetMode = 'uploaded';
    els.datasetSelect.value = 'uploaded';
    els.pollJobId.value = payload.job_id;
    await pollJob(payload.job_id, { modeTarget: 'uploaded', immediate: true });
  } catch (err) {
    showError(`Upload run failed to start: ${err.message}`);
    setStatus(`Upload run failed to start: ${err.message}`, 'error');
  } finally {
    els.uploadSubmitBtn.disabled = false;
  }
}

function getDrawnFeatureCollection() {
  if (!mapRef.drawnItems) return null;
  const layers = mapRef.drawnItems.getLayers();
  if (!layers.length) return null;
  const defaultCategory = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
  const features = layers.map((layer) => {
    const gj = layer.toGeoJSON();
    const currentCategory = String(layer?.feature?.properties?.exposure_category || gj?.properties?.exposure_category || defaultCategory);
    gj.properties = {
      ...(gj.properties || {}),
      exposure_category: currentCategory
    };
    layer.feature = layer.feature || { type: 'Feature', properties: {} };
    layer.feature.properties = {
      ...(layer.feature.properties || {}),
      exposure_category: currentCategory
    };
    return gj;
  });
  return { type: 'FeatureCollection', features };
}

async function submitDrawnExposure() {
  clearError();
  const fc = getDrawnFeatureCollection();
  if (!fc) {
    showError('Draw at least one geometry before submitting a drawn exposure run.');
    return;
  }

  const form = new FormData();
  form.append('input_mode', 'drawn_geojson');
  form.append('drawn_geojson', JSON.stringify(fc));
  form.append('default_exposure_category', (els.drawCategory?.value || 'habitation').trim() || 'habitation');
  if (els.spacingField.value) form.append('sampling_spacing_m', els.spacingField.value);
  if (els.runLabel.value.trim()) form.append('run_label', `${els.runLabel.value.trim()} (drawn)`);

  els.submitDrawingBtn.disabled = true;
  setStatus('Submitting drawn exposure run…', 'info');
  try {
    const res = await fetch('/api/v1/runs', { method: 'POST', body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
    setStatus(`Job accepted: ${payload.job_id}. Queueing drawn run.`, 'info');
    state.selectedDatasetMode = 'drawn';
    els.datasetSelect.value = 'drawn';
    els.pollJobId.value = payload.job_id;
    await pollJob(payload.job_id, { modeTarget: 'drawn', immediate: true });
  } catch (err) {
    showError(`Drawn exposure run failed to start: ${err.message}`);
    setStatus(`Drawn exposure run failed to start: ${err.message}`, 'error');
  } finally {
    els.submitDrawingBtn.disabled = mapRef.drawnItems ? mapRef.drawnItems.getLayers().length === 0 : true;
  }
}

function switchDatasetMode(mode) {
  state.selectedDatasetMode = mode;
  if (mode === 'demo') {
    state.selectedTerritoryId = null;
    setActiveResult(state.resultsByMode.demo, 'demo');
    return;
  }

  const candidate = state.resultsByMode[mode];
  if (!candidate) {
    setStatus(`No ${mode} result has been computed yet. Showing demo SIB example.`, 'info');
    els.datasetSelect.value = 'demo';
    state.selectedDatasetMode = 'demo';
    setActiveResult(state.resultsByMode.demo, 'demo');
    return;
  }

  state.selectedTerritoryId = null;
  setActiveResult(candidate, mode);
}

function bindEvents() {
  if (els.navPage1) {
    els.navPage1.addEventListener('click', () => {
      setActivePage('page1');
      renderAll();
    });
  }
  if (els.navPage2) {
    els.navPage2.addEventListener('click', () => {
      setActivePage('page2');
      renderAll();
    });
  }
  if (els.navPage3) {
    els.navPage3.addEventListener('click', () => {
      setActivePage('page3');
      renderAll();
    });
  }
  window.addEventListener('hashchange', () => {
    setActivePage(pageFromHash(), { updateHash: false });
    renderAll();
  });

  els.hazardSelect.addEventListener('change', () => {
    state.selectedHazard = els.hazardSelect.value;
    renderAll();
  });

  els.datasetSelect.addEventListener('change', () => {
    switchDatasetMode(els.datasetSelect.value);
  });

  if (els.windOpacitySlider) {
    const onWindOpacityChange = () => syncWindOpacityFromSlider({ forceApply: true });
    const sliderEvents = ['input', 'change', 'pointermove', 'pointerup', 'touchmove', 'touchend', 'mousemove', 'mouseup', 'keyup'];
    sliderEvents.forEach((eventName) => {
      els.windOpacitySlider.addEventListener(eventName, onWindOpacityChange);
    });
    updateWindOpacityUi();
    syncWindOpacityFromSlider({ forceApply: true });
  }

  if (els.impactMapHazardSelect) {
    els.impactMapHazardSelect.value = state.impactMapHazard;
    els.impactMapHazardSelect.addEventListener('change', () => {
      state.impactMapHazard = els.impactMapHazardSelect.value === 'storm_cmcc' ? 'storm_cmcc' : 'storm';
      renderNetworkStateMap();
    });
  }
  if (els.impactMapScenarioSelect) {
    els.impactMapScenarioSelect.value = state.impactMapScenario;
    els.impactMapScenarioSelect.addEventListener('change', () => {
      state.impactMapScenario = els.impactMapScenarioSelect.value === 'annual' ? 'annual' : 'event_max';
      renderNetworkStateMap();
    });
  }

  els.resetDemoBtn.addEventListener('click', () => {
    stopPolling();
    state.selectedTerritoryId = null;
    state.selectedDatasetMode = 'demo';
    els.datasetSelect.value = 'demo';
    setActiveResult(state.resultsByMode.demo, 'demo');
    setStatus('Reset to the Guadeloupe complete reference result.', 'success');
    setActivePage('page1');
  });

  els.reloadJobBtn.addEventListener('click', async () => {
    const jobId = els.pollJobId.value.trim();
    if (!jobId) {
      showError('Enter a job ID to reload a previous result.');
      return;
    }
    const target = els.datasetSelect.value === 'drawn' ? 'drawn' : 'uploaded';
    await pollJob(jobId, { modeTarget: target, immediate: true });
  });

  els.uploadForm.addEventListener('submit', submitUpload);
  els.submitDrawingBtn.addEventListener('click', submitDrawnExposure);
  els.refreshPreviewBtn.addEventListener('click', renderDrawPreview);
  if (els.drawCategory) {
    els.drawCategory.addEventListener('change', () => {
      if (!mapRef.drawnItems) return;
      mapRef.drawnItems.getLayers().forEach((layer) => {
        layer.feature = layer.feature || { type: 'Feature', properties: {} };
        layer.feature.properties = {
          ...(layer.feature.properties || {}),
          exposure_category: els.drawCategory.value
        };
      });
      renderDrawPreview();
    });
  }

  els.clearDrawingsBtn.addEventListener('click', () => {
    if (!mapRef.drawnItems) return;
    mapRef.drawnItems.clearLayers();
    renderDrawPreview();
    els.clearDrawingsBtn.disabled = true;
    els.submitDrawingBtn.disabled = true;
  });

  els.territorySearch.addEventListener('input', () => {
    state.territorySearch = els.territorySearch.value.trim();
    if (state.currentPage === 'page2') renderTerritoryTable();
  });

  els.clearTerritoryFilterBtn.addEventListener('click', () => {
    els.territorySearch.value = '';
    state.territorySearch = '';
    state.selectedTerritoryId = null;
    renderAll();
  });
}

async function bootstrap() {
  try {
    clearError();
    bindEvents();
    setActivePage(pageFromHash(), { updateHash: false });
    renderDrawPreview();
    state.windMaps = await fetchWindMaps().catch((err) => {
      console.warn('Wind maps could not be loaded', err);
      return null;
    });
    if (!state.windMaps) {
      if (els.windStormCaption) els.windStormCaption.textContent = 'Donnees vent indisponibles.';
      if (els.windCmccCaption) els.windCmccCaption.textContent = 'Donnees vent indisponibles.';
    }

    state.waterInfra = await fetchWaterInfra().catch((err) => {
      console.warn('Water infrastructures could not be loaded', err);
      return null;
    });
    if (!state.waterInfra && els.waterMapCaption) {
      els.waterMapCaption.textContent = "Donnees infrastructures d'eau indisponibles.";
    }

    state.page1Analysis = await fetchPage1Analysis().catch((err) => {
      console.warn('Page 1 analysis payload could not be loaded', err);
      return null;
    });
    if (!state.page1Analysis) {
      if (els.expositionSummaryText) els.expositionSummaryText.textContent = "Donnees d'exposition indisponibles.";
      if (els.hazardSummaryText) els.hazardSummaryText.textContent = "Donnees d'alea indisponibles.";
      if (els.impactSummaryText) els.impactSummaryText.textContent = "Donnees d'impact indisponibles.";
      if (els.conclusionText) els.conclusionText.textContent = 'Conclusion indisponible.';
    }

    const demo = await fetchDemoResult();
    state.demoResult = demo;
    state.resultsByMode.demo = demo;
    state.activeResult = demo;
    updateMetaBadges();
    renderAll();
    setStatus('Loaded Guadeloupe complete reference result. Submit an upload or a drawn exposure to start an async run.', 'success');
  } catch (err) {
    console.error(err);
    showError(`Startup error: ${err.message}`);
    setStatus(`Startup error: ${err.message}`, 'error');
    renderAll();
  }
}

bootstrap();
