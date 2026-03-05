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
  'AEP canalisations (Guadeloupe): 776 386 EUR/km',
  'EU canalisations (Guadeloupe): 791 691 EUR/km',
  'EU PR (Guadeloupe): 523 211 EUR/unite',
  'EU STEP (Guadeloupe): 7 777 800 EUR/unite',
  'AEP ouvrages: valeur fixe par ovrg_type (TRAIT/STPMP/CAP/CUV/autres)',
  'Source OFB: comparateur de couts, moyenne territoriale observee'
];

const chartRefs = {
  c1: null,
  c2: null,
  c3: null,
  c4: null,
  comparison: null,
  page1_year_compare: null,
  page1_track_compare: null,
  impact_eai_water: null,
  impact_eai_elec: null,
  impact_rp100_water: null,
  impact_rp100_elec: null,
  impact_rp1000_water: null,
  impact_rp1000_elec: null,
  impact_evt_water: null,
  impact_evt_elec: null,
  user_impact_eai: null,
  user_impact_rp100: null,
  user_impact_rp1000: null,
  user_impact_eventmax: null
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
  expositionNetworkTableBody: document.getElementById('exposition-network-table-body'),
  expositionOuvrageTableBody: document.getElementById('exposition-ouvrage-table-body'),
  expositionTotalNetworks: document.getElementById('exposition-total-networks'),
  expositionTotalOuvrages: document.getElementById('exposition-total-ouvrages'),
  expositionTotalValue: document.getElementById('exposition-total-value'),
  hazardGuadeloupeCompareBody: document.getElementById('hazard-guadeloupe-compare-body'),
  page1ChartYearCompare: document.getElementById('page1-chart-year-compare'),
  page1ChartTrackCompare: document.getElementById('page1-chart-track-compare'),
  impactSummaryText: document.getElementById('impact-summary-text'),
  impactTableAnnualBody: document.getElementById('impact-table-annual-body'),
  impactTableRp100Body: document.getElementById('impact-table-rp100-body'),
  impactTableRp1000Body: document.getElementById('impact-table-rp1000-body'),
  impactTableEventmaxBody: document.getElementById('impact-table-eventmax-body'),
  impactEaiWaterChart: document.getElementById('impact-eai-water-chart'),
  impactEaiElecChart: document.getElementById('impact-eai-elec-chart'),
  impactRp100WaterChart: document.getElementById('impact-rp100-water-chart'),
  impactRp100ElecChart: document.getElementById('impact-rp100-elec-chart'),
  impactRp1000WaterChart: document.getElementById('impact-rp1000-water-chart'),
  impactRp1000ElecChart: document.getElementById('impact-rp1000-elec-chart'),
  impactEvtWaterChart: document.getElementById('impact-evt-water-chart'),
  impactEvtElecChart: document.getElementById('impact-evt-elec-chart'),
  userImpactSummaryText: document.getElementById('user-impact-summary-text'),
  userImpactEaiChart: document.getElementById('user-impact-eai-chart'),
  userImpactRp100Chart: document.getElementById('user-impact-rp100-chart'),
  userImpactRp1000Chart: document.getElementById('user-impact-rp1000-chart'),
  userImpactEventmaxChart: document.getElementById('user-impact-eventmax-chart'),
  userConclusionText: document.getElementById('user-conclusion-text'),
  impactMapHazardSelect: document.getElementById('impact-map-hazard-select'),
  impactMapScenarioSelect: document.getElementById('impact-map-scenario-select'),
  networkLayerControls: document.getElementById('network-layer-controls'),
  networkStateMap: document.getElementById('network-state-map'),
  networkStateCaption: document.getElementById('network-state-caption'),
  conclusionText: document.getElementById('conclusion-text'),
  methodValuationOfb: document.getElementById('method-valuation-ofb')
};

const numberFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const percentFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const moneyFmt = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const FIXED_SAMPLING_SPACING_M = 100;
const dateFmt = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
});

const EXPOSURE_TYPE_TO_CATEGORY = {
  habitation: 'habitation',
  eau_aep: 'ouvrage_eau',
  eau_eu: 'ouvrage_eau',
  elec_bt_souterrain: 'ouvrage_electrique',
  elec_bt_aerien: 'ouvrage_electrique',
  elec_hta_souterrain: 'ouvrage_electrique',
  elec_hta_aerien: 'ouvrage_electrique',
  eau_eu_pr: 'ouvrage_eau',
  eau_eu_step: 'ouvrage_eau',
  aep_ouvrage_trait: 'ouvrage_eau',
  aep_ouvrage_stpmp: 'ouvrage_eau',
  aep_ouvrage_cap: 'ouvrage_eau',
  aep_ouvrage_cuv: 'ouvrage_eau',
  aep_ouvrage_autres: 'ouvrage_eau'
};

const EXPOSURE_TYPE_TO_ASSET = {
  habitation: 'habitation',
  eau_aep: 'eau_aep_cana',
  eau_eu: 'eau_eu_cana',
  elec_bt_souterrain: 'elec_bt_souterrain',
  elec_bt_aerien: 'elec_bt_aerien',
  elec_hta_souterrain: 'elec_hta_souterrain',
  elec_hta_aerien: 'elec_hta_aerien',
  eau_eu_pr: 'eau_eu_pr',
  eau_eu_step: 'eau_eu_step',
  aep_ouvrage_trait: 'eau_aep_ouvrage_TRAIT',
  aep_ouvrage_stpmp: 'eau_aep_ouvrage_STPMP',
  aep_ouvrage_cap: 'eau_aep_ouvrage_CAP',
  aep_ouvrage_cuv: 'eau_aep_ouvrage_CUV',
  aep_ouvrage_autres: 'eau_aep_ouvrage_NA'
};

