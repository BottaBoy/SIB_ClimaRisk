const state = {
  activeResult: null,
  activeResultMode: 'uploaded',
  selectedHazard: 'storm',
  selectedDatasetMode: 'uploaded',
  territorySearch: '',
  resultsByMode: {
    uploaded: null,
    drawn: null
  },
  backendComputeActive: false,
  uiComputeActive: false,
  uiComputeTimer: null,
  activeSubmitMode: null,
  runLabelsByJob: {},
  recentRuns: [],
  currentJobId: null,
  pollTimer: null,
  pollingModeTarget: null,
  currentPage: 'page1',
  caseStudyTerritory: 'guadeloupe',
  caseStudyCache: {
    guadeloupe: null,
    martinique: null
  },
  mapReady: false,
  windMaps: null,
  windLayerOpacity: 0.82,
  windMapMode: 'mean',
  adminVisuMaps: null,
  adminVisuMapsPromise: null,
  adminPopulationMaps: null,
  adminPopulationMapsPromise: null,
  adminVulnerabilityCurves: null,
  adminVulnerabilityCurvesPromise: null,
  adminPopulationTerritory: 'glp',
  adminVisuOpacity: 0.5,
  adminVisuCards: [
    { hazard: 'storm', scenario: 'mean' },
    { hazard: 'storm_cmcc', scenario: 'mean' },
    { hazard: 'storm', scenario: 'rp50' },
    { hazard: 'storm_cmcc', scenario: 'rp100' }
  ],
  waterInfra: null,
  waterLayerVisibility: {},
  page1Analysis: null,
  networkStates: null,
  networkStatesPromise: null,
  networkLayerVisibility: {},
  stormCoverageZones: [],
  stormCoverageGeoJson: null,
  stormCoveragePromise: null,
  outsideCoverageByMode: {
    uploaded: [],
    drawn: []
  },
  impactMapHazard: 'storm',
  impactMapScenario: 'event_max'
};

const mapRef = {
  instance: null,
  markersLayer: null,
  stormCoverageLayer: null,
  uploadedLayer: null,
  uploadedFeatureCount: 0,
  drawnItems: null,
  drawHandlers: {},
  activeDrawMode: null,
  hasFitted: false
};

const windMapRef = {
  storm: { instance: null, cellsLayer: null, hasFitted: false, legendControl: null, cellsPaneName: 'wind-cells-storm' },
  storm_cmcc: { instance: null, cellsLayer: null, hasFitted: false, legendControl: null, cellsPaneName: 'wind-cells-cmcc' }
};

const adminVisuMapRef = {
  cards: [
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-1', legendControl: null },
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-2', legendControl: null },
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-3', legendControl: null },
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-4', legendControl: null }
  ]
};

const adminPopulationMapRef = {
  instance: null,
  overlayLayer: null,
  overlayUrl: '',
  overlayPaneName: 'admin-pop-overlay',
  legendControl: null,
  currentTerritory: ''
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

const ASSET_TYPE_ADMIN_LABEL = {
  elec_bt_aerien: 'Electricite BT aerien',
  elec_hta_aerien: 'Electricite HTA aerien',
  elec_bt_souterrain: 'Electricite BT souterrain',
  elec_hta_souterrain: 'Electricite HTA souterrain',
  eau_aep_cana: 'Eau AEP canalisations',
  eau_eu_cana: 'Eau EU canalisations',
  eau_eu_pr: 'Eau EU postes de refoulement (PR)',
  eau_eu_step: "Eau EU stations d'epuration (STEP)",
  eau_aep_ouvrage_trait: 'Eau AEP ouvrage TRAIT',
  eau_aep_ouvrage_stpmp: 'Eau AEP ouvrage STPMP',
  eau_aep_ouvrage_cap: 'Eau AEP ouvrage CAP',
  eau_aep_ouvrage_cuv: 'Eau AEP ouvrage CUV',
  eau_aep_ouvrage_ouveb: 'Eau AEP ouvrage OUVEB',
  eau_aep_ouvrage_na: 'Eau AEP ouvrage NA'
};

const STATE_COLORS = {
  S0: '#6AB96F',
  S1: '#f2b66f',
  S2: '#d94832',
  S3: '#111111'
};

const WIND_PADDING_CELLS = 6;
const WIND_SCALE_STEP_MPS = 5;
const WIND_PALETTE = ['#d9f0a3', '#fee391', '#feb24c', '#fd8d3c', '#f46d43', '#e31a1c', '#b10026', '#800026', '#67000d'];
const ADMIN_VISU_LEGEND_COLORS = ['#30123b', '#4145ab', '#4685f9', '#39b6f7', '#1bd0d5', '#4be28a', '#a4ef63', '#f1e54e', '#f9b737', '#ed6925', '#c32503'];
const ADMIN_POP_DEFAULT_LEGEND_COLORS = ['#f2f2f2', '#d9d9d9', '#bdbdbd', '#969696', '#737373', '#525252', '#3a3a3a', '#1f1f1f', '#000000'];
const WIND_SPEED_MPS_TO_KMH = 3.6;
const WIND_SPEED_UNIT_DISPLAY = 'km/h';
const CMCC_VISUAL_MIN_BAND_SAMPLE_MAX = 5;
const CMCC_VISUAL_MIN_BAND_NEIGHBOR_RADIUS = 5;
const CMCC_VISUAL_MIN_BAND_NEIGHBOR_MIN = 3;
const CMCC_VISUAL_MIN_BAND_EPS = 0.06;

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
  navPage4: document.getElementById('nav-page-4'),
  navPage5: document.getElementById('nav-page-5'),
  runtimeAccessNote: document.getElementById('runtime-access-note'),
  pageBlocks: Array.from(document.querySelectorAll('.page-block')),
  caseStudyTitle: document.getElementById('case-study-title'),
  caseStudySubtitle: document.getElementById('case-study-subtitle'),
  errorBanner: document.getElementById('error-banner'),
  badgeSource: document.getElementById('badge-source'),
  badgeUpdated: document.getElementById('badge-updated'),
  badgeEngine: document.getElementById('badge-engine'),
  hazardSelect: document.getElementById('hazard-select'),
  datasetSelect: document.getElementById('dataset-select'),
  pollJobId: document.getElementById('poll-job-id'),
  reloadJobBtn: document.getElementById('reload-job-btn'),
  uploadForm: document.getElementById('upload-form'),
  uploadFile: document.getElementById('upload-file'),
  runLabel: document.getElementById('run-label'),
  drawRunLabel: document.getElementById('draw-run-label'),
  drawCategory: document.getElementById('draw-category'),
  drawModeButtons: document.getElementById('draw-mode-buttons'),
  uploadSubmitBtn: document.getElementById('upload-submit-btn'),
  submitDrawingBtn: document.getElementById('submit-drawing-btn'),
  uploadRunEstimate: document.getElementById('upload-run-estimate'),
  drawRunEstimate: document.getElementById('draw-run-estimate'),
  refreshPreviewBtn: document.getElementById('refresh-preview-btn'),
  clearDrawingsBtn: document.getElementById('clear-drawings-btn'),
  drawSummaryList: document.getElementById('draw-summary-list'),
  impactOutsideWarning: document.getElementById('impact-outside-warning'),
  jobStatusBox: document.getElementById('job-status-box'),
  computeIndicator: document.getElementById('compute-indicator'),
  runMemoryBox: document.getElementById('run-memory-box'),
  runMemoryList: document.getElementById('run-memory-list'),
  kpiGrid: document.getElementById('kpi-grid'),
  selectedTerritoryChip: document.getElementById('selected-territory-chip'),
  territorySearch: document.getElementById('territory-search'),
  clearTerritoryFilterBtn: document.getElementById('clear-territory-filter-btn'),
  territoryTableBody: document.getElementById('territory-table-body'),
  tableCaption: document.getElementById('table-caption'),
  mapCaption: document.getElementById('map-caption'),
  mapContainer: document.getElementById('territory-map'),
  mapFallback: document.getElementById('map-fallback'),
  notesBox: document.getElementById('notes-box'),
  windMapStorm: document.getElementById('wind-map-storm'),
  windMapCmcc: document.getElementById('wind-map-cmcc'),
  windStormCaption: document.getElementById('wind-storm-caption'),
  windCmccCaption: document.getElementById('wind-cmcc-caption'),
  windOpacitySlider: document.getElementById('wind-opacity-slider'),
  windOpacityValue: document.getElementById('wind-opacity-value'),
  windMapMode: document.getElementById('wind-map-mode'),
  windMapTitleStorm: document.getElementById('wind-map-title-storm'),
  windMapTitleCmcc: document.getElementById('wind-map-title-cmcc'),
  adminVisuOpacitySlider: document.getElementById('admin-visu-opacity-slider'),
  adminVisuOpacityValue: document.getElementById('admin-visu-opacity-value'),
  adminVisuHazardSelects: [
    document.getElementById('admin-visu-hazard-1'),
    document.getElementById('admin-visu-hazard-2'),
    document.getElementById('admin-visu-hazard-3'),
    document.getElementById('admin-visu-hazard-4')
  ],
  adminVisuScenarioSelects: [
    document.getElementById('admin-visu-scenario-1'),
    document.getElementById('admin-visu-scenario-2'),
    document.getElementById('admin-visu-scenario-3'),
    document.getElementById('admin-visu-scenario-4')
  ],
  adminVisuMapContainers: [
    document.getElementById('admin-visu-map-1'),
    document.getElementById('admin-visu-map-2'),
    document.getElementById('admin-visu-map-3'),
    document.getElementById('admin-visu-map-4')
  ],
  adminVisuCaptions: [
    document.getElementById('admin-visu-caption-1'),
    document.getElementById('admin-visu-caption-2'),
    document.getElementById('admin-visu-caption-3'),
    document.getElementById('admin-visu-caption-4')
  ],
  adminPopulationTerritorySelect: document.getElementById('admin-population-territory-select'),
  adminPopulationMap: document.getElementById('admin-population-map'),
  adminPopulationCaption: document.getElementById('admin-population-caption'),
  adminVulnerabilityGrid: document.getElementById('admin-vulnerability-grid'),
  adminVulnerabilityCaption: document.getElementById('admin-vulnerability-caption'),
  hazardSummaryText: document.getElementById('hazard-summary-text'),
  waterInfraMap: document.getElementById('water-infra-map'),
  waterMapCaption: document.getElementById('water-map-caption'),
  waterMapTitle: document.getElementById('water-map-title'),
  waterLayerControls: document.getElementById('water-layer-controls'),
  infraSummary: document.getElementById('infra-summary'),
  expositionSummaryText: document.getElementById('exposition-summary-text'),
  expositionNetworkTableBody: document.getElementById('exposition-network-table-body'),
  expositionOuvrageTableBody: document.getElementById('exposition-ouvrage-table-body'),
  expositionTotalNetworks: document.getElementById('exposition-total-networks'),
  expositionTotalOuvrages: document.getElementById('exposition-total-ouvrages'),
  expositionTotalValue: document.getElementById('exposition-total-value'),
  hazardGuadeloupeCompareBody: document.getElementById('hazard-guadeloupe-compare-body'),
  hazardCompareTitle: document.getElementById('hazard-compare-title'),
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
const tableNumberFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const tablePercentFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const tableMoneyFmt = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
const peopleFmtInt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const peopleFmtOne = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 });
const peopleFmtTwo = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const FIXED_SAMPLING_SPACING_M = 100;
const dateFmt = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
});

const PUBLIC_SHOWCASE_HOSTNAMES = new Set([
  'sib.elio.dev',
  'sib-copy.dev.elio.bottagisio.com',
  'visu.sib.dev.elio.bottagisio.com'
]);
const ADMIN_VISU_ALLOWED_HOSTNAMES = new Set([
  'sib.dev.elio.bottagisio.com',
  'localhost',
  '127.0.0.1'
]);

const runtime = {
  hostname: String(window.location.hostname || '').toLowerCase(),
  isPublicShowcase: false,
  allowAdminVisu: true
};
runtime.isPublicShowcase = PUBLIC_SHOWCASE_HOSTNAMES.has(runtime.hostname);
runtime.allowAdminVisu = ADMIN_VISU_ALLOWED_HOSTNAMES.has(runtime.hostname);

const STORM_COVERAGE_ENDPOINT = '/api/v1/hazard/coverage';
const STORM_COVERAGE_FALLBACK = [
  { id: 'na', label: 'North Atlantic', lat_min: 5.0, lat_max: 60.0, lon_min: -105.0, lon_max: -1.0 }
];

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
  if (hash === 'page3') return runtime.isPublicShowcase ? 'page1' : 'page3';
  if (hash === 'page4') return 'page4';
  if (hash === 'page5') return runtime.allowAdminVisu ? 'page5' : 'page1';
  return 'page1';
}

function setActivePage(pageKey, { updateHash = true } = {}) {
  if (runtime.isPublicShowcase && pageKey === 'page3') {
    pageKey = 'page1';
  }
  if (!runtime.allowAdminVisu && pageKey === 'page5') {
    pageKey = 'page1';
  }
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
    [els.navPage3, 'page3'],
    [els.navPage4, 'page4'],
    [els.navPage5, 'page5']
  ];
  tabs.forEach(([btn, key]) => {
    if (!btn) return;
    if (pageKey === key) btn.classList.add('active');
    else btn.classList.remove('active');
  });

  if (pageKey === 'page3') {
    renderMap();
    renderDrawPreview();
    setTimeout(() => {
      if (mapRef.instance) mapRef.instance.invalidateSize();
      if (chartRefs.user_impact_eai) chartRefs.user_impact_eai.resize();
      if (chartRefs.user_impact_rp100) chartRefs.user_impact_rp100.resize();
      if (chartRefs.user_impact_rp1000) chartRefs.user_impact_rp1000.resize();
      if (chartRefs.user_impact_eventmax) chartRefs.user_impact_eventmax.resize();
    }, 80);
  }
  if (pageKey === 'page1' || pageKey === 'page2') {
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
  if (pageKey === 'page5') {
    ensureAdminVisuMapsLoaded()
      .then(() => {
        renderAdminVisuPage();
      })
      .catch((err) => {
        console.warn('Admin visu maps could not be loaded', err);
        (els.adminVisuCaptions || []).forEach((caption) => {
          if (!caption) return;
          caption.textContent = `Donnees admin indisponibles: ${err.message}`;
        });
      });
    ensureAdminPopulationMapsLoaded()
      .then(() => {
        renderAdminPopulationMap();
      })
      .catch((err) => {
        if (els.adminPopulationCaption) {
          els.adminPopulationCaption.textContent = `Donnees population indisponibles: ${err.message}`;
        }
      });
    ensureAdminVulnerabilityCurvesLoaded()
      .then(() => {
        renderAdminVulnerabilityCurves();
      })
      .catch((err) => {
        if (els.adminVulnerabilityCaption) {
          els.adminVulnerabilityCaption.textContent = `Courbes de vulnerabilite indisponibles: ${err.message}`;
        }
      });
    setTimeout(() => {
      adminVisuMapRef.cards.forEach((card) => {
        if (card?.instance) card.instance.invalidateSize();
      });
      if (adminPopulationMapRef.instance) adminPopulationMapRef.instance.invalidateSize();
      resizeAdminVulnerabilityCharts();
    }, 80);
  }
}

function applyRuntimeMode() {
  if (!runtime.allowAdminVisu) {
    if (els.navPage5) {
      els.navPage5.hidden = true;
      els.navPage5.setAttribute('aria-hidden', 'true');
    }
  }

  if (!runtime.isPublicShowcase) {
    return;
  }

  document.body.classList.add('runtime-public');

  if (els.navPage3) {
    els.navPage3.hidden = true;
    els.navPage3.setAttribute('aria-hidden', 'true');
  }

  if (els.runtimeAccessNote) {
    els.runtimeAccessNote.hidden = false;
    els.runtimeAccessNote.textContent = "Mode vitrine publique actif: la section 'Donnees utilisateur' et l'API de calcul sont reservees aux collaborateurs autorises sur app.sib.elio.dev.";
  }

  if (els.datasetSelect) {
    els.datasetSelect.disabled = true;
  }

  if (els.pollJobId) els.pollJobId.disabled = true;
  if (els.reloadJobBtn) els.reloadJobBtn.disabled = true;
  if (els.clearDrawingsBtn) els.clearDrawingsBtn.disabled = true;
  if (els.runMemoryBox) els.runMemoryBox.hidden = true;
  if (els.computeIndicator) els.computeIndicator.hidden = true;
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

function refreshComputeIndicator() {
  if (!els.computeIndicator) return;
  const shouldShow = Boolean(state.backendComputeActive || state.uiComputeActive);
  els.computeIndicator.hidden = !shouldShow;
}

function normalizeDatasetMode(mode) {
  return String(mode || '').trim() === 'drawn' ? 'drawn' : 'uploaded';
}

function setSubmitButtonLoading(mode, active) {
  const normalized = normalizeDatasetMode(mode);
  const isDrawn = normalized === 'drawn';
  const button = isDrawn ? els.submitDrawingBtn : els.uploadSubmitBtn;
  if (!button) return;
  const spinner = button.querySelector('.btn-spinner-logo');
  if (spinner) spinner.hidden = !active;
  button.classList.toggle('is-loading', Boolean(active));
  if (active) {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    return;
  }
  button.removeAttribute('aria-busy');
  if (isDrawn) {
    button.disabled = mapRef.drawnItems ? mapRef.drawnItems.getLayers().length === 0 : true;
    return;
  }
  button.disabled = false;
}

function clearSubmitButtonLoading() {
  setSubmitButtonLoading('uploaded', false);
  setSubmitButtonLoading('drawn', false);
}

function setBackendComputeActive(active) {
  state.backendComputeActive = Boolean(active);
  refreshComputeIndicator();
}

function triggerUiComputePulse(durationMs = 900) {
  state.uiComputeActive = true;
  refreshComputeIndicator();
  if (state.uiComputeTimer) {
    clearTimeout(state.uiComputeTimer);
    state.uiComputeTimer = null;
  }
  state.uiComputeTimer = setTimeout(() => {
    state.uiComputeActive = false;
    state.uiComputeTimer = null;
    refreshComputeIndicator();
  }, Math.max(250, Number(durationMs) || 900));
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

function formatTableNumber(valueRaw) {
  return tableNumberFmt.format(Number(valueRaw) || 0);
}

function formatTableMoneyEUR(valueEur) {
  return `${tableMoneyFmt.format(Number(valueEur) || 0)} €`;
}

function formatTableRisk(valueRaw) {
  return tableNumberFmt.format(Number(valueRaw) || 0);
}

function windMpsToKmh(valueRaw) {
  const value = Number(valueRaw);
  if (!Number.isFinite(value)) return Number.NaN;
  return value * WIND_SPEED_MPS_TO_KMH;
}

function formatWindSpeed(valueRaw) {
  const kmh = windMpsToKmh(valueRaw);
  return Number.isFinite(kmh) ? numberFmt.format(kmh) : 'n/a';
}

function formatWindBinLabel(valueRaw) {
  const kmh = windMpsToKmh(valueRaw);
  if (!Number.isFinite(kmh)) return String(valueRaw ?? '');
  return numberFmt.format(kmh);
}

function toFiniteNumberArray(values) {
  if (!Array.isArray(values)) return [];
  return values
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v));
}