const EXPOSURE_TYPE_LABEL = {
  habitation: 'Habitation',
  eau_aep: 'Réseau eau AEP',
  eau_eu: 'Réseau eau EU',
  elec_bt_souterrain: 'Réseau élec basse tension souterrain',
  elec_bt_aerien: 'Réseau élec basse tension aérien',
  elec_hta_souterrain: 'Réseau élec haute tension souterrain',
  elec_hta_aerien: 'Réseau élec haute tension aérien',
  eau_eu_pr: 'Poste de refoulement EU',
  eau_eu_step: 'STEP',
  aep_ouvrage_trait: 'Ouvrage AEP TRAIT',
  aep_ouvrage_stpmp: 'Ouvrage AEP STPMP',
  aep_ouvrage_cap: 'Ouvrage AEP CAP',
  aep_ouvrage_cuv: 'Ouvrage AEP CUV',
  aep_ouvrage_autres: 'Ouvrage AEP autre'
};

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
      if (chartRefs.user_impact_eai) chartRefs.user_impact_eai.resize();
      if (chartRefs.user_impact_rp100) chartRefs.user_impact_rp100.resize();
      if (chartRefs.user_impact_rp1000) chartRefs.user_impact_rp1000.resize();
      if (chartRefs.user_impact_eventmax) chartRefs.user_impact_eventmax.resize();
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
      if (chartRefs.impact_eai_water) chartRefs.impact_eai_water.resize();
      if (chartRefs.impact_eai_elec) chartRefs.impact_eai_elec.resize();
      if (chartRefs.impact_rp100_water) chartRefs.impact_rp100_water.resize();
      if (chartRefs.impact_rp100_elec) chartRefs.impact_rp100_elec.resize();
      if (chartRefs.impact_rp1000_water) chartRefs.impact_rp1000_water.resize();
      if (chartRefs.impact_rp1000_elec) chartRefs.impact_rp1000_elec.resize();
      if (chartRefs.impact_evt_water) chartRefs.impact_evt_water.resize();
      if (chartRefs.impact_evt_elec) chartRefs.impact_evt_elec.resize();
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
  if (!raw || typeof raw !== 'object') throw new Error('Payload résultat invalide');
  if (!raw.meta || !raw.exposure_summary || !Array.isArray(raw.territory_results) || !raw.portfolio_results || !raw.graphs) {
    throw new Error('Payload résultat incomplet');
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
  els.badgeSource.textContent = `Source: ${result.meta?.source || 'inconnue'}`;
  els.badgeUpdated.textContent = `Mis a jour: ${formatDate(result.meta?.updated_at)}`;
  els.badgeEngine.textContent = `Moteur: ${result.meta?.engine || 'n/a'}`;
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
      label: "EAI de l'aléa sélectionné",
      value: formatMoneyMEUR(p.eai_eur),
      sub: `AAI agg ${formatMoneyMEUR(p.aai_agg_eur)} · ${getHazardLabel(hazardKey)}`
    },
    {
      label: "Perte de l'événement max",
      value: formatMoneyMEUR(p.max_event_loss_eur),
      sub: 'Estimation portefeuille sur le jeu de résultats actif'
    },
    {
      label: 'Exposition totale',
      value: formatMoneyMEUR(exposureForScope),
      sub: selectedRow
        ? `Territoire sélectionné: ${selectedRow.territory_label}`
        : `${numberFmt.format(assetCountForScope)} actifs · ${numberFmt.format(pointCountForScope || 0)} points désagrégés`
    },
    {
      label: 'Écart CMCC vs STORM',
      value: formatMoneyMEUR(delta.eai_eur),
      sub: `${percentFmt.format(delta.eai_pct || 0)}% de variation d'EAI portefeuille`
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
  renderMethodologyValuation(analysis);
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

function renderMethodologyValuation(analysis) {
  if (!els.methodValuationOfb) return;
  const valuation = analysis?.exposition?.valuation_metadata || {};
  const territory = String(valuation.territory_effective || 'guadeloupe');
  const source = String(valuation.source || 'Comparateur de couts OFB (moyenne territoriale observee)');
  const version = String(valuation.valuation_version || 'n/a');
  const nb = valuation.nb_prix_compares || {};
  const compared = [
    `AEP canalisations: ${numberFmt.format(Number(nb.aep_cana || 0))}`,
    `EU canalisations: ${numberFmt.format(Number(nb.eu_cana || 0))}`,
    `EU PR: ${numberFmt.format(Number(nb.eu_pr || 0))}`,
    `EU STEP: ${numberFmt.format(Number(nb.eu_step || 0))}`
  ].join(' | ');
  const policy = 'Regle territoriale: Guadeloupe/Martinique par bbox, hors zone = fallback Guadeloupe.';

  els.methodValuationOfb.innerHTML = `
    <p class="muted small">${escapeHtml(`Source: ${source}. Territoire applique: ${territory}. Version: ${version}.`)}</p>
    <p class="muted small">${escapeHtml(`Nombre de prix compares (${territory}): ${compared}.`)}</p>
    <p class="muted small">${escapeHtml(policy)}</p>
    <ul>${GUA_VALUATION_RULES.map((rule) => `<li>${escapeHtml(rule)}</li>`).join('')}</ul>
  `;
}

function renderPage1Exposition(analysis) {
  const expo = analysis?.exposition || {};
  const lengths = expo.lengths_km || {};
  const counts = expo.counts || {};
  const valuePerKm = expo.value_per_km_eur || {};
  const totals = expo.total_value_by_type_eur || {};
  const valuation = expo.valuation_metadata || {};
  const newValues = valuation.new_values || {};

  if (els.expositionSummaryText) {
    els.expositionSummaryText.textContent = "L’exposition représente tous les enjeux qui peuvent et doivent être protégés face aux risques physiques. Dans ce cas d’étude sur la Guadeloupe, ont été pris en compte les réseaux d’eau potable (AEP), d’eau usées (EU) ainsi que les réseaux electriques (Basse tension aérien, basse tension souterrain, haute tension aerien, haute tension souterrain).";
  }

  if (els.expositionNetworkTableBody) {
    const networkRows = NETWORK_LAYER_ORDER.map((key) => ({
      label: NETWORK_LAYER_LABEL[key] || key,
      lengthKm: Number(lengths[key] || 0),
      valuePerKm: Number(valuePerKm[key] || 0),
      total: Number(totals[key] || 0)
    }));
    const totalNetworks = networkRows.reduce((acc, row) => acc + Number(row.total || 0), 0);
    els.expositionNetworkTableBody.innerHTML = networkRows.map((row) => `
      <tr>
        <td>${escapeHtml(row.label)}</td>
        <td class="num">${escapeHtml(numberFmt.format(row.lengthKm || 0))}</td>
        <td class="num">${escapeHtml(numberFmt.format(row.valuePerKm || 0))}</td>
        <td class="num">${escapeHtml(formatMoneyEUR(row.total || 0))}</td>
      </tr>
    `).join('') + `
      <tr class="table-total-row">
        <td><strong>Total reseaux</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num"><strong>${escapeHtml(formatMoneyEUR(totalNetworks))}</strong></td>
      </tr>
    `;
    if (els.expositionTotalNetworks) {
      els.expositionTotalNetworks.textContent = `Valeur totale des reseaux: ${formatMoneyEUR(totalNetworks)}`;
    }
  }

  if (els.expositionOuvrageTableBody) {
    const ouvrageRows = [
      {
        label: 'Ouvrages eau AEP',
        count: Number(counts.aep_ouvrages_total || 0),
        valuePerUnitText: 'Selon ovrg_type',
        total: Number(totals.eau_aep_ouvrages || 0)
      },
      {
        label: 'Postes de refoulement EU',
        count: Number(counts.eu_pr_total || 0),
        valuePerUnitText: numberFmt.format(Number(newValues.eu_pr_eur_per_unit || 0)),
        total: Number(totals.eau_eu_pr || 0)
      },
      {
        label: 'STEP',
        count: Number(counts.eu_step_total || 0),
        valuePerUnitText: numberFmt.format(Number(newValues.eu_step_eur_per_unit || 0)),
        total: Number(totals.eau_eu_step || 0)
      }
    ];
    const totalOuvrages = ouvrageRows.reduce((acc, row) => acc + Number(row.total || 0), 0);
    els.expositionOuvrageTableBody.innerHTML = ouvrageRows.map((row) => `
      <tr>
        <td>${escapeHtml(row.label)}</td>
        <td class="num">${escapeHtml(numberFmt.format(row.count || 0))}</td>
        <td class="num">${escapeHtml(row.valuePerUnitText)}</td>
        <td class="num">${escapeHtml(formatMoneyEUR(row.total || 0))}</td>
      </tr>
    `).join('') + `
      <tr class="table-total-row">
        <td><strong>Total ouvrages</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num"><strong>${escapeHtml(formatMoneyEUR(totalOuvrages))}</strong></td>
      </tr>
    `;
    if (els.expositionTotalOuvrages) {
      els.expositionTotalOuvrages.textContent = `Valeur totale des ouvrages: ${formatMoneyEUR(totalOuvrages)}`;
    }
  }

  if (els.expositionTotalValue) {
    els.expositionTotalValue.textContent = `Valeur totale du portefeuille d'infrastructures: ${formatMoneyEUR(expo.total_value_all_eur || 0)}`;
  }
}

function renderPage1Hazard(analysis) {
  const hazard = analysis?.hazard || {};
  const hist = hazard.wind_histograms || {};
  if (els.hazardSummaryText) {
    els.hazardSummaryText.innerHTML = escapeHtml(String(hazard.summary_text || '')).replaceAll('\n', '<br />');
  }

  if (els.hazardGuadeloupeCompareBody) {
    const rows = Array.isArray(hazard.guadeloupe_wind_comparison_table) ? hazard.guadeloupe_wind_comparison_table : [];
    if (!rows.length) {
      els.hazardGuadeloupeCompareBody.innerHTML = '<tr><td colspan="4">Tableau indisponible.</td></tr>';
    } else {
      els.hazardGuadeloupeCompareBody.innerHTML = rows.map((row) => `
        <tr>
          <td>${escapeHtml(String(row.indicator || ''))}</td>
          <td class="num">${escapeHtml(String(row.storm || ''))}</td>
          <td class="num">${escapeHtml(String(row.storm_cmcc || ''))}</td>
          <td class="num">${escapeHtml(String(row.delta || ''))}</td>
        </tr>
      `).join('');
    }
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
  const tables = impact.state_damage_tables || {};
  renderImpactScenarioTable(els.impactTableAnnualBody, Array.isArray(tables.annual) ? tables.annual : [], 'EAI');
  renderImpactScenarioTable(els.impactTableRp100Body, Array.isArray(tables.rp100) ? tables.rp100 : [], 'RP100');
  renderImpactScenarioTable(els.impactTableRp1000Body, Array.isArray(tables.rp1000) ? tables.rp1000 : [], 'RP1000');
  renderImpactScenarioTable(els.impactTableEventmaxBody, Array.isArray(tables.event_max) ? tables.event_max : [], 'evt max');

  renderImpactBreakdownCharts(impact);
}

function renderImpactScenarioTable(targetBody, rows, damageLabel) {
  if (!targetBody) return;
  if (!rows.length) {
    targetBody.innerHTML = '<tr><td colspan="5">Aucune donnee d\'impact disponible.</td></tr>';
    return;
  }
  targetBody.innerHTML = rows.map((row) => {
    const storm = row.storm || {};
    const cmcc = row.storm_cmcc || {};
    const rowLabel = NETWORK_LAYER_LABEL[String(row.class_key || '')] || row.class_label || row.class_key || 'Reseau';
    return `
      <tr>
        <td>${escapeHtml(String(rowLabel))}</td>
        <td class="num">${escapeHtml(formatStateTuple(storm.state_pct))}</td>
        <td class="num">${escapeHtml(formatMoneyEUR(storm.damage_eur || 0))}</td>
        <td class="num">${escapeHtml(formatStateTuple(cmcc.state_pct))}</td>
        <td class="num">${escapeHtml(formatMoneyEUR(cmcc.damage_eur || 0))}</td>
      </tr>
    `;
  }).join('');
}

function renderPage1Conclusion(analysis) {
  if (!els.conclusionText) return;
  const expo = analysis?.exposition || {};
  const impact = analysis?.impact || {};
  const storm = impact?.summary_metrics?.storm || {};
  const cmcc = impact?.summary_metrics?.storm_cmcc || {};
  const totalValue = Number(expo.total_value_all_eur || 0);
  const safeTotal = totalValue > 0 ? totalValue : 1;
  const toPct = (value) => (Number(value || 0) / safeTotal) * 100;
  const toM = (value) => Math.round((Number(value || 0) / 1_000_000));
  const txt = [
    `Valeur totale du portefeuille d'infrastructures: ${numberFmt.format(Math.round(totalValue / 1_000_000))} M€.`,
    `Dommages annuels moyens: STORM ${numberFmt.format(toM(storm.eai_total_eur))} M€ (${percentFmt.format(toPct(storm.eai_total_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.eai_total_eur))} M€ (${percentFmt.format(toPct(cmcc.eai_total_eur))} %).`,
    `Scenario temps de retour 100 ans: STORM ${numberFmt.format(toM(storm.rp100_total_loss_eur))} M€ (${percentFmt.format(toPct(storm.rp100_total_loss_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.rp100_total_loss_eur))} M€ (${percentFmt.format(toPct(cmcc.rp100_total_loss_eur))} %).`,
    `Scenario temps de retour 1000 ans: STORM ${numberFmt.format(toM(storm.rp1000_total_loss_eur))} M€ (${percentFmt.format(toPct(storm.rp1000_total_loss_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.rp1000_total_loss_eur))} M€ (${percentFmt.format(toPct(cmcc.rp1000_total_loss_eur))} %).`,
    `Evenement le plus extreme: STORM ${numberFmt.format(toM(storm.event_max_total_loss_eur))} M€ (${percentFmt.format(toPct(storm.event_max_total_loss_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.event_max_total_loss_eur))} M€ (${percentFmt.format(toPct(cmcc.event_max_total_loss_eur))} %).`
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

function categoryFromExposureType(typeValue) {
  const raw = String(typeValue || '').trim();
  return EXPOSURE_TYPE_TO_CATEGORY[raw] || 'habitation';
}

function assetFromExposureType(typeValue) {
  const raw = String(typeValue || '').trim();
  return EXPOSURE_TYPE_TO_ASSET[raw] || 'habitation';
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
    els.territoryTableBody.innerHTML = '<tr><td colspan="6">Aucune donnée chargée.</td></tr>';
    return;
  }
  const rows = filteredTerritories();
  els.tableCaption.textContent = `${rows.length} territoire(s) · source ${result.meta?.source || 'inconnue'} · aléa ${getHazardLabel(currentHazardKey())}`;

  if (!rows.length) {
    els.territoryTableBody.innerHTML = '<tr><td colspan="6">Aucun territoire ne correspond au filtre.</td></tr>';
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
    els.selectedTerritoryChip.textContent = 'Aucun territoire sélectionné';
    return;
  }
  const result = getActiveResult();
  const row = (result?.territory_results || []).find((x) => x.territory_id === state.selectedTerritoryId);
  els.selectedTerritoryChip.textContent = row ? `Sélection: ${row.territory_label}` : 'Aucun territoire sélectionné';
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
      const exposureType = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
      evt.layer.feature = evt.layer.feature || { type: 'Feature', properties: {} };
      evt.layer.feature.properties = {
        ...(evt.layer.feature.properties || {}),
        exposure_type: exposureType,
        exposure_category: categoryFromExposureType(exposureType),
        asset_type: assetFromExposureType(exposureType)
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
    els.mapFallback.textContent = 'Leaflet n’a pas pu être chargé. La carte est indisponible.';
    return;
  }
  els.mapFallback.hidden = true;
  els.mapFallback.textContent = '';

  if (!ensureMap()) {
    els.mapFallback.hidden = false;
    els.mapFallback.textContent = 'Échec de l’initialisation de la carte.';
    return;
  }

  const rows = (result.territory_results || []).filter((row) => Number.isFinite(row.lat) && Number.isFinite(row.lon));
  const hazardKey = currentHazardKey();
  els.mapCaption.textContent = `Taille des points = exposition, couleur = indice de risque (${getHazardLabel(hazardKey)}). Cliquez un point pour surligner un territoire.`;

  mapRef.markerByTerritoryId.clear();
  mapRef.markersLayer.clearLayers();

  if (!rows.length) {
    els.mapFallback.hidden = false;
    els.mapFallback.textContent = 'Aucun centroïde cartographiable dans ce résultat. Les agrégats restent disponibles dans le tableau et les graphiques.';
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
        `Exposition: ${escapeHtml(formatMoneyMEUR(row.exposure_eur))}`,
        `EAI (${escapeHtml(getHazardLabel(hazardKey))}): ${escapeHtml(formatMoneyMEUR(eaiForHazard(row, hazardKey)))}`,
        `Indice de risque: ${escapeHtml(formatRisk(risk))}`
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

function getWindColor(value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return '#d9f0a3';
  if (v > 45) return '#67000d';
  if (v > 40) return '#b10026';
  if (v > 35) return '#e31a1c';
  if (v > 30) return '#fd8d3c';
  if (v > 25) return '#feb24c';
  if (v > 20) return '#fee391';
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

function buildWindLegendHtml() {
  const rows = [
    { label: '<20 m/s', color: getWindColor(19.99) },
    { label: '20,01-25 m/s', color: getWindColor(22.5) },
    { label: '25,01-30 m/s', color: getWindColor(27.5) },
    { label: '30,01-35 m/s', color: getWindColor(32.5) },
    { label: '35,01-40 m/s', color: getWindColor(37.5) },
    { label: '40,01-45 m/s', color: getWindColor(42.5) },
    { label: '>45 m/s', color: getWindColor(46.0) }
  ].map((entry) => (
    `<div class="wind-legend-row"><span class="wind-legend-swatch" style="background:${entry.color}"></span><span>${entry.label}</span></div>`
  ));
  return [
    '<div class="wind-legend">',
    '<div class="wind-legend-title">Vent moyen</div>',
    ...rows,
    '</div>'
  ].join('');
}

function ensureWindLegend(hazardKey) {
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
  if (legendEl) legendEl.innerHTML = buildWindLegendHtml();
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
        const color = getWindColor(meanWind);
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
            `Vent max moyen: ${escapeHtml(numberFmt.format(meanWind))} m/s`,
            `Echantillons: ${escapeHtml(numberFmt.format(sampleCount))}`,
            extrapolated ? 'Valeur: extrapolee (plus proche maille observee)' : 'Valeur: observee'
          ].join('<br/>'),
          { sticky: true }
        );
        rect.addTo(ref.cellsLayer);
      }
    }
  }

  ensureWindLegend(hazardKey);

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
    els.windStormCaption.textContent = `${numberFmt.format(storm.cell_count || 0)} mailles observees · extrapolation spatiale active autour de la zone etudiee · ${numberFmt.format(storm.years_covered || 0)} ans · echelle de classes fixe (<20, 20,01-25, 25,01-30, 30,01-35, 35,01-40, 40,01-45, >45 m/s)`;
    renderWindMap('storm', storm, meta, { gridSpec: sharedGrid, colorMin, colorMax });
  }
  if (cmcc && els.windCmccCaption) {
    els.windCmccCaption.textContent = `${numberFmt.format(cmcc.cell_count || 0)} mailles observees · extrapolation spatiale active autour de la zone etudiee · ${numberFmt.format(cmcc.years_covered || 0)} ans · echelle de classes fixe (<20, 20,01-25, 25,01-30, 30,01-35, 35,01-40, 40,01-45, >45 m/s)`;
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
  const allowedScenarios = new Set(['annual', 'rp100', 'rp1000', 'event_max', 'top10', 'top5']);
  const scenario = allowedScenarios.has(state.impactMapScenario) ? state.impactMapScenario : 'event_max';
  return `state_${scenario}_${hazard}`;
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
  if (state.networkLayerVisibility[typeKey] === undefined) state.networkLayerVisibility[typeKey] = false;
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
    const scenarioLabel = {
      annual: 'moyenne annuelle',
      rp100: 'temps de retour 100 ans',
      rp1000: 'temps de retour 1000 ans',
      event_max: 'evenement le plus fort',
      top10: '10% evenements les plus forts',
      top5: '5% evenements les plus forts'
    };
    const sc = scenarioLabel[state.impactMapScenario] || scenarioLabel.event_max;
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
  const mapA = new Map();
  const mapB = new Map();
  (graphA.bins_mps || []).forEach((x, idx) => {
    mapA.set(Number(x).toFixed(3), Number((graphA.percent || [])[idx] || 0));
  });
  (graphB.bins_mps || []).forEach((x, idx) => {
    mapB.set(Number(x).toFixed(3), Number((graphB.percent || [])[idx] || 0));
  });

  const xBins = Array.from(
    new Set([
      ...(graphA.bins_mps || []).map((x) => Number(x).toFixed(3)),
      ...(graphB.bins_mps || []).map((x) => Number(x).toFixed(3))
    ])
  )
    .map((x) => Number(x))
    .filter((x) => Number.isFinite(x))
    .sort((a, b) => a - b)
    .map((x) => x.toFixed(3));

  const baseA = xBins.map((bin) => [Number(bin), Number(mapA.get(bin) || 0)]);
  const baseB = xBins.map((bin) => [Number(bin), Number(mapB.get(bin) || 0)]);
  const interpolate = (pairs, segments = 8) => {
    if (!Array.isArray(pairs) || pairs.length <= 1) return pairs || [];
    const out = [];
    for (let i = 0; i < pairs.length - 1; i += 1) {
      const [x0, y0] = pairs[i];
      const [x1, y1] = pairs[i + 1];
      out.push([x0, y0]);
      for (let s = 1; s < segments; s += 1) {
        const t = s / segments;
        out.push([x0 + ((x1 - x0) * t), y0 + ((y1 - y0) * t)]);
      }
    }
    out.push(pairs[pairs.length - 1]);
    return out;
  };
  const seriesA = interpolate(baseA, 10);
  const seriesB = interpolate(baseB, 10);
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        const rows = Array.isArray(params) ? params : [params];
        if (!rows.length) return '';
        const binValue = Number(rows[0]?.value?.[0] ?? rows[0]?.axisValue ?? 0);
        const valA = Number(rows.find((r) => r.seriesName === labelA)?.value?.[1] || 0);
        const valB = Number(rows.find((r) => r.seriesName === labelB)?.value?.[1] || 0);
        return [
          `<strong>${escapeHtml(numberFmt.format(binValue))} m/s</strong>`,
          `${escapeHtml(labelA)}: ${escapeHtml(numberFmt.format(valA))}%`,
          `${escapeHtml(labelB)}: ${escapeHtml(numberFmt.format(valB))}%`
        ].join('<br/>');
      }
    },
    legend: {
      top: 2,
      textStyle: { color: '#abc0ba' }
    },
    xAxis: { ...chartThemeCommon().xAxis, type: 'value', name: 'm/s' },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '%', min: 0 },
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
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: (graph.return_period_years || []).map(String), name: 'Ans' },
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
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: (graph.series?.[0]?.return_period_years || []).map(String), name: 'Ans' },
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

function renderGroupedImpactBarChart(refKey, domId, labels, stormValues, cmccValues, palette) {
  const chart = ensureChart(refKey, domId);
  if (!chart) return;
  if (!labels.length) {
    chart.setOption({
      title: {
        text: 'Aucune donnee',
        left: 'center',
        top: 'middle',
        textStyle: { color: '#abc0ba', fontSize: 13, fontWeight: 500 }
      },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    }, true);
    return;
  }
  chart.setOption({
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
      { name: 'STORM', type: 'bar', data: stormValues, itemStyle: { color: palette.storm }, barMaxWidth: 30 },
      { name: 'STORM_CMCC', type: 'bar', data: cmccValues, itemStyle: { color: palette.cmcc }, barMaxWidth: 30 }
    ]
  }, true);
}

function renderImpactBreakdownCharts(impactPayload) {
  const scenarioRows = impactPayload?.damage_breakdown_by_scenario || {};
  const fallbackBreakdown = impactPayload?.damage_breakdown || {};

  const rowsForScenario = (scenario) => {
    const scenarioPayload = scenarioRows?.[scenario];
    if (scenarioPayload?.storm && scenarioPayload?.storm_cmcc) {
      const byStorm = new Map((scenarioPayload.storm || []).map((r) => [String(r.class_key), r]));
      const byCmcc = new Map((scenarioPayload.storm_cmcc || []).map((r) => [String(r.class_key), r]));
      const ordered = Array.from(new Set([...byStorm.keys(), ...byCmcc.keys()]));
      return ordered.map((key) => {
        const s = byStorm.get(key) || {};
        const c = byCmcc.get(key) || {};
        return {
          key,
          label: String(s.class_label || c.class_label || key),
          storm: Number(s.damage_eur || 0),
          cmcc: Number(c.damage_eur || 0)
        };
      });
    }

    if (scenario === 'annual' && fallbackBreakdown?.storm && fallbackBreakdown?.storm_cmcc) {
      const byStorm = new Map((fallbackBreakdown.storm || []).map((r) => [String(r.class_key), r]));
      const byCmcc = new Map((fallbackBreakdown.storm_cmcc || []).map((r) => [String(r.class_key), r]));
      const ordered = Array.from(new Set([...byStorm.keys(), ...byCmcc.keys()]));
      return ordered.map((key) => {
        const s = byStorm.get(key) || {};
        const c = byCmcc.get(key) || {};
        return {
          key,
          label: String(s.class_label || c.class_label || key),
          storm: Number(s.eai_eur || 0),
          cmcc: Number(c.eai_eur || 0)
        };
      });
    }

    if (scenario === 'event_max' && fallbackBreakdown?.storm && fallbackBreakdown?.storm_cmcc) {
      const byStorm = new Map((fallbackBreakdown.storm || []).map((r) => [String(r.class_key), r]));
      const byCmcc = new Map((fallbackBreakdown.storm_cmcc || []).map((r) => [String(r.class_key), r]));
      const ordered = Array.from(new Set([...byStorm.keys(), ...byCmcc.keys()]));
      return ordered.map((key) => {
        const s = byStorm.get(key) || {};
        const c = byCmcc.get(key) || {};
        return {
          key,
          label: String(s.class_label || c.class_label || key),
          storm: Number(s.event_max_loss_eur || 0),
          cmcc: Number(c.event_max_loss_eur || 0)
        };
      });
    }

    return [];
  };

  const annualRows = rowsForScenario('annual');
  const eventRows = rowsForScenario('event_max');
  const rp100Rows = rowsForScenario('rp100');
  const rp1000Rows = rowsForScenario('rp1000');

  const waterRows = annualRows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRows = annualRows.filter((r) => String(r.key).startsWith('elec_'));
  const waterRowsRp100 = rp100Rows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRowsRp100 = rp100Rows.filter((r) => String(r.key).startsWith('elec_'));
  const waterRowsRp1000 = rp1000Rows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRowsRp1000 = rp1000Rows.filter((r) => String(r.key).startsWith('elec_'));
  const waterRowsEvt = eventRows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRowsEvt = eventRows.filter((r) => String(r.key).startsWith('elec_'));

  renderGroupedImpactBarChart(
    'impact_eai_water',
    'impact-eai-water-chart',
    waterRows.map((r) => r.label),
    waterRows.map((r) => r.storm),
    waterRows.map((r) => r.cmcc),
    { storm: '#0083CB', cmcc: '#5BC5F2' }
  );
  renderGroupedImpactBarChart(
    'impact_eai_elec',
    'impact-eai-elec-chart',
    elecRows.map((r) => r.label),
    elecRows.map((r) => r.storm),
    elecRows.map((r) => r.cmcc),
    { storm: '#6AB96F', cmcc: '#A4A64B' }
  );
  renderGroupedImpactBarChart(
    'impact_rp100_water',
    'impact-rp100-water-chart',
    waterRowsRp100.map((r) => r.label),
    waterRowsRp100.map((r) => r.storm),
    waterRowsRp100.map((r) => r.cmcc),
    { storm: '#00A6E2', cmcc: '#99D7F7' }
  );
  renderGroupedImpactBarChart(
    'impact_rp100_elec',
    'impact-rp100-elec-chart',
    elecRowsRp100.map((r) => r.label),
    elecRowsRp100.map((r) => r.storm),
    elecRowsRp100.map((r) => r.cmcc),
    { storm: '#F39655', cmcc: '#FFD744' }
  );
  renderGroupedImpactBarChart(
    'impact_rp1000_water',
    'impact-rp1000-water-chart',
    waterRowsRp1000.map((r) => r.label),
    waterRowsRp1000.map((r) => r.storm),
    waterRowsRp1000.map((r) => r.cmcc),
    { storm: '#0083CB', cmcc: '#5BC5F2' }
  );
  renderGroupedImpactBarChart(
    'impact_rp1000_elec',
    'impact-rp1000-elec-chart',
    elecRowsRp1000.map((r) => r.label),
    elecRowsRp1000.map((r) => r.storm),
    elecRowsRp1000.map((r) => r.cmcc),
    { storm: '#A4A64B', cmcc: '#FFD744' }
  );
  renderGroupedImpactBarChart(
    'impact_evt_water',
    'impact-evt-water-chart',
    waterRowsEvt.map((r) => r.label),
    waterRowsEvt.map((r) => r.storm),
    waterRowsEvt.map((r) => r.cmcc),
    { storm: '#00A6E2', cmcc: '#99D7F7' }
  );
  renderGroupedImpactBarChart(
    'impact_evt_elec',
    'impact-evt-elec-chart',
    elecRowsEvt.map((r) => r.label),
    elecRowsEvt.map((r) => r.storm),
    elecRowsEvt.map((r) => r.cmcc),
    { storm: '#F39655', cmcc: '#FFD744' }
  );
}