function vulnerabilityIntensityToKmh(valueRaw, unitRaw) {
  const value = Number(valueRaw);
  if (!Number.isFinite(value)) return Number.NaN;
  const unit = String(unitRaw || '').trim().toLowerCase();
  if (unit.includes('km/h') || unit.includes('kmh')) return value;
  return windMpsToKmh(value);
}

function normalizeAdminVulnerabilityPayload(payload) {
  if (!payload || !Array.isArray(payload.curves)) {
    throw new Error('Payload de courbes de vulnerabilite invalide');
  }
  const curves = payload.curves
    .map((curveRaw) => {
      const intensityRaw = toFiniteNumberArray(curveRaw?.intensity);
      const mddRaw = toFiniteNumberArray(curveRaw?.mdd);
      if (!intensityRaw.length || !mddRaw.length) return null;
      const len = Math.min(intensityRaw.length, mddRaw.length);
      if (len <= 1) return null;

      const intensity = intensityRaw.slice(0, len);
      const mdd = mddRaw.slice(0, len).map((v) => clamp01(v));
      const uncertaintyLowerRaw = toFiniteNumberArray(curveRaw?.uncertainty_lower);
      const uncertaintyUpperRaw = toFiniteNumberArray(curveRaw?.uncertainty_upper);
      let uncertaintyLower = null;
      let uncertaintyUpper = null;
      if (uncertaintyLowerRaw.length >= len && uncertaintyUpperRaw.length >= len) {
        uncertaintyLower = uncertaintyLowerRaw.slice(0, len).map((v) => clamp01(v));
        uncertaintyUpper = uncertaintyUpperRaw.slice(0, len).map((v) => clamp01(v));
      }

      return {
        impf_id: Number(curveRaw?.impf_id),
        code: String(curveRaw?.code || 'n/a'),
        name: String(curveRaw?.name || curveRaw?.code || 'Courbe'),
        source: String(curveRaw?.source || 'source inconnue'),
        geography: String(curveRaw?.geography || 'geographie non renseignee'),
        modeledInfrastructureType: String(curveRaw?.modeled_infrastructure_type || 'N/A'),
        modeledInfrastructureCharacteristics: String(curveRaw?.modeled_infrastructure_characteristics || 'N/A'),
        sibAssetTypes: Array.isArray(curveRaw?.sib_asset_types) ? curveRaw.sib_asset_types.map((v) => String(v || '').trim()).filter(Boolean) : [],
        intensity_unit: String(curveRaw?.intensity_unit || payload?.intensity_unit || 'm/s'),
        intensity,
        mdd,
        uncertaintyLower,
        uncertaintyUpper
      };
    })
    .filter(Boolean);

  if (!curves.length) throw new Error('Aucune courbe exploitable dans le payload de vulnerabilite');

  return {
    profile: String(payload.profile || 'unknown'),
    curves
  };
}

function parseLocaleNumber(valueRaw) {
  const text = String(valueRaw ?? '').trim();
  if (!text) return Number.NaN;
  const normalized = text.replace(/\s+/g, '').replace(',', '.');
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function isWindMpsIndicator(indicatorRaw) {
  return String(indicatorRaw || '').toLowerCase().includes('m/s');
}

function indicatorDisplayUnit(indicatorRaw) {
  return String(indicatorRaw || '').replace(/\(\s*m\/s\s*\)/gi, `(${WIND_SPEED_UNIT_DISPLAY})`);
}

function formatWindTableValueFromMps(valueRaw) {
  const parsed = parseLocaleNumber(valueRaw);
  const kmh = windMpsToKmh(parsed);
  if (!Number.isFinite(kmh)) return String(valueRaw ?? '');
  return formatTableNumber(kmh);
}

function formatGenericTableCellValue(valueRaw) {
  const parsed = parseLocaleNumber(valueRaw);
  if (Number.isFinite(parsed)) return formatTableNumber(parsed);
  return String(valueRaw ?? '');
}

function estimatedRunDurationMessage(mode) {
  const normalized = normalizeDatasetMode(mode);
  const isFirstRun = !Array.isArray(state.recentRuns) || state.recentRuns.length === 0;
  if (normalized === 'drawn') {
    if (isFirstRun) return 'Temps estime du run: environ 2 a 6 min (premier lancement souvent plus long).';
    return 'Temps estime du run: environ 1 a 3 min (selon la charge serveur et le nombre de geometries).';
  }
  if (isFirstRun) return 'Temps estime du run: environ 3 a 8 min (premier lancement souvent plus long).';
  return "Temps estime du run: environ 1 a 4 min (selon la taille du fichier et la charge serveur).";
}

function showRunDurationEstimate(mode) {
  if (els.uploadRunEstimate) {
    els.uploadRunEstimate.hidden = true;
    els.uploadRunEstimate.textContent = '';
  }
  if (els.drawRunEstimate) {
    els.drawRunEstimate.hidden = true;
    els.drawRunEstimate.textContent = '';
  }
  const normalized = normalizeDatasetMode(mode);
  const target = normalized === 'drawn' ? els.drawRunEstimate : els.uploadRunEstimate;
  if (!target) return;
  target.textContent = estimatedRunDurationMessage(normalized);
  target.hidden = false;
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

function dedupeNonEmptyStrings(values) {
  const seen = new Set();
  const out = [];
  (Array.isArray(values) ? values : []).forEach((value) => {
    const text = String(value || '').trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    out.push(text);
  });
  return out;
}

function parseCoverageZoneFromPayload(payload, fallbackId, fallbackLabel) {
  const direct = payload && typeof payload === 'object' && payload.lat_min != null && payload.lat_max != null
    ? payload
    : null;
  const bbox = direct || payload?.meta?.bbox;
  if (!bbox || typeof bbox !== 'object') return null;
  const latMin = Number(bbox.lat_min);
  const latMax = Number(bbox.lat_max);
  const lonMin = Number(bbox.lon_min);
  const lonMax = Number(bbox.lon_max);
  if (![latMin, latMax, lonMin, lonMax].every((v) => Number.isFinite(v))) return null;
  if (latMin >= latMax || lonMin === lonMax) return null;
  const territory = String(payload?.id || payload?.code || payload?.meta?.territory || fallbackId || '').trim() || fallbackId;
  const territoryLabel = String(payload?.label || fallbackLabel || territory || fallbackId || '').trim() || 'Territoire';
  return {
    id: territory,
    label: territoryLabel,
    lat_min: latMin,
    lat_max: latMax,
    lon_min: lonMin,
    lon_max: lonMax
  };
}

function coverageFeatureCollectionFromZones(zones) {
  const features = (Array.isArray(zones) ? zones : []).map((zone) => ({
    type: 'Feature',
    properties: {
      zone_id: String(zone.id || ''),
      label: String(zone.label || zone.id || 'Zone STORM')
    },
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [Number(zone.lon_min), Number(zone.lat_min)],
        [Number(zone.lon_max), Number(zone.lat_min)],
        [Number(zone.lon_max), Number(zone.lat_max)],
        [Number(zone.lon_min), Number(zone.lat_max)],
        [Number(zone.lon_min), Number(zone.lat_min)]
      ]]
    }
  }));
  return { type: 'FeatureCollection', features };
}