function scenarioLossFromPortfolio(hazardData, scenario) {
  const h = hazardData || {};
  if (scenario === 'annual') return Number(h.eai_eur || 0);
  if (scenario === 'rp100') return Number(h.pml_100_eur || 0);
  if (scenario === 'rp1000') {
    if (Number.isFinite(Number(h.pml_1000_eur))) return Number(h.pml_1000_eur || 0);
    return Number(h.max_event_loss_eur || 0);
  }
  return Number(h.max_event_loss_eur || 0);
}

function renderUserImpactChartsFromResult(result) {
  const storm = result?.portfolio_results?.storm || {};
  const cmcc = result?.portfolio_results?.storm_cmcc || {};
  const scenarioChart = (refKey, domId, scenario, colorA, colorB) => {
    renderGroupedImpactBarChart(
      refKey,
      domId,
      ['Portefeuille total'],
      [scenarioLossFromPortfolio(storm, scenario)],
      [scenarioLossFromPortfolio(cmcc, scenario)],
      { storm: colorA, cmcc: colorB }
    );
  };
  scenarioChart('user_impact_eai', 'user-impact-eai-chart', 'annual', '#0083CB', '#5BC5F2');
  scenarioChart('user_impact_rp100', 'user-impact-rp100-chart', 'rp100', '#00A6E2', '#99D7F7');
  scenarioChart('user_impact_rp1000', 'user-impact-rp1000-chart', 'rp1000', '#A4A64B', '#FFD744');
  scenarioChart('user_impact_eventmax', 'user-impact-eventmax-chart', 'event_max', '#F39655', '#FFD744');
}

function renderUserConclusionText(result) {
  if (!els.userConclusionText) return;
  const totalExposure = Number(result?.exposure_summary?.total_exposure_eur || 0);
  const safeExposure = totalExposure > 0 ? totalExposure : 1;
  const storm = result?.portfolio_results?.storm || {};
  const cmcc = result?.portfolio_results?.storm_cmcc || {};
  const pct = (value) => ((Number(value || 0) / safeExposure) * 100);
  const text = [
    `Exposition totale utilisateur: ${formatMoneyEUR(totalExposure)}.`,
    `Dommages annuels moyens: STORM ${formatMoneyEUR(scenarioLossFromPortfolio(storm, 'annual'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(storm, 'annual')))} %), STORM_CMCC ${formatMoneyEUR(scenarioLossFromPortfolio(cmcc, 'annual'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(cmcc, 'annual')))} %).`,
    `Temps de retour 100 ans: STORM ${formatMoneyEUR(scenarioLossFromPortfolio(storm, 'rp100'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(storm, 'rp100')))} %), STORM_CMCC ${formatMoneyEUR(scenarioLossFromPortfolio(cmcc, 'rp100'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(cmcc, 'rp100')))} %).`,
    `Temps de retour 1000 ans: STORM ${formatMoneyEUR(scenarioLossFromPortfolio(storm, 'rp1000'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(storm, 'rp1000')))} %), STORM_CMCC ${formatMoneyEUR(scenarioLossFromPortfolio(cmcc, 'rp1000'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(cmcc, 'rp1000')))} %).`,
    `Événement maximum: STORM ${formatMoneyEUR(scenarioLossFromPortfolio(storm, 'event_max'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(storm, 'event_max')))} %), STORM_CMCC ${formatMoneyEUR(scenarioLossFromPortfolio(cmcc, 'event_max'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(cmcc, 'event_max')))} %).`
  ];
  els.userConclusionText.textContent = text.join(' ');
}