async function ensureStormCoverageLoaded() {
  if (Array.isArray(state.stormCoverageZones) && state.stormCoverageZones.length) {
    return state.stormCoverageZones;
  }
  if (state.stormCoveragePromise) return state.stormCoveragePromise;

  state.stormCoveragePromise = (async () => {
    let zones = [];
    try {
      const res = await fetch(STORM_COVERAGE_ENDPOINT, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      const rawCoverages = Array.isArray(payload?.coverages) ? payload.coverages : [];
      zones = rawCoverages
        .map((zone, idx) => parseCoverageZoneFromPayload(zone, `zone-${idx + 1}`, `Zone ${idx + 1}`))
        .filter((zone) => Boolean(zone));
    } catch (err) {
      console.warn('STORM coverage load failed, using fallback bounds', err);
    }

    if (!zones.length) zones = STORM_COVERAGE_FALLBACK.map((zone) => ({ ...zone }));
    state.stormCoverageZones = zones;
    state.stormCoverageGeoJson = coverageFeatureCollectionFromZones(zones);
    renderStormCoverageLayer();
    if (state.currentPage === 'page3') {
      setTimeout(() => {
        if (state.currentPage === 'page3') renderMap();
      }, 0);
    }
    return zones;
  })().finally(() => {
    state.stormCoveragePromise = null;
  });

  return state.stormCoveragePromise;
}

function renderStormCoverageLayer() {
  if (!window.L || !mapRef.instance) return;
  if (mapRef.stormCoverageLayer) {
    mapRef.instance.removeLayer(mapRef.stormCoverageLayer);
    mapRef.stormCoverageLayer = null;
  }
  const fc = state.stormCoverageGeoJson;
  if (!fc || fc.type !== 'FeatureCollection' || !Array.isArray(fc.features) || !fc.features.length) return;

  mapRef.stormCoverageLayer = L.geoJSON(fc, {
    style: {
      color: '#ff8f73',
      weight: 2,
      opacity: 0.9,
      fillColor: '#ffca58',
      fillOpacity: 0.05,
      dashArray: '8 5'
    },
    interactive: false
  }).addTo(mapRef.instance);

  if (typeof mapRef.stormCoverageLayer.bringToBack === 'function') {
    mapRef.stormCoverageLayer.bringToBack();
  }
}

function getStormCoverageBounds() {
  const zones = Array.isArray(state.stormCoverageZones) ? state.stormCoverageZones : [];
  if (!zones.length || !window.L) return null;
  let bounds = null;
  zones.forEach((zone) => {
    const minLat = Number(zone.lat_min);
    const maxLat = Number(zone.lat_max);
    const minLon = Number(zone.lon_min);
    const maxLon = Number(zone.lon_max);
    if (![minLat, maxLat, minLon, maxLon].every((v) => Number.isFinite(v))) return;
    const b = L.latLngBounds([minLat, minLon], [maxLat, maxLon]);
    bounds = bounds ? bounds.extend(b) : b;
  });
  return bounds && bounds.isValid() ? bounds : null;
}

function geometryBoundsFromCoords(coords, acc = { minLon: Number.POSITIVE_INFINITY, minLat: Number.POSITIVE_INFINITY, maxLon: Number.NEGATIVE_INFINITY, maxLat: Number.NEGATIVE_INFINITY, count: 0 }) {
  if (Array.isArray(coords) && coords.length >= 2 && Number.isFinite(Number(coords[0])) && Number.isFinite(Number(coords[1]))) {
    const lon = Number(coords[0]);
    const lat = Number(coords[1]);
    acc.minLon = Math.min(acc.minLon, lon);
    acc.minLat = Math.min(acc.minLat, lat);
    acc.maxLon = Math.max(acc.maxLon, lon);
    acc.maxLat = Math.max(acc.maxLat, lat);
    acc.count += 1;
    return acc;
  }
  if (Array.isArray(coords)) {
    coords.forEach((child) => geometryBoundsFromCoords(child, acc));
  }
  return acc;
}

function geometryBounds(geometry) {
  if (!geometry || typeof geometry !== 'object') return null;
  if (geometry.type === 'GeometryCollection' && Array.isArray(geometry.geometries)) {
    const all = geometry.geometries
      .map((geom) => geometryBounds(geom))
      .filter((bbox) => Array.isArray(bbox));
    if (!all.length) return null;
    return [
      Math.min(...all.map((b) => b[0])),
      Math.min(...all.map((b) => b[1])),
      Math.max(...all.map((b) => b[2])),
      Math.max(...all.map((b) => b[3]))
    ];
  }
  const acc = geometryBoundsFromCoords(geometry.coordinates);
  if (!acc || acc.count <= 0) return null;
  return [acc.minLon, acc.minLat, acc.maxLon, acc.maxLat];
}

function bboxIntersectsCoverageZone(a, zone) {
  const [aMinLon, aMinLat, aMaxLon, aMaxLat] = a;
  const bMinLon = Number(zone.lon_min);
  const bMinLat = Number(zone.lat_min);
  const bMaxLon = Number(zone.lon_max);
  const bMaxLat = Number(zone.lat_max);
  if (![aMinLon, aMinLat, aMaxLon, aMaxLat, bMinLon, bMinLat, bMaxLon, bMaxLat].every((v) => Number.isFinite(v))) {
    return true;
  }
  if (aMaxLon < bMinLon) return false;
  if (aMinLon > bMaxLon) return false;
  if (aMaxLat < bMinLat) return false;
  if (aMinLat > bMaxLat) return false;
  return true;
}

function featureOutsideStormCoverage(feature) {
  const zones = Array.isArray(state.stormCoverageZones) ? state.stormCoverageZones : [];
  if (!zones.length) return false;
  const bbox = geometryBounds(feature?.geometry);
  if (!bbox) return false;
  const intersects = zones.some((zone) => bboxIntersectsCoverageZone(bbox, zone));
  return !intersects;
}

function outsideCoverageRefsForFeatureCollection(fc, mode = 'uploaded') {
  if (!fc || fc.type !== 'FeatureCollection' || !Array.isArray(fc.features)) return [];
  const refs = fc.features.flatMap((feature, idx) => {
    if (!featureOutsideStormCoverage(feature)) return [];
    const props = feature?.properties || {};
    if (mode === 'drawn') {
      const label = String(props.label || props.asset_label || props.asset_id || `Geometrie ${idx + 1}`).trim();
      return label ? [label] : [];
    }
    const assetId = String(props.asset_id || props.id || props.label || `Ligne ${idx + 1}`).trim();
    return assetId ? [assetId] : [];
  });
  return dedupeNonEmptyStrings(refs);
}

function drawFeatureCollectionFromMapLayers() {
  if (!mapRef.drawnItems) return null;
  const layers = mapRef.drawnItems.getLayers();
  if (!layers.length) return null;
  return {
    type: 'FeatureCollection',
    features: layers.map((layer) => layer.toGeoJSON())
  };
}

function renderOutsideCoverageWarnings() {
  const uploaded = dedupeNonEmptyStrings(state.outsideCoverageByMode.uploaded || []);
  const drawn = dedupeNonEmptyStrings(state.outsideCoverageByMode.drawn || []);

  const lines = [];
  if (uploaded.length) {
    lines.push(`Attention, l'asset ID ${uploaded.join(', ')} est hors de la zone d'aléas. Il ne serait donc pas affecté par les aléas.`);
  }
  if (drawn.length) {
    lines.push(`Attention, la geometrie ${drawn.join(', ')} est hors de la zone d'aléas. Elle ne sera donc pas affectee par les aléas.`);
  }

  if (els.impactOutsideWarning) {
    if (!lines.length) {
      els.impactOutsideWarning.hidden = true;
      els.impactOutsideWarning.textContent = '';
      return;
    }
    els.impactOutsideWarning.hidden = false;
    els.impactOutsideWarning.innerHTML = lines.map((line) => escapeHtml(line)).join('<br />');
  }
}

function setOutsideCoverageWarning(mode, refs) {
  const normalized = normalizeDatasetMode(mode);
  state.outsideCoverageByMode[normalized] = dedupeNonEmptyStrings(refs);
  renderOutsideCoverageWarnings();
}

function formatStateTuple(statePct) {
  const p = statePct || {};
  return `S0 ${tablePercentFmt.format(Number(p.S0 || 0))} · S1 ${tablePercentFmt.format(Number(p.S1 || 0))} · S2 ${tablePercentFmt.format(Number(p.S2 || 0))} · S3 ${tablePercentFmt.format(Number(p.S3 || 0))}`;
}

function ensureResultShape(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('Payload résultat invalide');
  if (!raw.meta || !raw.exposure_summary || !Array.isArray(raw.territory_results) || !raw.portfolio_results || !raw.graphs) {
    throw new Error('Payload résultat incomplet');
  }
  if (!Array.isArray(raw.asset_results)) raw.asset_results = [];
  if (!raw.input_features_geojson || typeof raw.input_features_geojson !== 'object') raw.input_features_geojson = null;
  if (!raw.meta.run_label) raw.meta.run_label = raw.meta.title || '';
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
  const caseMeta = state.page1Analysis?.meta || null;
  if ((state.currentPage === 'page1' || state.currentPage === 'page2') && caseMeta) {
    els.badgeSource.textContent = `Source: ${caseMeta.source || 'inconnue'}`;
    els.badgeUpdated.textContent = `Mis a jour: ${formatDate(caseMeta.generated_at)}`;
    els.badgeEngine.textContent = `Moteur: climada_with_interdependency_v1`;
    return;
  }
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
  const p = getHazardPortfolio(result, hazardKey);
  const delta = result.portfolio_results?.delta || { eai_eur: 0, eai_pct: 0 };
  const summary = result.exposure_summary || {};
  const exposureForScope = Number(summary.total_exposure_eur || 0);
  const safeExposure = exposureForScope > 0 ? exposureForScope : 1;
  const pctExposure = (value) => (Number(value || 0) / safeExposure) * 100;
  const assetCountForScope = Number(summary.asset_count_original || 0);
  const pointCountForScope = Number(summary.asset_count_points || 0);
  const lossRp50 = scenarioLossFromPortfolio(p, 'rp50');
  const lossRp100 = scenarioLossFromPortfolio(p, 'rp100');
  const lossEventMax = scenarioLossFromPortfolio(p, 'event_max');

  const cards = [
    {
      label: 'Exposition totale',
      value: formatMoneyMEUR(exposureForScope),
      sub: `${numberFmt.format(assetCountForScope)} actifs · ${numberFmt.format(pointCountForScope || 0)} points desagreges`
    },
    {
      label: "EAI de l'aléa sélectionné",
      value: formatMoneyMEUR(p.eai_eur),
      sub: `${percentFmt.format(pctExposure(p.eai_eur))}% de l'exposition totale · AAI agg ${formatMoneyMEUR(p.aai_agg_eur)} · ${getHazardLabel(hazardKey)}`
    },
    {
      label: 'Pertes evenements temps de retour 50 ans',
      value: formatMoneyMEUR(lossRp50),
      sub: `${percentFmt.format(pctExposure(lossRp50))}% de l'exposition totale · ${getHazardLabel(hazardKey)}`
    },
    {
      label: 'Pertes evenements temps de retour 100 ans',
      value: formatMoneyMEUR(lossRp100),
      sub: `${percentFmt.format(pctExposure(lossRp100))}% de l'exposition totale · ${getHazardLabel(hazardKey)}`
    },
    {
      label: "Pertes de l'evenement max",
      value: formatMoneyMEUR(lossEventMax),
      sub: `${percentFmt.format(pctExposure(lossEventMax))}% de l'exposition totale · Estimation portefeuille`
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
  const territory = state.caseStudyTerritory === 'martinique' ? 'martinique' : 'guadeloupe';
  const territoryLabel = territory === 'martinique' ? 'Martinique' : 'Guadeloupe';
  const territoryLabelLower = territoryLabel.toLowerCase();
  if (els.caseStudyTitle) {
    els.caseStudyTitle.textContent = `Impact des risques physiques sur les infrastructures : etude de cas ${territoryLabel}`;
  }
  if (els.caseStudySubtitle) {
    els.caseStudySubtitle.textContent =
      `Cette page presente un exercice de demonstration d'une analyse complete des risques cycloniques sur les reseaux d'eau et d'electricite en ${territoryLabel}. Les aleas cycloniques sont modelises a partir des bases STORM (Bloemdaal et al., 2020) et STORM_CMCC (Bloemdaal et al., 2022). Les resultats sont proposes comme prototype methodologique a valider et affiner.`;
  }
  if (els.waterMapTitle) {
    els.waterMapTitle.textContent = `Carte des infrastructures d'eau et d'electricite de ${territoryLabel}`;
  }
  if (els.hazardCompareTitle) {
    els.hazardCompareTitle.textContent = `Comparaison vitesses max - zone ${territoryLabel}`;
  }
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
  const newValues = valuation.new_values || {};
  const dynamicRules = [
    'Elec basse tension aerien: 167 060 EUR/km (D3 overhead line 220kV)',
    'Elec basse tension souterrain: 1 336 480 EUR/km (derive D3)',
    'Elec haute tension aerien: 249 299 EUR/km (D3 overhead line 380kV)',
    'Elec haute tension souterrain: 1 994 390 EUR/km (D3)',
    `AEP canalisations (${territory}): ${numberFmt.format(Number(newValues.aep_cana_eur_per_km || 0))} EUR/km`,
    `EU canalisations (${territory}): ${numberFmt.format(Number(newValues.eu_cana_eur_per_km || 0))} EUR/km`,
    `EU PR (${territory}): ${numberFmt.format(Number(newValues.eu_pr_eur_per_unit || 0))} EUR/unite`,
    `EU STEP (${territory}): ${numberFmt.format(Number(newValues.eu_step_eur_per_unit || 0))} EUR/unite`,
    'AEP ouvrages: valeur fixe par ovrg_type (TRAIT/STPMP/CAP/CUV/autres)',
    'Source OFB: comparateur de couts, moyenne territoriale observee'
  ];

  els.methodValuationOfb.innerHTML = `
    <p class="muted small">${escapeHtml(`Source: ${source}. Territoire applique: ${territory}. Version: ${version}.`)}</p>
    <p class="muted small">${escapeHtml(`Nombre de prix compares (${territory}): ${compared}.`)}</p>
    <p class="muted small">${escapeHtml(policy)}</p>
    <ul>${dynamicRules.map((rule) => `<li>${escapeHtml(rule)}</li>`).join('')}</ul>
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
  const territory = state.caseStudyTerritory === 'martinique' ? 'Martinique' : 'Guadeloupe';

  if (els.expositionSummaryText) {
    els.expositionSummaryText.textContent = `L’exposition représente tous les enjeux qui peuvent et doivent être protégés face aux risques physiques. Dans ce cas d’étude sur la ${territory}, ont été pris en compte les réseaux d’eau potable (AEP), d’eau usées (EU) ainsi que les réseaux electriques (Basse tension aérien, basse tension souterrain, haute tension aerien, haute tension souterrain).`;
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
        <td class="num">${escapeHtml(formatTableNumber(row.lengthKm || 0))}</td>
        <td class="num">${escapeHtml(formatTableNumber(row.valuePerKm || 0))}</td>
        <td class="num">${escapeHtml(formatTableMoneyEUR(row.total || 0))}</td>
      </tr>
    `).join('') + `
      <tr class="table-total-row">
        <td><strong>Total reseaux</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num"><strong>${escapeHtml(formatTableMoneyEUR(totalNetworks))}</strong></td>
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
        valuePerUnitText: formatTableNumber(Number(newValues.eu_pr_eur_per_unit || 0)),
        total: Number(totals.eau_eu_pr || 0)
      },
      {
        label: 'STEP',
        count: Number(counts.eu_step_total || 0),
        valuePerUnitText: formatTableNumber(Number(newValues.eu_step_eur_per_unit || 0)),
        total: Number(totals.eau_eu_step || 0)
      }
    ];
    const totalOuvrages = ouvrageRows.reduce((acc, row) => acc + Number(row.total || 0), 0);
    els.expositionOuvrageTableBody.innerHTML = ouvrageRows.map((row) => `
      <tr>
        <td>${escapeHtml(row.label)}</td>
        <td class="num">${escapeHtml(formatTableNumber(row.count || 0))}</td>
        <td class="num">${escapeHtml(row.valuePerUnitText)}</td>
        <td class="num">${escapeHtml(formatTableMoneyEUR(row.total || 0))}</td>
      </tr>
    `).join('') + `
      <tr class="table-total-row">
        <td><strong>Total ouvrages</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num"><strong>${escapeHtml(formatTableMoneyEUR(totalOuvrages))}</strong></td>
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
    const rows = Array.isArray(hazard.zone_wind_comparison_table)
      ? hazard.zone_wind_comparison_table
      : (Array.isArray(hazard.guadeloupe_wind_comparison_table) ? hazard.guadeloupe_wind_comparison_table : []);
    if (!rows.length) {
      els.hazardGuadeloupeCompareBody.innerHTML = '<tr><td colspan="4">Tableau indisponible.</td></tr>';
    } else {
      els.hazardGuadeloupeCompareBody.innerHTML = rows.map((row) => `
        <tr>
          <td>${escapeHtml(isWindMpsIndicator(row.indicator) ? indicatorDisplayUnit(row.indicator) : String(row.indicator || ''))}</td>
          <td class="num">${escapeHtml(isWindMpsIndicator(row.indicator) ? formatWindTableValueFromMps(row.storm) : formatGenericTableCellValue(row.storm))}</td>
          <td class="num">${escapeHtml(isWindMpsIndicator(row.indicator) ? formatWindTableValueFromMps(row.storm_cmcc) : formatGenericTableCellValue(row.storm_cmcc))}</td>
          <td class="num">${escapeHtml(isWindMpsIndicator(row.indicator) ? formatWindTableValueFromMps(row.delta) : formatGenericTableCellValue(row.delta))}</td>
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

function withRp50ImpactScenario(impactPayload) {
  const impact = impactPayload || {};
  const tables = impact?.state_damage_tables || {};
  const summary = impact?.summary_metrics || {};
  const stormSummary = summary?.storm || {};
  const cmccSummary = summary?.storm_cmcc || {};

  const stormRp50 = Number.isFinite(Number(stormSummary.rp50_total_loss_eur))
    ? Number(stormSummary.rp50_total_loss_eur)
    : estimateRp50FromRp100AndRp1000(stormSummary.rp100_total_loss_eur, stormSummary.rp1000_total_loss_eur);
  const cmccRp50 = Number.isFinite(Number(cmccSummary.rp50_total_loss_eur))
    ? Number(cmccSummary.rp50_total_loss_eur)
    : estimateRp50FromRp100AndRp1000(cmccSummary.rp100_total_loss_eur, cmccSummary.rp1000_total_loss_eur);

  const stormRp100 = Number(stormSummary.rp100_total_loss_eur || 0);
  const cmccRp100 = Number(cmccSummary.rp100_total_loss_eur || 0);
  const stormFactor = stormRp100 > 0 ? (stormRp50 / stormRp100) : 1;
  const cmccFactor = cmccRp100 > 0 ? (cmccRp50 / cmccRp100) : 1;

  const rp100Rows = Array.isArray(tables.rp100) ? tables.rp100 : [];
  const rp50Rows = Array.isArray(tables.rp50) && tables.rp50.length
    ? tables.rp50
    : rp100Rows.map((row) => {
      const storm = row?.storm || {};
      const cmcc = row?.storm_cmcc || {};
      return {
        ...row,
        storm: { ...storm, damage_eur: Number(storm.damage_eur || 0) * stormFactor },
        storm_cmcc: { ...cmcc, damage_eur: Number(cmcc.damage_eur || 0) * cmccFactor },
      };
    });

  const byScenario = impact?.damage_breakdown_by_scenario || {};
  let rp50Breakdown = byScenario?.rp50;
  if (!rp50Breakdown && byScenario?.rp100) {
    const rp100Breakdown = byScenario.rp100 || {};
    const stormRows = Array.isArray(rp100Breakdown.storm) ? rp100Breakdown.storm : [];
    const cmccRows = Array.isArray(rp100Breakdown.storm_cmcc) ? rp100Breakdown.storm_cmcc : [];
    rp50Breakdown = {
      storm: stormRows.map((row) => ({ ...row, damage_eur: Number(row?.damage_eur || 0) * stormFactor })),
      storm_cmcc: cmccRows.map((row) => ({ ...row, damage_eur: Number(row?.damage_eur || 0) * cmccFactor })),
    };
  }

  return {
    ...impact,
    summary_metrics: {
      ...summary,
      storm: { ...stormSummary, rp50_total_loss_eur: stormRp50 },
      storm_cmcc: { ...cmccSummary, rp50_total_loss_eur: cmccRp50 },
    },
    state_damage_tables: {
      ...tables,
      rp50: rp50Rows,
    },
    damage_breakdown_by_scenario: {
      ...byScenario,
      ...(rp50Breakdown ? { rp50: rp50Breakdown } : {}),
    },
  };
}

function renderPage1Impact(analysis) {
  const impact = withRp50ImpactScenario(analysis?.impact || {});
  const tables = impact.state_damage_tables || {};
  renderImpactScenarioTable(els.impactTableAnnualBody, Array.isArray(tables.annual) ? tables.annual : [], 'EAI');
  renderImpactScenarioTable(els.impactTableRp100Body, Array.isArray(tables.rp50) ? tables.rp50 : [], 'RP50');
  renderImpactScenarioTable(els.impactTableRp1000Body, Array.isArray(tables.rp100) ? tables.rp100 : [], 'RP100');
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
        <td class="num">${escapeHtml(formatTableMoneyEUR(storm.damage_eur || 0))}</td>
        <td class="num">${escapeHtml(formatStateTuple(cmcc.state_pct))}</td>
        <td class="num">${escapeHtml(formatTableMoneyEUR(cmcc.damage_eur || 0))}</td>
      </tr>
    `;
  }).join('');
}

function renderPage1Conclusion(analysis) {
  if (!els.conclusionText) return;
  const expo = analysis?.exposition || {};
  const impact = withRp50ImpactScenario(analysis?.impact || {});
  const storm = impact?.summary_metrics?.storm || {};
  const cmcc = impact?.summary_metrics?.storm_cmcc || {};
  const totalValue = Number(expo.total_value_all_eur || 0);
  const safeTotal = totalValue > 0 ? totalValue : 1;
  const toPct = (value) => (Number(value || 0) / safeTotal) * 100;
  const toM = (value) => Math.round((Number(value || 0) / 1_000_000));
  const txt = [
    `Valeur totale du portefeuille d'infrastructures: ${numberFmt.format(Math.round(totalValue / 1_000_000))} M€.`,
    `Dommages annuels moyens: STORM ${numberFmt.format(toM(storm.eai_total_eur))} M€ (${percentFmt.format(toPct(storm.eai_total_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.eai_total_eur))} M€ (${percentFmt.format(toPct(cmcc.eai_total_eur))} %).`,
    `Scenario temps de retour 50 ans: STORM ${numberFmt.format(toM(storm.rp50_total_loss_eur))} M€ (${percentFmt.format(toPct(storm.rp50_total_loss_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.rp50_total_loss_eur))} M€ (${percentFmt.format(toPct(cmcc.rp50_total_loss_eur))} %).`,
    `Scenario temps de retour 100 ans: STORM ${numberFmt.format(toM(storm.rp100_total_loss_eur))} M€ (${percentFmt.format(toPct(storm.rp100_total_loss_eur))} %), STORM_CMCC ${numberFmt.format(toM(cmcc.rp100_total_loss_eur))} M€ (${percentFmt.format(toPct(cmcc.rp100_total_loss_eur))} %).`,
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

function rememberRunLabel(jobId, runLabel) {
  const id = String(jobId || '').trim();
  if (!id) return;
  const label = String(runLabel || '').trim();
  state.runLabelsByJob[id] = label || id;
}

function datasetModeFromResult(result, fallbackMode = state.selectedDatasetMode) {
  if (!result || typeof result !== 'object') return normalizeDatasetMode(fallbackMode);
  const modeRaw = result?.meta?.dataset_mode || result?.dataset_mode || fallbackMode;
  return normalizeDatasetMode(modeRaw);
}

function runLabelForJob(jobId) {
  const id = String(jobId || '').trim();
  if (!id) return '';
  return String(state.runLabelsByJob[id] || '').trim();
}

function resultRunLabel(result) {
  if (!result || typeof result !== 'object') return '';
  return String(result?.meta?.run_label || result?.meta?.title || '').trim();
}

function renderRunMemoryList() {
  if (!els.runMemoryList) return;
  const runs = Array.isArray(state.recentRuns) ? state.recentRuns : [];
  if (!runs.length) {
    els.runMemoryList.innerHTML = '<li class="muted small">Aucun run en memoire.</li>';
    return;
  }
  els.runMemoryList.innerHTML = runs.map((run) => {
    const runLabel = String(run?.run_label || run?.job_id || 'Run').trim();
    const jobId = String(run?.job_id || '').trim();
    const mode = run?.dataset_mode === 'drawn' ? 'drawn' : 'uploaded';
    const status = String(run?.status || 'unknown');
    const updatedAt = formatDate(run?.updated_at);
    const stage = String(run?.stage || '').trim();
    return `
      <li class="run-memory-item">
        <button type="button" class="run-memory-btn" data-run-job-id="${escapeHtml(jobId)}" data-run-mode="${escapeHtml(mode)}" data-run-label="${escapeHtml(runLabel)}">${escapeHtml(runLabel)}</button>
        <div class="run-memory-meta">${escapeHtml(status)}${stage ? ` · ${escapeHtml(stage)}` : ''} · ${escapeHtml(updatedAt)} · ${escapeHtml(jobId)}</div>
      </li>
    `;
  }).join('');
}

async function refreshRunMemoryList() {
  if (runtime.isPublicShowcase) return;
  if (!els.runMemoryList) return;
  try {
    const res = await fetch('/api/v1/runs/recent?limit=10', { cache: 'no-store' });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
    const runs = Array.isArray(payload.runs) ? payload.runs : [];
    state.recentRuns = runs;
    runs.forEach((run) => {
      rememberRunLabel(run?.job_id, run?.run_label || run?.job_id);
    });
    renderRunMemoryList();
  } catch (err) {
    els.runMemoryList.innerHTML = `<li class="muted small">Memoire des runs indisponible (${escapeHtml(err.message)}).</li>`;
  }
}

function syncMapPreviewFromResult(result, mode = 'uploaded') {
  const fc = result?.input_features_geojson;
  if (!fc || typeof fc !== 'object' || fc.type !== 'FeatureCollection' || !Array.isArray(fc.features)) {
    return;
  }
  if (!ensureMap()) return;
  const normalizedMode = normalizeDatasetMode(mode);
  setUploadedPreviewGeoJson(fc, normalizedMode);
  renderTerritorySelectionState();
  renderMap();
}

function categoryFromExposureType(typeValue) {
  const raw = String(typeValue || '').trim();
  return EXPOSURE_TYPE_TO_CATEGORY[raw] || 'habitation';
}

function assetFromExposureType(typeValue) {
  const raw = String(typeValue || '').trim();
  return EXPOSURE_TYPE_TO_ASSET[raw] || 'habitation';
}

function filteredResultRows() {
  const result = getActiveResult();
  if (!result) return [];
  const sourceRows = Array.isArray(result.asset_results) && result.asset_results.length
    ? result.asset_results
    : (result.territory_results || []).map((row) => ({
      asset_id: row.territory_id,
      asset_label: row.territory_label,
      geometry_type: 'Aggregate',
      exposure_eur: row.exposure_eur,
      eai_storm_eur: row.eai_storm_eur,
      eai_cmcc_eur: row.eai_cmcc_eur,
      risk_index_storm: row.risk_index_storm,
      risk_index_cmcc: row.risk_index_cmcc
    }));
  let rows = [...sourceRows];
  if (state.territorySearch) {
    const q = state.territorySearch.toLowerCase();
    rows = rows.filter((r) => String(r.asset_label || '').toLowerCase().includes(q) || String(r.asset_id || '').toLowerCase().includes(q));
  }
  rows.sort((a, b) => {
    const key = currentHazardKey() === 'storm_cmcc' ? 'risk_index_cmcc' : 'risk_index_storm';
    return (Number(b[key]) || 0) - (Number(a[key]) || 0);
  });
  return rows;
}

function renderTerritoryTable() {
  const result = getActiveResult();
  if (!result) {
    if (els.tableCaption) els.tableCaption.textContent = "Aucun resultat d'impact charge.";
    els.territoryTableBody.innerHTML = '<tr><td colspan="7">Aucune donnée chargée.</td></tr>';
    return;
  }
  const rows = filteredResultRows();
  const modeLabel = state.activeResultMode === 'drawn' ? 'géométrie(s) dessinée(s)' : 'actif(s) importé(s)';
  els.tableCaption.textContent = `${rows.length} ${modeLabel} · source ${result.meta?.source || 'inconnue'} · aléa ${getHazardLabel(currentHazardKey())}`;

  if (!rows.length) {
    els.territoryTableBody.innerHTML = '<tr><td colspan="7">Aucun actif / géométrie ne correspond au filtre.</td></tr>';
    return;
  }

  els.territoryTableBody.innerHTML = rows.map((row) => {
    return `
      <tr>
        <td>${escapeHtml(row.asset_label || row.asset_id || 'Sans label')}</td>
        <td>${escapeHtml(row.geometry_type || 'Unknown')}</td>
        <td class="num">${escapeHtml(formatTableNumber((row.exposure_eur || 0) / 1_000_000))}</td>
        <td class="num">${escapeHtml(formatTableNumber((row.eai_storm_eur || 0) / 1_000_000))}</td>
        <td class="num">${escapeHtml(formatTableNumber((row.eai_cmcc_eur || 0) / 1_000_000))}</td>
        <td class="num">${escapeHtml(formatTableRisk(row.risk_index_storm))}</td>
        <td class="num">${escapeHtml(formatTableRisk(row.risk_index_cmcc))}</td>
      </tr>
    `;
  }).join('');
}

function renderTerritorySelectionState() {
  const drawnCount = mapRef.drawnItems ? mapRef.drawnItems.getLayers().length : 0;
  const importedCount = Number(mapRef.uploadedFeatureCount || 0);
  els.selectedTerritoryChip.textContent = `${drawnCount} dessin(s) · ${importedCount} entite(s) importees`;
}

function drawModeLabel(mode) {
  if (mode === 'marker') return 'point';
  if (mode === 'polyline') return 'ligne';
  if (mode === 'polygon') return 'polygone';
  if (mode === 'rectangle') return 'rectangle';
  return mode || 'dessin';
}

function updateDrawModeButtons() {
  if (!els.drawModeButtons) return;
  const buttons = els.drawModeButtons.querySelectorAll('button[data-draw-mode]');
  buttons.forEach((btn) => {
    const mode = String(btn.getAttribute('data-draw-mode') || '');
    if (mode === state.activeDrawMode) btn.classList.add('active');
    else btn.classList.remove('active');
  });
}

function disableActiveDrawMode() {
  if (!state.activeDrawMode) return;
  const handler = mapRef.drawHandlers[state.activeDrawMode];
  if (handler && typeof handler.disable === 'function') handler.disable();
  state.activeDrawMode = null;
  updateDrawModeButtons();
}

function startDrawMode(mode) {
  if (!ensureMap() || !window.L || !window.L.Draw) {
    showError("Les outils de dessin Leaflet ne sont pas disponibles.");
    return;
  }

  disableActiveDrawMode();

  const markerIcon = window.L.divIcon({
    className: 'draw-point-icon',
    iconSize: [14, 14],
    iconAnchor: [7, 7]
  });
  const markerHandler = window.L.Draw.CircleMarker || window.L.Draw.Marker;
  const optionsByMode = {
    marker: window.L.Draw.CircleMarker
      ? { radius: 7, shapeOptions: { color: '#5bc5f2', fillColor: '#5bc5f2', fillOpacity: 0.92, weight: 2 } }
      : { icon: markerIcon },
    polyline: { shapeOptions: { color: '#dfb85a', weight: 3, opacity: 0.9 } },
    polygon: { allowIntersection: false, shapeOptions: { color: '#4bb1cb', weight: 2, fillOpacity: 0.12 } },
    rectangle: { shapeOptions: { color: '#4bb1cb', weight: 2, fillOpacity: 0.12 } }
  };
  const constructors = {
    marker: markerHandler,
    polyline: L.Draw.Polyline,
    polygon: L.Draw.Polygon,
    rectangle: L.Draw.Rectangle
  };
  const Handler = constructors[mode];
  if (!Handler) {
    showError(`Mode de dessin non supporte: ${mode}`);
    return;
  }

  const handler = new Handler(mapRef.instance, optionsByMode[mode] || {});
  mapRef.drawHandlers[mode] = handler;
  state.activeDrawMode = mode;
  updateDrawModeButtons();
  handler.enable();
  setStatus(`Mode dessin actif: ${drawModeLabel(mode)}. Cliquez sur la carte pour tracer.`, 'info');
}

function reenableCurrentDrawMode() {
  if (!state.activeDrawMode) return;
  const activeMode = state.activeDrawMode;
  const handler = mapRef.drawHandlers[activeMode];
  if (!handler || typeof handler.enable !== 'function') return;
  window.setTimeout(() => {
    if (state.activeDrawMode === activeMode) handler.enable();
  }, 0);
}

function clearUploadedPreview() {
  if (mapRef.uploadedLayer && mapRef.instance) {
    mapRef.instance.removeLayer(mapRef.uploadedLayer);
  }
  mapRef.uploadedLayer = null;
  mapRef.uploadedFeatureCount = 0;
  setOutsideCoverageWarning('uploaded', []);
}

function parseCsvLine(rawLine) {
  const out = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < rawLine.length; i += 1) {
    const char = rawLine[i];
    if (char === '"') {
      if (inQuotes && rawLine[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === ',' && !inQuotes) {
      out.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  out.push(current);
  return out.map((v) => v.trim());
}

function parseCsvToGeoJson(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  if (!lines.length) throw new Error('CSV vide');
  const headers = parseCsvLine(lines[0]);
  const lower = headers.map((h) => h.toLowerCase());
  const latIdx = lower.indexOf('lat') >= 0 ? lower.indexOf('lat') : lower.indexOf('latitude');
  const lonIdx = lower.indexOf('lon') >= 0 ? lower.indexOf('lon') : lower.indexOf('longitude');
  if (latIdx < 0 || lonIdx < 0) {
    throw new Error('CSV: colonnes lat/lon manquantes pour l’aperçu carte');
  }
  const labelIdx = lower.indexOf('label');
  const assetIdIdx = lower.indexOf('asset_id');
  const features = [];
  lines.slice(1).forEach((line, idx) => {
    const cols = parseCsvLine(line);
    const lat = Number(cols[latIdx]);
    const lon = Number(cols[lonIdx]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const assetId = (assetIdIdx >= 0 ? cols[assetIdIdx] : '') || `Ligne ${idx + 1}`;
    const label = (labelIdx >= 0 ? cols[labelIdx] : '') || (assetIdIdx >= 0 ? cols[assetIdIdx] : '') || `Ligne ${idx + 1}`;
    features.push({
      type: 'Feature',
      properties: { label: String(label), asset_id: String(assetId) },
      geometry: { type: 'Point', coordinates: [lon, lat] }
    });
  });
  return { type: 'FeatureCollection', features };
}

function normalizeToFeatureCollection(obj) {
  if (!obj || typeof obj !== 'object') throw new Error('GeoJSON invalide');
  if (obj.type === 'FeatureCollection' && Array.isArray(obj.features)) return obj;
  if (obj.type === 'Feature' && obj.geometry) return { type: 'FeatureCollection', features: [obj] };
  throw new Error('GeoJSON doit etre un FeatureCollection ou Feature');
}

function setUploadedPreviewGeoJson(fc, warningMode = 'uploaded') {
  if (!window.L || !mapRef.instance) return;
  clearUploadedPreview();
  const styleLine = { color: '#ffd744', weight: 3, opacity: 0.9 };
  const stylePoly = { color: '#ffd744', weight: 2, fillColor: '#ffd744', fillOpacity: 0.12 };
  mapRef.uploadedLayer = L.geoJSON(fc, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
      radius: 6,
      color: '#ffca58',
      fillColor: '#ffd744',
      fillOpacity: 0.9,
      weight: 1.5
    }),
    style: (feature) => {
      const gtype = String(feature?.geometry?.type || '');
      if (gtype.includes('Polygon')) return stylePoly;
      return styleLine;
    },
    onEachFeature: (feature, layer) => {
      const lbl = String(feature?.properties?.label || feature?.properties?.name || '').trim();
      if (lbl) layer.bindTooltip(escapeHtml(lbl), { sticky: true });
    }
  }).addTo(mapRef.instance);
  mapRef.uploadedFeatureCount = Array.isArray(fc.features) ? fc.features.length : 0;
  const normalizedMode = normalizeDatasetMode(warningMode);
  ensureStormCoverageLoaded()
    .then(() => {
      setOutsideCoverageWarning(normalizedMode, outsideCoverageRefsForFeatureCollection(fc, normalizedMode));
    })
    .catch(() => {
      setOutsideCoverageWarning(normalizedMode, []);
    });
}

async function previewUploadedFile(file) {
  if (!file) {
    clearUploadedPreview();
    renderTerritorySelectionState();
    renderMap();
    return;
  }
  try {
    const lower = String(file.name || '').toLowerCase();
    if (lower.endsWith('.csv')) {
      const text = await file.text();
      const fc = parseCsvToGeoJson(text);
      setUploadedPreviewGeoJson(fc);
      setStatus(`Aperçu carte import: ${mapRef.uploadedFeatureCount} entité(s).`, 'info');
    } else if (lower.endsWith('.geojson') || lower.endsWith('.json')) {
      const text = await file.text();
      const fc = normalizeToFeatureCollection(JSON.parse(text));
      setUploadedPreviewGeoJson(fc);
      setStatus(`Aperçu carte import: ${mapRef.uploadedFeatureCount} entité(s).`, 'info');
    } else {
      clearUploadedPreview();
      setStatus("Aperçu carte non disponible pour ce format. Utilisez CSV (lat/lon) ou GeoJSON pour visualiser l'import.", 'info');
    }
  } catch (err) {
    clearUploadedPreview();
    showError(`Impossible de générer l'aperçu de l'import: ${err.message}`);
  } finally {
    renderTerritorySelectionState();
    renderMap();
  }
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
  renderStormCoverageLayer();
  ensureStormCoverageLoaded().catch(() => {});

  if (window.L.Draw && window.L.Draw.Event) {
    const onDrawChange = () => {
      renderDrawPreview();
      const drawFc = drawFeatureCollectionFromMapLayers();
      if (drawFc) {
        ensureStormCoverageLoaded()
          .then(() => {
            setOutsideCoverageWarning('drawn', outsideCoverageRefsForFeatureCollection(drawFc, 'drawn'));
          })
          .catch(() => {
            setOutsideCoverageWarning('drawn', []);
          });
      } else {
        setOutsideCoverageWarning('drawn', []);
      }
      renderTerritorySelectionState();
      renderMap();
      els.clearDrawingsBtn.disabled = mapRef.drawnItems.getLayers().length === 0;
      els.submitDrawingBtn.disabled = mapRef.drawnItems.getLayers().length === 0;
    };

    mapRef.instance.on(L.Draw.Event.CREATED, (evt) => {
      const exposureType = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
      const nextIdx = mapRef.drawnItems.getLayers().length + 1;
      evt.layer.feature = evt.layer.feature || { type: 'Feature', properties: {} };
      evt.layer.feature.properties = {
        ...(evt.layer.feature.properties || {}),
        label: String(evt.layer.feature.properties?.label || `Geometrie ${nextIdx}`),
        value_eur: Number(evt.layer.feature.properties?.value_eur || 1_000_000),
        exposure_type: exposureType,
        exposure_category: categoryFromExposureType(exposureType),
        asset_type: assetFromExposureType(exposureType)
      };
      mapRef.drawnItems.addLayer(evt.layer);
      onDrawChange();
      reenableCurrentDrawMode();
    });
    mapRef.instance.on(L.Draw.Event.EDITED, onDrawChange);
    mapRef.instance.on(L.Draw.Event.DELETED, onDrawChange);
  }

  state.mapReady = true;
  return true;
}

function renderMap() {
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

  renderStormCoverageLayer();
  els.mapCaption.textContent = "Tracez vos geometries et visualisez vos importations sur cette carte. Les limites orange indiquent la zone de couverture STORM.";
  if (mapRef.markersLayer) mapRef.markersLayer.clearLayers();

  const drawnCount = mapRef.drawnItems ? mapRef.drawnItems.getLayers().length : 0;
  const importedCount = Number(mapRef.uploadedFeatureCount || 0);
  const hasContent = drawnCount > 0 || importedCount > 0;
  if (!hasContent) {
    els.mapFallback.hidden = false;
    els.mapFallback.textContent = "Aucune exposition sur la carte pour l'instant (importez un fichier ou dessinez).";
    const coverageBounds = getStormCoverageBounds();
    if (!mapRef.hasFitted && coverageBounds && coverageBounds.isValid()) {
      mapRef.instance.fitBounds(coverageBounds, { padding: [22, 22], maxZoom: 8 });
      mapRef.hasFitted = true;
    }
    setTimeout(() => mapRef.instance && mapRef.instance.invalidateSize(), 0);
    return;
  }

  els.mapFallback.hidden = true;
  els.mapFallback.textContent = '';
  const group = L.featureGroup();
  if (mapRef.uploadedLayer) group.addLayer(mapRef.uploadedLayer);
  if (mapRef.drawnItems && mapRef.drawnItems.getLayers().length) group.addLayer(mapRef.drawnItems);
  const bounds = group.getBounds();
  if (bounds && bounds.isValid()) {
    mapRef.instance.fitBounds(bounds, { padding: [22, 22], maxZoom: 8 });
    mapRef.hasFitted = true;
  }
  setTimeout(() => mapRef.instance && mapRef.instance.invalidateSize(), 0);
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

function normalizeWindMapMode(raw) {
  const value = String(raw || '').trim().toLowerCase();
  if (value === 'rp50') return 'rp50';
  if (value === 'rp100') return 'rp100';
  if (value === 'rp1000') return 'rp50';
  return 'mean';
}

function currentWindMapMode() {
  return normalizeWindMapMode(state.windMapMode);
}

function updateWindModeUi() {
  if (!els.windMapMode) return;
  els.windMapMode.value = currentWindMapMode();
}

function windMetricConfig(modeRaw) {
  const mode = normalizeWindMapMode(modeRaw);
  if (mode === 'rp50') {
    return {
      mode,
      valueKey: 'rp50_wind_mps',
      minKey: 'rp50_wind_min_mps',
      maxKey: 'rp50_wind_max_mps',
      legendTitle: 'Vents (retour 50 ans)',
      captionLabel: 'vitesse du vent (temps de retour 50 ans)',
      mapLabel: 'temps de retour 50 ans',
      tooltipLabel: 'Vents (retour 50 ans)'
    };
  }
  if (mode === 'rp100') {
    return {
      mode,
      valueKey: 'rp100_wind_mps',
      minKey: 'rp100_wind_min_mps',
      maxKey: 'rp100_wind_max_mps',
      legendTitle: 'Vents (retour 100 ans)',
      captionLabel: 'vitesse du vent (temps de retour 100 ans)',
      mapLabel: 'temps de retour 100 ans',
      tooltipLabel: 'Vents (retour 100 ans)'
    };
  }
  return {
    mode: 'mean',
    valueKey: 'mean_wind_mps',
    minKey: 'mean_wind_min_mps',
    maxKey: 'mean_wind_max_mps',
    legendTitle: 'Vents moyens',
    captionLabel: 'vitesse moyenne du vent',
    mapLabel: 'vents moyens',
    tooltipLabel: 'Vents moyens'
  };
}

function estimateRp50FromRp100AndRp1000(rp100Raw, rp1000Raw) {
  const rp100 = Number(rp100Raw);
  const rp1000 = Number(rp1000Raw);
  if (Number.isFinite(rp100) && rp100 > 0 && Number.isFinite(rp1000) && rp1000 > 0) {
    const ln50 = Math.log(50.0);
    const ln100 = Math.log(100.0);
    const ln1000 = Math.log(1000.0);
    const slope = (rp1000 - rp100) / (ln1000 - ln100);
    const est = rp100 + (slope * (ln50 - ln100));
    return Math.max(0, Math.min(rp100, est));
  }
  if (Number.isFinite(rp100) && rp100 > 0) {
    return rp100 * 0.86;
  }
  return 0;
}

function buildWindScale(minRaw, maxRaw, stepMps = WIND_SCALE_STEP_MPS) {
  const step = Number(stepMps);
  const rawMin = Number(minRaw);
  const rawMax = Number(maxRaw);
  let minEdge = Number.isFinite(rawMin) ? Math.floor(rawMin / step) * step : 0;
  let maxEdge = Number.isFinite(rawMax) ? Math.ceil(rawMax / step) * step : minEdge + step;
  if (!Number.isFinite(minEdge)) minEdge = 0;
  if (!Number.isFinite(maxEdge)) maxEdge = minEdge + step;
  if (maxEdge <= minEdge) maxEdge = minEdge + step;

  const edges = [];
  for (let value = minEdge; value <= maxEdge + 1e-9; value += step) {
    edges.push(Number(value.toFixed(6)));
  }
  if (edges.length < 2) edges.push(Number((minEdge + step).toFixed(6)));
  return {
    minEdge: Number(minEdge),
    maxEdge: Number(maxEdge),
    step,
    edges
  };
}

function windColorFromScale(valueRaw, scale) {
  const value = Number(valueRaw);
  const edges = Array.isArray(scale?.edges) ? scale.edges : [0, 5];
  const minEdge = Number(edges[0] || 0);
  const maxEdge = Number(edges[edges.length - 1] || (minEdge + 5));
  const span = Math.max(1e-9, maxEdge - minEdge);
  const normalized = Number.isFinite(value) ? (value - minEdge) / span : 0;
  const clamped = Math.max(0, Math.min(1, normalized));
  const paletteIdx = Math.round(clamped * (WIND_PALETTE.length - 1));
  return WIND_PALETTE[Math.max(0, Math.min(WIND_PALETTE.length - 1, paletteIdx))];
}

function buildWindLegendHtml(scale, metric) {
  const edges = Array.isArray(scale?.edges) ? scale.edges : [0, 5];
  const rows = [];
  for (let idx = 0; idx < edges.length - 1; idx += 1) {
    const lo = Number(edges[idx]);
    const hi = Number(edges[idx + 1]);
    const mid = (lo + hi) / 2;
    const color = windColorFromScale(mid, scale);
    rows.push(
      `<div class="wind-legend-row"><span class="wind-legend-swatch" style="background:${color}"></span><span>${escapeHtml(formatWindSpeed(lo))} - ${escapeHtml(formatWindSpeed(hi))} ${WIND_SPEED_UNIT_DISPLAY}</span></div>`
    );
  }
  return [
    '<div class="wind-legend">',
    `<div class="wind-legend-title">${escapeHtml(metric?.legendTitle || 'Vents')}</div>`,
    ...rows,
    '</div>'
  ].join('');
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
  if (!ref || !ref.instance) return;
  const factor = currentWindOpacityFactor();
  const pane = ref.instance.getPane(ref.cellsPaneName);
  if (!pane) return;
  pane.style.opacity = String(clamp01(factor));
}

function applyWindLayerOpacity() {
  applyWindOpacityToMap('storm');
  applyWindOpacityToMap('storm_cmcc');
}

function ensureWindLegend(hazardKey, scale, metric) {
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
  if (legendEl) legendEl.innerHTML = buildWindLegendHtml(scale, metric);
}

function ensureWindMap(hazardKey) {
  if (!window.L) return null;
  const ref = windMapRef[hazardKey];
  if (!ref) return null;
  if (ref.instance) return ref;

  const container = hazardKey === 'storm' ? els.windMapStorm : els.windMapCmcc;
  if (!container) return null;

  ref.instance = L.map(container, { zoomControl: true, attributionControl: true }).setView([16.25, -61.5], 8);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 11,
    minZoom: 4,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(ref.instance);
  if (!ref.instance.getPane(ref.cellsPaneName)) {
    const pane = ref.instance.createPane(ref.cellsPaneName);
    pane.style.zIndex = '430';
    pane.style.pointerEvents = 'auto';
  }
  ref.cellsLayer = L.layerGroup().addTo(ref.instance);
  return ref;
}

function nearestWindCellValue(i, j, knownCells, fallbackValue, metricKey) {
  if (!knownCells.length) return { metric_value: fallbackValue, sample_count: 0, extrapolated: true };
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
  if (!best) return { metric_value: fallbackValue, sample_count: 0, extrapolated: true };
  const bestMetric = Number(best[metricKey]);
  return { metric_value: Number.isFinite(bestMetric) ? bestMetric : fallbackValue, sample_count: best.sample_count, extrapolated: true };
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

function resolveWindMetricValue(cell, metricValueKey, fallbackValue) {
  const direct = Number(cell?.[metricValueKey]);
  if (Number.isFinite(direct)) return direct;
  if (metricValueKey === 'rp50_wind_mps') {
    return estimateRp50FromRp100AndRp1000(cell?.rp100_wind_mps, cell?.rp1000_wind_mps);
  }
  return fallbackValue;
}

function resolveWindMetricRange(payload, metric) {
  const directMin = Number(payload?.[metric?.minKey]);
  const directMax = Number(payload?.[metric?.maxKey]);
  if (Number.isFinite(directMin) && Number.isFinite(directMax)) {
    return { min: directMin, max: directMax };
  }
  if (metric?.mode === 'rp50') {
    const minEst = estimateRp50FromRp100AndRp1000(payload?.rp100_wind_min_mps, payload?.rp1000_wind_min_mps);
    const maxEst = estimateRp50FromRp100AndRp1000(payload?.rp100_wind_max_mps, payload?.rp1000_wind_max_mps);
    return { min: minEst, max: maxEst };
  }
  return { min: 0, max: 0 };
}

function isCaseStudyCmccMeanVisualSmoothingEnabled(hazardKey, metric, meta) {
  if (hazardKey !== 'storm_cmcc') return false;
  if (String(metric?.mode || '').toLowerCase() !== 'mean') return false;
  const territory = String(meta?.territory || '').trim().toLowerCase();
  return territory === 'guadeloupe' || territory === 'martinique';
}

function collectNeighborValuesForVisualSmoothing(i, j, knownByIndex, metricValueKey, floorValue) {
  const out = [];
  const radius = CMCC_VISUAL_MIN_BAND_NEIGHBOR_RADIUS;
  for (let di = -radius; di <= radius; di += 1) {
    for (let dj = -radius; dj <= radius; dj += 1) {
      if (di === 0 && dj === 0) continue;
      const neighbor = knownByIndex.get(`${i + di}|${j + dj}`);
      if (!neighbor) continue;
      const value = Number(neighbor[metricValueKey]);
      const sampleCount = Number(neighbor.sample_count || 0);
      if (!Number.isFinite(value)) continue;
      if (value <= floorValue + CMCC_VISUAL_MIN_BAND_EPS) continue;
      if (sampleCount <= CMCC_VISUAL_MIN_BAND_SAMPLE_MAX) continue;
      const dist2 = (di * di) + (dj * dj);
      out.push({ value, dist2 });
    }
  }
  return out.sort((a, b) => a.dist2 - b.dist2);
}

function applyCaseStudyCmccMinBandVisualSmoothing(knownCells, knownByIndex, payload, metricValueKey) {
  const floorValue = Number(payload?.mean_wind_min_mps);
  if (!Number.isFinite(floorValue)) return;

  const candidates = knownCells.filter((cell) => {
    const value = Number(cell[metricValueKey]);
    const sampleCount = Number(cell.sample_count || 0);
    return (
      Number.isFinite(value)
      && Math.abs(value - floorValue) <= CMCC_VISUAL_MIN_BAND_EPS
      && sampleCount <= CMCC_VISUAL_MIN_BAND_SAMPLE_MAX
    );
  });
  if (!candidates.length) return;

  candidates.forEach((cell) => {
    const i = Number(cell.i);
    const j = Number(cell.j);
    if (!Number.isFinite(i) || !Number.isFinite(j)) return;
    const neighbors = collectNeighborValuesForVisualSmoothing(i, j, knownByIndex, metricValueKey, floorValue);
    if (neighbors.length < CMCC_VISUAL_MIN_BAND_NEIGHBOR_MIN) return;
    const take = neighbors.slice(0, 6);
    const avg = take.reduce((acc, item) => acc + item.value, 0) / take.length;
    if (!Number.isFinite(avg)) return;
    cell[metricValueKey] = avg;
    cell.metric_value = avg;
    cell.visual_adjusted = true;
  });
}

function renderWindMap(hazardKey, payload, meta, options = {}) {
  if (!payload || !Array.isArray(payload.cells)) return;
  const ref = ensureWindMap(hazardKey);
  if (!ref || !ref.cellsLayer) return;

  ref.cellsLayer.clearLayers();
  const cells = payload.cells || [];
  if (!cells.length) return;

  const metric = options.metric || windMetricConfig('mean');
  const metricValueKey = String(metric.valueKey || 'mean_wind_mps');
  const grid = options.gridSpec || buildSharedWindGridSpec(payload, meta);
  if (!grid) return;

  const range = resolveWindMetricRange(payload, metric);
  const min = Number.isFinite(options.colorMin) ? Number(options.colorMin) : Number(range.min || 0);
  const max = Number.isFinite(options.colorMax) ? Number(options.colorMax) : Number(range.max || 0);
  const scale = options.colorScale || buildWindScale(min, max, WIND_SCALE_STEP_MPS);
  const fallbackValue = Number(scale.minEdge || min || 0);
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
    const observedMetric = resolveWindMetricValue(cell, metricValueKey, fallbackValue);
    const observed = {
      i,
      j,
      [metricValueKey]: observedMetric,
      metric_value: observedMetric,
      sample_count: Number(cell.sample_count || 0)
    };
    knownCells.push(observed);
    if (!knownByIndex.has(key)) knownByIndex.set(key, observed);
  });

  if (isCaseStudyCmccMeanVisualSmoothingEnabled(hazardKey, metric, meta)) {
    applyCaseStudyCmccMinBandVisualSmoothing(knownCells, knownByIndex, payload, metricValueKey);
  }

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
        const data = observed || nearestWindCellValue(i, j, knownCells, fallbackValue, metricValueKey);
        const metricValue = Number(data.metric_value ?? fallbackValue);
        const sampleCount = Number(data.sample_count ?? 0);
        const extrapolated = !observed;
        const visualAdjusted = Boolean(data.visual_adjusted);
        const color = windColorFromScale(metricValue, scale);
        const rect = L.rectangle([[south, west], [north, east]], {
          pane: ref.cellsPaneName,
          stroke: false,
          fillColor: color,
          fillOpacity: 1
        });
        rect.bindTooltip(
          [
            `<strong>${escapeHtml(getHazardLabel(hazardKey))}</strong>`,
            `${escapeHtml(metric.tooltipLabel)}: ${escapeHtml(formatWindSpeed(metricValue))} ${WIND_SPEED_UNIT_DISPLAY}`,
            `Echantillons: ${escapeHtml(numberFmt.format(sampleCount))}`,
            extrapolated
              ? 'Valeur: extrapolee (plus proche maille observee)'
              : (visualAdjusted ? 'Valeur: lissage visuel (sans impact calcul)' : 'Valeur: observee')
          ].join('<br/>'),
          { sticky: true }
        );
        rect.addTo(ref.cellsLayer);
      }
    }
  }

  ensureWindLegend(hazardKey, scale, metric);

  setTimeout(() => ref.instance && ref.instance.invalidateSize(), 0);
}

function renderWindMaps() {
  const payload = state.windMaps;
  if (!payload) return;
  const meta = payload.meta || {};
  const storm = payload.storm;
  const cmcc = payload.storm_cmcc;
  const metric = windMetricConfig(currentWindMapMode());

  const sharedCells = [
    ...((storm && Array.isArray(storm.cells)) ? storm.cells : []),
    ...((cmcc && Array.isArray(cmcc.cells)) ? cmcc.cells : [])
  ];
  const sharedGrid = buildSharedWindGridSpec({ cells: sharedCells }, meta);
  const stormRange = resolveWindMetricRange(storm, metric);
  const cmccRange = resolveWindMetricRange(cmcc, metric);
  const sharedMin = Math.min(
    Number(stormRange.min ?? Number.POSITIVE_INFINITY),
    Number(cmccRange.min ?? Number.POSITIVE_INFINITY)
  );
  const sharedMax = Math.max(
    Number(stormRange.max ?? Number.NEGATIVE_INFINITY),
    Number(cmccRange.max ?? Number.NEGATIVE_INFINITY)
  );
  const colorMin = Number.isFinite(sharedMin) ? sharedMin : 0;
  const colorMax = Number.isFinite(sharedMax) ? sharedMax : 1;
  const colorScale = buildWindScale(colorMin, colorMax, WIND_SCALE_STEP_MPS);

  if (els.windMapTitleStorm) {
    els.windMapTitleStorm.textContent = `Carte des aleas vent/tempete ${metric.mapLabel} (STORM)`;
  }
  if (els.windMapTitleCmcc) {
    els.windMapTitleCmcc.textContent = `Carte des aleas vent/tempete ${metric.mapLabel} (STORM_CMCC)`;
  }

  if (storm && els.windStormCaption) {
    const stepKmh = WIND_SCALE_STEP_MPS * WIND_SPEED_MPS_TO_KMH;
    els.windStormCaption.textContent = `${numberFmt.format(storm.cell_count || 0)} mailles observees · extrapolation spatiale active autour de la zone etudiee · ${numberFmt.format(storm.years_covered || 0)} ans · ${metric.captionLabel} · echelle de classes reguliere (${numberFmt.format(stepKmh)} ${WIND_SPEED_UNIT_DISPLAY})`;
    renderWindMap('storm', storm, meta, { gridSpec: sharedGrid, colorMin, colorMax, colorScale, metric });
  }
  if (cmcc && els.windCmccCaption) {
    const stepKmh = WIND_SCALE_STEP_MPS * WIND_SPEED_MPS_TO_KMH;
    els.windCmccCaption.textContent = `${numberFmt.format(cmcc.cell_count || 0)} mailles observees · extrapolation spatiale active autour de la zone etudiee · ${numberFmt.format(cmcc.years_covered || 0)} ans · ${metric.captionLabel} · echelle de classes reguliere (${numberFmt.format(stepKmh)} ${WIND_SPEED_UNIT_DISPLAY})`;
    renderWindMap('storm_cmcc', cmcc, meta, { gridSpec: sharedGrid, colorMin, colorMax, colorScale, metric });
  }
  applyWindLayerOpacity();
}

function normalizeAdminVisuHazard(raw) {
  return String(raw || '').trim().toLowerCase() === 'storm_cmcc' ? 'storm_cmcc' : 'storm';
}

function normalizeAdminVisuScenario(raw) {
  const value = String(raw || '').trim().toLowerCase();
  if (value === 'rp50') return 'rp50';
  if (value === 'rp100') return 'rp100';
  return 'mean';
}

function adminVisuScenarioConfig(raw) {
  const scenario = normalizeAdminVisuScenario(raw);
  if (scenario === 'rp50') return { key: 'rp50', label: 'temps de retour 50 ans', legendTitle: 'Vents (retour 50 ans)' };
  if (scenario === 'rp100') return { key: 'rp100', label: 'temps de retour 100 ans', legendTitle: 'Vents (retour 100 ans)' };
  return { key: 'mean', label: 'vents moyens', legendTitle: 'Vents moyens' };
}

function currentAdminVisuOpacityFactor() {
  return clamp01(state.adminVisuOpacity ?? 0.5);
}

function updateAdminVisuOpacityUi() {
  const factor = currentAdminVisuOpacityFactor();
  if (els.adminVisuOpacitySlider) els.adminVisuOpacitySlider.value = String(Math.round(factor * 100));
  if (els.adminVisuOpacityValue) els.adminVisuOpacityValue.textContent = `${Math.round(factor * 100)}%`;
}

function applyAdminVisuOpacity() {
  const factor = currentAdminVisuOpacityFactor();
  adminVisuMapRef.cards.forEach((card) => {
    if (card?.overlayLayer && typeof card.overlayLayer.setOpacity === 'function') {
      card.overlayLayer.setOpacity(factor);
    }
  });
}

function syncAdminVisuOpacityFromSlider({ forceApply = false } = {}) {
  if (!els.adminVisuOpacitySlider) return;
  const pct = Number(els.adminVisuOpacitySlider.value);
  if (!Number.isFinite(pct)) return;
  const next = clamp01(pct / 100);
  const previous = currentAdminVisuOpacityFactor();
  const changed = Math.abs(next - previous) > 0.0001;
  if (changed) state.adminVisuOpacity = next;
  updateAdminVisuOpacityUi();
  if (changed || forceApply) applyAdminVisuOpacity();
}

function adminVisuLegendGradientCss() {
  return `linear-gradient(90deg, ${ADMIN_VISU_LEGEND_COLORS.join(', ')})`;
}

function buildAdminVisuLegendHtml(minRaw, maxRaw, legendTitle) {
  const minVal = Number(minRaw);
  const maxVal = Number(maxRaw);
  const minTxt = Number.isFinite(minVal) ? formatWindSpeed(minVal) : 'n/a';
  const maxTxt = Number.isFinite(maxVal) ? formatWindSpeed(maxVal) : 'n/a';
  const midTxt = Number.isFinite(minVal) && Number.isFinite(maxVal)
    ? formatWindSpeed((minVal + maxVal) / 2)
    : 'n/a';
  return [
    '<div class="admin-wind-legend">',
    `<div class="admin-wind-legend-title">${escapeHtml(legendTitle || 'Vents')}</div>`,
    `<div class="admin-wind-legend-bar" style="background:${adminVisuLegendGradientCss()}"></div>`,
    '<div class="admin-wind-legend-labels">',
    `<span>${escapeHtml(minTxt)} ${WIND_SPEED_UNIT_DISPLAY}</span>`,
    `<span>${escapeHtml(midTxt)} ${WIND_SPEED_UNIT_DISPLAY}</span>`,
    `<span>${escapeHtml(maxTxt)} ${WIND_SPEED_UNIT_DISPLAY}</span>`,
    '</div>',
    '</div>'
  ].join('');
}

function ensureAdminVisuLegend(cardIdx, metricMin, metricMax, legendTitle) {
  if (!window.L) return;
  const ref = adminVisuMapRef.cards[cardIdx];
  if (!ref?.instance) return;

  if (!ref.legendControl) {
    ref.legendControl = L.control({ position: 'bottomright' });
    ref.legendControl.onAdd = () => {
      const div = L.DomUtil.create('div');
      div.className = 'leaflet-control wind-legend-control admin-wind-legend-control';
      return div;
    };
    ref.legendControl.addTo(ref.instance);
  }

  const legendEl = ref.legendControl.getContainer();
  if (legendEl) legendEl.innerHTML = buildAdminVisuLegendHtml(metricMin, metricMax, legendTitle);
}

function adminVisuOverlayUrl(pathValue) {
  const raw = String(pathValue || '').trim();
  if (!raw) return '';
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  if (raw.startsWith('/')) return new URL(raw, window.location.origin).toString();
  return new URL(`/hazard-maps/${raw}`, window.location.origin).toString();
}

function ensureAdminVisuMap(cardIdx) {
  if (!window.L) return null;
  const ref = adminVisuMapRef.cards[cardIdx];
  if (!ref) return null;
  if (ref.instance) return ref;
  const container = Array.isArray(els.adminVisuMapContainers) ? els.adminVisuMapContainers[cardIdx] : null;
  if (!container) return null;

  ref.instance = L.map(container, { zoomControl: true, attributionControl: true, preferCanvas: true }).setView([24.0, -58.0], 4);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 8,
    minZoom: 2,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(ref.instance);

  if (!ref.instance.getPane(ref.overlayPaneName)) {
    const pane = ref.instance.createPane(ref.overlayPaneName);
    pane.style.zIndex = '430';
    pane.style.pointerEvents = 'none';
  }

  return ref;
}

function renderAdminVisuCard(cardIdx) {
  if (!runtime.allowAdminVisu) return;
  const payload = state.adminVisuMaps;
  if (!payload) return;
  const ref = ensureAdminVisuMap(cardIdx);
  if (!ref || !ref.instance) return;

  const cardState = state.adminVisuCards[cardIdx] || { hazard: 'storm', scenario: 'mean' };
  const hazard = normalizeAdminVisuHazard(cardState.hazard);
  const scenarioCfg = adminVisuScenarioConfig(cardState.scenario);
  const scenario = scenarioCfg.key;

  const hazardSelect = Array.isArray(els.adminVisuHazardSelects) ? els.adminVisuHazardSelects[cardIdx] : null;
  const scenarioSelect = Array.isArray(els.adminVisuScenarioSelects) ? els.adminVisuScenarioSelects[cardIdx] : null;
  if (hazardSelect) hazardSelect.value = hazard;
  if (scenarioSelect) scenarioSelect.value = scenario;

  const bounds = payload?.meta?.bounds || {};
  const south = Number(bounds.south);
  const north = Number(bounds.north);
  const west = Number(bounds.west);
  const east = Number(bounds.east);
  if (!Number.isFinite(south) || !Number.isFinite(north) || !Number.isFinite(west) || !Number.isFinite(east)) {
    return;
  }

  const overlayPath = payload?.overlays?.[hazard]?.[scenario];
  const overlayUrl = adminVisuOverlayUrl(overlayPath);
  const caption = Array.isArray(els.adminVisuCaptions) ? els.adminVisuCaptions[cardIdx] : null;
  const metricMeta = payload?.metrics?.[scenario] || {};
  const metricMin = Number(metricMeta.min_mps);
  const metricMax = Number(metricMeta.max_mps);
  const hazardLabel = hazard === 'storm_cmcc' ? 'STORM_CMCC' : 'STORM';
  const boundsLeaflet = [[south, west], [north, east]];

  if (!overlayUrl) {
    if (caption) caption.textContent = 'Couche indisponible pour cette combinaison.';
    if (ref.overlayLayer) {
      ref.instance.removeLayer(ref.overlayLayer);
      ref.overlayLayer = null;
      ref.overlayUrl = '';
    }
    return;
  }

  if (!ref.overlayLayer || ref.overlayUrl !== overlayUrl) {
    if (ref.overlayLayer) ref.instance.removeLayer(ref.overlayLayer);
    ref.overlayLayer = L.imageOverlay(overlayUrl, boundsLeaflet, {
      pane: ref.overlayPaneName,
      opacity: currentAdminVisuOpacityFactor(),
      interactive: false,
      crossOrigin: true
    }).addTo(ref.instance);
    ref.overlayUrl = overlayUrl;
    ref.hasFitted = false;
  }

  if (!ref.hasFitted) {
    ref.instance.fitBounds(boundsLeaflet, { padding: [8, 8], maxZoom: 6 });
    ref.hasFitted = true;
  }

  if (caption) {
    const minTxt = Number.isFinite(metricMin) ? formatWindSpeed(metricMin) : 'n/a';
    const maxTxt = Number.isFinite(metricMax) ? formatWindSpeed(metricMax) : 'n/a';
    caption.textContent = `${hazardLabel} · ${scenarioCfg.label} · echelle ${minTxt} a ${maxTxt} ${WIND_SPEED_UNIT_DISPLAY}`;
  }

  ensureAdminVisuLegend(cardIdx, metricMin, metricMax, scenarioCfg.legendTitle);

  setTimeout(() => {
    if (ref.instance) ref.instance.invalidateSize();
  }, 0);
}

function renderAdminVisuPage() {
  if (!runtime.allowAdminVisu) return;
  if (!state.adminVisuMaps) {
    (els.adminVisuCaptions || []).forEach((caption) => {
      if (!caption) return;
      caption.textContent = 'Chargement des couches admin...';
    });
    return;
  }
  for (let idx = 0; idx < adminVisuMapRef.cards.length; idx += 1) {
    renderAdminVisuCard(idx);
  }
  applyAdminVisuOpacity();
}

function normalizeAdminPopulationTerritory(raw, payload = null) {
  const value = String(raw || '').trim().toLowerCase();
  if (!payload || !Array.isArray(payload.territories) || payload.territories.length === 0) {
    return value || 'glp';
  }
  const territories = payload.territories
    .map((t) => String(t?.code || '').trim().toLowerCase())
    .filter(Boolean);
  if (territories.includes(value)) return value;
  return territories[0] || 'glp';
}

function adminPopulationLegendColors(payload) {
  const fromPayload = payload?.meta?.palette_hex;
  if (Array.isArray(fromPayload)) {
    const clean = fromPayload
      .map((v) => String(v || '').trim())
      .filter((v) => /^#[0-9a-fA-F]{6}$/.test(v));
    if (clean.length >= 2) return clean;
  }
  return ADMIN_POP_DEFAULT_LEGEND_COLORS;
}

function formatPopulationPerPixel(raw) {
  const value = Number(raw);
  if (!Number.isFinite(value)) return 'n/a';
  const abs = Math.abs(value);
  if (abs >= 100) return peopleFmtInt.format(value);
  if (abs >= 10) return peopleFmtOne.format(value);
  return peopleFmtTwo.format(value);
}

function adminPopulationLegendGradientCss(colors) {
  const safe = Array.isArray(colors) && colors.length >= 2 ? colors : ADMIN_POP_DEFAULT_LEGEND_COLORS;
  return `linear-gradient(90deg, ${safe.join(', ')})`;
}

function buildAdminPopulationLegendHtml(minRaw, maxRaw, colors) {
  const minVal = Number(minRaw);
  const maxVal = Number(maxRaw);
  const midVal = Number.isFinite(minVal) && Number.isFinite(maxVal) ? (minVal + maxVal) / 2.0 : NaN;
  return [
    '<div class="admin-pop-legend">',
    '<div class="admin-pop-legend-title">Population (pers./pixel)</div>',
    `<div class="admin-pop-legend-bar" style="background:${adminPopulationLegendGradientCss(colors)}"></div>`,
    '<div class="admin-pop-legend-labels">',
    `<span>${escapeHtml(formatPopulationPerPixel(minVal))}</span>`,
    `<span>${escapeHtml(formatPopulationPerPixel(midVal))}</span>`,
    `<span>${escapeHtml(formatPopulationPerPixel(maxVal))}</span>`,
    '</div>',
    '</div>'
  ].join('');
}

function ensureAdminPopulationLegend(scaleMin, scaleMax, paletteColors) {
  if (!window.L) return;
  if (!adminPopulationMapRef.instance) return;

  if (!adminPopulationMapRef.legendControl) {
    adminPopulationMapRef.legendControl = L.control({ position: 'bottomright' });
    adminPopulationMapRef.legendControl.onAdd = () => {
      const div = L.DomUtil.create('div');
      div.className = 'leaflet-control wind-legend-control admin-pop-legend-control';
      return div;
    };
    adminPopulationMapRef.legendControl.addTo(adminPopulationMapRef.instance);
  }

  const legendEl = adminPopulationMapRef.legendControl.getContainer();
  if (legendEl) {
    legendEl.innerHTML = buildAdminPopulationLegendHtml(scaleMin, scaleMax, paletteColors);
  }
}

function ensureAdminPopulationMap() {
  if (!window.L || !els.adminPopulationMap) return null;
  if (adminPopulationMapRef.instance) return adminPopulationMapRef;

  adminPopulationMapRef.instance = L.map(els.adminPopulationMap, {
    zoomControl: true,
    attributionControl: true,
    preferCanvas: true
  }).setView([17.0, -61.0], 5);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 11,
    minZoom: 2,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(adminPopulationMapRef.instance);

  if (!adminPopulationMapRef.instance.getPane(adminPopulationMapRef.overlayPaneName)) {
    const pane = adminPopulationMapRef.instance.createPane(adminPopulationMapRef.overlayPaneName);
    pane.style.zIndex = '430';
    pane.style.pointerEvents = 'none';
    pane.style.filter = 'brightness(0.72) contrast(1.35)';
  }
  return adminPopulationMapRef;
}

function syncAdminPopulationTerritorySelect(payload, selectedCode) {
  const select = els.adminPopulationTerritorySelect;
  if (!select || !payload || !Array.isArray(payload.territories)) return;

  const territories = payload.territories
    .filter((t) => t && String(t.code || '').trim() && String(t.name || '').trim())
    .map((t) => ({ code: String(t.code).trim().toLowerCase(), name: String(t.name).trim() }));
  const signature = territories.map((t) => `${t.code}:${t.name}`).join('|');
  if (select.dataset.signature !== signature) {
    select.innerHTML = territories
      .map((t) => `<option value="${escapeHtml(t.code)}">${escapeHtml(t.name)}</option>`)
      .join('');
    select.dataset.signature = signature;
  }
  select.value = selectedCode;
}

function renderAdminPopulationMap() {
  if (!runtime.allowAdminVisu) return;
  const payload = state.adminPopulationMaps;
  if (!payload || !Array.isArray(payload.territories) || payload.territories.length === 0) {
    if (els.adminPopulationCaption) {
      els.adminPopulationCaption.textContent = 'Chargement des couches population...';
    }
    return;
  }

  const selectedCode = normalizeAdminPopulationTerritory(state.adminPopulationTerritory, payload);
  state.adminPopulationTerritory = selectedCode;
  syncAdminPopulationTerritorySelect(payload, selectedCode);

  const territory = payload.territories.find((t) => String(t?.code || '').trim().toLowerCase() === selectedCode);
  if (!territory) return;

  const ref = ensureAdminPopulationMap();
  if (!ref || !ref.instance) return;

  const bounds = territory?.bounds || {};
  const south = Number(bounds.south);
  const north = Number(bounds.north);
  const west = Number(bounds.west);
  const east = Number(bounds.east);
  const boundsLeaflet = [[south, west], [north, east]];

  if (!Number.isFinite(south) || !Number.isFinite(north) || !Number.isFinite(west) || !Number.isFinite(east)) {
    if (els.adminPopulationCaption) {
      els.adminPopulationCaption.textContent = `Emprise geographique indisponible pour ${territory.name || selectedCode}.`;
    }
    return;
  }

  const overlayUrl = adminVisuOverlayUrl(territory?.overlay);
  if (!overlayUrl) {
    if (els.adminPopulationCaption) {
      els.adminPopulationCaption.textContent = `Couche population indisponible pour ${territory.name || selectedCode}.`;
    }
    if (ref.overlayLayer) {
      ref.instance.removeLayer(ref.overlayLayer);
      ref.overlayLayer = null;
      ref.overlayUrl = '';
    }
    return;
  }

  const territoryChanged = ref.currentTerritory !== selectedCode;
  if (!ref.overlayLayer || ref.overlayUrl !== overlayUrl) {
    if (ref.overlayLayer) ref.instance.removeLayer(ref.overlayLayer);
    ref.overlayLayer = L.imageOverlay(overlayUrl, boundsLeaflet, {
      pane: ref.overlayPaneName,
      opacity: 0.95,
      interactive: false,
      crossOrigin: true
    }).addTo(ref.instance);
    ref.overlayUrl = overlayUrl;
  }

  if (territoryChanged || !ref.currentTerritory) {
    ref.instance.fitBounds(boundsLeaflet, { padding: [12, 12], maxZoom: 9 });
    ref.currentTerritory = selectedCode;
  }

  const scaleMeta = payload?.meta?.scale || {};
  const minPeople = Number(scaleMeta.min_people_per_pixel);
  const maxPeople = Number(scaleMeta.max_people_per_pixel);
  const fallbackMax = Number(territory?.stats?.max_people_per_pixel);
  const scaleMin = Number.isFinite(minPeople) ? minPeople : 0.0;
  const scaleMax = Number.isFinite(maxPeople) && maxPeople > 0 ? maxPeople : (Number.isFinite(fallbackMax) ? fallbackMax : 0.0);
  const paletteColors = adminPopulationLegendColors(payload);

  ensureAdminPopulationLegend(scaleMin, scaleMax, paletteColors);

  if (els.adminPopulationCaption) {
    const name = String(territory?.name || selectedCode).trim();
    const maxTxt = formatPopulationPerPixel(scaleMax);
    els.adminPopulationCaption.textContent = `${name} · WorldPop 2020 · echelle 0 a ${maxTxt} personnes/pixel`;
  }

  setTimeout(() => {
    if (ref.instance) ref.instance.invalidateSize();
  }, 0);
}

function adminVulnerabilityRefKey(curve) {
  const code = String(curve?.code || 'curve').replace(/[^a-zA-Z0-9_-]+/g, '_');
  const impfId = Number(curve?.impf_id);
  const id = Number.isFinite(impfId) ? String(Math.trunc(impfId)) : 'na';
  return `admin_vulnerability_${id}_${code}`;
}

function adminVulnerabilityDomId(curve) {
  return adminVulnerabilityRefKey(curve).replace(/_/g, '-');
}

function disposeAdminVulnerabilityCharts() {
  Object.keys(chartRefs)
    .filter((key) => key.startsWith('admin_vulnerability_'))
    .forEach((key) => {
      try {
        if (chartRefs[key] && typeof chartRefs[key].dispose === 'function') chartRefs[key].dispose();
      } catch (err) {
        console.warn('Unable to dispose vulnerability chart', key, err);
      }
      chartRefs[key] = null;
    });
}

function ensureAdminVulnerabilityCurveCards(payload) {
  const grid = els.adminVulnerabilityGrid;
  if (!grid || !payload || !Array.isArray(payload.curves)) return;
  const signature = payload.curves
    .map((curve) => `${curve.impf_id}:${curve.code}:${curve.name}`)
    .join('|');
  if (grid.dataset.signature === signature) return;

  disposeAdminVulnerabilityCharts();

  grid.innerHTML = payload.curves.map((curve) => {
    const domId = adminVulnerabilityDomId(curve);
    const code = String(curve.code || 'n/a');
    const title = String(curve.name || code);
    const source = String(curve.source || 'source inconnue');
    const geography = String(curve.geography || 'geographie non renseignee');
    const modeledType = String(curve.modeledInfrastructureType || 'N/A');
    const modeledCharacteristics = String(curve.modeledInfrastructureCharacteristics || 'N/A');
    const sibAssetLabels = (Array.isArray(curve.sibAssetTypes) ? curve.sibAssetTypes : [])
      .map((assetType) => ASSET_TYPE_ADMIN_LABEL[assetType] || assetType)
      .join(' · ');
    return `
      <article class="admin-vulnerability-item">
        <div class="admin-vulnerability-item-title">${escapeHtml(title)}</div>
        <div class="admin-vulnerability-item-meta">${escapeHtml(source)} · ${escapeHtml(geography)}</div>
        <div class="admin-vulnerability-item-meta"><strong>Infra modele source:</strong> ${escapeHtml(modeledType)} (${escapeHtml(modeledCharacteristics)})</div>
        <div class="admin-vulnerability-item-meta"><strong>Infra etude SIB:</strong> ${escapeHtml(sibAssetLabels || 'Aucune affectation')}</div>
        <div id="${escapeHtml(domId)}" class="admin-vulnerability-chart"></div>
      </article>
    `;
  }).join('');
  grid.dataset.signature = signature;
}

function renderAdminVulnerabilityCurveChart(curve) {
  const domId = adminVulnerabilityDomId(curve);
  const refKey = adminVulnerabilityRefKey(curve);
  const chart = ensureChart(refKey, domId);
  if (!chart) return;

  const intensity = Array.isArray(curve.intensity) ? curve.intensity : [];
  const mdd = Array.isArray(curve.mdd) ? curve.mdd : [];
  const len = Math.min(intensity.length, mdd.length);
  if (len <= 1) return;

  const xValues = intensity.slice(0, len).map((v) => vulnerabilityIntensityToKmh(v, curve.intensity_unit));
  const mainPoints = xValues.map((x, idx) => [x, clamp01(mdd[idx]) * 100]).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));

  const lowerArr = Array.isArray(curve.uncertaintyLower) ? curve.uncertaintyLower : [];
  const upperArr = Array.isArray(curve.uncertaintyUpper) ? curve.uncertaintyUpper : [];
  const hasUncertainty = lowerArr.length >= len && upperArr.length >= len;
  const lowerPoints = hasUncertainty
    ? xValues.map((x, idx) => [x, clamp01(lowerArr[idx]) * 100]).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
    : [];
  const upperPoints = hasUncertainty
    ? xValues.map((x, idx) => [x, clamp01(upperArr[idx]) * 100]).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
    : [];

  const series = [];
  if (hasUncertainty && lowerPoints.length && upperPoints.length) {
    series.push({
      name: 'Borne basse',
      type: 'line',
      data: lowerPoints,
      showSymbol: false,
      symbol: 'none',
      lineStyle: { width: 1, type: 'dashed', color: 'rgba(91, 197, 242, 0.65)' }
    });
    series.push({
      name: 'Borne haute',
      type: 'line',
      data: upperPoints,
      showSymbol: false,
      symbol: 'none',
      lineStyle: { width: 1, type: 'dashed', color: 'rgba(255, 215, 68, 0.70)' }
    });
  }
  series.push({
    name: 'Vulnérabilité',
    type: 'line',
    data: mainPoints,
    showSymbol: false,
    symbol: 'none',
    lineStyle: { width: 2, color: '#F39655' },
    areaStyle: { color: 'rgba(243, 150, 85, 0.18)' }
  });

  chart.setOption({
    ...chartThemeCommon(),
    grid: { left: 52, right: 20, top: 26, bottom: 44, containLabel: true },
    legend: hasUncertainty ? { top: 0, right: 0, textStyle: { color: '#abc0ba', fontSize: 10 } } : undefined,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        const rows = Array.isArray(params) ? params : [params];
        if (!rows.length) return '';
        const speed = Number(rows[0]?.value?.[0] ?? 0);
        const body = rows.map((row) => {
          const label = String(row?.seriesName || '');
          const val = Number(row?.value?.[1] ?? row?.data?.[1] ?? 0);
          return `${escapeHtml(label)}: ${escapeHtml(numberFmt.format(val))}%`;
        });
        return [`<strong>${escapeHtml(numberFmt.format(speed))} ${WIND_SPEED_UNIT_DISPLAY}</strong>`, ...body].join('<br/>');
      }
    },
    xAxis: {
      ...chartThemeCommon().xAxis,
      type: 'value',
      min: 0,
      max: 500,
      name: `Vitesse vent (${WIND_SPEED_UNIT_DISPLAY})`,
      nameLocation: 'middle',
      nameGap: 30,
      axisLabel: {
        color: '#abc0ba',
        formatter: (value) => numberFmt.format(Number(value) || 0)
      }
    },
    yAxis: {
      ...chartThemeCommon().yAxis,
      type: 'value',
      min: 0,
      max: 100,
      name: 'Dommage (%)',
      axisLabel: {
        color: '#abc0ba',
        formatter: (value) => `${numberFmt.format(Number(value) || 0)}%`
      }
    },
    series
  }, true);
}

function resizeAdminVulnerabilityCharts() {
  Object.keys(chartRefs)
    .filter((key) => key.startsWith('admin_vulnerability_'))
    .forEach((key) => {
      if (chartRefs[key] && typeof chartRefs[key].resize === 'function') chartRefs[key].resize();
    });
}

function renderAdminVulnerabilityCurves() {
  if (!runtime.allowAdminVisu) return;
  const payload = state.adminVulnerabilityCurves;
  if (!payload || !Array.isArray(payload.curves)) {
    if (els.adminVulnerabilityCaption) {
      els.adminVulnerabilityCaption.textContent = 'Chargement des courbes de vulnerabilite...';
    }
    return;
  }

  ensureAdminVulnerabilityCurveCards(payload);
  payload.curves.forEach((curve) => {
    renderAdminVulnerabilityCurveChart(curve);
  });

  if (els.adminVulnerabilityCaption) {
    const curveCount = payload.curves.length;
    const hasUncertainty = payload.curves.some((curve) => Array.isArray(curve.uncertaintyLower) && Array.isArray(curve.uncertaintyUpper));
    const uncertaintyText = hasUncertainty ? 'incertitude visible (bornes basse/haute)' : 'incertitude non disponible dans la source';
    els.adminVulnerabilityCaption.textContent = `${curveCount} courbes (${payload.profile}) · axe X en ${WIND_SPEED_UNIT_DISPLAY} · ${uncertaintyText}.`;
  }

  setTimeout(() => {
    resizeAdminVulnerabilityCharts();
  }, 0);
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
  const allowedScenarios = new Set(['annual', 'rp50', 'rp100', 'event_max']);
  const scenario = allowedScenarios.has(state.impactMapScenario) ? state.impactMapScenario : 'event_max';
  return `state_${scenario}_${hazard}`;
}