function renderUserImpactSection(result) {
  if (!els.userImpactSummaryText) return;
  if (!result) {
    els.userImpactSummaryText.textContent = 'Aucun résultat utilisateur chargé.';
    if (els.userConclusionText) els.userConclusionText.textContent = 'Conclusion indisponible.';
    return;
  }
  const modeLabel = {
    demo: 'référence Guadeloupe',
    uploaded: 'exposition importée',
    drawn: 'exposition dessinée'
  }[state.selectedDatasetMode] || 'résultat actif';
  els.userImpactSummaryText.textContent = `Cette section présente les impacts du ${modeLabel}, sans carte d’état des réseaux.`;
  renderUserImpactChartsFromResult(result);
  renderUserConclusionText(result);
}

function renderHazardCharts() {
  const result = getActiveResult();
  if (!result) return;
  const hazardKey = currentHazardKey();
  const hazardGraphs = result.graphs?.[hazardKey];
  if (!hazardGraphs) return;

  els.chartsCaption.textContent = `Graphiques du run actif (${getHazardLabel(hazardKey)}), générés depuis les sorties backend.`;
  els.chartTitle1.textContent = hazardGraphs.wind_year_hist?.title || 'Vitesse max du vent par année';
  els.chartTitle2.textContent = hazardGraphs.wind_track_hist?.title || 'Vitesse max du vent par track';
  els.chartTitle3.textContent = hazardGraphs.annual_fec?.title || 'FEC annuelle';
  els.chartTitle4.textContent = hazardGraphs.lifetime_fec?.title || 'FEC longue durée';

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
    els.artifactLinks.innerHTML = '<span class="muted">Aucun artefact téléchargeable pour ce résultat.</span>';
    return;
  }
  els.artifactLinks.innerHTML = all.map((a) => `<a href="${escapeHtml(a.url)}" target="_blank" rel="noopener">${escapeHtml(a.name)}</a>`).join('');
}