function networkFeatureState(feature) {
  const key = networkStatePropertyKey();
  const props = feature?.properties || {};
  let rawValue = props[key];
  if ((rawValue === undefined || rawValue === null || rawValue === '') && state.impactMapScenario === 'rp50') {
    const hazard = state.impactMapHazard === 'storm_cmcc' ? 'storm_cmcc' : 'storm';
    rawValue = props[`state_rp100_${hazard}`];
  }
  const raw = String(rawValue || 'S0').toUpperCase();
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
      rp50: 'temps de retour 50 ans',
      rp100: 'temps de retour 100 ans',
      event_max: 'evenement le plus fort'
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
  const binsKmh = (graph.bins_mps || []).map((value) => formatWindBinLabel(value));
  chart.setOption({
    ...chartThemeCommon(),
    tooltip: { trigger: 'axis' },
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: binsKmh, name: WIND_SPEED_UNIT_DISPLAY },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '%' },
    series: [{ type: 'bar', data: graph.percent || [], itemStyle: { color }, barMaxWidth: 26 }]
  }, true);
}

function renderHistogramComparisonChart(refKey, domId, graphA, graphB, labelA, labelB, colorA, colorB) {
  const chart = ensureChart(refKey, domId);
  if (!chart || !graphA || !graphB) return;
  const rawBinsA = Array.isArray(graphA.bins_mps) ? graphA.bins_mps : [];
  const rawBinsB = Array.isArray(graphB.bins_mps) ? graphB.bins_mps : [];
  const rawPctA = Array.isArray(graphA.percent) ? graphA.percent : [];
  const rawPctB = Array.isArray(graphB.percent) ? graphB.percent : [];
  const seriesA = rawBinsA
    .map((x, idx) => [windMpsToKmh(x), Number(rawPctA[idx] || 0)])
    .filter(([x]) => Number.isFinite(x));
  const seriesB = rawBinsB
    .map((x, idx) => [windMpsToKmh(x), Number(rawPctB[idx] || 0)])
    .filter(([x]) => Number.isFinite(x));

  chart.setOption({
    ...chartThemeCommon(),
    grid: { left: 94, right: 24, top: 50, bottom: 82, containLabel: true },
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
          `<strong>${escapeHtml(numberFmt.format(binValue))} ${WIND_SPEED_UNIT_DISPLAY}</strong>`,
          `${escapeHtml(labelA)}: ${escapeHtml(numberFmt.format(valA))}%`,
          `${escapeHtml(labelB)}: ${escapeHtml(numberFmt.format(valB))}%`
        ].join('<br/>');
      }
    },
    legend: {
      top: 2,
      textStyle: { color: '#abc0ba' }
    },
    xAxis: {
      ...chartThemeCommon().xAxis,
      type: 'value',
      name: `Vitesse maximale du vent (${WIND_SPEED_UNIT_DISPLAY})`,
      nameLocation: 'middle',
      nameGap: 54,
      nameTextStyle: { color: '#edf4f2', fontSize: 12, fontWeight: 700, padding: [10, 0, 0, 0] },
      axisLine: { show: true, lineStyle: { color: 'rgba(177,208,203,0.45)' } },
      axisLabel: { color: '#abc0ba', margin: 10 }
    },
    yAxis: {
      ...chartThemeCommon().yAxis,
      type: 'value',
      name: "Part des evenements (%)",
      nameLocation: 'middle',
      nameRotate: 90,
      nameGap: 72,
      nameTextStyle: { color: '#edf4f2', fontSize: 12, fontWeight: 700, padding: [0, 0, 12, 0] },
      min: 0,
      axisLine: { show: true, lineStyle: { color: 'rgba(177,208,203,0.45)' } },
      axisLabel: { color: '#abc0ba', margin: 12 }
    },
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
  const rp50Rows = rowsForScenario('rp50');
  const rp100Rows = rowsForScenario('rp100');

  const waterRows = annualRows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRows = annualRows.filter((r) => String(r.key).startsWith('elec_'));
  const waterRowsRp50 = rp50Rows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRowsRp50 = rp50Rows.filter((r) => String(r.key).startsWith('elec_'));
  const waterRowsRp100 = rp100Rows.filter((r) => String(r.key).startsWith('eau_'));
  const elecRowsRp100 = rp100Rows.filter((r) => String(r.key).startsWith('elec_'));
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
    waterRowsRp50.map((r) => r.label),
    waterRowsRp50.map((r) => r.storm),
    waterRowsRp50.map((r) => r.cmcc),
    { storm: '#00A6E2', cmcc: '#99D7F7' }
  );
  renderGroupedImpactBarChart(
    'impact_rp100_elec',
    'impact-rp100-elec-chart',
    elecRowsRp50.map((r) => r.label),
    elecRowsRp50.map((r) => r.storm),
    elecRowsRp50.map((r) => r.cmcc),
    { storm: '#F39655', cmcc: '#FFD744' }
  );
  renderGroupedImpactBarChart(
    'impact_rp1000_water',
    'impact-rp1000-water-chart',
    waterRowsRp100.map((r) => r.label),
    waterRowsRp100.map((r) => r.storm),
    waterRowsRp100.map((r) => r.cmcc),
    { storm: '#0083CB', cmcc: '#5BC5F2' }
  );
  renderGroupedImpactBarChart(
    'impact_rp1000_elec',
    'impact-rp1000-elec-chart',
    elecRowsRp100.map((r) => r.label),
    elecRowsRp100.map((r) => r.storm),
    elecRowsRp100.map((r) => r.cmcc),
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
  if (scenario === 'rp50') {
    if (Number.isFinite(Number(h.pml_50_eur))) return Number(h.pml_50_eur || 0);
    return estimateRp50FromRp100AndRp1000(h.pml_100_eur, h.pml_1000_eur);
  }
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
  scenarioChart('user_impact_rp100', 'user-impact-rp100-chart', 'rp50', '#00A6E2', '#99D7F7');
  scenarioChart('user_impact_rp1000', 'user-impact-rp1000-chart', 'rp100', '#A4A64B', '#FFD744');
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
    `Temps de retour 50 ans: STORM ${formatMoneyEUR(scenarioLossFromPortfolio(storm, 'rp50'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(storm, 'rp50')))} %), STORM_CMCC ${formatMoneyEUR(scenarioLossFromPortfolio(cmcc, 'rp50'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(cmcc, 'rp50')))} %).`,
    `Temps de retour 100 ans: STORM ${formatMoneyEUR(scenarioLossFromPortfolio(storm, 'rp100'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(storm, 'rp100')))} %), STORM_CMCC ${formatMoneyEUR(scenarioLossFromPortfolio(cmcc, 'rp100'))} (${percentFmt.format(pct(scenarioLossFromPortfolio(cmcc, 'rp100')))} %).`,
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
    uploaded: 'exposition importée',
    drawn: 'exposition dessinée'
  }[state.activeResultMode] || 'résultat actif';
  els.userImpactSummaryText.textContent = `Cette section présente les impacts du ${modeLabel}, sans carte d’état des réseaux.`;
  renderUserImpactChartsFromResult(result);
  renderUserConclusionText(result);
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

  const rows = layers.map((layer, idx) => {
    const props = layer.feature?.properties || {};
    const lid = String(layer._leaflet_id || idx + 1);
    const gtype = String(layer.feature?.geometry?.type || layer?.toGeoJSON?.()?.geometry?.type || 'Unknown');
    const type = String(props.exposure_type || els.drawCategory?.value || 'habitation');
    const label = String(props.label || `Geometrie ${idx + 1}`);
    const valueEur = Number(props.value_eur);
    const geomLabel = gtype === 'Polygon' ? 'Polygone'
      : gtype === 'LineString' ? 'Ligne'
        : gtype === 'Point' ? 'Point'
          : gtype === 'Rectangle' ? 'Rectangle'
            : gtype;
    const typeLabel = EXPOSURE_TYPE_LABEL[type] || type;
    return `
      <li class="draw-item" data-layer-id="${escapeHtml(lid)}">
        <div class="draw-item-main">
          <input class="draw-name-input" type="text" value="${escapeHtml(label)}" aria-label="Nom de la geometrie ${escapeHtml(String(idx + 1))}" />
          <button class="draw-delete-btn" type="button" aria-label="Supprimer la geometrie ${escapeHtml(String(idx + 1))}">&times;</button>
        </div>
        <div class="draw-item-meta">${escapeHtml(geomLabel)} · ${escapeHtml(typeLabel)}</div>
        <div class="draw-item-value">
          <label>Valeur monetaire (€)</label>
          <input class="draw-value-input" type="number" min="0" step="1" value="${escapeHtml(String(Number.isFinite(valueEur) && valueEur > 0 ? valueEur : 1000000))}" />
        </div>
      </li>
    `;
  });
  els.drawSummaryList.innerHTML = rows.join('');
  const drawBusy = state.activeSubmitMode === 'drawn' && state.backendComputeActive;
  els.submitDrawingBtn.disabled = drawBusy || layers.length === 0;
}