function renderNotes() {
  const result = getActiveResult();
  const notes = Array.isArray(result?.notes) ? result.notes : [];
  if (!notes.length) {
    els.notesBox.textContent = 'Aucune note disponible pour ce résultat.';
    return;
  }
  els.notesBox.innerHTML = `<ul>${notes.slice(0, 8).map((n) => `<li>${escapeHtml(n)}</li>`).join('')}</ul>`;
}

function renderDrawPreview() {
  if (!mapRef.drawnItems) {
    els.drawSummaryList.innerHTML = '<li>Outils de dessin indisponibles.</li>';
    return;
  }
  const layers = mapRef.drawnItems.getLayers();
  if (!layers.length) {
    els.drawSummaryList.innerHTML = '<li>Aucun dessin pour le moment.</li>';
    els.submitDrawingBtn.disabled = true;
    return;
  }
  const counts = { marker: 0, circle: 0, polyline: 0, polygon: 0, rectangle: 0 };
  const typeCounts = {};
  layers.forEach((layer) => {
    if (!window.L) return;
    if (layer instanceof L.Circle) counts.circle += 1;
    else if (layer instanceof L.Marker) counts.marker += 1;
    else if (layer instanceof L.Polygon) counts.polygon += 1;
    else if (layer instanceof L.Polyline) counts.polyline += 1;
    const type = String(layer?.feature?.properties?.exposure_type || els.drawCategory?.value || 'habitation');
    typeCounts[type] = (typeCounts[type] || 0) + 1;
  });
  const shapeLabels = {
    marker: 'points',
    circle: 'cercles',
    polyline: 'lignes',
    polygon: 'polygones',
    rectangle: 'rectangles'
  };
  const lines = [`${layers.length} dessin(s) prêt(s) pour soumission.`];
  Object.entries(counts).forEach(([k, v]) => {
    if (v > 0) lines.push(`${shapeLabels[k] || k}: ${v}`);
  });
  const typeSummary = Object.entries(typeCounts)
    .map(([k, v]) => `${EXPOSURE_TYPE_LABEL[k] || k}: ${v}`)
    .join(' · ');
  lines.push(`types d'exposition: ${typeSummary}`);
  lines.push("Le backend applique actuellement une valeur par défaut par objet dessiné.");
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
  renderUserImpactSection(state.activeResult);
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
  throw lastErr || new Error('Impossible de charger le résultat de référence');
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
        throw new Error('Payload carte des vents invalide');
      }
      return payload;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error('Impossible de charger les cartes des vents');
}

async function fetchWaterInfra() {
  const url = new URL('/data/guadeloupe-water-infra.geojson', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    throw new Error("Payload des infrastructures d'eau invalide");
  }
  return payload;
}

async function fetchPage1Analysis() {
  const url = new URL('/data/guadeloupe-page1-analysis.json', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || !payload.exposition || !payload.hazard || !payload.impact || !payload.conclusion) {
    throw new Error('Payload analyse page 1 invalide');
  }
  return payload;
}