function renderAll() {
  renderWindMaps();
  if (state.currentPage === 'page5') {
    renderAdminVisuPage();
    renderAdminPopulationMap();
    renderAdminVulnerabilityCurves();
  }
  renderWaterInfraMap();
  renderInfraSummary();
  renderUserImpactSection(state.activeResult);
  if (state.currentPage === 'page1' || state.currentPage === 'page2') {
    ensureNetworkStatesLoaded();
  }
  renderNetworkStateMap();

  if (state.currentPage === 'page3') {
    renderTerritorySelectionState();
    renderKpis();
    renderMap();
    renderTerritoryTable();
  }

  if (!state.activeResult) {
    return;
  }
  updateMetaBadges();
  renderNotes();

}

function setActiveResult(result, mode = state.selectedDatasetMode) {
  if (!result) {
    state.activeResult = null;
    renderAll();
    return;
  }
  ensureResultShape(result);
  const label = resultRunLabel(result);
  rememberRunLabel(result?.meta?.job_id, label || result?.meta?.job_id);
  const resolvedMode = datasetModeFromResult(result, mode);
  state.activeResult = result;
  state.activeResultMode = resolvedMode;
  state.selectedDatasetMode = resolvedMode;
  if (resolvedMode) state.resultsByMode[resolvedMode] = result;
  syncMapPreviewFromResult(result, resolvedMode);
  renderAll();
}

function normalizeCaseStudyTerritory(territory) {
  return String(territory || '').trim().toLowerCase() === 'martinique' ? 'martinique' : 'guadeloupe';
}

function caseStudyFileBase(territory) {
  return normalizeCaseStudyTerritory(territory);
}

async function fetchWindMaps(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const urls = [new URL(`/data/${base}-wind-maps.json`, window.location.origin).toString()];
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

async function fetchAdminVisuMaps() {
  const urls = [
    new URL('/hazard-maps/na-leaflet-overlays.json', window.location.origin).toString(),
    new URL('/hazard-maps/na_wind_leaflet_overlays.json', window.location.origin).toString()
  ];
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      if (!payload?.meta?.bounds || !payload?.overlays?.storm || !payload?.overlays?.storm_cmcc) {
        throw new Error('Payload admin visu invalide');
      }
      return payload;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error('Impossible de charger les couches admin visu');
}

function ensureAdminVisuMapsLoaded() {
  if (state.adminVisuMaps) return Promise.resolve(state.adminVisuMaps);
  if (state.adminVisuMapsPromise) return state.adminVisuMapsPromise;
  state.adminVisuMapsPromise = fetchAdminVisuMaps()
    .then((payload) => {
      state.adminVisuMaps = payload;
      return payload;
    })
    .finally(() => {
      state.adminVisuMapsPromise = null;
    });
  return state.adminVisuMapsPromise;
}

async function fetchAdminPopulationMaps() {
  const urls = [new URL('/hazard-maps/population-overlays.json', window.location.origin).toString()];
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      if (!payload || !Array.isArray(payload.territories) || payload.territories.length === 0) {
        throw new Error('Payload population invalide');
      }
      return payload;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error('Impossible de charger les couches population');
}

function ensureAdminPopulationMapsLoaded() {
  if (state.adminPopulationMaps) return Promise.resolve(state.adminPopulationMaps);
  if (state.adminPopulationMapsPromise) return state.adminPopulationMapsPromise;
  state.adminPopulationMapsPromise = fetchAdminPopulationMaps()
    .then((payload) => {
      state.adminPopulationMaps = payload;
      return payload;
    })
    .finally(() => {
      state.adminPopulationMapsPromise = null;
    });
  return state.adminPopulationMapsPromise;
}

async function fetchAdminVulnerabilityCurves() {
  const url = new URL('/api/v1/vulnerability/curves', window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  return normalizeAdminVulnerabilityPayload(payload);
}

function ensureAdminVulnerabilityCurvesLoaded() {
  if (state.adminVulnerabilityCurves) return Promise.resolve(state.adminVulnerabilityCurves);
  if (state.adminVulnerabilityCurvesPromise) return state.adminVulnerabilityCurvesPromise;
  state.adminVulnerabilityCurvesPromise = fetchAdminVulnerabilityCurves()
    .then((payload) => {
      state.adminVulnerabilityCurves = payload;
      return payload;
    })
    .finally(() => {
      state.adminVulnerabilityCurvesPromise = null;
    });
  return state.adminVulnerabilityCurvesPromise;
}

async function fetchWaterInfra(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const url = new URL(`/data/${base}-water-infra.geojson`, window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    throw new Error("Payload des infrastructures d'eau invalide");
  }
  return payload;
}

async function fetchPage1Analysis(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const suffix = base === 'martinique' ? 'page2' : 'page1';
  const url = new URL(`/data/${base}-${suffix}-analysis.json`, window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || !payload.exposition || !payload.hazard || !payload.impact || !payload.conclusion) {
    throw new Error('Payload analyse cas d etude invalide');
  }
  return payload;
}

async function fetchNetworkStates(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const url = new URL(`/data/${base}-network-states.geojson`, window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    throw new Error("Payload des états de réseaux invalide");
  }
  return payload;
}

function ensureNetworkStatesLoaded() {
  const territory = normalizeCaseStudyTerritory(state.caseStudyTerritory);
  const cached = state.caseStudyCache[territory];
  if (cached && cached.networkStates) {
    state.networkStates = cached.networkStates;
    return;
  }
  if (state.networkStatesPromise) return;
  state.networkStatesPromise = fetchNetworkStates(territory)
    .then((payload) => {
      state.networkStates = payload;
      if (!state.caseStudyCache[territory]) state.caseStudyCache[territory] = {};
      state.caseStudyCache[territory].networkStates = payload;
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

function resetCaseStudyMapLayers() {
  windMapRef.storm.hasFitted = false;
  windMapRef.storm_cmcc.hasFitted = false;
  if (windMapRef.storm.cellsLayer) windMapRef.storm.cellsLayer.clearLayers();
  if (windMapRef.storm_cmcc.cellsLayer) windMapRef.storm_cmcc.cellsLayer.clearLayers();
  if (waterMapRef.instance) {
    waterMapRef.layersByType.forEach((entry) => {
      if (entry?.layer && waterMapRef.instance.hasLayer(entry.layer)) waterMapRef.instance.removeLayer(entry.layer);
    });
  }
  waterMapRef.layersByType.clear();
  waterMapRef.order = [];
  waterMapRef.hasFitted = false;
  if (networkMapRef.instance) {
    networkMapRef.layersByType.forEach((entry) => {
      if (entry?.layer && networkMapRef.instance.hasLayer(entry.layer)) networkMapRef.instance.removeLayer(entry.layer);
    });
  }
  networkMapRef.layersByType.clear();
  networkMapRef.order = [];
  networkMapRef.hasFitted = false;
}

async function ensureCaseStudyLoaded(territory) {
  const key = normalizeCaseStudyTerritory(territory);
  if (state.caseStudyCache[key]?.ready) return state.caseStudyCache[key];
  if (!state.caseStudyCache[key]) state.caseStudyCache[key] = {};
  const cache = state.caseStudyCache[key];
  if (cache.promise) return cache.promise;
  cache.promise = Promise.all([
    fetchWindMaps(key),
    fetchWaterInfra(key),
    fetchPage1Analysis(key),
    fetchNetworkStates(key)
  ]).then(([windMaps, waterInfra, analysis, networkStates]) => {
    cache.windMaps = windMaps;
    cache.waterInfra = waterInfra;
    cache.analysis = analysis;
    cache.networkStates = networkStates;
    cache.ready = true;
    return cache;
  }).finally(() => {
    cache.promise = null;
  });
  return cache.promise;
}

function applyCaseStudyState(territory, payload) {
  const key = normalizeCaseStudyTerritory(territory);
  const previous = state.caseStudyTerritory;
  state.caseStudyTerritory = key;
  if (previous !== key) {
    resetCaseStudyMapLayers();
  }
  state.windMaps = payload?.windMaps || null;
  state.waterInfra = payload?.waterInfra || null;
  state.page1Analysis = payload?.analysis || null;
  state.networkStates = payload?.networkStates || null;
}

function stopPolling() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
  state.activeSubmitMode = null;
  clearSubmitButtonLoading();
  setBackendComputeActive(false);
}

async function pollJob(jobId, { modeTarget = 'uploaded', immediate = false, submitMode = null } = {}) {
  if (runtime.isPublicShowcase) {
    showError("Le suivi de jobs est indisponible en mode vitrine publique.");
    return;
  }
  const normalizedModeTarget = normalizeDatasetMode(modeTarget);
  stopPolling();
  if (submitMode) {
    state.activeSubmitMode = normalizeDatasetMode(submitMode);
    setSubmitButtonLoading(state.activeSubmitMode, true);
  }
  setBackendComputeActive(true);
  state.currentJobId = jobId;
  state.pollingModeTarget = normalizedModeTarget;
  if (els.pollJobId && !els.pollJobId.value) els.pollJobId.value = jobId;

  const runOnce = async () => {
    try {
      const res = await fetch(`/api/v1/runs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const job = await res.json();
      rememberRunLabel(job.job_id, runLabelForJob(jobId) || job.job_id);
      const runLabel = runLabelForJob(job.job_id);
      const msg = `${runLabel || job.job_id} · ${job.status} · ${job.stage} · ${Math.round((job.progress || 0) * 100)}%${job.message ? ` · ${job.message}` : ''}${job?.error?.message ? ` · ${job.error.message}` : ''}`;
      setStatus(msg, job.status === 'failed' ? 'error' : (job.status === 'completed' ? 'success' : 'info'));

      if (job.status === 'completed') {
        const resultRes = await fetch(`/api/v1/runs/${encodeURIComponent(jobId)}/result`, { cache: 'no-store' });
        if (!resultRes.ok) throw new Error(`Result HTTP ${resultRes.status}`);
        const payload = ensureResultShape(await resultRes.json());
        const resolvedMode = datasetModeFromResult(payload, job?.dataset_mode || normalizedModeTarget);
        const payloadLabel = resultRunLabel(payload);
        rememberRunLabel(jobId, payloadLabel || runLabelForJob(jobId) || jobId);
        state.resultsByMode[resolvedMode] = payload;
        state.selectedDatasetMode = resolvedMode;
        setActiveResult(payload, resolvedMode);
        refreshRunMemoryList().catch(() => {});
        stopPolling();
        return;
      }

      if (job.status === 'failed' || job.status === 'expired') {
        refreshRunMemoryList().catch(() => {});
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

async function resolveRunLookup(inputValue) {
  const query = String(inputValue || '').trim();
  if (!query) {
    throw new Error('Renseignez un nom de run ou un identifiant de job.');
  }
  if (query.startsWith('jr_')) {
    const recent = state.recentRuns.find((run) => String(run?.job_id || '').trim() === query);
    let modeTarget = normalizeDatasetMode(recent?.dataset_mode || state.selectedDatasetMode);
    let runLabel = runLabelForJob(query) || String(recent?.run_label || query).trim() || query;
    try {
      const jobRes = await fetch(`/api/v1/runs/${encodeURIComponent(query)}`, { cache: 'no-store' });
      if (jobRes.ok) {
        const jobPayload = await jobRes.json();
        modeTarget = normalizeDatasetMode(jobPayload?.dataset_mode || modeTarget);
        runLabel = String(jobPayload?.run_label || runLabel || query).trim() || query;
        rememberRunLabel(query, runLabel);
      }
    } catch (_) {
      /* fallback to memory */
    }
    return { jobId: query, modeTarget, runLabel };
  }
  const res = await fetch(`/api/v1/runs/search?run_label=${encodeURIComponent(query)}`, { cache: 'no-store' });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(payload.detail || `HTTP ${res.status}`);
  }
  const jobId = String(payload.job_id || '').trim();
  if (!jobId) {
    throw new Error("L'API n'a pas renvoye de job_id valide.");
  }
  const modeTarget = payload.dataset_mode === 'drawn' ? 'drawn' : 'uploaded';
  const runLabel = String(payload.run_label || query).trim() || query;
  rememberRunLabel(jobId, runLabel);
  return { jobId, modeTarget, runLabel };
}

async function submitUpload(event) {
  event.preventDefault();
  if (runtime.isPublicShowcase) {
    showError("L'import d'exposition est reserve aux collaborateurs autorises.");
    return;
  }
  clearError();
  const file = els.uploadFile.files?.[0];
  if (!file) {
    showError("Sélectionnez un fichier avant de lancer un run d'exposition importée.");
    return;
  }
  const runLabel = els.runLabel.value.trim();
  if (!runLabel) {
    showError("Le nom du run est obligatoire.");
    return;
  }

  const form = new FormData();
  form.append('input_mode', 'file');
  form.append('exposure_file', file);
  form.append('value_field', 'value_eur');
  form.append('id_field', 'asset_id');
  form.append('asset_type_field', 'asset_type');
  form.append('exposure_category_field', 'exposure_category');
  form.append('default_exposure_category', 'habitation');
  form.append('sampling_spacing_m', String(FIXED_SAMPLING_SPACING_M));
  form.append('run_label', runLabel);

  showRunDurationEstimate('uploaded');
  setSubmitButtonLoading('uploaded', true);
  setStatus("Soumission du run d'exposition importée…", 'info');
  try {
    const res = await fetch('/api/v1/runs', { method: 'POST', body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    setStatus(`Job accepté: ${payload.job_id}. Run importé en file d'attente.`, 'info');
    state.selectedDatasetMode = 'uploaded';
    rememberRunLabel(payload.job_id, runLabel);
    if (els.pollJobId) els.pollJobId.value = runLabel;
    refreshRunMemoryList().catch(() => {});
    await pollJob(payload.job_id, { modeTarget: 'uploaded', immediate: true, submitMode: 'uploaded' });
  } catch (err) {
    showError(`Échec du lancement du run importé: ${err.message}`);
    setStatus(`Échec du lancement du run importé: ${err.message}`, 'error');
  } finally {
    if (state.activeSubmitMode !== 'uploaded') {
      setSubmitButtonLoading('uploaded', false);
    }
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
    const currentLabel = String(layer?.feature?.properties?.label || gj?.properties?.label || `Geometrie ${layer._leaflet_id || ''}`).trim();
    const valueEur = Number(layer?.feature?.properties?.value_eur || gj?.properties?.value_eur || 0);
    if (!Number.isFinite(valueEur) || valueEur <= 0) {
      throw new Error(`La valeur monetaire est invalide pour la geometrie "${currentLabel || layer._leaflet_id}".`);
    }
    gj.properties = {
      ...(gj.properties || {}),
      label: currentLabel || `Geometrie ${layer._leaflet_id || ''}`,
      value_eur: valueEur,
      exposure_type: currentType,
      exposure_category: currentCategory,
      asset_type: currentAssetType
    };
    layer.feature = layer.feature || { type: 'Feature', properties: {} };
    layer.feature.properties = {
      ...(layer.feature.properties || {}),
      label: currentLabel || `Geometrie ${layer._leaflet_id || ''}`,
      value_eur: valueEur,
      exposure_type: currentType,
      exposure_category: currentCategory,
      asset_type: currentAssetType
    };
    return gj;
  });
  return { type: 'FeatureCollection', features };
}

async function submitDrawnExposure() {
  if (runtime.isPublicShowcase) {
    showError("Le run d'exposition dessinee est reserve aux collaborateurs autorises.");
    return;
  }
  clearError();
  let fc = null;
  try {
    fc = getDrawnFeatureCollection();
  } catch (err) {
    showError(err.message || 'Valeur de geometrie invalide.');
    return;
  }
  if (!fc) {
    showError("Dessinez au moins une géométrie avant de lancer un run d'exposition dessinée.");
    return;
  }
  const runLabel = els.drawRunLabel?.value.trim() || '';
  if (!runLabel) {
    showError("Le nom du run dessine est obligatoire.");
    return;
  }

  const form = new FormData();
  form.append('input_mode', 'drawn_geojson');
  form.append('drawn_geojson', JSON.stringify(fc));
  const defaultExposureType = (els.drawCategory?.value || 'habitation').trim() || 'habitation';
  form.append('default_exposure_category', categoryFromExposureType(defaultExposureType));
  form.append('sampling_spacing_m', String(FIXED_SAMPLING_SPACING_M));
  form.append('run_label', runLabel);

  showRunDurationEstimate('drawn');
  setSubmitButtonLoading('drawn', true);
  setStatus("Soumission du run d'exposition dessinée…", 'info');
  try {
    const res = await fetch('/api/v1/runs', { method: 'POST', body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
    setStatus(`Job accepté: ${payload.job_id}. Run dessiné en file d'attente.`, 'info');
    state.selectedDatasetMode = 'drawn';
    rememberRunLabel(payload.job_id, runLabel);
    if (els.pollJobId) els.pollJobId.value = runLabel;
    refreshRunMemoryList().catch(() => {});
    await pollJob(payload.job_id, { modeTarget: 'drawn', immediate: true, submitMode: 'drawn' });
  } catch (err) {
    showError(`Échec du lancement du run dessiné: ${err.message}`);
    setStatus(`Échec du lancement du run dessiné: ${err.message}`, 'error');
  } finally {
    if (state.activeSubmitMode !== 'drawn') {
      setSubmitButtonLoading('drawn', false);
    }
  }
}

function switchDatasetMode(mode) {
  if (runtime.isPublicShowcase) return;
  state.selectedDatasetMode = mode;

  const candidate = state.resultsByMode[mode];
  if (!candidate) {
    const modeLabel = mode === 'drawn' ? 'dessine' : 'importe';
    setStatus(`Aucun resultat ${modeLabel} n'est encore disponible.`, 'info');
    setActiveResult(null, mode);
    renderMap();
    renderTerritoryTable();
    renderTerritorySelectionState();
    renderKpis();
    return;
  }

  setActiveResult(candidate, mode);
}

async function switchCaseStudyPage(pageKey, territory, { updateHash = true } = {}) {
  setActivePage(pageKey, { updateHash });
  try {
    const payload = await ensureCaseStudyLoaded(territory);
    applyCaseStudyState(territory, payload);
    renderAll();
  } catch (err) {
    console.warn(`Case-study ${territory} could not be loaded`, err);
    if (els.expositionSummaryText) els.expositionSummaryText.textContent = "Donnees d'exposition indisponibles.";
    if (els.hazardSummaryText) els.hazardSummaryText.textContent = "Donnees d'alea indisponibles.";
    if (els.impactSummaryText) els.impactSummaryText.textContent = "Donnees d'impact indisponibles.";
    if (els.conclusionText) els.conclusionText.textContent = 'Conclusion indisponible.';
    renderAll();
    showError(`Erreur de chargement de l'etude de cas ${territory}: ${err.message}`);
  }
}

function bindEvents() {
  if (els.navPage1) {
    els.navPage1.addEventListener('click', async () => {
      await switchCaseStudyPage('page1', 'guadeloupe');
    });
  }
  if (els.navPage2) {
    els.navPage2.addEventListener('click', async () => {
      await switchCaseStudyPage('page2', 'martinique');
    });
  }
  if (els.navPage3) {
    els.navPage3.addEventListener('click', () => {
      if (runtime.isPublicShowcase) {
        setActivePage('page1');
        setStatus("L'espace collaborateur est disponible sur app.sib.elio.dev.", 'info');
        return;
      }
      setActivePage('page3');
      renderAll();
    });
  }
  if (els.navPage4) {
    els.navPage4.addEventListener('click', () => {
      setActivePage('page4');
      renderAll();
    });
  }
  if (els.navPage5) {
    els.navPage5.addEventListener('click', () => {
      if (!runtime.allowAdminVisu) {
        setActivePage('page1');
        setStatus("La page Admin visu n'est pas disponible sur ce domaine.", 'info');
        return;
      }
      setActivePage('page5');
      ensureAdminVisuMapsLoaded()
        .then(() => {
          renderAdminVisuPage();
        })
        .catch((err) => {
          setStatus(`Admin visu indisponible: ${err.message}`, 'error');
        });
      ensureAdminPopulationMapsLoaded()
        .then(() => {
          renderAdminPopulationMap();
        })
        .catch((err) => {
          setStatus(`Population admin indisponible: ${err.message}`, 'error');
        });
      ensureAdminVulnerabilityCurvesLoaded()
        .then(() => {
          renderAdminVulnerabilityCurves();
        })
        .catch((err) => {
          setStatus(`Courbes de vulnerabilite indisponibles: ${err.message}`, 'error');
        });
    });
  }
  window.addEventListener('hashchange', () => {
    const page = pageFromHash();
    if (page === 'page2') {
      switchCaseStudyPage('page2', 'martinique', { updateHash: false });
      return;
    }
    if (page === 'page1') {
      switchCaseStudyPage('page1', 'guadeloupe', { updateHash: false });
      return;
    }
    if (page === 'page5') {
      setActivePage('page5', { updateHash: false });
      ensureAdminVisuMapsLoaded()
        .then(() => {
          renderAdminVisuPage();
        })
        .catch((err) => {
          setStatus(`Admin visu indisponible: ${err.message}`, 'error');
        });
      ensureAdminPopulationMapsLoaded()
        .then(() => {
          renderAdminPopulationMap();
        })
        .catch((err) => {
          setStatus(`Population admin indisponible: ${err.message}`, 'error');
        });
      ensureAdminVulnerabilityCurvesLoaded()
        .then(() => {
          renderAdminVulnerabilityCurves();
        })
        .catch((err) => {
          setStatus(`Courbes de vulnerabilite indisponibles: ${err.message}`, 'error');
        });
      return;
    }
    setActivePage(page, { updateHash: false });
    renderAll();
  });

  if (els.hazardSelect) {
    els.hazardSelect.addEventListener('change', () => {
      state.selectedHazard = els.hazardSelect.value;
      triggerUiComputePulse(700);
      renderAll();
    });
  }

  if (els.windOpacitySlider) {
    const onWindOpacityChange = () => syncWindOpacityFromSlider({ forceApply: true });
    const sliderEvents = ['input', 'change', 'pointermove', 'pointerup', 'touchmove', 'touchend', 'mousemove', 'mouseup', 'keyup'];
    sliderEvents.forEach((eventName) => {
      els.windOpacitySlider.addEventListener(eventName, onWindOpacityChange);
    });
    updateWindOpacityUi();
    syncWindOpacityFromSlider({ forceApply: true });
  }
  if (els.windMapMode) {
    updateWindModeUi();
    els.windMapMode.addEventListener('change', () => {
      state.windMapMode = normalizeWindMapMode(els.windMapMode.value);
      updateWindModeUi();
      renderWindMaps();
    });
  }
  if (els.adminVisuOpacitySlider) {
    const onAdminOpacityChange = () => syncAdminVisuOpacityFromSlider({ forceApply: true });
    const sliderEvents = ['input', 'change', 'pointermove', 'pointerup', 'touchmove', 'touchend', 'mousemove', 'mouseup', 'keyup'];
    sliderEvents.forEach((eventName) => {
      els.adminVisuOpacitySlider.addEventListener(eventName, onAdminOpacityChange);
    });
    updateAdminVisuOpacityUi();
    syncAdminVisuOpacityFromSlider({ forceApply: true });
  }
  (els.adminVisuHazardSelects || []).forEach((select, idx) => {
    if (!select) return;
    select.value = normalizeAdminVisuHazard(state.adminVisuCards[idx]?.hazard);
    select.addEventListener('change', () => {
      state.adminVisuCards[idx] = {
        ...(state.adminVisuCards[idx] || {}),
        hazard: normalizeAdminVisuHazard(select.value),
        scenario: normalizeAdminVisuScenario(state.adminVisuCards[idx]?.scenario)
      };
      renderAdminVisuCard(idx);
    });
  });
  (els.adminVisuScenarioSelects || []).forEach((select, idx) => {
    if (!select) return;
    select.value = normalizeAdminVisuScenario(state.adminVisuCards[idx]?.scenario);
    select.addEventListener('change', () => {
      state.adminVisuCards[idx] = {
        ...(state.adminVisuCards[idx] || {}),
        hazard: normalizeAdminVisuHazard(state.adminVisuCards[idx]?.hazard),
        scenario: normalizeAdminVisuScenario(select.value)
      };
      renderAdminVisuCard(idx);
    });
  });
  if (els.adminPopulationTerritorySelect) {
    els.adminPopulationTerritorySelect.addEventListener('change', () => {
      state.adminPopulationTerritory = normalizeAdminPopulationTerritory(
        els.adminPopulationTerritorySelect.value,
        state.adminPopulationMaps
      );
      renderAdminPopulationMap();
    });
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
      const allowedScenarios = new Set(['annual', 'rp50', 'rp100', 'event_max']);
      state.impactMapScenario = allowedScenarios.has(els.impactMapScenarioSelect.value)
        ? els.impactMapScenarioSelect.value
        : 'event_max';
      renderNetworkStateMap();
    });
  }

  els.reloadJobBtn.addEventListener('click', async () => {
    if (runtime.isPublicShowcase) {
      showError("Le rechargement de jobs est reserve aux collaborateurs autorises.");
      return;
    }
    const lookup = els.pollJobId.value.trim();
    if (!lookup) {
      showError('Renseignez un nom de run ou un identifiant de job pour recharger un résultat.');
      return;
    }
    try {
      const resolved = await resolveRunLookup(lookup);
      if (els.pollJobId) {
        els.pollJobId.value = resolved.runLabel || lookup;
      }
      if (resolved.runLabel) {
        setStatus(`Run trouve: "${resolved.runLabel}" (${resolved.jobId}).`, 'info');
      }
      state.selectedDatasetMode = resolved.modeTarget;
      await pollJob(resolved.jobId, { modeTarget: resolved.modeTarget, immediate: true });
    } catch (err) {
      showError(`Impossible de recharger le resultat: ${err.message}`);
    }
  });

  if (els.runMemoryList) {
    els.runMemoryList.addEventListener('click', async (event) => {
      if (runtime.isPublicShowcase) return;
      const target = event.target instanceof Element ? event.target : null;
      const btn = target ? target.closest('button[data-run-job-id]') : null;
      if (!btn) return;
      const jobId = String(btn.getAttribute('data-run-job-id') || '').trim();
      const modeTarget = String(btn.getAttribute('data-run-mode') || '').trim() === 'drawn' ? 'drawn' : 'uploaded';
      const runLabel = String(btn.getAttribute('data-run-label') || '').trim();
      if (!jobId) return;
      rememberRunLabel(jobId, runLabel || jobId);
      if (els.pollJobId) els.pollJobId.value = runLabel || jobId;
      state.selectedDatasetMode = modeTarget;
      await pollJob(jobId, { modeTarget, immediate: true });
    });
  }

  els.uploadForm.addEventListener('submit', submitUpload);
  if (els.uploadFile) {
    els.uploadFile.addEventListener('change', async () => {
      const file = els.uploadFile.files?.[0];
      await previewUploadedFile(file);
    });
  }
  els.submitDrawingBtn.addEventListener('click', submitDrawnExposure);
  els.refreshPreviewBtn.addEventListener('click', renderDrawPreview);
  if (els.drawModeButtons) {
    els.drawModeButtons.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const btn = target ? target.closest('button[data-draw-mode]') : null;
      if (!btn) return;
      const mode = String(btn.getAttribute('data-draw-mode') || '').trim();
      if (!mode) return;
      startDrawMode(mode);
    });
  }
  if (els.drawSummaryList) {
    els.drawSummaryList.addEventListener('input', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const input = target ? target.closest('.draw-name-input') : null;
      const valueInput = target ? target.closest('.draw-value-input') : null;
      if (!input && !valueInput) return;
      const row = (input || valueInput).closest('[data-layer-id]');
      if (!row || !mapRef.drawnItems) return;
      const layerId = Number(row.getAttribute('data-layer-id'));
      const layer = mapRef.drawnItems.getLayer(layerId);
      if (!layer) return;
      layer.feature = layer.feature || { type: 'Feature', properties: {} };
      if (input) {
        layer.feature.properties = {
          ...(layer.feature.properties || {}),
          label: input.value.trim() || `Geometrie ${layerId}`
        };
      }
      if (valueInput) {
        layer.feature.properties = {
          ...(layer.feature.properties || {}),
          value_eur: Number(valueInput.value)
        };
      }
      const drawFc = drawFeatureCollectionFromMapLayers();
      if (drawFc) {
        ensureStormCoverageLoaded()
          .then(() => {
            setOutsideCoverageWarning('drawn', outsideCoverageRefsForFeatureCollection(drawFc, 'drawn'));
          })
          .catch(() => {
            setOutsideCoverageWarning('drawn', []);
          });
      } else {
        setOutsideCoverageWarning('drawn', []);
      }
    });
    els.drawSummaryList.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const btn = target ? target.closest('.draw-delete-btn') : null;
      if (!btn) return;
      const row = btn.closest('[data-layer-id]');
      if (!row || !mapRef.drawnItems) return;
      const layerId = Number(row.getAttribute('data-layer-id'));
      const layer = mapRef.drawnItems.getLayer(layerId);
      if (!layer) return;
      mapRef.drawnItems.removeLayer(layer);
      const drawFc = drawFeatureCollectionFromMapLayers();
      if (drawFc) {
        ensureStormCoverageLoaded()
          .then(() => {
            setOutsideCoverageWarning('drawn', outsideCoverageRefsForFeatureCollection(drawFc, 'drawn'));
          })
          .catch(() => {
            setOutsideCoverageWarning('drawn', []);
          });
      } else {
        setOutsideCoverageWarning('drawn', []);
      }
      renderDrawPreview();
      renderTerritorySelectionState();
      renderMap();
      els.clearDrawingsBtn.disabled = mapRef.drawnItems.getLayers().length === 0;
      els.submitDrawingBtn.disabled = mapRef.drawnItems.getLayers().length === 0;
    });
  }
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
    disableActiveDrawMode();
    mapRef.drawnItems.clearLayers();
    setOutsideCoverageWarning('drawn', []);
    renderDrawPreview();
    renderTerritorySelectionState();
    renderMap();
    els.clearDrawingsBtn.disabled = true;
    els.submitDrawingBtn.disabled = true;
  });

  els.territorySearch.addEventListener('input', () => {
    state.territorySearch = els.territorySearch.value.trim();
    if (state.currentPage === 'page3') renderTerritoryTable();
  });

  els.clearTerritoryFilterBtn.addEventListener('click', () => {
    els.territorySearch.value = '';
    state.territorySearch = '';
    renderAll();
  });
}