async function fetchNetworkStates() {
  const url = new URL('/data/guadeloupe-network-states.geojson', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    throw new Error("Payload des états de réseaux invalide");
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
      setStatus(`Erreur de suivi du job ${jobId}: ${err.message}`, 'error');
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
    showError("Sélectionnez un fichier avant de lancer un run d'exposition importée.");
    return;
  }

  const form = new FormData();
  form.append('input_mode', 'file');
  form.append('exposure_file', file);
  if (els.valueField.value.trim()) form.append('value_field', els.valueField.value.trim());
  if (els.idField.value.trim()) form.append('id_field', els.idField.value.trim());
  if (els.assetTypeField.value.trim()) form.append('asset_type_field', els.assetTypeField.value.trim());
  if (els.categoryField.value.trim()) form.append('exposure_category_field', els.categoryField.value.trim());
  const defaultExposureType = (els.defaultCategory?.value || 'habitation').trim() || 'habitation';
  form.append('default_exposure_category', categoryFromExposureType(defaultExposureType));
  if (els.crsField.value.trim()) form.append('crs', els.crsField.value.trim());
  form.append('sampling_spacing_m', String(FIXED_SAMPLING_SPACING_M));
  if (els.runLabel.value.trim()) form.append('run_label', els.runLabel.value.trim());

  els.uploadSubmitBtn.disabled = true;
  setStatus("Soumission du run d'exposition importée…", 'info');
  try {
    const res = await fetch('/api/v1/runs', { method: 'POST', body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    setStatus(`Job accepté: ${payload.job_id}. Run importé en file d'attente.`, 'info');
    state.selectedDatasetMode = 'uploaded';
    els.datasetSelect.value = 'uploaded';
    els.pollJobId.value = payload.job_id;
    await pollJob(payload.job_id, { modeTarget: 'uploaded', immediate: true });
  } catch (err) {
    showError(`Échec du lancement du run importé: ${err.message}`);
    setStatus(`Échec du lancement du run importé: ${err.message}`, 'error');
  } finally {
    els.uploadSubmitBtn.disabled = false;
  }
}

function getDrawnFeatureCollection() {
  if (!mapRef.drawnItems) return null;
  const layers = mapRef.drawnItems.getLayers();
  if (!layers.length) return null;
  const defaultExposureType = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
  const features = layers.map((layer) => {
    const gj = layer.toGeoJSON();
    const currentType = String(layer?.feature?.properties?.exposure_type || gj?.properties?.exposure_type || defaultExposureType);
    const currentCategory = categoryFromExposureType(currentType);
    const currentAssetType = assetFromExposureType(currentType);
    gj.properties = {
      ...(gj.properties || {}),
      exposure_type: currentType,
      exposure_category: currentCategory,
      asset_type: currentAssetType
    };
    layer.feature = layer.feature || { type: 'Feature', properties: {} };
    layer.feature.properties = {
      ...(layer.feature.properties || {}),
      exposure_type: currentType,
      exposure_category: currentCategory,
      asset_type: currentAssetType
    };
    return gj;
  });
  return { type: 'FeatureCollection', features };
}

async function submitDrawnExposure() {
  clearError();
  const fc = getDrawnFeatureCollection();
  if (!fc) {
    showError("Dessinez au moins une géométrie avant de lancer un run d'exposition dessinée.");
    return;
  }

  const form = new FormData();
  form.append('input_mode', 'drawn_geojson');
  form.append('drawn_geojson', JSON.stringify(fc));
  const defaultExposureType = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
  form.append('default_exposure_category', categoryFromExposureType(defaultExposureType));
  form.append('sampling_spacing_m', String(FIXED_SAMPLING_SPACING_M));
  if (els.runLabel.value.trim()) form.append('run_label', `${els.runLabel.value.trim()} (dessin)`);

  els.submitDrawingBtn.disabled = true;
  setStatus("Soumission du run d'exposition dessinée…", 'info');
  try {
    const res = await fetch('/api/v1/runs', { method: 'POST', body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
    setStatus(`Job accepté: ${payload.job_id}. Run dessiné en file d'attente.`, 'info');
    state.selectedDatasetMode = 'drawn';
    els.datasetSelect.value = 'drawn';
    els.pollJobId.value = payload.job_id;
    await pollJob(payload.job_id, { modeTarget: 'drawn', immediate: true });
  } catch (err) {
    showError(`Échec du lancement du run dessiné: ${err.message}`);
    setStatus(`Échec du lancement du run dessiné: ${err.message}`, 'error');
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
    setStatus(`Aucun résultat ${mode} n'est encore disponible. Affichage de la référence Guadeloupe.`, 'info');
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
      const allowedScenarios = new Set(['annual', 'rp100', 'rp1000', 'event_max', 'top10', 'top5']);
      state.impactMapScenario = allowedScenarios.has(els.impactMapScenarioSelect.value)
        ? els.impactMapScenarioSelect.value
        : 'event_max';
      renderNetworkStateMap();
    });
  }

  els.resetDemoBtn.addEventListener('click', () => {
    stopPolling();
    state.selectedTerritoryId = null;
    state.selectedDatasetMode = 'demo';
    els.datasetSelect.value = 'demo';
    setActiveResult(state.resultsByMode.demo, 'demo');
    setStatus('Retour à la référence complète Guadeloupe.', 'success');
    setActivePage('page1');
  });

  els.reloadJobBtn.addEventListener('click', async () => {
    const jobId = els.pollJobId.value.trim();
    if (!jobId) {
      showError('Renseignez un identifiant de job pour recharger un résultat.');
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
      const exposureType = (els.drawCategory.value || 'habitation').trim() || 'habitation';
      mapRef.drawnItems.getLayers().forEach((layer) => {
        layer.feature = layer.feature || { type: 'Feature', properties: {} };
        layer.feature.properties = {
          ...(layer.feature.properties || {}),
          exposure_type: exposureType,
          exposure_category: categoryFromExposureType(exposureType),
          asset_type: assetFromExposureType(exposureType)
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
    setStatus("Référence Guadeloupe complète chargée. Importez ou dessinez une exposition pour lancer un run asynchrone.", 'success');
  } catch (err) {
    console.error(err);
    showError(`Erreur au démarrage: ${err.message}`);
    setStatus(`Erreur au démarrage: ${err.message}`, 'error');
    renderAll();
  }
}

bootstrap();