async function bootstrap() {
  try {
    clearError();
    applyRuntimeMode();
    bindEvents();
    ensureStormCoverageLoaded().catch(() => {});
    if (!runtime.isPublicShowcase) {
      await refreshRunMemoryList();
    }
    const initialPage = pageFromHash();
    setActivePage(initialPage, { updateHash: false });
    renderDrawPreview();
    const initialTerritory = initialPage === 'page2' ? 'martinique' : 'guadeloupe';
    const initialCasePayload = await ensureCaseStudyLoaded(initialTerritory).catch((err) => {
      console.warn(`Case-study ${initialTerritory} payload could not be loaded`, err);
      return null;
    });
    if (initialCasePayload) {
      applyCaseStudyState(initialTerritory, initialCasePayload);
      const secondaryTerritory = initialTerritory === 'guadeloupe' ? 'martinique' : 'guadeloupe';
      ensureCaseStudyLoaded(secondaryTerritory).catch((err) => {
        console.warn(`Case-study ${secondaryTerritory} preload failed`, err);
      });
    } else {
      if (els.expositionSummaryText) els.expositionSummaryText.textContent = "Donnees d'exposition indisponibles.";
      if (els.hazardSummaryText) els.hazardSummaryText.textContent = "Donnees d'alea indisponibles.";
      if (els.impactSummaryText) els.impactSummaryText.textContent = "Donnees d'impact indisponibles.";
      if (els.conclusionText) els.conclusionText.textContent = 'Conclusion indisponible.';
    }

    if (runtime.allowAdminVisu) {
      ensureAdminVisuMapsLoaded()
        .then(() => {
          if (state.currentPage === 'page5') renderAdminVisuPage();
        })
        .catch((err) => {
          console.warn('Admin visu preload failed', err);
          if (state.currentPage === 'page5') {
            setStatus(`Admin visu indisponible: ${err.message}`, 'error');
          }
        });
      ensureAdminPopulationMapsLoaded()
        .then(() => {
          if (state.currentPage === 'page5') renderAdminPopulationMap();
        })
        .catch((err) => {
          console.warn('Admin population preload failed', err);
          if (state.currentPage === 'page5') {
            setStatus(`Population admin indisponible: ${err.message}`, 'error');
          }
        });
      ensureAdminVulnerabilityCurvesLoaded()
        .then(() => {
          if (state.currentPage === 'page5') renderAdminVulnerabilityCurves();
        })
        .catch((err) => {
          console.warn('Admin vulnerability curves preload failed', err);
          if (state.currentPage === 'page5') {
            setStatus(`Courbes de vulnerabilite indisponibles: ${err.message}`, 'error');
          }
        });
    }

    state.activeResult = null;
    if (els.datasetSelect) els.datasetSelect.value = state.selectedDatasetMode;
    renderAll();
    if (runtime.isPublicShowcase) {
      setStatus("References Guadeloupe/Martinique chargees. Pour collaborer sur des runs personnalises, demande un acces a app.sib.elio.dev.", 'success');
    } else {
      setStatus("Page collaborateur prete. Importez ou dessinez une exposition pour lancer un premier run.", 'success');
    }
  } catch (err) {
    console.error(err);
    showError(`Erreur au démarrage: ${err.message}`);
    setStatus(`Erreur au démarrage: ${err.message}`, 'error');
    renderAll();
  }
}

bootstrap();
