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
  landslideMaps: null,
  windLayerOpacity: 0.82,
  windMapMode: 'mean',
  selectedHazardComponents: {
    wind: true,
    rain: false,
    surge: false,
    landslide: false
  },
  adminVisuMaps: null,
  adminVisuMapsPromise: null,
  adminPopulationMaps: null,
  adminPopulationMapsPromise: null,
  adminVulnerabilityCurves: null,
  adminVulnerabilityCurvesPromise: null,
  adminHydroVulnerabilityCurves: {
    rain: null,
    surge: null,
    landslide: null
  },
  adminHydroVulnerabilityPromises: {
    rain: null,
    surge: null,
    landslide: null
  },
  adminHydroHazardComponent: 'rain',
  adminPopulationTerritory: 'glp',
  adminVisuOpacity: 0.5,
  caseStudyVisuHazard: 'storm',
  caseStudyVisuScenario: 'mean',
  caseStudyVisuPromise: null,
  caseStudyVulnerabilityExamplesPromise: null,
  adminVisuCards: [
    { basin: 'na', hazard: 'storm', scenario: 'mean' },
    { basin: 'na', hazard: 'storm_cmcc', scenario: 'mean' },
    { basin: 'na', hazard: 'storm', scenario: 'rp50' },
    { basin: 'na', hazard: 'storm_cmcc', scenario: 'rp100' }
  ],
  waterInfra: null,
  waterLayerVisibility: {},
  page1Analysis: null,
  completeAnalysis: null,
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
  impactMapScenario: 'event_max',
  impactTableScenario: 'annual',
  impactTableDisplayMode: 'money',
  conclusionDisplayMode: 'money',
  caseStudyPopulationVisible: false,
  caseStudyScenarioSocialSummary: null
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
  storm: {
    instance: null,
    hasFitted: false,
    legendControl: null,
    layersByComponent: {
      wind: null,
      rain: null,
      surge: null,
      landslide: null
    },
    paneNamesByComponent: {
      wind: 'hazard-cells-storm-wind',
      rain: 'hazard-cells-storm-rain',
      surge: 'hazard-cells-storm-surge',
      landslide: 'hazard-cells-storm-landslide'
    }
  },
  storm_cmcc: {
    instance: null,
    hasFitted: false,
    legendControl: null,
    layersByComponent: {
      wind: null,
      rain: null,
      surge: null,
      landslide: null
    },
    paneNamesByComponent: {
      wind: 'hazard-cells-cmcc-wind',
      rain: 'hazard-cells-cmcc-rain',
      surge: 'hazard-cells-cmcc-surge',
      landslide: 'hazard-cells-cmcc-landslide'
    }
  }
};

const adminVisuMapRef = {
  cards: [
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-1', legendControl: null },
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-2', legendControl: null },
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-3', legendControl: null },
    { instance: null, overlayLayer: null, overlayUrl: '', hasFitted: false, overlayPaneName: 'admin-visu-overlay-4', legendControl: null }
  ]
};

const caseStudyVisuMapRef = {
  instance: null,
  overlayLayer: null,
  overlayUrl: '',
  hasFitted: false,
  overlayPaneName: 'case-study-visu-overlay',
  legendControl: null
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
  hasFitted: false,
  overlayPaneName: 'case-study-pop-overlay',
  populationOverlayLayer: null,
  populationLegendControl: null,
  populationOverlayUrl: ''
};

const POPULATION_OVERLAY_VISUAL = Object.freeze({
  opacity: 0.95,
  filter: 'brightness(0.72) contrast(1.35)'
});

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
const RAIN_SCALE_STEP_MMPH = 25;
const SURGE_SCALE_STEP_M = 0.25;
const HAZARD_COMPONENT_ORDER = ['wind', 'rain', 'surge', 'landslide'];
const IMPACT_COMPONENT_ORDER = ['wind', 'rain', 'surge', 'landslide'];
const HAZARD_COMPONENT_LABEL = {
  wind: 'Vent',
  rain: 'Pluie',
  surge: 'Inond. cotiere',
  landslide: 'Mouv. terrain'
};
const HAZARD_COMPONENT_LONG_LABEL = {
  wind: 'Storm (vent)',
  rain: 'Pluie',
  surge: 'Inondations cotieres',
  landslide: 'Mouvements de terrain'
};
const HAZARD_COMPONENT_PALETTES = {
  wind: ['#d9f0a3', '#fee391', '#feb24c', '#fd8d3c', '#f46d43', '#e31a1c', '#b10026', '#800026', '#67000d'],
  rain: ['#edf8fb', '#ccece6', '#99d8c9', '#66c2a4', '#41ae76', '#238b45', '#006d2c', '#005824'],
  surge: ['#f7fcfd', '#d0eff2', '#a6dbe4', '#72c5d6', '#3eaac4', '#167f96', '#0a596e', '#04384a'],
  landslide: ['#f7efe8', '#e8c9ae', '#d39b6f', '#ac6940', '#734127']
};
const WIND_PALETTE = ['#d9f0a3', '#fee391', '#feb24c', '#fd8d3c', '#f46d43', '#e31a1c', '#b10026', '#800026', '#67000d'];
const ADMIN_VISU_LEGEND_COLORS = ['#30123b', '#4145ab', '#4685f9', '#39b6f7', '#1bd0d5', '#4be28a', '#a4ef63', '#f1e54e', '#f9b737', '#ed6925', '#c32503'];
const ADMIN_POP_DEFAULT_LEGEND_COLORS = ['#f2f2f2', '#d9d9d9', '#bdbdbd', '#969696', '#737373', '#525252', '#3a3a3a', '#1f1f1f', '#000000'];
const WIND_SPEED_MPS_TO_KMH = 3.6;
const WIND_SPEED_UNIT_DISPLAY = 'km/h';
const ADMIN_VISU_SCENARIO_LABEL = {
  mean: 'Moyenne annuelle',
  rp50: 'Temps de retour 50 ans',
  rp100: 'Temps de retour 100 ans',
  event_max: 'Evenement le plus fort',
};
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
  impact_overview_water: null,
  impact_overview_elec: null,
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
  hazardLayerControls: document.getElementById('hazard-layer-controls'),
  hazardLayerWind: document.getElementById('hazard-layer-wind'),
  hazardLayerRain: document.getElementById('hazard-layer-rain'),
  hazardLayerSurge: document.getElementById('hazard-layer-surge'),
  hazardLayerLandslide: document.getElementById('hazard-layer-landslide'),
  hazardCompareGrid: document.getElementById('hazard-compare-grid'),
  hazardChartYearCard: document.getElementById('hazard-chart-year-card'),
  hazardChartEventCard: document.getElementById('hazard-chart-event-card'),
  windMapTitleStorm: document.getElementById('wind-map-title-storm'),
  windMapTitleCmcc: document.getElementById('wind-map-title-cmcc'),
  adminVisuOpacitySlider: document.getElementById('admin-visu-opacity-slider'),
  adminVisuOpacityValue: document.getElementById('admin-visu-opacity-value'),
  adminVisuBasinSelects: [
    document.getElementById('admin-visu-basin-1'),
    document.getElementById('admin-visu-basin-2'),
    document.getElementById('admin-visu-basin-3'),
    document.getElementById('admin-visu-basin-4')
  ],
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
  caseStudyVulnerabilityGrid: document.getElementById('case-study-vulnerability-grid'),
  caseStudyVulnerabilityCaption: document.getElementById('case-study-vulnerability-caption'),
  caseStudyVisuMap: document.getElementById('case-study-visu-map'),
  caseStudyVisuHazardSelect: document.getElementById('case-study-visu-hazard-select'),
  caseStudyVisuScenarioSelect: document.getElementById('case-study-visu-scenario-select'),
  caseStudyVisuCaption: document.getElementById('case-study-visu-caption'),
  adminVisuCompareNaBody: document.getElementById('admin-visu-compare-na-body'),
  adminVisuCompareSiBody: document.getElementById('admin-visu-compare-si-body'),
  adminPopulationTerritorySelect: document.getElementById('admin-population-territory-select'),
  adminPopulationMap: document.getElementById('admin-population-map'),
  adminPopulationCaption: document.getElementById('admin-population-caption'),
  adminVulnerabilityGrid: document.getElementById('admin-vulnerability-grid'),
  adminVulnerabilityCaption: document.getElementById('admin-vulnerability-caption'),
  adminLandslideVulnerabilityGrid: document.getElementById('admin-landslide-vulnerability-grid'),
  adminLandslideVulnerabilityCaption: document.getElementById('admin-landslide-vulnerability-caption'),
  adminHydroHazardSelect: document.getElementById('admin-hydro-hazard-select'),
  adminHydroVulnerabilityGrid: document.getElementById('admin-hydro-vulnerability-grid'),
  adminHydroVulnerabilityCaption: document.getElementById('admin-hydro-vulnerability-caption'),
  hazardSummaryText: document.getElementById('hazard-summary-text'),
  waterInfraMap: document.getElementById('water-infra-map'),
  waterMapCaption: document.getElementById('water-map-caption'),
  waterMapTitle: document.getElementById('water-map-title'),
  waterPopulationToggle: document.getElementById('water-population-toggle'),
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
  hazardChartYearTitle: document.getElementById('hazard-chart-year-title'),
  hazardChartEventTitle: document.getElementById('hazard-chart-event-title'),
  page1ChartYearCompare: document.getElementById('page1-chart-year-compare'),
  page1ChartTrackCompare: document.getElementById('page1-chart-track-compare'),
  impactSummaryText: document.getElementById('impact-summary-text'),
  impactTableModeButtons: document.getElementById('impact-table-mode-buttons'),
  impactTableStormBody: document.getElementById('impact-table-storm-body'),
  impactTableCmccBody: document.getElementById('impact-table-cmcc-body'),
  impactSocialTableBody: document.getElementById('impact-social-table-body'),
  impactTableScenarioSelect: document.getElementById('impact-table-scenario-select'),
  impactTableTitle: document.getElementById('impact-table-title'),
  impactOverviewWaterChart: document.getElementById('impact-overview-water-chart'),
  impactOverviewElecChart: document.getElementById('impact-overview-elec-chart'),
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
  conclusionModeButtons: document.getElementById('conclusion-mode-buttons'),
  conclusionTableBody: document.getElementById('conclusion-table-body'),
  conclusionText: document.getElementById('conclusion-text'),
  methodValuationOfb: document.getElementById('method-valuation-ofb')
};

const numberFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const percentFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const moneyFmt = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const tableNumberFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const tablePercentFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const tablePercentDetailFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 3 });
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

function loadAdminPage5Panels() {
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
  Promise.all([
    ensureAdminVulnerabilityCurvesLoaded(),
    ensureAdminHydroVulnerabilityCurvesLoaded('rain'),
    ensureAdminHydroVulnerabilityCurvesLoaded('surge')
  ])
    .then(() => {
      renderAdminVulnerabilityOverviewCurves();
    })
    .catch((err) => {
      if (els.adminVulnerabilityCaption) {
        els.adminVulnerabilityCaption.textContent = `Courbes de vulnerabilite indisponibles: ${err.message}`;
      }
    });
  ensureAdminHydroVulnerabilityCurvesLoaded('landslide')
    .then(() => {
      renderAdminLandslideVulnerabilityCurves();
    })
    .catch((err) => {
      if (els.adminLandslideVulnerabilityCaption) {
        els.adminLandslideVulnerabilityCaption.textContent = `Courbes de mouvements de terrain indisponibles: ${err.message}`;
      }
    });
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
      if (caseStudyVisuMapRef.instance) caseStudyVisuMapRef.instance.invalidateSize();
      if (chartRefs.page1_year_compare) chartRefs.page1_year_compare.resize();
      if (chartRefs.page1_track_compare) chartRefs.page1_track_compare.resize();
      if (chartRefs.impact_overview_water) chartRefs.impact_overview_water.resize();
      if (chartRefs.impact_overview_elec) chartRefs.impact_overview_elec.resize();
      resizeAdminVulnerabilityOverviewCharts('page1_examples');
    }, 80);
  }
  if (pageKey === 'page5') {
    loadAdminPage5Panels();
    setTimeout(() => {
      adminVisuMapRef.cards.forEach((card) => {
        if (card?.instance) card.instance.invalidateSize();
      });
      if (adminPopulationMapRef.instance) adminPopulationMapRef.instance.invalidateSize();
      resizeAdminVulnerabilityOverviewCharts();
      resizeAdminVulnerabilityCharts('landslide');
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

function normalizeHazardComponent(raw) {
  const value = String(raw || '').trim().toLowerCase();
  if (value.includes('landslide') || value === 'ls') return 'landslide';
  if (value.includes('surge')) return 'surge';
  if (value === 'tr' || value.includes('rain')) return 'rain';
  if (value === 'rain') return 'rain';
  if (value === 'surge') return 'surge';
  return 'wind';
}

function isHazardComponentVisible(component) {
  const key = normalizeHazardComponent(component);
  return Boolean(state.selectedHazardComponents?.[key]);
}

function getSelectedHazardComponent() {
  const active = HAZARD_COMPONENT_ORDER.find((component) => isHazardComponentVisible(component));
  return active || 'wind';
}

function setSelectedHazardComponent(componentRaw) {
  const selected = normalizeHazardComponent(componentRaw);
  state.selectedHazardComponents = {
    wind: selected === 'wind',
    rain: selected === 'rain',
    surge: selected === 'surge',
    landslide: selected === 'landslide'
  };
  updateHazardLayerUi();
}

function currentVisibleHazardComponents() {
  return [getSelectedHazardComponent()];
}

function toFiniteNumberArray(values) {
  if (!Array.isArray(values)) return [];
  return values
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v));
}

function vulnerabilityIntensityToDisplayValue(valueRaw, unitRaw) {
  const value = Number(valueRaw);
  if (!Number.isFinite(value)) return Number.NaN;
  const unit = String(unitRaw || '').trim().toLowerCase();
  if (unit.includes('km/h') || unit.includes('kmh')) return value;
  if (unit.includes('m/s')) return windMpsToKmh(value);
  return value;
}

function vulnerabilityIntensityDisplayUnit(unitRaw) {
  const unit = String(unitRaw || '').trim().toLowerCase();
  if (unit.includes('km/h') || unit.includes('kmh') || unit.includes('m/s')) return WIND_SPEED_UNIT_DISPLAY;
  if (unit.includes('mm')) return 'mm proxy';
  if (unit === 'm') return 'm';
  if (unit === 'class' || unit === 'classe') return 'classe';
  return String(unitRaw || '').trim() || 'unite';
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
    haz_type: String(payload.haz_type || ''),
    hazard_component: normalizeHazardComponent(payload.hazard_component || payload.haz_type),
    intensity_unit: String(payload.intensity_unit || curves[0]?.intensity_unit || ''),
    explicitAssetTypeMapping: payload?.explicit_asset_type_mapping || {},
    defaultCurve: payload?.default_curve || null,
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
  if (Number.isFinite(parsed)) return numberFmt.format(parsed);
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

function dateValueTimestamp(value) {
  if (!value) return null;
  const d = new Date(value);
  const ts = d.getTime();
  return Number.isNaN(ts) ? null : ts;
}

function currentCaseStudyBadgeMeta() {
  const caseMeta = state.page1Analysis?.meta || null;
  const completeMeta = state.completeAnalysis?.meta || null;
  const caseUpdatedAt = caseMeta?.generated_at || null;
  const completeUpdatedAt = completeMeta?.updated_at || completeMeta?.generated_at || null;
  const caseTs = dateValueTimestamp(caseUpdatedAt);
  const completeTs = dateValueTimestamp(completeUpdatedAt);
  return {
    caseMeta,
    completeMeta,
    caseUpdatedAt,
    completeUpdatedAt,
    hasNewerCompleteAnalysis:
      Number.isFinite(completeTs) && (!Number.isFinite(caseTs) || completeTs > caseTs)
  };
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

function normalizeImpactTableDisplayMode(raw) {
  return String(raw || '').trim().toLowerCase() === 'percent' ? 'percent' : 'money';
}

function impactTableDisplayModeLabel(modeRaw) {
  const mode = normalizeImpactTableDisplayMode(modeRaw);
  return mode === 'percent' ? '% d\'infrastructure affectée' : 'Montant monétaire';
}

function updateImpactTableModeUi() {
  if (!els.impactTableModeButtons) return;
  const buttons = els.impactTableModeButtons.querySelectorAll('button[data-impact-table-mode]');
  buttons.forEach((button) => {
    const mode = normalizeImpactTableDisplayMode(button.getAttribute('data-impact-table-mode'));
    const active = mode === normalizeImpactTableDisplayMode(state.impactTableDisplayMode);
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function roundToNearestHalf(valueRaw) {
  const value = Number(valueRaw);
  if (!Number.isFinite(value)) return Number.NaN;
  return Math.round(value * 2) / 2;
}

function formatLegendBoundaryValue(valueRaw, componentRaw) {
  const component = normalizeHazardComponent(componentRaw);
  const value = component === 'wind' ? windMpsToKmh(valueRaw) : Number(valueRaw);
  if (!Number.isFinite(value)) return 'n/a';
  const rounded = roundToNearestHalf(value);
  if (!Number.isFinite(rounded)) return 'n/a';
  if (Math.abs(rounded - Math.round(rounded)) < 1e-9) {
    return numberFmt.format(Math.round(rounded));
  }
  return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(rounded);
}

function formatDamageDisplayValue(valueEur, exposureEur, modeRaw) {
  const mode = normalizeImpactTableDisplayMode(modeRaw);
  const value = Number(valueEur || 0);
  if (mode === 'percent') {
    const exposure = Number(exposureEur || 0);
    if (!(exposure > 0)) return 'n/a';
    return `${tablePercentDetailFmt.format((value / exposure) * 100.0)} %`;
  }
  return formatTableMoneyEUR(value);
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
  if (state.currentPage === 'page1' || state.currentPage === 'page2') {
    const badgeMeta = currentCaseStudyBadgeMeta();
    if (badgeMeta.caseMeta || badgeMeta.completeMeta) {
      const engine = badgeMeta.completeMeta?.engine || 'climada_with_interdependency_v1';
      if (badgeMeta.hasNewerCompleteAnalysis && badgeMeta.completeUpdatedAt) {
        const sourceParts = dedupeNonEmptyStrings([
          badgeMeta.completeMeta?.source,
          badgeMeta.caseMeta?.source
        ]);
        els.badgeSource.textContent = `Source: ${sourceParts.join(' + ') || "analyse complete + vue cas d'etude"}`;
        els.badgeUpdated.textContent =
          `Mis a jour impacts: ${formatDate(badgeMeta.completeUpdatedAt)} | ` +
          `Vue cas d'etude: ${formatDate(badgeMeta.caseUpdatedAt)}`;
        els.badgeEngine.textContent = `Moteur: ${engine}`;
        return;
      }
      if (badgeMeta.caseMeta) {
        els.badgeSource.textContent = `Source: ${badgeMeta.caseMeta.source || 'inconnue'}`;
        els.badgeUpdated.textContent = `Mis a jour: ${formatDate(badgeMeta.caseUpdatedAt)}`;
        els.badgeEngine.textContent = `Moteur: ${engine}`;
        return;
      }
      els.badgeSource.textContent = `Source: ${badgeMeta.completeMeta?.source || 'inconnue'}`;
      els.badgeUpdated.textContent = `Mis a jour: ${formatDate(badgeMeta.completeUpdatedAt)}`;
      els.badgeEngine.textContent = `Moteur: ${engine}`;
      return;
    }
  }
  const result = getActiveResult();
  if (!result) {
    els.badgeSource.textContent = 'Source: —';
    els.badgeUpdated.textContent = 'Mis a jour: —';
    els.badgeEngine.textContent = 'Moteur: —';
    return;
  }
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
  const territory = caseStudyTerritoryFromAnalysis(analysis, state.currentPage === 'page2' ? 'martinique' : 'guadeloupe');
  const territoryLabel = caseStudyTerritoryLabel(territory);
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
    els.hazardCompareTitle.textContent = `Comparaison aléas - zone ${territoryLabel}`;
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
  loadCaseStudyVulnerabilityExamples();
  loadCaseStudyVisuCard();
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
  const territory = caseStudyTerritoryLabel(caseStudyTerritoryFromAnalysis(analysis));

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

function finiteMetricValuesFromCells(cells, metricKey) {
  if (!Array.isArray(cells)) return [];
  return cells
    .map((cell) => Number(cell?.[metricKey]))
    .filter((value) => Number.isFinite(value));
}

function averageFinite(values) {
  if (!Array.isArray(values) || !values.length) return Number.NaN;
  const sum = values.reduce((acc, value) => acc + Number(value || 0), 0);
  return sum / values.length;
}

function buildHistogramFromValues(values, minRaw, maxRaw, binCount = 14) {
  const safeValues = Array.isArray(values) ? values.filter((value) => Number.isFinite(Number(value))).map((value) => Number(value)) : [];
  if (!safeValues.length) return null;
  const min = Number(minRaw);
  const max = Number(maxRaw);
  const finiteMin = Number.isFinite(min) ? min : Math.min(...safeValues);
  const finiteMax = Number.isFinite(max) ? max : Math.max(...safeValues);
  const span = Math.max(1e-9, finiteMax - finiteMin);
  const binsCount = Math.max(6, Math.min(28, Math.trunc(binCount) || 14));
  const step = span / binsCount;
  const counts = new Array(binsCount).fill(0);
  safeValues.forEach((value) => {
    const relative = (value - finiteMin) / span;
    const idx = Math.max(0, Math.min(binsCount - 1, Math.floor(relative * binsCount)));
    counts[idx] += 1;
  });
  const total = safeValues.length;
  return {
    bins: counts.map((_, idx) => finiteMin + ((idx + 0.5) * step)),
    percent: counts.map((count) => (count / total) * 100)
  };
}

function buildSharedHistogramPair(valuesStorm, valuesCmcc, binCount = 14) {
  const stormValues = Array.isArray(valuesStorm) ? valuesStorm : [];
  const cmccValues = Array.isArray(valuesCmcc) ? valuesCmcc : [];
  const all = [...stormValues, ...cmccValues].filter((value) => Number.isFinite(Number(value))).map((value) => Number(value));
  if (!all.length) {
    return { storm: null, storm_cmcc: null };
  }
  const min = Math.min(...all);
  const max = Math.max(...all);
  return {
    storm: buildHistogramFromValues(stormValues, min, max, binCount),
    storm_cmcc: buildHistogramFromValues(cmccValues, min, max, binCount)
  };
}

function caseStudyHazardMapsForComponent(componentRaw) {
  const component = normalizeHazardComponent(componentRaw);
  return component === 'landslide' ? state.landslideMaps : state.windMaps;
}

function selectedHazardChartConfig(componentRaw) {
  const component = normalizeHazardComponent(componentRaw);
  if (component === 'landslide') {
    return {
      component,
      yearTitle: 'Répartition des mailles par risque score des mouvements de terrain (climat actuel vs SSP585)',
      eventTitle: 'Comparaison non affichée pour les mouvements de terrain',
      xAxisLabel: 'Risque score des mailles',
      unitDisplay: '',
      yAxisName: 'Part des mailles (%)'
    };
  }
  if (component === 'rain') {
    return {
      component,
      yearTitle: 'Intensité pluie proxy par annee (STORM vs STORM_CMCC)',
      eventTitle: 'Intensité pluie proxy par evenement cyclonique (STORM vs STORM_CMCC)',
      xAxisLabel: 'Intensité pluie proxy',
      unitDisplay: 'mm/h',
      yAxisName: 'Part des mailles (%)'
    };
  }
  if (component === 'surge') {
    return {
      component,
      yearTitle: "Hauteur d'eau submersion côtière par annee (STORM vs STORM_CMCC)",
      eventTitle: "Hauteur d'eau submersion côtière par evenement cyclonique (STORM vs STORM_CMCC)",
      xAxisLabel: "Hauteur d'eau",
      unitDisplay: 'm',
      yAxisName: 'Part des mailles (%)'
    };
  }
  return {
    component: 'wind',
    yearTitle: 'Vitesse max du vent par annee (STORM vs STORM_CMCC)',
    eventTitle: 'Vitesse max du vent par evenement cyclonique (STORM vs STORM_CMCC)',
    xAxisLabel: 'Vitesse maximale du vent',
    unitDisplay: WIND_SPEED_UNIT_DISPLAY,
    yAxisName: 'Part des evenements (%)'
  };
}

function buildAdditionalHazardComparisonRows(componentRaw) {
  const component = normalizeHazardComponent(componentRaw);
  const maps = caseStudyHazardMapsForComponent(component);
  const storm = maps?.storm;
  const cmcc = maps?.storm_cmcc;
  if (!storm || !cmcc) return [];

  if (component === 'landslide') {
    const metric = hazardMetricConfig(component, 'mean');
    const stormValues = finiteMetricValuesFromCells(storm.cells, metric.valueKey);
    const cmccValues = finiteMetricValuesFromCells(cmcc.cells, metric.valueKey);
    if (!stormValues.length || !cmccValues.length) return [];
    const stormAvg = averageFinite(stormValues);
    const cmccAvg = averageFinite(cmccValues);
    if (!Number.isFinite(stormAvg) || !Number.isFinite(cmccAvg)) return [];
    return [{
      indicator: 'Mouvements de terrain - score moyen (risque score)',
      storm: stormAvg,
      storm_cmcc: cmccAvg,
      delta: cmccAvg - stormAvg
    }];
  }

  const scenarios = [
    { key: 'mean', label: 'Moyenne annuelle' },
    { key: 'rp50', label: 'Temps de retour 50 ans' },
    { key: 'rp100', label: 'Temps de retour 100 ans' },
    { key: 'event_max', label: 'Evenement le plus fort' }
  ];
  const componentLabel = component === 'wind'
    ? 'Vent'
    : (component === 'rain' ? 'Pluie proxy' : 'Inondation côtière');
  const unit = component === 'wind'
    ? 'm/s'
    : (component === 'rain' ? 'mm/h' : 'm');
  const rows = [];

  scenarios.forEach((scenario) => {
    const metric = component === 'wind'
      ? windMetricConfig(scenario.key)
      : hazardMetricConfig(component, scenario.key);
    const stormValues = finiteMetricValuesFromCells(storm.cells, metric.valueKey);
    const cmccValues = finiteMetricValuesFromCells(cmcc.cells, metric.valueKey);
    if (!stormValues.length || !cmccValues.length) return;
    const stormAvg = averageFinite(stormValues);
    const cmccAvg = averageFinite(cmccValues);
    if (!Number.isFinite(stormAvg) || !Number.isFinite(cmccAvg)) return;
    rows.push({
      indicator: `${componentLabel} - ${scenario.label} (${unit})`,
      storm: stormAvg,
      storm_cmcc: cmccAvg,
      delta: cmccAvg - stormAvg
    });
  });

  // Clarify that "evenement le plus fort" row is an average over cells.
  // Add explicit absolute max over cells for wind tables.
  if (component === 'wind') {
    const eventMetric = windMetricConfig('event_max');
    const stormEventValues = finiteMetricValuesFromCells(storm.cells, eventMetric.valueKey);
    const cmccEventValues = finiteMetricValuesFromCells(cmcc.cells, eventMetric.valueKey);
    if (stormEventValues.length && cmccEventValues.length) {
      const stormAbsMax = Math.max(...stormEventValues);
      const cmccAbsMax = Math.max(...cmccEventValues);
      if (Number.isFinite(stormAbsMax) && Number.isFinite(cmccAbsMax)) {
        rows.push({
          indicator: 'Vent - Maximum absolu (m/s)',
          storm: stormAbsMax,
          storm_cmcc: cmccAbsMax,
          delta: cmccAbsMax - stormAbsMax
        });
      }
    }
  }

  return rows;
}

function renderSelectedHazardComparisonCharts(analysis, componentRaw) {
  void analysis;
  const component = normalizeHazardComponent(componentRaw);
  const cfg = selectedHazardChartConfig(component);
  if (els.hazardChartYearTitle) els.hazardChartYearTitle.textContent = cfg.yearTitle;
  if (els.hazardChartEventTitle) els.hazardChartEventTitle.textContent = cfg.eventTitle;

  const maps = caseStudyHazardMapsForComponent(component);
  const storm = maps?.storm;
  const cmcc = maps?.storm_cmcc;
  if (els.hazardCompareGrid) {
    els.hazardCompareGrid.classList.toggle('landslide-mode', component === 'landslide');
  }
  if (els.hazardChartEventCard) {
    els.hazardChartEventCard.hidden = component === 'landslide';
  }
  if (els.hazardChartYearCard) {
    els.hazardChartYearCard.classList.toggle('full-span', component === 'landslide');
  }
  if (!storm || !cmcc) {
    if (component === 'landslide') {
      renderHistogramComparisonChart(
        'page1_year_compare',
        'page1-chart-year-compare',
        null,
        null,
        'Climat actuel',
        'SSP585',
        '#8C5A3C',
        '#D39B6F',
        cfg
      );
    } else {
      renderHistogramComparisonChart('page1_year_compare', 'page1-chart-year-compare', null, null, 'STORM', 'STORM_CMCC', '#0083CB', '#F39655', cfg);
      renderHistogramComparisonChart('page1_track_compare', 'page1-chart-track-compare', null, null, 'STORM', 'STORM_CMCC', '#00A6E2', '#A4A64B', cfg);
    }
    return;
  }

  if (component === 'landslide') {
    const metric = hazardMetricConfig(component, 'mean');
    const stormHist = buildHistogramFromValues(finiteMetricValuesFromCells(storm.cells, metric.valueKey), 0, 5, 5);
    const cmccHist = buildHistogramFromValues(finiteMetricValuesFromCells(cmcc.cells, metric.valueKey), 0, 5, 5);
    renderHistogramComparisonChart(
      'page1_year_compare',
      'page1-chart-year-compare',
      stormHist,
      cmccHist,
      'Climat actuel',
      'SSP585',
      '#8C5A3C',
      '#D39B6F',
      cfg
    );
    return;
  }

  const metricYear = component === 'wind' ? windMetricConfig('mean') : hazardMetricConfig(component, 'mean');
  const metricEvent = component === 'wind' ? windMetricConfig('event_max') : hazardMetricConfig(component, 'event_max');
  const yearHist = buildSharedHistogramPair(
    finiteMetricValuesFromCells(storm.cells, metricYear.valueKey),
    finiteMetricValuesFromCells(cmcc.cells, metricYear.valueKey),
    14
  );
  const eventHist = buildSharedHistogramPair(
    finiteMetricValuesFromCells(storm.cells, metricEvent.valueKey),
    finiteMetricValuesFromCells(cmcc.cells, metricEvent.valueKey),
    14
  );

  renderHistogramComparisonChart(
    'page1_year_compare',
    'page1-chart-year-compare',
    yearHist.storm,
    yearHist.storm_cmcc,
    'STORM',
    'STORM_CMCC',
    '#0083CB',
    '#F39655',
    cfg
  );
  renderHistogramComparisonChart(
    'page1_track_compare',
    'page1-chart-track-compare',
    eventHist.storm,
    eventHist.storm_cmcc,
    'STORM',
    'STORM_CMCC',
    '#00A6E2',
    '#A4A64B',
    cfg
  );
}

function renderPage1Hazard(analysis) {
  const hazard = analysis?.hazard || {};
  if (els.hazardSummaryText) {
    const territory = caseStudyTerritoryLabel(caseStudyTerritoryFromAnalysis(analysis));
    const summaryParts = [escapeHtml(String(hazard.summary_text || '')).replaceAll('\n', '<br />')];
    const landslideMaps = state.landslideMaps;
    const landslideStormMean = Number(landslideMaps?.storm?.mean_landslide_score_mean);
    const landslideCmccMean = Number(landslideMaps?.storm_cmcc?.mean_landslide_score_mean);
    if (Number.isFinite(landslideStormMean) && Number.isFinite(landslideCmccMean)) {
      summaryParts.push(
        `Les mouvements de terrain sont affichés comme un <strong>modèle probabiliste</strong> sans unité. Sur la ${territory}, le score moyen des mailles est de ${escapeHtml(numberFmt.format(landslideStormMean))} pour le climat actuel et de ${escapeHtml(numberFmt.format(landslideCmccMean))} pour SSP585.`
      );
      summaryParts.push(
        'Dans les cartes NGI, 0 et 1 correspondent à une probabilité nulle de mouvement de terrain, tandis que 2, 3, 4 et 5 indiquent une probabilité croissante.'
      );
    }
    els.hazardSummaryText.innerHTML = summaryParts.join('<br /><br />');
  }

  if (els.hazardGuadeloupeCompareBody) {
    const windRows = buildAdditionalHazardComparisonRows('wind');
    const rainRows = buildAdditionalHazardComparisonRows('rain');
    const surgeRows = buildAdditionalHazardComparisonRows('surge');
    const landslideRows = buildAdditionalHazardComparisonRows('landslide');
    const rows = [...windRows, ...rainRows, ...surgeRows, ...landslideRows];
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

  renderSelectedHazardComparisonCharts(analysis, getSelectedHazardComponent());
}

function impactComponentOrder(impactPayload) {
  const raw = Array.isArray(impactPayload?.component_order) ? impactPayload.component_order : IMPACT_COMPONENT_ORDER;
  const normalized = raw.map((component) => normalizeHazardComponent(component));
  const ordered = IMPACT_COMPONENT_ORDER.filter((component) => normalized.includes(component));
  return ordered.length ? ordered : [...IMPACT_COMPONENT_ORDER];
}

function normalizeDamageComponentMap(mapRaw, totalFallback = 0) {
  const out = {
    wind: 0,
    rain: 0,
    surge: 0,
    landslide: 0
  };
  let hasExplicitValue = false;
  if (mapRaw && typeof mapRaw === 'object') {
    IMPACT_COMPONENT_ORDER.forEach((component) => {
      const value = Number(mapRaw?.[component]);
      if (Number.isFinite(value)) {
        out[component] = value;
        hasExplicitValue = true;
      }
    });
  }
  if (!hasExplicitValue) {
    const total = Number(totalFallback || 0);
    out.wind = Number.isFinite(total) ? total : 0;
  }
  return out;
}

function scaleDamageComponentMap(mapRaw, factorRaw, totalFallback = 0) {
  const factor = Number.isFinite(Number(factorRaw)) ? Number(factorRaw) : 1;
  const base = normalizeDamageComponentMap(mapRaw, totalFallback);
  const scaled = {};
  IMPACT_COMPONENT_ORDER.forEach((component) => {
    scaled[component] = Number(base[component] || 0) * factor;
  });
  return scaled;
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
        storm: {
          ...storm,
          exposure_eur: Number(storm.exposure_eur || 0),
          damage_eur: Number(storm.damage_eur || 0) * stormFactor,
          direct_damage_eur: Number(storm.direct_damage_eur ?? storm.damage_eur ?? 0) * stormFactor,
          indirect_damage_eur: Number(storm.indirect_damage_eur || 0) * stormFactor,
          damage_components_eur: scaleDamageComponentMap(storm.damage_components_eur, stormFactor, storm.damage_eur)
        },
        storm_cmcc: {
          ...cmcc,
          exposure_eur: Number(cmcc.exposure_eur || 0),
          damage_eur: Number(cmcc.damage_eur || 0) * cmccFactor,
          direct_damage_eur: Number(cmcc.direct_damage_eur ?? cmcc.damage_eur ?? 0) * cmccFactor,
          indirect_damage_eur: Number(cmcc.indirect_damage_eur || 0) * cmccFactor,
          damage_components_eur: scaleDamageComponentMap(cmcc.damage_components_eur, cmccFactor, cmcc.damage_eur)
        },
      };
    });

  const byScenario = impact?.damage_breakdown_by_scenario || {};
  let rp50Breakdown = byScenario?.rp50;
  if (!rp50Breakdown && byScenario?.rp100) {
    const rp100Breakdown = byScenario.rp100 || {};
    const stormRows = Array.isArray(rp100Breakdown.storm) ? rp100Breakdown.storm : [];
    const cmccRows = Array.isArray(rp100Breakdown.storm_cmcc) ? rp100Breakdown.storm_cmcc : [];
    rp50Breakdown = {
      storm: stormRows.map((row) => ({
        ...row,
        exposure_eur: Number(row?.exposure_eur || 0),
        damage_eur: Number(row?.damage_eur || 0) * stormFactor,
        direct_damage_eur: Number(row?.direct_damage_eur ?? row?.damage_eur ?? 0) * stormFactor,
        indirect_damage_eur: Number(row?.indirect_damage_eur || 0) * stormFactor,
        damage_components_eur: scaleDamageComponentMap(row?.damage_components_eur, stormFactor, row?.damage_eur)
      })),
      storm_cmcc: cmccRows.map((row) => ({
        ...row,
        exposure_eur: Number(row?.exposure_eur || 0),
        damage_eur: Number(row?.damage_eur || 0) * cmccFactor,
        direct_damage_eur: Number(row?.direct_damage_eur ?? row?.damage_eur ?? 0) * cmccFactor,
        indirect_damage_eur: Number(row?.indirect_damage_eur || 0) * cmccFactor,
        damage_components_eur: scaleDamageComponentMap(row?.damage_components_eur, cmccFactor, row?.damage_eur)
      })),
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

function normalizeImpactTableScenario(raw) {
  const value = String(raw || '').trim().toLowerCase();
  if (value === 'rp50') return 'rp50';
  if (value === 'rp100') return 'rp100';
  if (value === 'event_max') return 'event_max';
  return 'annual';
}

function impactTableScenarioMeta(scenarioRaw) {
  const scenario = normalizeImpactTableScenario(scenarioRaw);
  if (scenario === 'rp50') {
    return { key: 'rp50', title: 'Tableau des impacts causes par les evenements a temps de retour 50 ans' };
  }
  if (scenario === 'rp100') {
    return { key: 'rp100', title: 'Tableau des impacts causes par les evenements a temps de retour 100 ans' };
  }
  if (scenario === 'event_max') {
    return { key: 'event_max', title: "Tableau des impacts causes par l'evenement le plus fort" };
  }
  return { key: 'annual', title: 'Tableau des impacts annuels (moyenne)' };
}

function renderPage1Impact(analysis) {
  const impact = withRp50ImpactScenario(analysis?.impact || {});
  const componentOrder = impactComponentOrder(impact);
  const tables = impact.state_damage_tables || {};
  const scenarioMeta = impactTableScenarioMeta(state.impactTableScenario);
  state.impactTableScenario = scenarioMeta.key;
  const rows = Array.isArray(tables[scenarioMeta.key]) ? tables[scenarioMeta.key] : [];
  renderImpactScenarioTables(rows, analysis?.exposition?.total_value_by_type_eur || {}, componentOrder);
  renderSocialImpactTable(analysis);
  if (els.impactTableTitle) {
    els.impactTableTitle.textContent = scenarioMeta.title;
  }
  if (els.impactTableScenarioSelect) {
    els.impactTableScenarioSelect.value = scenarioMeta.key;
  }
  updateImpactTableModeUi();

  renderImpactBreakdownCharts(impact);
}

function normalizeConclusionDisplayMode(raw) {
  return String(raw || '').trim().toLowerCase() === 'percent' ? 'percent' : 'money';
}

function updateConclusionModeUi() {
  if (!els.conclusionModeButtons) return;
  const activeMode = normalizeConclusionDisplayMode(state.conclusionDisplayMode);
  Array.from(els.conclusionModeButtons.querySelectorAll('button[data-conclusion-mode]')).forEach((button) => {
    const mode = normalizeConclusionDisplayMode(button.getAttribute('data-conclusion-mode'));
    const active = mode === activeMode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function territoryPopulationByCell(analysis) {
  const rows = Array.isArray(state.completeAnalysis?.territory_results)
    ? state.completeAnalysis.territory_results
    : (Array.isArray(analysis?.impact?.territory_results) ? analysis.impact.territory_results : []);
  return rows.reduce((acc, row) => {
    const territoryId = String(row?.territory_id || '').trim();
    if (territoryId) acc[territoryId] = Number(row?.population_total || 0);
    return acc;
  }, {});
}

function annualSocialSummaryFromCompleteAnalysis() {
  const summary = state.completeAnalysis?.portfolio_results?.social_impact_summary;
  if (!summary || typeof summary !== 'object') return null;
  const normalize = (metricsRaw) => {
    const metrics = metricsRaw && typeof metricsRaw === 'object' ? metricsRaw : {};
    return {
      total_population_affected_any_network: Number(metrics.total_population_affected_any_network || 0),
      total_without_elec: Number(metrics.total_without_elec || 0),
      total_without_water_aep: Number(metrics.total_without_water_aep || 0),
      total_without_water_eu: Number(metrics.total_without_water_eu || 0),
      total_without_water:
        Number(metrics.total_without_water_aep || 0) + Number(metrics.total_without_water_eu || 0),
      total_with_degraded_elec: Number(metrics.total_with_degraded_elec || 0),
      total_with_degraded_water_aep: Number(metrics.total_with_degraded_water_aep || 0),
      total_with_degraded_water_eu: Number(metrics.total_with_degraded_water_eu || 0)
    };
  };
  return {
    storm: normalize(summary.storm),
    storm_cmcc: normalize(summary.storm_cmcc)
  };
}

function featureRepresentativePoint(feature) {
  const geometry = feature?.geometry || {};
  const coordinates = geometry?.coordinates;
  if (!Array.isArray(coordinates)) return null;

  const points = [];
  const walk = (node) => {
    if (!Array.isArray(node)) return;
    if (node.length >= 2 && typeof node[0] === 'number' && typeof node[1] === 'number') {
      points.push([Number(node[0]), Number(node[1])]);
      return;
    }
    node.forEach((child) => walk(child));
  };
  walk(coordinates);
  if (!points.length) return null;
  const totals = points.reduce((acc, point) => ({ lon: acc.lon + point[0], lat: acc.lat + point[1] }), { lon: 0, lat: 0 });
  return {
    lon: totals.lon / points.length,
    lat: totals.lat / points.length,
  };
}

function territoryCellIdFromLatLon(latRaw, lonRaw) {
  const lat = Number(latRaw);
  const lon = Number(lonRaw);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const latBin = Math.round(lat / 0.2) * 0.2;
  const lonBin = Math.round(lon / 0.2) * 0.2;
  const latTxt = `${latBin >= 0 ? '+' : ''}${latBin.toFixed(2)}`;
  const lonTxt = `${lonBin >= 0 ? '+' : ''}${lonBin.toFixed(2)}`;
  return `cell-${latTxt}_${lonTxt}`;
}

function serviceKeyFromLayerKey(layerKeyRaw) {
  const layerKey = String(layerKeyRaw || '').trim().toLowerCase();
  if (layerKey.startsWith('elec_')) return 'elec';
  if (layerKey === 'eau_aep') return 'water_aep';
  if (layerKey === 'eau_eu') return 'water_eu';
  return null;
}

function stateSeverity(stateRaw) {
  const stateCode = String(stateRaw || 'S0').toUpperCase();
  if (stateCode === 'S3') return 3;
  if (stateCode === 'S2') return 2;
  if (stateCode === 'S1') return 1;
  return 0;
}

function aggregateScenarioSocialSummary(analysis, networkStates) {
  const populationByCell = territoryPopulationByCell(analysis);
  const features = Array.isArray(networkStates?.features) ? networkStates.features : [];
  const scenarios = ['annual', 'rp50', 'rp100', 'event_max'];
  const hazards = ['storm', 'storm_cmcc'];
  const worstStates = {};

  scenarios.forEach((scenario) => {
    worstStates[scenario] = {};
    hazards.forEach((hazard) => {
      worstStates[scenario][hazard] = {};
    });
  });

  features.forEach((feature) => {
    const serviceKey = serviceKeyFromLayerKey(feature?.properties?.layer_key);
    if (!serviceKey) return;
    const point = featureRepresentativePoint(feature);
    if (!point) return;
    const cellId = territoryCellIdFromLatLon(point.lat, point.lon);
    if (!cellId || populationByCell[cellId] === undefined) return;

    scenarios.forEach((scenario) => {
      hazards.forEach((hazard) => {
        const stateCode = String(feature?.properties?.[`state_${scenario}_${hazard}`] || 'S0').toUpperCase();
        if (!worstStates[scenario][hazard][cellId]) {
          worstStates[scenario][hazard][cellId] = { elec: 'S0', water_aep: 'S0', water_eu: 'S0' };
        }
        const current = String(worstStates[scenario][hazard][cellId][serviceKey] || 'S0').toUpperCase();
        if (stateSeverity(stateCode) > stateSeverity(current)) {
          worstStates[scenario][hazard][cellId][serviceKey] = stateCode;
        }
      });
    });
  });

  const summary = {};
  scenarios.forEach((scenario) => {
    summary[scenario] = {};
    hazards.forEach((hazard) => {
      const totals = {
        total_population_affected_any_network: 0,
        total_without_elec: 0,
        total_without_water_aep: 0,
        total_without_water_eu: 0,
        total_without_water: 0,
        total_with_degraded_elec: 0,
        total_with_degraded_water_aep: 0,
        total_with_degraded_water_eu: 0
      };
      Object.entries(populationByCell).forEach(([cellId, populationRaw]) => {
        const population = Number(populationRaw || 0);
        if (population <= 0) return;
        const states = worstStates[scenario][hazard][cellId] || { elec: 'S0', water_aep: 'S0', water_eu: 'S0' };
        const elec = String(states.elec || 'S0').toUpperCase();
        const waterAep = String(states.water_aep || 'S0').toUpperCase();
        const waterEu = String(states.water_eu || 'S0').toUpperCase();
        if (elec !== 'S0' || waterAep !== 'S0' || waterEu !== 'S0') totals.total_population_affected_any_network += population;
        if (elec === 'S3') totals.total_without_elec += population;
        if (waterAep === 'S3') totals.total_without_water_aep += population;
        if (waterEu === 'S3') totals.total_without_water_eu += population;
        if (elec === 'S1' || elec === 'S2') totals.total_with_degraded_elec += population;
        if (waterAep === 'S1' || waterAep === 'S2') totals.total_with_degraded_water_aep += population;
        if (waterEu === 'S1' || waterEu === 'S2') totals.total_with_degraded_water_eu += population;
      });
      totals.total_without_water = totals.total_without_water_aep + totals.total_without_water_eu;
      summary[scenario][hazard] = totals;
    });
  });
  return summary;
}

function ensureScenarioSocialSummary(analysis) {
  if (state.caseStudyScenarioSocialSummary) return state.caseStudyScenarioSocialSummary;
  const socialSummary = aggregateScenarioSocialSummary(analysis, state.networkStates);
  const annualSummary = annualSocialSummaryFromCompleteAnalysis();
  if (annualSummary) {
    socialSummary.annual = annualSummary;
  }
  state.caseStudyScenarioSocialSummary = socialSummary;
  return state.caseStudyScenarioSocialSummary;
}

function formatConclusionLossValue(valueRaw, totalValueRaw, modeRaw) {
  const value = Number(valueRaw || 0);
  const totalValue = Number(totalValueRaw || 0);
  if (normalizeConclusionDisplayMode(modeRaw) === 'percent') {
    const pct = totalValue > 0 ? (value / totalValue) * 100 : 0;
    return `${percentFmt.format(pct)} %`;
  }
  return formatTableMoneyEUR(value);
}

function renderImpactScenarioTables(rows, exposureByClass = {}, componentOrder = IMPACT_COMPONENT_ORDER) {
  renderImpactScenarioTableForHazard(els.impactTableStormBody, rows, 'storm', exposureByClass, componentOrder);
  renderImpactScenarioTableForHazard(els.impactTableCmccBody, rows, 'storm_cmcc', exposureByClass, componentOrder);
}

function renderImpactScenarioTableForHazard(targetBody, rows, hazardKeyRaw, exposureByClass = {}, componentOrder = IMPACT_COMPONENT_ORDER) {
  if (!targetBody) return;
  const hazardKey = String(hazardKeyRaw || '').trim().toLowerCase() === 'storm_cmcc' ? 'storm_cmcc' : 'storm';
  if (!rows.length) {
    targetBody.innerHTML = `<tr><td colspan="${5 + componentOrder.length}">Aucune donnee d'impact disponible.</td></tr>`;
    return;
  }
  const displayMode = normalizeImpactTableDisplayMode(state.impactTableDisplayMode);
  targetBody.innerHTML = rows.map((row) => {
    const hazardRow = hazardKey === 'storm_cmcc' ? (row.storm_cmcc || {}) : (row.storm || {});
    const components = normalizeDamageComponentMap(hazardRow.damage_components_eur, hazardRow.damage_eur);
    const rowLabel = NETWORK_LAYER_LABEL[String(row.class_key || '')] || row.class_label || row.class_key || 'Reseau';
    const exposureEur = Number(hazardRow.exposure_eur ?? exposureByClass?.[row.class_key] ?? 0);
    const directDamage = Number.isFinite(Number(hazardRow.direct_damage_eur))
      ? Number(hazardRow.direct_damage_eur)
      : Number(hazardRow.damage_eur || 0);
    const indirectDamage = Number.isFinite(Number(hazardRow.indirect_damage_eur))
      ? Number(hazardRow.indirect_damage_eur)
      : Math.max(0, Number(hazardRow.damage_eur || 0) - directDamage);
    const componentCells = componentOrder.map((component) => `
      <td class="num">${escapeHtml(formatDamageDisplayValue(components[component] || 0, exposureEur, displayMode))}</td>
    `).join('');
    return `
      <tr>
        <td>${escapeHtml(String(rowLabel))}</td>
        <td class="num">${escapeHtml(formatStateTuple(hazardRow.state_pct))}</td>
        ${componentCells}
        <td class="num">${escapeHtml(formatDamageDisplayValue(directDamage, exposureEur, displayMode))}</td>
        <td class="num">${escapeHtml(formatDamageDisplayValue(indirectDamage, exposureEur, displayMode))}</td>
        <td class="num">${escapeHtml(formatDamageDisplayValue(hazardRow.damage_eur || 0, exposureEur, displayMode))}</td>
      </tr>
    `;
  }).join('');
}

function renderSocialImpactTable(analysis) {
  if (!els.impactSocialTableBody) return;
  const socialSummary = ensureScenarioSocialSummary(analysis).annual || {};
  const stormMetrics = socialSummary.storm || {};
  const cmccMetrics = socialSummary.storm_cmcc || {};
  
  const metrics = [
    { label: 'Population totale affectée (S1/S2/S3)', key: 'total_population_affected_any_network' },
    { label: 'Population sans électricité (S3)', key: 'total_without_elec' },
    { label: 'Population sans eau potable AEP (S3)', key: 'total_without_water_aep' },
    { label: 'Population sans eau EU (S3)', key: 'total_without_water_eu' },
    { label: 'Population électricité dégradée (S1/S2)', key: 'total_with_degraded_elec' },
    { label: 'Population eau potable dégradée (S1/S2)', key: 'total_with_degraded_water_aep' },
    { label: 'Population eau EU dégradée (S1/S2)', key: 'total_with_degraded_water_eu' }
  ];
  
  if (!Object.keys(stormMetrics).length) {
    els.impactSocialTableBody.innerHTML = '<tr><td colspan="4">Aucune donnée d\'impact sociodémographique disponible.</td></tr>';
    return;
  }
  
  els.impactSocialTableBody.innerHTML = metrics.map((metric) => {
    const stormVal = Number(stormMetrics[metric.key] || 0);
    const cmccVal = Number(cmccMetrics[metric.key] || 0);
    const deltaVal = cmccVal - stormVal;
    
    return `
      <tr>
        <td>${escapeHtml(metric.label)}</td>
        <td class="num">${escapeHtml(numberFmt.format(Math.round(stormVal)))}</td>
        <td class="num">${escapeHtml(numberFmt.format(Math.round(cmccVal)))}</td>
        <td class="num">${escapeHtml(Math.abs(deltaVal) < 1 ? '0' : ((deltaVal > 0 ? '+' : '') + numberFmt.format(Math.round(deltaVal))))}</td>
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
  const socialSummaryByScenario = ensureScenarioSocialSummary(analysis);
  const rows = [
    { label: 'Moyenne annuelle', key: 'annual', stormLoss: Number(storm.eai_total_eur || 0), cmccLoss: Number(cmcc.eai_total_eur || 0) },
    { label: 'Temps de retour 50 ans', key: 'rp50', stormLoss: Number(storm.rp50_total_loss_eur || 0), cmccLoss: Number(cmcc.rp50_total_loss_eur || 0) },
    { label: 'Temps de retour 100 ans', key: 'rp100', stormLoss: Number(storm.rp100_total_loss_eur || 0), cmccLoss: Number(cmcc.rp100_total_loss_eur || 0) },
    { label: 'Evenement le plus fort', key: 'event_max', stormLoss: Number(storm.event_max_total_loss_eur || 0), cmccLoss: Number(cmcc.event_max_total_loss_eur || 0) }
  ];

  if (els.conclusionTableBody) {
    els.conclusionTableBody.innerHTML = rows.map((row) => {
      const social = socialSummaryByScenario[row.key] || {};
      const stormSocial = social.storm || {};
      const cmccSocial = social.storm_cmcc || {};
      return `
        <tr>
          <td>${escapeHtml(row.label)}</td>
          <td class="num">${escapeHtml(formatConclusionLossValue(row.stormLoss, totalValue, state.conclusionDisplayMode))}</td>
          <td class="num">${escapeHtml(formatConclusionLossValue(row.cmccLoss, totalValue, state.conclusionDisplayMode))}</td>
          <td class="num">${escapeHtml(formatConclusionLossValue(row.cmccLoss - row.stormLoss, totalValue, state.conclusionDisplayMode))}</td>
          <td class="num">${escapeHtml(numberFmt.format(Math.round(Number(stormSocial.total_without_elec || 0))))}</td>
          <td class="num">${escapeHtml(numberFmt.format(Math.round(Number(cmccSocial.total_without_elec || 0))))}</td>
          <td class="num">${escapeHtml(numberFmt.format(Math.round(Number(stormSocial.total_without_water || 0))))}</td>
          <td class="num">${escapeHtml(numberFmt.format(Math.round(Number(cmccSocial.total_without_water || 0))))}</td>
        </tr>
      `;
    }).join('');
  }

  els.conclusionText.textContent = `Valeur totale du portefeuille d'infrastructures: ${numberFmt.format(Math.round(totalValue / 1_000_000))} M€. Le tableau compare les pertes STORM et STORM_CMCC pour chaque scénario, avec le nombre total de personnes sans électricité et sans eau.`;
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
  if (value === 'event_max') return 'event_max';
  return 'mean';
}

function currentWindMapMode() {
  return normalizeWindMapMode(state.windMapMode);
}

function updateWindModeUi() {
  if (!els.windMapMode) return;
  els.windMapMode.value = currentWindMapMode();
}

function hazardScenarioLabel(modeRaw) {
  const mode = normalizeWindMapMode(modeRaw);
  if (mode === 'rp50') {
    return 'temps de retour 50 ans';
  }
  if (mode === 'rp100') {
    return 'temps de retour 100 ans';
  }
  if (mode === 'event_max') {
    return 'evenement le plus fort';
  }
  return 'moyenne annuelle';
}

function hazardMetricConfig(componentRaw, modeRaw) {
  const component = normalizeHazardComponent(componentRaw);
  const mode = normalizeWindMapMode(modeRaw);

  if (component === 'landslide') {
    return {
      component,
      mode: 'mean',
      valueKey: 'mean_landslide_score',
      minKey: 'mean_landslide_score_min',
      maxKey: 'mean_landslide_score_max',
      legendTitle: 'Probabilités de mouvements de terrain',
      captionLabel: 'probabilités de mouvements de terrain',
      mapLabel: 'risque score',
      tooltipLabel: 'Risque score',
      unitDisplay: 'risque score',
      scaleStep: 1,
      estimateFrom: null
    };
  }

  if (component === 'rain') {
    if (mode === 'rp50') {
      return {
        component,
        mode,
        valueKey: 'rp50_rain_mmph',
        minKey: 'rp50_rain_min_mmph',
        maxKey: 'rp50_rain_max_mmph',
        legendTitle: 'Pluie proxy (retour 50 ans)',
        captionLabel: 'pluie proxy (temps de retour 50 ans)',
        mapLabel: 'temps de retour 50 ans',
        tooltipLabel: 'Pluie proxy (retour 50 ans)',
        unitDisplay: 'mm/h proxy',
        scaleStep: RAIN_SCALE_STEP_MMPH,
        estimateFrom: null
      };
    }
    if (mode === 'rp100') {
      return {
        component,
        mode,
        valueKey: 'rp100_rain_mmph',
        minKey: 'rp100_rain_min_mmph',
        maxKey: 'rp100_rain_max_mmph',
        legendTitle: 'Pluie proxy (retour 100 ans)',
        captionLabel: 'pluie proxy (temps de retour 100 ans)',
        mapLabel: 'temps de retour 100 ans',
        tooltipLabel: 'Pluie proxy (retour 100 ans)',
        unitDisplay: 'mm/h proxy',
        scaleStep: RAIN_SCALE_STEP_MMPH,
        estimateFrom: null
      };
    }
    if (mode === 'event_max') {
      return {
        component,
        mode,
        valueKey: 'event_max_rain_mmph',
        minKey: 'event_max_rain_min_mmph',
        maxKey: 'event_max_rain_max_mmph',
        legendTitle: 'Pluie proxy (evenement le plus fort)',
        captionLabel: 'pluie proxy (evenement le plus fort)',
        mapLabel: 'evenement le plus fort',
        tooltipLabel: 'Pluie proxy (evenement le plus fort)',
        unitDisplay: 'mm/h proxy',
        scaleStep: RAIN_SCALE_STEP_MMPH,
        estimateFrom: null
      };
    }
    return {
      component,
      mode: 'mean',
      valueKey: 'mean_rain_mmph',
      minKey: 'mean_rain_min_mmph',
      maxKey: 'mean_rain_max_mmph',
      legendTitle: 'Pluie proxy moyenne',
      captionLabel: 'pluie proxy moyenne',
      mapLabel: 'moyenne annuelle',
      tooltipLabel: 'Pluie proxy moyenne',
      unitDisplay: 'mm/h proxy',
      scaleStep: RAIN_SCALE_STEP_MMPH,
      estimateFrom: null
    };
  }

  if (component === 'surge') {
    if (mode === 'rp50') {
      return {
        component,
        mode,
        valueKey: 'rp50_surge_m',
        minKey: 'rp50_surge_min_m',
        maxKey: 'rp50_surge_max_m',
        legendTitle: 'Inondation cotiere (retour 50 ans)',
        captionLabel: 'inondation cotiere (temps de retour 50 ans)',
        mapLabel: 'temps de retour 50 ans',
        tooltipLabel: 'Inondation cotiere (retour 50 ans)',
        unitDisplay: 'm',
        scaleStep: SURGE_SCALE_STEP_M,
        estimateFrom: null
      };
    }
    if (mode === 'rp100') {
      return {
        component,
        mode,
        valueKey: 'rp100_surge_m',
        minKey: 'rp100_surge_min_m',
        maxKey: 'rp100_surge_max_m',
        legendTitle: 'Inondation cotiere (retour 100 ans)',
        captionLabel: 'inondation cotiere (temps de retour 100 ans)',
        mapLabel: 'temps de retour 100 ans',
        tooltipLabel: 'Inondation cotiere (retour 100 ans)',
        unitDisplay: 'm',
        scaleStep: SURGE_SCALE_STEP_M,
        estimateFrom: null
      };
    }
    if (mode === 'event_max') {
      return {
        component,
        mode,
        valueKey: 'event_max_surge_m',
        minKey: 'event_max_surge_min_m',
        maxKey: 'event_max_surge_max_m',
        legendTitle: 'Inondation cotiere (evenement le plus fort)',
        captionLabel: 'inondation cotiere (evenement le plus fort)',
        mapLabel: 'evenement le plus fort',
        tooltipLabel: 'Inondation cotiere (evenement le plus fort)',
        unitDisplay: 'm',
        scaleStep: SURGE_SCALE_STEP_M,
        estimateFrom: null
      };
    }
    return {
      component,
      mode: 'mean',
      valueKey: 'mean_surge_m',
      minKey: 'mean_surge_min_m',
      maxKey: 'mean_surge_max_m',
      legendTitle: 'Inondation cotiere moyenne',
      captionLabel: 'inondation cotiere moyenne',
      mapLabel: 'moyenne annuelle',
      tooltipLabel: 'Inondation cotiere moyenne',
      unitDisplay: 'm',
      scaleStep: SURGE_SCALE_STEP_M,
      estimateFrom: null
    };
  }
  return {
    component: 'wind',
    mode: 'mean',
    valueKey: 'mean_wind_mps',
    minKey: 'mean_wind_min_mps',
    maxKey: 'mean_wind_max_mps',
    legendTitle: 'Vents moyens',
    captionLabel: 'vitesse moyenne du vent',
    mapLabel: 'vents moyens',
    tooltipLabel: 'Vents moyens',
    unitDisplay: WIND_SPEED_UNIT_DISPLAY,
    scaleStep: WIND_SCALE_STEP_MPS,
    estimateFrom: null
  };
}

function windMetricConfig(modeRaw) {
  const mode = normalizeWindMapMode(modeRaw);
  if (mode === 'rp50') {
    return {
      component: 'wind',
      mode,
      valueKey: 'rp50_wind_mps',
      minKey: 'rp50_wind_min_mps',
      maxKey: 'rp50_wind_max_mps',
      legendTitle: 'Vents (retour 50 ans)',
      captionLabel: 'vitesse du vent (temps de retour 50 ans)',
      mapLabel: 'temps de retour 50 ans',
      tooltipLabel: 'Vents (retour 50 ans)',
      unitDisplay: WIND_SPEED_UNIT_DISPLAY,
      scaleStep: WIND_SCALE_STEP_MPS,
      estimateFrom: null
    };
  }
  if (mode === 'rp100') {
    return {
      component: 'wind',
      mode,
      valueKey: 'rp100_wind_mps',
      minKey: 'rp100_wind_min_mps',
      maxKey: 'rp100_wind_max_mps',
      legendTitle: 'Vents (retour 100 ans)',
      captionLabel: 'vitesse du vent (temps de retour 100 ans)',
      mapLabel: 'temps de retour 100 ans',
      tooltipLabel: 'Vents (retour 100 ans)',
      unitDisplay: WIND_SPEED_UNIT_DISPLAY,
      scaleStep: WIND_SCALE_STEP_MPS,
      estimateFrom: null
    };
  }
  if (mode === 'event_max') {
    return {
      component: 'wind',
      mode,
      valueKey: 'event_max_wind_mps',
      minKey: 'event_max_wind_min_mps',
      maxKey: 'event_max_wind_max_mps',
      legendTitle: 'Vents (evenement le plus fort)',
      captionLabel: 'vitesse du vent (evenement le plus fort)',
      mapLabel: 'evenement le plus fort',
      tooltipLabel: 'Vents (evenement le plus fort)',
      unitDisplay: WIND_SPEED_UNIT_DISPLAY,
      scaleStep: WIND_SCALE_STEP_MPS,
      estimateFrom: null
    };
  }
  return hazardMetricConfig('wind', 'mean');
}

function estimateRp50FromRp100AndRp1000(rp100Raw, rp1000Raw) {
  void rp1000Raw;
  const rp100 = Number(rp100Raw);
  if (Number.isFinite(rp100) && rp100 > 0) {
    return rp100 * 0.86;
  }
  return 0;
}

function buildContinuousScale(minRaw, maxRaw, stepRaw) {
  const step = Math.max(1e-6, Number(stepRaw) || 1);
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

function buildFiveClassScale(minRaw, maxRaw) {
  const rawMin = Number(minRaw);
  const rawMax = Number(maxRaw);
  const minEdge = Number.isFinite(rawMin) ? Math.floor(rawMin * 2) / 2 : 0;
  const rawSpan = Number.isFinite(rawMax) ? Math.max(0, rawMax - minEdge) : 0;
  const step = Math.max(0.5, Math.ceil((rawSpan / 5.0) * 2.0) / 2.0);
  const edges = [];
  for (let idx = 0; idx <= 5; idx += 1) {
    edges.push(Number((minEdge + (step * idx)).toFixed(3)));
  }
  return {
    minEdge: edges[0] ?? minEdge,
    maxEdge: edges[edges.length - 1] ?? (minEdge + (step * 5)),
    step,
    edges
  };
}

function buildWindScale(minRaw, maxRaw, stepMps = WIND_SCALE_STEP_MPS) {
  return buildContinuousScale(minRaw, maxRaw, stepMps);
}

function hazardColorFromScale(componentRaw, valueRaw, scale) {
  const component = normalizeHazardComponent(componentRaw);
  const palette = HAZARD_COMPONENT_PALETTES[component] || WIND_PALETTE;
  const value = Number(valueRaw);
  const edges = Array.isArray(scale?.edges) ? scale.edges : [0, 1];
  if (edges.length >= 2 && Number.isFinite(value)) {
    const bins = Math.max(1, edges.length - 1);
    let binIdx = bins - 1;
    for (let idx = 0; idx < bins; idx += 1) {
      const hi = Number(edges[idx + 1]);
      if (!Number.isFinite(hi) || value < hi || idx === bins - 1) {
        binIdx = idx;
        break;
      }
    }
    const paletteIdx = Math.round((binIdx / Math.max(1, bins - 1)) * (palette.length - 1));
    return palette[Math.max(0, Math.min(palette.length - 1, paletteIdx))];
  }
  const minEdge = Number(edges[0] || 0);
  const maxEdge = Number(edges[edges.length - 1] || (minEdge + 1));
  const span = Math.max(1e-9, maxEdge - minEdge);
  const normalized = Number.isFinite(value) ? (value - minEdge) / span : 0;
  const clamped = Math.max(0, Math.min(1, normalized));
  const paletteIdx = Math.round(clamped * (palette.length - 1));
  return palette[Math.max(0, Math.min(palette.length - 1, paletteIdx))];
}

function windColorFromScale(valueRaw, scale) {
  return hazardColorFromScale('wind', valueRaw, scale);
}

function formatHazardMetricValue(componentRaw, valueRaw) {
  const component = normalizeHazardComponent(componentRaw);
  if (component === 'wind') return formatWindSpeed(valueRaw);
  const value = Number(valueRaw);
  return Number.isFinite(value) ? numberFmt.format(value) : 'n/a';
}

function buildHazardLegendHtml(activeComponents, scalesByComponent, metricsByComponent) {
  const visibleComponents = Array.isArray(activeComponents) ? activeComponents.map((component) => normalizeHazardComponent(component)) : [];
  if (!visibleComponents.length) {
    return [
      '<div class="wind-legend">',
      '<div class="wind-legend-title">Aucune couche active</div>',
      '</div>'
    ].join('');
  }
  const sections = [];
  visibleComponents.forEach((component) => {
    const scale = scalesByComponent?.[component];
    const metric = metricsByComponent?.[component];
    const edges = Array.isArray(scale?.edges) ? scale.edges : [0, 1];
    sections.push(`<div class="wind-legend-title">${escapeHtml(metric?.legendTitle || HAZARD_COMPONENT_LONG_LABEL[component] || component)}</div>`);
    for (let idx = 0; idx < edges.length - 1; idx += 1) {
      const lo = Number(edges[idx]);
      const hi = Number(edges[idx + 1]);
      const mid = (lo + hi) / 2;
      const color = hazardColorFromScale(component, mid, scale);
      sections.push(
        `<div class="wind-legend-row"><span class="wind-legend-swatch" style="background:${color}"></span><span>${escapeHtml(formatLegendBoundaryValue(lo, component))} - ${escapeHtml(formatLegendBoundaryValue(hi, component))} ${escapeHtml(metric?.unitDisplay || '')}</span></div>`
      );
    }
  });
  return ['<div class="wind-legend">', ...sections, '</div>'].join('');
}

function buildWindLegendHtml(scale, metric) {
  return buildHazardLegendHtml(['wind'], { wind: scale }, { wind: metric });
}

function updateHazardLayerUi() {
  const selected = getSelectedHazardComponent();
  if (els.hazardLayerWind) els.hazardLayerWind.checked = isHazardComponentVisible('wind');
  if (els.hazardLayerRain) els.hazardLayerRain.checked = isHazardComponentVisible('rain');
  if (els.hazardLayerSurge) els.hazardLayerSurge.checked = isHazardComponentVisible('surge');
  if (els.hazardLayerLandslide) els.hazardLayerLandslide.checked = isHazardComponentVisible('landslide');
  if (els.hazardLayerWind && selected === 'wind') els.hazardLayerWind.checked = true;
  if (els.hazardLayerRain && selected === 'rain') els.hazardLayerRain.checked = true;
  if (els.hazardLayerSurge && selected === 'surge') els.hazardLayerSurge.checked = true;
  if (els.hazardLayerLandslide && selected === 'landslide') els.hazardLayerLandslide.checked = true;
}

function currentHazardLayerPaneOpacity() {
  return clamp01(currentWindOpacityFactor());
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
  const factor = currentHazardLayerPaneOpacity();
  HAZARD_COMPONENT_ORDER.forEach((component) => {
    const paneName = ref.paneNamesByComponent?.[component];
    if (!paneName) return;
    const pane = ref.instance.getPane(paneName);
    if (!pane) return;
    const visible = isHazardComponentVisible(component);
    pane.style.opacity = visible ? String(clamp01(factor)) : '0';
    pane.style.display = visible ? 'block' : 'none';
  });
}

function applyWindLayerOpacity() {
  applyWindOpacityToMap('storm');
  applyWindOpacityToMap('storm_cmcc');
}

function ensureWindLegend(hazardKey, activeComponents, scalesByComponent, metricsByComponent) {
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
  if (legendEl) legendEl.innerHTML = buildHazardLegendHtml(activeComponents, scalesByComponent, metricsByComponent);
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
  HAZARD_COMPONENT_ORDER.forEach((component, idx) => {
    const paneName = ref.paneNamesByComponent?.[component];
    if (!paneName) return;
    if (!ref.instance.getPane(paneName)) {
      const pane = ref.instance.createPane(paneName);
      pane.style.zIndex = String(430 + idx);
      pane.style.pointerEvents = 'auto';
      pane.style.mixBlendMode = 'multiply';
    }
    ref.layersByComponent[component] = L.layerGroup().addTo(ref.instance);
  });
  return ref;
}

function nearestHazardCellValue(i, j, knownCells, fallbackValue, metricKey) {
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

  const bbox = meta?.bbox || {};
  const bboxSouth = Number(bbox.lat_min);
  const bboxNorth = Number(bbox.lat_max);
  const bboxWest = Number(bbox.lon_min);
  const bboxEast = Number(bbox.lon_max);
  if (
    Number.isFinite(bboxSouth)
    && Number.isFinite(bboxNorth)
    && Number.isFinite(bboxWest)
    && Number.isFinite(bboxEast)
    && bboxNorth > bboxSouth
    && bboxEast > bboxWest
  ) {
    const nLat = Math.max(1, Math.ceil((bboxNorth - bboxSouth) / cellDeg));
    const nLon = Math.max(1, Math.ceil((bboxEast - bboxWest) / cellDeg));
    return {
      cellDeg,
      south: bboxSouth,
      north: bboxSouth + (nLat * cellDeg),
      west: bboxWest,
      east: bboxWest + (nLon * cellDeg),
      nLat,
      nLon
    };
  }

  let minI = Number.POSITIVE_INFINITY;
  let maxI = Number.NEGATIVE_INFINITY;
  let minJ = Number.POSITIVE_INFINITY;
  let maxJ = Number.NEGATIVE_INFINITY;
  cells.forEach((cell) => {
    const i = Number(cell.i);
    const j = Number(cell.j);
    if (!Number.isFinite(i) || !Number.isFinite(j)) return;
    minI = Math.min(minI, i);
    maxI = Math.max(maxI, i);
    minJ = Math.min(minJ, j);
    maxJ = Math.max(maxJ, j);
  });
  if (Number.isFinite(minI) && Number.isFinite(maxI) && Number.isFinite(minJ) && Number.isFinite(maxJ)) {
    const south = minI * cellDeg;
    const west = minJ * cellDeg;
    const nLat = Math.max(1, (maxI - minI) + 1);
    const nLon = Math.max(1, (maxJ - minJ) + 1);
    return {
      cellDeg,
      south,
      north: south + (nLat * cellDeg),
      west,
      east: west + (nLon * cellDeg),
      nLat,
      nLon
    };
  }

  let minLat = Number.POSITIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;
  let minLon = Number.POSITIVE_INFINITY;
  let maxLon = Number.NEGATIVE_INFINITY;
  cells.forEach((cell) => {
    const lat = Number(cell.grid_lat ?? cell.lat);
    const lon = Number(cell.grid_lon ?? cell.lon);
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
  const south = minLat - half;
  const north = maxLat + half;
  const west = minLon - half;
  const east = maxLon + half;
  const nLat = Math.max(1, Math.round((north - south) / cellDeg));
  const nLon = Math.max(1, Math.round((east - west) / cellDeg));
  return { cellDeg, south, north, west, east, nLat, nLon };
}

function resolveHazardMetricValue(cell, metric, fallbackValue) {
  const direct = Number(cell?.[metric?.valueKey]);
  if (Number.isFinite(direct)) return direct;
  if (metric?.estimateFrom) {
    return estimateRp50FromRp100AndRp1000(cell?.[metric.estimateFrom.valueAKey], cell?.[metric.estimateFrom.valueBKey]);
  }
  return fallbackValue;
}

function resolveHazardMetricRange(payload, metric) {
  const directMin = Number(payload?.[metric?.minKey]);
  const directMax = Number(payload?.[metric?.maxKey]);
  if (Number.isFinite(directMin) && Number.isFinite(directMax)) {
    return { min: directMin, max: directMax };
  }
  if (metric?.estimateFrom) {
    const minEst = estimateRp50FromRp100AndRp1000(payload?.[metric.estimateFrom.minAKey], payload?.[metric.estimateFrom.minBKey]);
    const maxEst = estimateRp50FromRp100AndRp1000(payload?.[metric.estimateFrom.maxAKey], payload?.[metric.estimateFrom.maxBKey]);
    return { min: minEst, max: maxEst };
  }
  return { min: 0, max: 0 };
}

function isCaseStudyCmccMeanVisualSmoothingEnabled(hazardKey, metric, meta) {
  if (hazardKey !== 'storm_cmcc') return false;
  if (normalizeHazardComponent(metric?.component) !== 'wind') return false;
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

function clearHazardMapLayers(hazardKey) {
  const ref = windMapRef[hazardKey];
  if (!ref) return;
  HAZARD_COMPONENT_ORDER.forEach((component) => {
    if (ref.layersByComponent?.[component]) ref.layersByComponent[component].clearLayers();
  });
}

function resetHazardMapFitState() {
  if (windMapRef.storm) windMapRef.storm.hasFitted = false;
  if (windMapRef.storm_cmcc) windMapRef.storm_cmcc.hasFitted = false;
}

function initialHazardMapBounds(meta, grid) {
  const bbox = meta?.bbox || {};
  const bboxLatMin = Number(bbox.lat_min);
  const bboxLatMax = Number(bbox.lat_max);
  const bboxLonMin = Number(bbox.lon_min);
  const bboxLonMax = Number(bbox.lon_max);
  if (
    Number.isFinite(bboxLatMin)
    && Number.isFinite(bboxLatMax)
    && Number.isFinite(bboxLonMin)
    && Number.isFinite(bboxLonMax)
  ) {
    return [[bboxLatMin, bboxLonMin], [bboxLatMax, bboxLonMax]];
  }
  const latMin = Number(grid?.south);
  const latMax = Number(grid?.north);
  const lonMin = Number(grid?.west);
  const lonMax = Number(grid?.east);
  if (
    Number.isFinite(latMin)
    && Number.isFinite(latMax)
    && Number.isFinite(lonMin)
    && Number.isFinite(lonMax)
  ) {
    return [[latMin, lonMin], [latMax, lonMax]];
  }
  return null;
}

function renderHazardComponentMapLayer(hazardKey, componentRaw, payload, meta, options = {}) {
  if (!payload || !Array.isArray(payload.cells)) return;
  const component = normalizeHazardComponent(componentRaw);
  const ref = ensureWindMap(hazardKey);
  const layer = ref?.layersByComponent?.[component];
  if (!ref || !layer) return;

  layer.clearLayers();
  const cells = payload.cells || [];
  if (!cells.length) return;

  const metric = options.metric || hazardMetricConfig(component, 'mean');
  const metricValueKey = String(metric.valueKey || '');
  const grid = options.gridSpec || buildSharedWindGridSpec(payload, meta);
  if (!grid) return;

  const range = resolveHazardMetricRange(payload, metric);
  const min = Number.isFinite(options.colorMin) ? Number(options.colorMin) : Number(range.min || 0);
  const max = Number.isFinite(options.colorMax) ? Number(options.colorMax) : Number(range.max || 0);
  const scale = options.colorScale || buildFiveClassScale(min, max);
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
  const allowExtrapolation = !Boolean(meta?.territory_mask_path || meta?.cell_clip_rule);

  if (!ref.hasFitted) {
    const initialBounds = initialHazardMapBounds(meta, grid);
    if (initialBounds) {
      ref.instance.fitBounds(initialBounds, { padding: [12, 12], maxZoom: 10 });
    }
    ref.hasFitted = true;
  }

  cells.forEach((cell) => {
    let i = Number(cell.i);
    let j = Number(cell.j);
    if (!Number.isFinite(i) || !Number.isFinite(j)) {
      const lat = Number(cell.grid_lat ?? cell.lat);
      const lon = Number(cell.grid_lon ?? cell.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      if (!Number.isFinite(centerLat0) || !Number.isFinite(centerLon0) || !Number.isFinite(cellDeg)) return;
      i = Math.round((lat - centerLat0) / cellDeg);
      j = Math.round((lon - centerLon0) / cellDeg);
    }
    const key = `${i}|${j}`;
    const observedMetric = resolveHazardMetricValue(cell, metric, fallbackValue);
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
        if (!observed && !allowExtrapolation) continue;
        const data = observed || nearestHazardCellValue(i, j, knownCells, fallbackValue, metricValueKey);
        const metricValue = Number(data.metric_value ?? fallbackValue);
        const sampleCount = Number(data.sample_count ?? 0);
        const extrapolated = !observed;
        const visualAdjusted = Boolean(data.visual_adjusted);
        const color = hazardColorFromScale(component, metricValue, scale);
        const rect = L.rectangle([[south, west], [north, east]], {
          pane: ref.paneNamesByComponent?.[component],
          stroke: false,
          fillColor: color,
          fillOpacity: 1
        });
        const unitText = String(metric.unitDisplay || '').trim();
        rect.bindTooltip(
          [
            `<strong>${escapeHtml(getHazardLabel(hazardKey))} · ${escapeHtml(HAZARD_COMPONENT_LABEL[component] || component)}</strong>`,
            `${escapeHtml(metric.tooltipLabel)}: ${escapeHtml(formatHazardMetricValue(component, metricValue))}${unitText ? ` ${escapeHtml(unitText)}` : ''}`,
            `Echantillons: ${escapeHtml(numberFmt.format(sampleCount))}`,
            extrapolated
              ? 'Valeur: extrapolee (plus proche maille observee)'
              : (visualAdjusted ? 'Valeur: lissage visuel (sans impact calcul)' : 'Valeur: observee')
          ].join('<br/>'),
          { sticky: true }
        );
        rect.addTo(layer);
      }
    }
  }

  setTimeout(() => ref.instance && ref.instance.invalidateSize(), 0);
}

function renderWindMaps() {
  const selectedComponent = getSelectedHazardComponent();
  const payload = selectedComponent === 'landslide' ? state.landslideMaps : state.windMaps;
  if (!payload) return;
  const meta = payload.meta || {};
  const storm = payload.storm;
  const cmcc = payload.storm_cmcc;
  const activeComponents = currentVisibleHazardComponents();
  const mode = currentWindMapMode();
  const sharedCells = [
    ...((storm && Array.isArray(storm.cells)) ? storm.cells : []),
    ...((cmcc && Array.isArray(cmcc.cells)) ? cmcc.cells : [])
  ];
  const sharedGrid = buildSharedWindGridSpec({ cells: sharedCells }, meta);
  const metricsByComponent = {};
  const scalesByComponent = {};

  activeComponents.forEach((component) => {
    const metric = component === 'wind' ? windMetricConfig(mode) : hazardMetricConfig(component, mode);
    const stormRange = resolveHazardMetricRange(storm, metric);
    const cmccRange = resolveHazardMetricRange(cmcc, metric);
    const sharedMin = Math.min(
      Number(stormRange.min ?? Number.POSITIVE_INFINITY),
      Number(cmccRange.min ?? Number.POSITIVE_INFINITY)
    );
    const sharedMax = Math.max(
      Number(stormRange.max ?? Number.NEGATIVE_INFINITY),
      Number(cmccRange.max ?? Number.NEGATIVE_INFINITY)
    );
    const colorMin = Number.isFinite(sharedMin) ? sharedMin : 0;
    const colorMax = Number.isFinite(sharedMax) ? sharedMax : Math.max(colorMin + metric.scaleStep, 1);
    metricsByComponent[component] = metric;
    scalesByComponent[component] = buildFiveClassScale(colorMin, colorMax);
  });

  updateHazardLayerUi();
  clearHazardMapLayers('storm');
  clearHazardMapLayers('storm_cmcc');

  if (els.windMapTitleStorm) {
    els.windMapTitleStorm.textContent = selectedComponent === 'landslide'
      ? 'Cartes des probabilités de mouvements de terrain (climat actuel)'
      : 'Cartes des aleas (STORM)';
  }
  if (els.windMapTitleCmcc) {
    els.windMapTitleCmcc.textContent = selectedComponent === 'landslide'
      ? 'Cartes des probabilités de mouvements de terrain (SSP585)'
      : 'Cartes des aleas (STORM_CMCC)';
  }

  if (!activeComponents.length) {
    if (els.windStormCaption) {
      els.windStormCaption.textContent = 'Aucune couche d alea selectionnee.';
    }
    if (els.windCmccCaption) {
      els.windCmccCaption.textContent = 'Aucune couche d alea selectionnee.';
    }
    ensureWindLegend('storm', [], {}, {});
    ensureWindLegend('storm_cmcc', [], {}, {});
    applyWindLayerOpacity();
    return;
  }

  const componentText = activeComponents.map((component) => HAZARD_COMPONENT_LONG_LABEL[component] || component).join(', ');
  const allowExtrapolation = !Boolean(meta?.territory_mask_path || meta?.cell_clip_rule);
  const coverageText = allowExtrapolation
    ? 'extrapolation spatiale active autour de la zone etudiee'
    : 'clipping territorial natif (mailles hors territoire masquees)';

  if (storm && els.windStormCaption) {
    if (selectedComponent === 'landslide') {
      const meanScore = Number(storm.mean_landslide_score_mean);
      els.windStormCaption.textContent = `${numberFmt.format(storm.cell_count || 0)} mailles observees · ${coverageText} · ${componentText} · climat actuel · score moyen ${Number.isFinite(meanScore) ? numberFmt.format(meanScore) : 'n/a'} (risque score)`;
    } else {
      const scenarioText = hazardScenarioLabel(mode);
      els.windStormCaption.textContent = `${numberFmt.format(storm.cell_count || 0)} mailles observees · ${coverageText} · ${numberFmt.format(storm.years_covered || 0)} ans · couches actives: ${componentText} · scenario: ${scenarioText}`;
    }
    activeComponents.forEach((component) => {
      renderHazardComponentMapLayer('storm', component, storm, meta, {
        gridSpec: sharedGrid,
        colorScale: scalesByComponent[component],
        metric: metricsByComponent[component]
      });
    });
    ensureWindLegend('storm', activeComponents, scalesByComponent, metricsByComponent);
  }
  if (cmcc && els.windCmccCaption) {
    if (selectedComponent === 'landslide') {
      const meanScore = Number(cmcc.mean_landslide_score_mean);
      els.windCmccCaption.textContent = `${numberFmt.format(cmcc.cell_count || 0)} mailles observees · ${coverageText} · ${componentText} · SSP585 · score moyen ${Number.isFinite(meanScore) ? numberFmt.format(meanScore) : 'n/a'} (risque score)`;
    } else {
      const scenarioText = hazardScenarioLabel(mode);
      els.windCmccCaption.textContent = `${numberFmt.format(cmcc.cell_count || 0)} mailles observees · ${coverageText} · ${numberFmt.format(cmcc.years_covered || 0)} ans · couches actives: ${componentText} · scenario: ${scenarioText}`;
    }
    activeComponents.forEach((component) => {
      renderHazardComponentMapLayer('storm_cmcc', component, cmcc, meta, {
        gridSpec: sharedGrid,
        colorScale: scalesByComponent[component],
        metric: metricsByComponent[component]
      });
    });
    ensureWindLegend('storm_cmcc', activeComponents, scalesByComponent, metricsByComponent);
  }
  applyWindLayerOpacity();
}

function normalizeAdminVisuHazard(raw) {
  return String(raw || '').trim().toLowerCase() === 'storm_cmcc' ? 'storm_cmcc' : 'storm';
}

function normalizeAdminVisuBasin(raw, payload = null) {
  const value = String(raw || '').trim().toLowerCase();
  if (payload && payload.basins && typeof payload.basins === 'object') {
    const keys = Object.keys(payload.basins)
      .map((k) => String(k || '').trim().toLowerCase())
      .filter(Boolean);
    if (keys.length) {
      if (keys.includes(value)) return value;
      if (keys.includes('na')) return 'na';
      return keys[0];
    }
  }
  if (value === 'si') return 'si';
  return 'na';
}

function normalizeAdminVisuScenario(raw) {
  const value = String(raw || '').trim().toLowerCase();
  if (value === 'rp50') return 'rp50';
  if (value === 'rp100') return 'rp100';
  if (value === 'event_max') return 'event_max';
  return 'mean';
}

function adminVisuScenarioConfig(raw) {
  const scenario = normalizeAdminVisuScenario(raw);
  if (scenario === 'rp50') return { key: 'rp50', label: 'temps de retour 50 ans', legendTitle: 'Vents (retour 50 ans)' };
  if (scenario === 'rp100') return { key: 'rp100', label: 'temps de retour 100 ans', legendTitle: 'Vents (retour 100 ans)' };
  if (scenario === 'event_max') return { key: 'event_max', label: 'evenement le plus fort', legendTitle: 'Vents (evenement max)' };
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

  const cardState = state.adminVisuCards[cardIdx] || { basin: 'na', hazard: 'storm', scenario: 'mean' };
  const basin = normalizeAdminVisuBasin(cardState.basin, payload);
  const hazard = normalizeAdminVisuHazard(cardState.hazard);
  const scenarioCfg = adminVisuScenarioConfig(cardState.scenario);
  const scenario = scenarioCfg.key;
  const basinPayload = payload?.basins?.[basin] || null;
  if (!basinPayload) return;

  const basinSelect = Array.isArray(els.adminVisuBasinSelects) ? els.adminVisuBasinSelects[cardIdx] : null;
  const hazardSelect = Array.isArray(els.adminVisuHazardSelects) ? els.adminVisuHazardSelects[cardIdx] : null;
  const scenarioSelect = Array.isArray(els.adminVisuScenarioSelects) ? els.adminVisuScenarioSelects[cardIdx] : null;
  if (basinSelect) basinSelect.value = basin;
  if (hazardSelect) hazardSelect.value = hazard;
  if (scenarioSelect) scenarioSelect.value = scenario;

  state.adminVisuCards[cardIdx] = {
    ...(state.adminVisuCards[cardIdx] || {}),
    basin,
    hazard,
    scenario,
  };

  const bounds = basinPayload?.bounds || {};
  const south = Number(bounds.south);
  const north = Number(bounds.north);
  const west = Number(bounds.west);
  const east = Number(bounds.east);
  if (!Number.isFinite(south) || !Number.isFinite(north) || !Number.isFinite(west) || !Number.isFinite(east)) {
    return;
  }

  const overlayPath = basinPayload?.overlays?.[hazard]?.[scenario];
  const overlayUrl = adminVisuOverlayUrl(overlayPath);
  const caption = Array.isArray(els.adminVisuCaptions) ? els.adminVisuCaptions[cardIdx] : null;
  const metricMeta = basinPayload?.metrics?.[scenario] || {};
  const metricMin = Number(metricMeta.min_mps);
  const metricMax = Number(metricMeta.max_mps);
  const hazardLabel = hazard === 'storm_cmcc' ? 'STORM_CMCC' : 'STORM';
  const basinLabel = adminVisuBasinLabel(basin, payload);
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
    caption.textContent = `${basinLabel} · ${hazardLabel} · ${scenarioCfg.label} · echelle ${minTxt} a ${maxTxt} ${WIND_SPEED_UNIT_DISPLAY}`;
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
    if (els.adminVisuCompareNaBody) els.adminVisuCompareNaBody.innerHTML = '<tr><td colspan="4">Chargement...</td></tr>';
    if (els.adminVisuCompareSiBody) els.adminVisuCompareSiBody.innerHTML = '<tr><td colspan="4">Chargement...</td></tr>';
    return;
  }
  for (let idx = 0; idx < adminVisuMapRef.cards.length; idx += 1) {
    renderAdminVisuCard(idx);
  }
  renderAdminVisuComparisonTables();
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

function ensurePopulationOverlayPane(mapInstance, paneName, zIndex = 430) {
  if (!mapInstance || !paneName) return null;
  let pane = mapInstance.getPane(paneName);
  if (!pane) pane = mapInstance.createPane(paneName);
  pane.style.zIndex = String(zIndex);
  pane.style.pointerEvents = 'none';
  pane.style.filter = POPULATION_OVERLAY_VISUAL.filter;
  return pane;
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

  ensurePopulationOverlayPane(adminPopulationMapRef.instance, adminPopulationMapRef.overlayPaneName, 430);
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
      opacity: POPULATION_OVERLAY_VISUAL.opacity,
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

function adminVulnerabilityRefKey(curve, groupKey = 'wind') {
  const code = String(curve?.code || 'curve').replace(/[^a-zA-Z0-9_-]+/g, '_');
  const impfId = Number(curve?.impf_id);
  const id = Number.isFinite(impfId) ? String(Math.trunc(impfId)) : 'na';
  return `admin_vulnerability_${groupKey}_${id}_${code}`;
}

function adminVulnerabilityDomId(curve, groupKey = 'wind') {
  return adminVulnerabilityRefKey(curve, groupKey).replace(/_/g, '-');
}

function disposeAdminVulnerabilityCharts(groupKey = null) {
  const prefix = groupKey ? `admin_vulnerability_${groupKey}_` : 'admin_vulnerability_';
  Object.keys(chartRefs)
    .filter((key) => key.startsWith(prefix))
    .forEach((key) => {
      try {
        if (chartRefs[key] && typeof chartRefs[key].dispose === 'function') chartRefs[key].dispose();
      } catch (err) {
        console.warn('Unable to dispose vulnerability chart', key, err);
      }
      chartRefs[key] = null;
    });
}

function ensureAdminVulnerabilityCurveCards(payload, options = {}) {
  const grid = options.gridEl || els.adminVulnerabilityGrid;
  const groupKey = String(options.groupKey || 'wind');
  if (!grid || !payload || !Array.isArray(payload.curves)) return;
  const signature = payload.curves
    .map((curve) => `${curve.impf_id}:${curve.code}:${curve.name}`)
    .join('|');
  if (grid.dataset.signature === signature) return;

  disposeAdminVulnerabilityCharts(groupKey);

  grid.innerHTML = payload.curves.map((curve) => {
    const domId = adminVulnerabilityDomId(curve, groupKey);
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

function adminVulnerabilityXAxisLabel(payload) {
  const component = normalizeHazardComponent(payload?.hazard_component || payload?.haz_type);
  const unitDisplay = vulnerabilityIntensityDisplayUnit(payload?.intensity_unit);
  if (component === 'rain') return `Pluie proxy (${unitDisplay})`;
  if (component === 'surge') return `Submersion cotiere (${unitDisplay})`;
  if (component === 'landslide') return `Valeur pixel (${unitDisplay})`;
  return `Vitesse vent (${unitDisplay})`;
}

function adminVulnerabilityHazardLabel(payload) {
  const component = normalizeHazardComponent(payload?.hazard_component || payload?.haz_type);
  if (component === 'rain') return 'pluie';
  if (component === 'surge') return 'submersion cotiere';
  if (component === 'landslide') return 'mouvements de terrain';
  return 'vent';
}

function renderAdminVulnerabilityCurveChart(curve, payload, options = {}) {
  const groupKey = String(options.groupKey || 'wind');
  const domId = adminVulnerabilityDomId(curve, groupKey);
  const refKey = adminVulnerabilityRefKey(curve, groupKey);
  const chart = ensureChart(refKey, domId);
  if (!chart) return;

  const intensity = Array.isArray(curve.intensity) ? curve.intensity : [];
  const mdd = Array.isArray(curve.mdd) ? curve.mdd : [];
  const len = Math.min(intensity.length, mdd.length);
  if (len <= 1) return;

  const xValues = intensity.slice(0, len).map((v) => vulnerabilityIntensityToDisplayValue(v, curve.intensity_unit));
  const mainPoints = xValues.map((x, idx) => [x, clamp01(mdd[idx]) * 100]).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  const maxX = mainPoints.reduce((acc, point) => Math.max(acc, Number(point?.[0] || 0)), 0);
  const axisMax = maxX > 0 ? Math.ceil(maxX * 1.05) : 1;
  const unitDisplay = vulnerabilityIntensityDisplayUnit(curve.intensity_unit || payload?.intensity_unit);
  const component = normalizeHazardComponent(payload?.hazard_component || payload?.haz_type);
  const curveCode = String(curve.code || '').toLowerCase();
  const color = component === 'landslide'
    ? (curveCode.includes('proxy') ? '#C88B5A' : '#8C5A3C')
    : '#F39655';

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
    lineStyle: { width: 2, color },
    areaStyle: { color: `${color}33` }
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
        const xValue = Number(rows[0]?.value?.[0] ?? 0);
        const body = rows.map((row) => {
          const label = String(row?.seriesName || '');
          const val = Number(row?.value?.[1] ?? row?.data?.[1] ?? 0);
          return `${escapeHtml(label)}: ${escapeHtml(numberFmt.format(val))}%`;
        });
        return [`<strong>${escapeHtml(numberFmt.format(xValue))} ${escapeHtml(unitDisplay)}</strong>`, ...body].join('<br/>');
      }
    },
    xAxis: {
      ...chartThemeCommon().xAxis,
      type: 'value',
      min: 0,
      max: axisMax,
      name: adminVulnerabilityXAxisLabel(payload),
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

function resizeAdminVulnerabilityCharts(groupKey = null) {
  const prefix = groupKey ? `admin_vulnerability_${groupKey}_` : 'admin_vulnerability_';
  Object.keys(chartRefs)
    .filter((key) => key.startsWith(prefix))
    .forEach((key) => {
      if (chartRefs[key] && typeof chartRefs[key].resize === 'function') chartRefs[key].resize();
    });
}

function renderAdminVulnerabilityCurveSet(payload, options = {}) {
  if (!runtime.allowAdminVisu) return;
  const gridEl = options.gridEl || els.adminVulnerabilityGrid;
  const captionEl = options.captionEl || els.adminVulnerabilityCaption;
  const groupKey = String(options.groupKey || 'wind');
  const loadingText = String(options.loadingText || 'Chargement des courbes de vulnerabilite...');
  if (!payload || !Array.isArray(payload.curves)) {
    if (captionEl) {
      captionEl.textContent = loadingText;
    }
    return;
  }

  ensureAdminVulnerabilityCurveCards(payload, { gridEl, groupKey });
  payload.curves.forEach((curve) => {
    renderAdminVulnerabilityCurveChart(curve, payload, { groupKey });
  });

  if (captionEl) {
    const curveCount = payload.curves.length;
    const hasUncertainty = payload.curves.some((curve) => Array.isArray(curve.uncertaintyLower) && Array.isArray(curve.uncertaintyUpper));
    const uncertaintyText = hasUncertainty ? 'incertitude visible (bornes basse/haute)' : 'incertitude non disponible dans la source';
    captionEl.textContent = String(
      options.captionText
      || `${curveCount} courbes (${payload.profile}) · alea ${adminVulnerabilityHazardLabel(payload)} · axe X en ${vulnerabilityIntensityDisplayUnit(payload.intensity_unit)} · ${uncertaintyText}.`
    );
  }

  setTimeout(() => {
    resizeAdminVulnerabilityCharts(groupKey);
  }, 0);
}

function renderVulnerabilityOverviewCards(cards, options = {}) {
  const gridEl = options.gridEl || els.adminVulnerabilityGrid;
  const captionEl = options.captionEl || els.adminVulnerabilityCaption;
  const scope = String(options.scope || '').trim();
  const componentOrder = Array.isArray(options.componentOrder) && options.componentOrder.length
    ? options.componentOrder.map((component) => normalizeHazardComponent(component))
    : ADMIN_VULNERABILITY_OVERVIEW_COMPONENTS;
  if (!gridEl) return;

  if (!cards.length) {
    if (captionEl) captionEl.textContent = String(options.emptyCaptionText || 'Courbes de vulnerabilite indisponibles.');
    gridEl.innerHTML = `<article class="admin-vulnerability-item"><div class="admin-vulnerability-item-title">${escapeHtml(String(options.emptyTitle || 'Aucune courbe disponible'))}</div></article>`;
    return;
  }

  const signature = cards
    .map((card) => `${card.key}:${componentOrder.map((component) => card.curves?.[component]?.code || '-').join('/')}`)
    .join('|');

  if (gridEl.dataset.signature !== signature) {
    disposeAdminVulnerabilityOverviewCharts(scope);
    gridEl.innerHTML = cards.map((card) => {
      const codes = componentOrder
        .map((component) => `${ADMIN_VULNERABILITY_OVERVIEW_META[component].label}: ${card.curves?.[component]?.code || 'n/a'}`)
        .join(' · ');
      return `
        <article class="admin-vulnerability-item admin-vulnerability-item-overview">
          <div class="admin-vulnerability-item-title">${escapeHtml(card.label)}</div>
          <div class="admin-vulnerability-item-meta">${escapeHtml(card.source)} · ${escapeHtml(card.geography)}</div>
          <div class="admin-vulnerability-item-meta"><strong>Infra modele source:</strong> ${escapeHtml(card.modeledType)} (${escapeHtml(card.modeledCharacteristics)})</div>
          <div class="admin-vulnerability-item-code"><strong>Codes courbes:</strong> ${escapeHtml(codes)}</div>
          <div class="admin-vulnerability-mini-grid">
            ${componentOrder.map((component) => `
              <div class="admin-vulnerability-mini-card">
                <div class="admin-vulnerability-mini-title">${escapeHtml(ADMIN_VULNERABILITY_OVERVIEW_META[component].label)}</div>
                <div id="${escapeHtml(adminOverviewDomId(card.key, component, scope))}" class="admin-vulnerability-chart admin-vulnerability-chart-mini"></div>
              </div>
            `).join('')}
          </div>
        </article>
      `;
    }).join('');
    gridEl.dataset.signature = signature;
  }

  cards.forEach((card) => {
    componentOrder.forEach((component) => {
      renderAdminVulnerabilityOverviewMiniChart(card.key, component, card.curves?.[component] || null, scope);
    });
  });

  if (captionEl) {
    captionEl.textContent = String(
      options.captionText || `${cards.length} infrastructures affichées · chaque carte combine vent, submersion côtière et pluie.`
    );
  }

  setTimeout(() => {
    resizeAdminVulnerabilityOverviewCharts(scope);
  }, 0);
}

function collectCaseStudyVulnerabilityExampleCards() {
  const wantedKeys = ['eau_eu_pr', 'elec_bt_aerien'];
  const cards = collectAdminVulnerabilityOverviewCards();
  mergeComponentCurveIntoCards(cards, 'landslide', state.adminHydroVulnerabilityCurves?.landslide || null);
  const byKey = new Map(cards.map((card) => [String(card.key), card]));
  return wantedKeys
    .map((key) => byKey.get(key))
    .filter(Boolean)
    .sort((a, b) => wantedKeys.indexOf(String(a.key)) - wantedKeys.indexOf(String(b.key)));
}

function renderAdminVulnerabilityOverviewCurves() {
  if (!runtime.allowAdminVisu) return;
  if (!els.adminVulnerabilityGrid) return;
  const cards = collectAdminVulnerabilityOverviewCards();
  renderVulnerabilityOverviewCards(cards, {
    gridEl: els.adminVulnerabilityGrid,
    captionEl: els.adminVulnerabilityCaption,
    scope: '',
    emptyCaptionText: 'Courbes de vulnerabilite indisponibles.',
    emptyTitle: 'Aucune courbe disponible',
    captionText: `${cards.length} infrastructures affichées · chaque carte combine vent, submersion côtière et pluie.`
  });
}

function selectCaseStudyLandslideCurve(payload) {
  if (!payload || !Array.isArray(payload.curves)) return null;
  const preferredCode = String(payload?.default_curve?.code || '').trim();
  if (preferredCode) {
    const preferred = payload.curves.find((curve) => String(curve?.code || '') === preferredCode);
    if (preferred) return preferred;
  }
  return payload.curves[0] || null;
}

function mergeComponentCurveIntoCards(cards, component, payload, options = {}) {
  const curve = options.curve || selectCaseStudyLandslideCurve(payload);
  if (!curve) return cards;
  const assetTypes = new Set(
    Array.isArray(curve.sibAssetTypes)
      ? curve.sibAssetTypes.map((assetType) => String(assetType || '').trim()).filter(Boolean)
      : Array.isArray(curve.sib_asset_types)
        ? curve.sib_asset_types.map((assetType) => String(assetType || '').trim()).filter(Boolean)
        : []
  );
  if (!assetTypes.size) return cards;

  cards.forEach((card) => {
    if (assetTypes.has(String(card.key || '').trim())) {
      card.curves = card.curves || {};
      card.curves[component] = curve;
    }
  });
  return cards;
}

function renderCaseStudyVulnerabilityExamples() {
  const gridEl = els.caseStudyVulnerabilityGrid;
  if (!gridEl) return;
  const cards = collectCaseStudyVulnerabilityExampleCards();
  renderVulnerabilityOverviewCards(cards, {
    gridEl,
    captionEl: els.caseStudyVulnerabilityCaption,
    scope: 'page1_examples',
    componentOrder: ['wind', 'surge', 'rain', 'landslide'],
    emptyCaptionText: 'Courbes de vulnérabilité indisponibles.',
    emptyTitle: 'Aucune courbe disponible',
    captionText: `${cards.length} infrastructures affichées · chaque carte combine vent, submersion côtière, pluie et mouvements de terrain.`
  });
}

function loadCaseStudyVulnerabilityExamples() {
  if (state.caseStudyVulnerabilityExamplesPromise) return state.caseStudyVulnerabilityExamplesPromise;
  state.caseStudyVulnerabilityExamplesPromise = Promise.all([
    ensureAdminVulnerabilityCurvesLoaded(),
    ensureAdminHydroVulnerabilityCurvesLoaded('rain'),
    ensureAdminHydroVulnerabilityCurvesLoaded('surge'),
    ensureAdminHydroVulnerabilityCurvesLoaded('landslide')
  ])
    .then(() => {
      renderCaseStudyVulnerabilityExamples();
    })
    .catch((err) => {
      if (els.caseStudyVulnerabilityCaption) {
        els.caseStudyVulnerabilityCaption.textContent = `Courbes de vulnérabilité indisponibles: ${err.message}`;
      }
    })
    .finally(() => {
      state.caseStudyVulnerabilityExamplesPromise = null;
    });
  return state.caseStudyVulnerabilityExamplesPromise;
}

function resizeAdminVulnerabilityOverviewCharts(scope = '') {
  const prefix = scope ? `admin_vulnerability_overview_${scope}_` : 'admin_vulnerability_overview_';
  Object.keys(chartRefs)
    .filter((key) => key.startsWith(prefix))
    .forEach((key) => {
      if (chartRefs[key] && typeof chartRefs[key].resize === 'function') chartRefs[key].resize();
    });
}

function renderAdminHydroVulnerabilityCurves() {
  renderAdminVulnerabilityOverviewCurves();
}

function renderAdminLandslideVulnerabilityCurves() {
  if (!runtime.allowAdminVisu) return;
  const gridEl = els.adminLandslideVulnerabilityGrid;
  const captionEl = els.adminLandslideVulnerabilityCaption;
  if (!gridEl || !captionEl) return;

  const payload = state.adminHydroVulnerabilityCurves?.landslide || null;
  if (!payload || !Array.isArray(payload.curves)) {
    captionEl.textContent = 'Chargement des courbes de mouvements de terrain...';
    return;
  }

  const curveCount = payload.curves.length;
  const hasUncertainty = payload.curves.some((curve) => Array.isArray(curve.uncertaintyLower) && Array.isArray(curve.uncertaintyUpper));
  const uncertaintyText = hasUncertainty ? 'incertitude visible (bornes basse/haute)' : 'incertitude non disponible dans la source';
  renderAdminVulnerabilityCurveSet(payload, {
    gridEl,
    captionEl,
    groupKey: 'landslide',
    loadingText: 'Chargement des courbes de mouvements de terrain...',
    captionText: `${curveCount} courbes (${payload.profile}) · hypothèse 5 paliers (référence) et proxy D2 (comparaison) · axe X en ${vulnerabilityIntensityDisplayUnit(payload.intensity_unit)} · ${uncertaintyText}.`
  });
}

const ADMIN_VULNERABILITY_OVERVIEW_COMPONENTS = ['wind', 'surge', 'rain'];
const ADMIN_VULNERABILITY_OVERVIEW_META = {
  wind: { label: 'Vent', color: '#FFFFFF' },
  surge: { label: 'Submersion côtière', color: '#003A76' },
  rain: { label: 'Pluie', color: '#5BC5F2' },
  landslide: { label: 'Mouv. terrain', color: '#8C5A3C' }
};

function adminOverviewSlug(raw) {
  return String(raw || 'infra')
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'infra';
}

function adminOverviewRefKey(assetKey, component, scope = '') {
  const scopeSlug = String(scope || '').trim();
  const prefix = scopeSlug ? `admin_vulnerability_overview_${scopeSlug}_` : 'admin_vulnerability_overview_';
  return `${prefix}${adminOverviewSlug(assetKey)}_${component}`;
}

function adminOverviewDomId(assetKey, component, scope = '') {
  return adminOverviewRefKey(assetKey, component, scope).replace(/_/g, '-');
}

function disposeAdminVulnerabilityOverviewCharts(scope = '') {
  const scopeSlug = String(scope || '').trim();
  const prefix = scopeSlug ? `admin_vulnerability_overview_${scopeSlug}_` : 'admin_vulnerability_overview_';
  Object.keys(chartRefs)
    .filter((key) => key.startsWith(prefix))
    .forEach((key) => {
      try {
        if (chartRefs[key] && typeof chartRefs[key].dispose === 'function') chartRefs[key].dispose();
      } catch (err) {
        console.warn('Unable to dispose vulnerability overview chart', key, err);
      }
      chartRefs[key] = null;
    });
}

function collectAdminVulnerabilityOverviewCards() {
  const byAsset = new Map();
  const payloads = {
    wind: state.adminVulnerabilityCurves,
    surge: state.adminHydroVulnerabilityCurves?.surge,
    rain: state.adminHydroVulnerabilityCurves?.rain
  };

  ADMIN_VULNERABILITY_OVERVIEW_COMPONENTS.forEach((component) => {
    const payload = payloads[component];
    if (!payload || !Array.isArray(payload.curves)) return;
    payload.curves.forEach((curve, curveIdx) => {
      const sourceAssets = Array.isArray(curve?.sibAssetTypes) && curve.sibAssetTypes.length
        ? curve.sibAssetTypes
        : [String(curve?.modeledInfrastructureType || `infra_${curveIdx}`)];
      sourceAssets.forEach((assetTypeRaw, assetIdx) => {
        const assetType = String(assetTypeRaw || '').trim();
        const fallbackKey = `${component}_${curve.code || 'curve'}_${curveIdx}_${assetIdx}`;
        const key = assetType || fallbackKey;
        const mapKey = adminOverviewSlug(key);
        if (!byAsset.has(mapKey)) {
          byAsset.set(mapKey, {
            key: mapKey,
            label: ASSET_TYPE_ADMIN_LABEL[assetType] || assetType || String(curve?.modeledInfrastructureType || 'Infrastructure'),
            modeledType: String(curve?.modeledInfrastructureType || 'N/A'),
            modeledCharacteristics: String(curve?.modeledInfrastructureCharacteristics || 'N/A'),
            source: String(curve?.source || 'source inconnue'),
            geography: String(curve?.geography || 'geographie non renseignee'),
            curves: {}
          });
        }
        const entry = byAsset.get(mapKey);
        if (!entry.curves[component]) {
          entry.curves[component] = curve;
        }
      });
    });
  });

  return Array.from(byAsset.values()).sort((a, b) => String(a.label || '').localeCompare(String(b.label || ''), 'fr'));
}

function renderNoDataMiniChart(refKey, domId) {
  const chart = ensureChart(refKey, domId);
  if (!chart) return;
  chart.setOption({
    title: {
      text: 'N/A',
      left: 'center',
      top: 'middle',
      textStyle: { color: '#abc0ba', fontSize: 12, fontWeight: 500 }
    },
    xAxis: { show: false },
    yAxis: { show: false },
    series: []
  }, true);
}

function renderAdminVulnerabilityOverviewMiniChart(assetKey, component, curve, scope = '') {
  const domId = adminOverviewDomId(assetKey, component, scope);
  const refKey = adminOverviewRefKey(assetKey, component, scope);
  const chart = ensureChart(refKey, domId);
  if (!chart || !curve) {
    renderNoDataMiniChart(refKey, domId);
    return;
  }

  const intensity = Array.isArray(curve.intensity) ? curve.intensity : [];
  const mdd = Array.isArray(curve.mdd) ? curve.mdd : [];
  const len = Math.min(intensity.length, mdd.length);
  if (len <= 1) {
    renderNoDataMiniChart(refKey, domId);
    return;
  }

  const points = intensity
    .slice(0, len)
    .map((value, idx) => [vulnerabilityIntensityToDisplayValue(value, curve.intensity_unit), clamp01(mdd[idx]) * 100])
    .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
  if (!points.length) {
    renderNoDataMiniChart(refKey, domId);
    return;
  }

  const maxX = points.reduce((acc, point) => Math.max(acc, Number(point?.[0] || 0)), 0);
  const axisMax = maxX > 0 ? Math.ceil(maxX * 1.05) : 1;
  const unitDisplay = vulnerabilityIntensityDisplayUnit(curve.intensity_unit);
  const color = ADMIN_VULNERABILITY_OVERVIEW_META[component]?.color || '#F39655';

  chart.setOption({
    ...chartThemeCommon(),
    grid: { left: 36, right: 8, top: 16, bottom: 30, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        const row = Array.isArray(params) ? params[0] : params;
        const xValue = Number(row?.value?.[0] ?? 0);
        const yValue = Number(row?.value?.[1] ?? 0);
        return `<strong>${escapeHtml(numberFmt.format(xValue))} ${escapeHtml(unitDisplay)}</strong><br/>Dommage: ${escapeHtml(numberFmt.format(yValue))}%`;
      }
    },
    xAxis: {
      ...chartThemeCommon().xAxis,
      type: 'value',
      min: 0,
      max: axisMax,
      axisLabel: {
        color: '#abc0ba',
        fontSize: 9,
        formatter: (value) => numberFmt.format(Number(value) || 0)
      }
    },
    yAxis: {
      ...chartThemeCommon().yAxis,
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: {
        color: '#abc0ba',
        fontSize: 9,
        formatter: (value) => `${numberFmt.format(Number(value) || 0)}%`
      }
    },
    series: [{
      name: ADMIN_VULNERABILITY_OVERVIEW_META[component]?.label || component,
      type: 'line',
      data: points,
      showSymbol: false,
      symbol: 'none',
      lineStyle: { width: 2, color },
      areaStyle: { color: `${color}33` }
    }]
  }, true);
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
  ensurePopulationOverlayPane(waterMapRef.instance, waterMapRef.overlayPaneName, 350);
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

  renderCaseStudyPopulationOverlay();

  if (!ref.hasFitted && bounds && bounds.isValid()) {
      ref.instance.fitBounds(bounds, { padding: [18, 18], maxZoom: 11 });
      ref.hasFitted = true;
  }
  setTimeout(() => ref.instance && ref.instance.invalidateSize(), 0);
}

function normalizeCaseStudyPopulationTerritory(territoryRaw) {
  return normalizeCaseStudyTerritory(territoryRaw) === 'martinique' ? 'mtq' : 'glp';
}

function updateWaterPopulationToggleUi() {
  if (!els.waterPopulationToggle) return;
  const active = !!state.caseStudyPopulationVisible;
  els.waterPopulationToggle.classList.toggle('active', active);
  els.waterPopulationToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
  els.waterPopulationToggle.textContent = active ? 'Masquer la population' : 'Afficher la population';
}

function ensureWaterPopulationLegend(scaleMin, scaleMax, paletteColors) {
  if (!waterMapRef.instance) return;
  if (!waterMapRef.populationLegendControl) {
    waterMapRef.populationLegendControl = L.control({ position: 'bottomright' });
    waterMapRef.populationLegendControl.onAdd = () => L.DomUtil.create('div', 'admin-pop-legend');
  }
  if (!waterMapRef.populationLegendControl._map) {
    waterMapRef.populationLegendControl.addTo(waterMapRef.instance);
  }
  const legendEl = waterMapRef.populationLegendControl.getContainer();
  if (legendEl) {
    legendEl.innerHTML = buildAdminPopulationLegendHtml(scaleMin, scaleMax, paletteColors);
  }
}

function renderCaseStudyPopulationOverlay() {
  const ref = ensureWaterMap();
  if (!ref || !ref.instance) return;

  const clearOverlay = () => {
    if (ref.populationOverlayLayer && ref.instance.hasLayer(ref.populationOverlayLayer)) {
      ref.instance.removeLayer(ref.populationOverlayLayer);
    }
    if (ref.populationLegendControl && ref.populationLegendControl._map) {
      ref.instance.removeControl(ref.populationLegendControl);
    }
    ref.populationOverlayLayer = null;
    ref.populationLegendControl = null;
    ref.populationOverlayUrl = '';
  };

  const applyOverlay = () => {
    clearOverlay();
    updateWaterPopulationToggleUi();
    if (!state.caseStudyPopulationVisible) return;
    const payload = state.adminPopulationMaps;
    if (!payload || !Array.isArray(payload.territories)) return;
    const territoryCode = normalizeCaseStudyPopulationTerritory(state.caseStudyTerritory);
    const territory = payload.territories.find((item) => String(item?.code || '').toLowerCase() === territoryCode);
    if (!territory) return;

    const bounds = [
      [Number(territory.bounds?.south || 0), Number(territory.bounds?.west || 0)],
      [Number(territory.bounds?.north || 0), Number(territory.bounds?.east || 0)]
    ];
    const overlayUrl = adminVisuOverlayUrl(territory.overlay);
    if (!overlayUrl) return;
    ref.populationOverlayLayer = L.imageOverlay(overlayUrl, bounds, {
      pane: ref.overlayPaneName,
      opacity: POPULATION_OVERLAY_VISUAL.opacity,
      interactive: false,
      crossOrigin: true
    });
    ref.populationOverlayLayer.addTo(ref.instance);
    ref.populationOverlayUrl = overlayUrl;

    const meta = payload.meta || {};
    const scale = meta.scale || {};
    ensureWaterPopulationLegend(
      Number(scale.min_people_per_pixel || 0),
      Number(scale.max_people_per_pixel || territory.stats?.max_people_per_pixel || 0),
      adminPopulationLegendColors(payload)
    );
  };

  if (state.adminPopulationMaps) {
    applyOverlay();
    return;
  }

  ensureAdminPopulationMapsLoaded()
    .then(() => {
      applyOverlay();
    })
    .catch((err) => {
      console.warn('Population overlay unavailable', err);
      updateWaterPopulationToggleUi();
    });
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

function histogramPointsForComponent(graph, componentRaw) {
  const component = normalizeHazardComponent(componentRaw);
  const rawBins = Array.isArray(graph?.bins_mps)
    ? graph.bins_mps
    : (Array.isArray(graph?.bins) ? graph.bins : []);
  const rawPct = Array.isArray(graph?.percent) ? graph.percent : [];
  return rawBins
    .map((x, idx) => {
      const rawX = Number(x);
      if (!Number.isFinite(rawX)) return null;
      const xValue = component === 'wind' ? windMpsToKmh(rawX) : rawX;
      if (!Number.isFinite(xValue)) return null;
      return [xValue, Number(rawPct[idx] || 0)];
    })
    .filter(Boolean);
}

function renderHistogramComparisonChart(refKey, domId, graphA, graphB, labelA, labelB, colorA, colorB, options = {}) {
  const chart = ensureChart(refKey, domId);
  if (!chart) return;
  const component = normalizeHazardComponent(options.component || 'wind');
  const xAxisLabel = String(options.xAxisLabel || 'Vitesse maximale du vent');
  const unitDisplay = String(options.unitDisplay || WIND_SPEED_UNIT_DISPLAY);
  const yAxisName = String(options.yAxisName || 'Part des evenements (%)');
  const seriesA = histogramPointsForComponent(graphA, component);
  const seriesB = histogramPointsForComponent(graphB, component);
  if (!seriesA.length || !seriesB.length) {
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

  const xValues = [...seriesA, ...seriesB]
    .map((point) => Number(point?.[0]))
    .filter((value) => Number.isFinite(value));
  let axisMinX = Math.min(...xValues);
  let axisMaxX = Math.max(...xValues);
  if (!Number.isFinite(axisMinX) || !Number.isFinite(axisMaxX)) {
    axisMinX = 0;
    axisMaxX = 1;
  } else if (Math.abs(axisMaxX - axisMinX) < 1e-6) {
    const spread = Math.max(1, Math.abs(axisMinX) * 0.05);
    axisMinX = Math.max(0, axisMinX - spread);
    axisMaxX += spread;
  } else {
    const spread = (axisMaxX - axisMinX) * 0.08;
    axisMinX = Math.max(0, axisMinX - spread);
    axisMaxX += spread;
  }

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
          `<strong>${escapeHtml(numberFmt.format(binValue))}${unitDisplay ? ` ${escapeHtml(unitDisplay)}` : ''}</strong>`,
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
      min: axisMinX,
      max: axisMaxX,
      name: unitDisplay ? `${xAxisLabel} (${unitDisplay})` : xAxisLabel,
      nameLocation: 'middle',
      nameGap: 54,
      nameTextStyle: { color: '#edf4f2', fontSize: 12, fontWeight: 700, padding: [10, 0, 0, 0] },
      axisLine: { show: true, lineStyle: { color: 'rgba(177,208,203,0.45)' } },
      axisLabel: {
        color: '#abc0ba',
        margin: 10,
        formatter: component === 'landslide'
          ? (value) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(Number(value) || 0)
          : (value) => peopleFmtInt.format(Math.round(Number(value) || 0))
      }
    },
    yAxis: {
      ...chartThemeCommon().yAxis,
      type: 'value',
      name: yAxisName,
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

function renderStackedImpactBarChart(refKey, domId, rows, paletteByComponent) {
  const chart = ensureChart(refKey, domId);
  if (!chart) return;
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) {
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

  const labels = safeRows.map((row) => row.label);
  const series = [];
  const components = [...IMPACT_COMPONENT_ORDER];
  components.forEach((component) => {
    series.push({
      name: `STORM ${HAZARD_COMPONENT_LABEL[component] || component}`,
      type: 'bar',
      stack: 'storm',
      data: safeRows.map((row) => Number(row?.stormComponents?.[component] || 0)),
      itemStyle: { color: paletteByComponent?.storm?.[component] || '#0083CB' },
      barMaxWidth: 24
    });
  });
  components.forEach((component) => {
    series.push({
      name: `STORM_CMCC ${HAZARD_COMPONENT_LABEL[component] || component}`,
      type: 'bar',
      stack: 'storm_cmcc',
      data: safeRows.map((row) => Number(row?.cmccComponents?.[component] || 0)),
      itemStyle: { color: paletteByComponent?.storm_cmcc?.[component] || '#5BC5F2' },
      barMaxWidth: 24
    });
  });

  chart.setOption({
    ...chartThemeCommon(),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => formatMoneyEUR(value)
    },
    legend: { top: 2, textStyle: { color: '#abc0ba', fontSize: 10 } },
    xAxis: { ...chartThemeCommon().xAxis, type: 'category', data: labels, axisLabel: { color: '#abc0ba', rotate: 20 } },
    yAxis: { ...chartThemeCommon().yAxis, type: 'value', name: '€' },
    series
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
          cmcc: Number(c.damage_eur || 0),
          stormComponents: normalizeDamageComponentMap(s.damage_components_eur, s.damage_eur),
          cmccComponents: normalizeDamageComponentMap(c.damage_components_eur, c.damage_eur)
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
          cmcc: Number(c.eai_eur || 0),
          stormComponents: normalizeDamageComponentMap(s.damage_components_eur, s.eai_eur),
          cmccComponents: normalizeDamageComponentMap(c.damage_components_eur, c.eai_eur)
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
          cmcc: Number(c.event_max_loss_eur || 0),
          stormComponents: normalizeDamageComponentMap(s.damage_components_eur, s.event_max_loss_eur),
          cmccComponents: normalizeDamageComponentMap(c.damage_components_eur, c.event_max_loss_eur)
        };
      });
    }

    return [];
  };

  const scenarios = [
    { key: 'annual', label: 'Annuel' },
    { key: 'rp50', label: 'RP50' },
    { key: 'rp100', label: 'RP100' },
    { key: 'event_max', label: 'Evt max' }
  ];
  const totalByScenarioAndPrefix = (scenarioKey, prefix) => {
    const rows = rowsForScenario(scenarioKey).filter((row) => String(row.key || '').startsWith(prefix));
    return rows.reduce((acc, row) => {
      acc.storm += Number(row?.storm || 0);
      acc.cmcc += Number(row?.cmcc || 0);
      return acc;
    }, { storm: 0, cmcc: 0 });
  };

  const labels = scenarios.map((scenario) => scenario.label);
  const waterTotals = scenarios.map((scenario) => totalByScenarioAndPrefix(scenario.key, 'eau_'));
  const elecTotals = scenarios.map((scenario) => totalByScenarioAndPrefix(scenario.key, 'elec_'));

  renderGroupedImpactBarChart(
    'impact_overview_water',
    'impact-overview-water-chart',
    labels,
    waterTotals.map((row) => row.storm),
    waterTotals.map((row) => row.cmcc),
    { storm: '#0083CB', cmcc: '#F39655' }
  );
  renderGroupedImpactBarChart(
    'impact_overview_elec',
    'impact-overview-elec-chart',
    labels,
    elecTotals.map((row) => row.storm),
    elecTotals.map((row) => row.cmcc),
    { storm: '#6AB96F', cmcc: '#A4A64B' }
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
    renderAdminVulnerabilityOverviewCurves();
    renderAdminLandslideVulnerabilityCurves();
  }
  renderWaterInfraMap();
  renderInfraSummary();
  renderUserImpactSection(state.activeResult);
  if (state.currentPage === 'page1' || state.currentPage === 'page2') {
    ensureNetworkStatesLoaded();
  }
  renderNetworkStateMap();
  updateMetaBadges();
  if (state.currentPage === 'page3') {
    renderTerritorySelectionState();
    renderKpis();
    renderMap();
    renderTerritoryTable();
  }

  if (!state.activeResult) {
    return;
  }
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

function caseStudyTerritoryFromAnalysis(analysis, fallbackTerritory = null) {
  const meta = analysis?.meta || {};
  const territoryRaw = meta.case_study_territory || meta.valuation_territory || fallbackTerritory || 'guadeloupe';
  return normalizeCaseStudyTerritory(territoryRaw);
}

function caseStudyTerritoryLabel(territory) {
  return normalizeCaseStudyTerritory(territory) === 'martinique' ? 'Martinique' : 'Guadeloupe';
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

async function fetchLandslideMaps(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const url = new URL(`/data/${base}-landslide-maps.json`, window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || !payload.meta || !payload.storm || !payload.storm_cmcc) {
    throw new Error('Payload carte des mouvements de terrain invalide');
  }
  return payload;
}

async function fetchCaseStudyMultiHazardProxy(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const url = new URL(`/data/${base}-multi-hazard-proxy.json`, window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  if (!payload || !payload.meta || !payload.hazards) {
    throw new Error('Payload proxy multi-aleas invalide');
  }
  return payload;
}

function parseIsoTimestampSafe(raw) {
  const text = String(raw || '').trim();
  if (!text) return Number.NaN;
  const ts = Number(new Date(text).getTime());
  return Number.isFinite(ts) ? ts : Number.NaN;
}

function adminVisuBasinLabel(basinRaw, payload = null) {
  const basin = normalizeAdminVisuBasin(basinRaw, payload);
  const fromPayload = payload?.basins?.[basin]?.label;
  if (fromPayload) return String(fromPayload);
  if (basin === 'si') return 'Sud Indien (SI)';
  return 'Nord Atlantique (NA)';
}

function caseStudyRunId(payload) {
  return String(payload?.meta?.case_study_run_id || '').trim();
}

function validateCaseStudyArtifactsCoherence(territory, windMaps, landslideMaps, analysis, multiHazardProxy) {
  const key = normalizeCaseStudyTerritory(territory);
  const windRunId = caseStudyRunId(windMaps);
  const landslideRunId = caseStudyRunId(landslideMaps);
  const analysisRunId = caseStudyRunId(analysis);
  const proxyRunId = caseStudyRunId(multiHazardProxy);
  const runIds = [windRunId, landslideRunId, analysisRunId, proxyRunId];
  const withRunIdCount = runIds.filter((value) => Boolean(value)).length;
  if (withRunIdCount > 0 && withRunIdCount < runIds.length) {
    console.warn(`Artefacts incoherents pour ${key}: run_id partiellement present (wind/landslide/proxy/analysis).`);
    return;
  }

  const referenceRunId = windRunId || landslideRunId || analysisRunId || proxyRunId || '';
  if (referenceRunId) {
    const mismatch = [];
    if (windRunId && windRunId !== referenceRunId) mismatch.push(`wind=${windRunId}`);
    if (landslideRunId && landslideRunId !== referenceRunId) mismatch.push(`landslide=${landslideRunId}`);
    if (analysisRunId && analysisRunId !== referenceRunId) mismatch.push(`analysis=${analysisRunId}`);
    if (proxyRunId && proxyRunId !== referenceRunId) mismatch.push(`proxy=${proxyRunId}`);
    if (mismatch.length) {
      console.warn(
        `Artefacts incoherents pour ${key}: run_id attendu ${referenceRunId}, recu ${mismatch.join(', ')}`
      );
      return;
    }
  }

  const windAt = parseIsoTimestampSafe(windMaps?.meta?.generated_at);
  const landslideAt = parseIsoTimestampSafe(landslideMaps?.meta?.generated_at);
  const proxyAt = parseIsoTimestampSafe(multiHazardProxy?.meta?.generated_at);
  const analysisAt = parseIsoTimestampSafe(analysis?.meta?.generated_at);
  if (Number.isFinite(windAt) && Number.isFinite(proxyAt) && proxyAt < windAt) {
    console.warn(`Artefacts incoherents pour ${key}: proxy plus ancien que wind-maps.`);
    return;
  }
  if (Number.isFinite(windAt) && Number.isFinite(landslideAt) && landslideAt < windAt) {
    console.warn(`Artefacts incoherents pour ${key}: landslide plus ancien que wind-maps.`);
    return;
  }
  if (Number.isFinite(proxyAt) && Number.isFinite(analysisAt) && analysisAt < proxyAt) {
    console.warn(`Artefacts incoherents pour ${key}: page-analysis plus ancien que proxy.`);
  }
}

function normalizeAdminVisuPayload(payloadRaw) {
  const payload = payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : {};
  if (payload.basins && typeof payload.basins === 'object') {
    const basins = {};
    Object.entries(payload.basins).forEach(([rawKey, basinValue]) => {
      const key = normalizeAdminVisuBasin(rawKey);
      if (!basinValue || typeof basinValue !== 'object') return;
      const bounds = basinValue.bounds || {};
      if (!Number.isFinite(Number(bounds.south)) || !Number.isFinite(Number(bounds.north))
        || !Number.isFinite(Number(bounds.west)) || !Number.isFinite(Number(bounds.east))) {
        return;
      }
      const overlays = basinValue.overlays || {};
      if (!overlays?.storm || !overlays?.storm_cmcc) return;
      basins[key] = {
        ...basinValue,
        label: String(basinValue.label || adminVisuBasinLabel(key)),
      };
    });
    if (Object.keys(basins).length) {
      return {
        meta: payload.meta || {},
        basins,
      };
    }
  }

  if (payload?.meta?.bounds && payload?.overlays?.storm && payload?.overlays?.storm_cmcc) {
    return {
      meta: payload.meta || {},
      basins: {
        na: {
          label: 'Nord Atlantique (NA)',
          bounds: payload.meta.bounds,
          grid: payload.meta.grid || {},
          metrics: payload.metrics || {},
          overlays: payload.overlays || {},
          comparison_rows: [],
        },
      },
    };
  }

  throw new Error('Payload admin visu invalide');
}

function renderAdminVisuComparisonTables() {
  const payload = state.adminVisuMaps;
  const tableByBasin = {
    na: els.adminVisuCompareNaBody,
    si: els.adminVisuCompareSiBody,
  };
  Object.entries(tableByBasin).forEach(([basin, body]) => {
    if (!body) return;
    const rows = Array.isArray(payload?.basins?.[basin]?.comparison_rows) ? payload.basins[basin].comparison_rows : [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="4">Tableau indisponible.</td></tr>';
      return;
    }
    body.innerHTML = rows.map((row) => {
      const indicator = String(
        row?.indicator
        || `Vent - ${ADMIN_VISU_SCENARIO_LABEL[String(row?.scenario || 'mean')] || ADMIN_VISU_SCENARIO_LABEL.mean} (m/s)`
      );
      const storm = Number(row?.storm_mps);
      const cmcc = Number(row?.storm_cmcc_mps);
      const delta = Number(row?.delta_mps);
      return `
        <tr>
          <td>${escapeHtml(indicatorDisplayUnit(indicator))}</td>
          <td class="num">${escapeHtml(formatWindTableValueFromMps(storm))}</td>
          <td class="num">${escapeHtml(formatWindTableValueFromMps(cmcc))}</td>
          <td class="num">${escapeHtml(formatWindTableValueFromMps(delta))}</td>
        </tr>
      `;
    }).join('');
  });
}

async function fetchAdminVisuMaps() {
  const urls = [
    new URL('/hazard-maps/basin-leaflet-overlays.json', window.location.origin).toString(),
    new URL('/hazard-maps/na-leaflet-overlays.json', window.location.origin).toString(),
    new URL('/hazard-maps/na_wind_leaflet_overlays.json', window.location.origin).toString()
  ];
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      const normalized = normalizeAdminVisuPayload(payload);
      if (!normalized?.basins || !Object.keys(normalized.basins).length) throw new Error('Payload admin visu invalide');
      return normalized;
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

function normalizeCaseStudyVisuScenario(raw) {
  return String(raw || '').trim().toLowerCase() === 'rp100' ? 'rp100' : 'mean';
}

function ensureCaseStudyVisuMap() {
  if (!window.L || !els.caseStudyVisuMap) return null;
  if (caseStudyVisuMapRef.instance) return caseStudyVisuMapRef;

  caseStudyVisuMapRef.instance = L.map(els.caseStudyVisuMap, {
    zoomControl: true,
    attributionControl: true,
    preferCanvas: true
  }).setView([24.0, -58.0], 4);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 8,
    minZoom: 2,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(caseStudyVisuMapRef.instance);

  if (!caseStudyVisuMapRef.instance.getPane(caseStudyVisuMapRef.overlayPaneName)) {
    const pane = caseStudyVisuMapRef.instance.createPane(caseStudyVisuMapRef.overlayPaneName);
    pane.style.zIndex = '430';
    pane.style.pointerEvents = 'none';
  }

  return caseStudyVisuMapRef;
}

function ensureCaseStudyVisuLegend(metricMin, metricMax, legendTitle) {
  if (!window.L) return;
  if (!caseStudyVisuMapRef.instance) return;

  if (!caseStudyVisuMapRef.legendControl) {
    caseStudyVisuMapRef.legendControl = L.control({ position: 'bottomright' });
    caseStudyVisuMapRef.legendControl.onAdd = () => {
      const div = L.DomUtil.create('div');
      div.className = 'leaflet-control wind-legend-control admin-wind-legend-control';
      return div;
    };
    caseStudyVisuMapRef.legendControl.addTo(caseStudyVisuMapRef.instance);
  }

  const legendEl = caseStudyVisuMapRef.legendControl.getContainer();
  if (legendEl) legendEl.innerHTML = buildAdminVisuLegendHtml(metricMin, metricMax, legendTitle);
}

function renderCaseStudyVisuCard() {
  const payload = state.adminVisuMaps;
  if (!els.caseStudyVisuMap || !els.caseStudyVisuCaption) return;
  if (!payload || !payload.basins) {
    els.caseStudyVisuCaption.textContent = 'Chargement des couches aléa...';
    return;
  }

  const ref = ensureCaseStudyVisuMap();
  if (!ref || !ref.instance) return;

  const basin = 'na';
  const hazard = normalizeAdminVisuHazard(state.caseStudyVisuHazard);
  const scenario = normalizeCaseStudyVisuScenario(state.caseStudyVisuScenario);
  state.caseStudyVisuHazard = hazard;
  state.caseStudyVisuScenario = scenario;

  if (els.caseStudyVisuHazardSelect) els.caseStudyVisuHazardSelect.value = hazard;
  if (els.caseStudyVisuScenarioSelect) els.caseStudyVisuScenarioSelect.value = scenario;

  const basinPayload = payload.basins?.[basin] || null;
  const bounds = basinPayload?.bounds || {};
  const south = Number(bounds.south);
  const north = Number(bounds.north);
  const west = Number(bounds.west);
  const east = Number(bounds.east);
  const boundsLeaflet = [[south, west], [north, east]];
  if (!Number.isFinite(south) || !Number.isFinite(north) || !Number.isFinite(west) || !Number.isFinite(east)) {
    els.caseStudyVisuCaption.textContent = 'Emprise géographique indisponible pour le bassin NA.';
    return;
  }

  const overlayPath = basinPayload?.overlays?.[hazard]?.[scenario];
  const overlayUrl = adminVisuOverlayUrl(overlayPath);
  const metricMeta = basinPayload?.metrics?.[scenario] || {};
  const metricMin = Number(metricMeta.min_mps);
  const metricMax = Number(metricMeta.max_mps);
  const hazardLabel = hazard === 'storm_cmcc' ? 'STORM_CMCC' : 'STORM';
  const scenarioCfg = adminVisuScenarioConfig(scenario);

  if (!overlayUrl) {
    els.caseStudyVisuCaption.textContent = 'Couche indisponible pour cette combinaison.';
    if (caseStudyVisuMapRef.overlayLayer) {
      caseStudyVisuMapRef.instance.removeLayer(caseStudyVisuMapRef.overlayLayer);
      caseStudyVisuMapRef.overlayLayer = null;
      caseStudyVisuMapRef.overlayUrl = '';
    }
    return;
  }

  if (!caseStudyVisuMapRef.overlayLayer || caseStudyVisuMapRef.overlayUrl !== overlayUrl) {
    if (caseStudyVisuMapRef.overlayLayer) caseStudyVisuMapRef.instance.removeLayer(caseStudyVisuMapRef.overlayLayer);
    caseStudyVisuMapRef.overlayLayer = L.imageOverlay(overlayUrl, boundsLeaflet, {
      pane: caseStudyVisuMapRef.overlayPaneName,
      opacity: 0.95,
      interactive: false,
      crossOrigin: true
    }).addTo(caseStudyVisuMapRef.instance);
    caseStudyVisuMapRef.overlayUrl = overlayUrl;
    caseStudyVisuMapRef.hasFitted = false;
  }

  if (!caseStudyVisuMapRef.hasFitted) {
    caseStudyVisuMapRef.instance.fitBounds(boundsLeaflet, { padding: [8, 8], maxZoom: 6 });
    caseStudyVisuMapRef.hasFitted = true;
  }

  const basinLabel = adminVisuBasinLabel(basin, payload);
  const minTxt = Number.isFinite(metricMin) ? formatWindSpeed(metricMin) : 'n/a';
  const maxTxt = Number.isFinite(metricMax) ? formatWindSpeed(metricMax) : 'n/a';
  els.caseStudyVisuCaption.textContent = `${basinLabel} · ${hazardLabel} · ${scenarioCfg.label} · échelle ${minTxt} à ${maxTxt} ${WIND_SPEED_UNIT_DISPLAY}`;
  ensureCaseStudyVisuLegend(metricMin, metricMax, scenarioCfg.legendTitle);

  setTimeout(() => {
    if (caseStudyVisuMapRef.instance) caseStudyVisuMapRef.instance.invalidateSize();
  }, 0);
}

function loadCaseStudyVisuCard() {
  if (state.caseStudyVisuPromise) return state.caseStudyVisuPromise;
  state.caseStudyVisuPromise = ensureAdminVisuMapsLoaded()
    .then(() => {
      renderCaseStudyVisuCard();
    })
    .catch((err) => {
      if (els.caseStudyVisuCaption) {
        els.caseStudyVisuCaption.textContent = `Couche aléa indisponible: ${err.message}`;
      }
    })
    .finally(() => {
      state.caseStudyVisuPromise = null;
    });
  return state.caseStudyVisuPromise;
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

async function fetchAdminVulnerabilityCurves(hazardComponent = 'wind') {
  const component = normalizeHazardComponent(hazardComponent);
  const url = new URL('/api/v1/vulnerability/curves', window.location.origin);
  url.searchParams.set('hazard_component', component);
  const targetUrl = url.toString();
  const res = await fetch(targetUrl, { cache: 'no-store' });
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

function ensureAdminHydroVulnerabilityCurvesLoaded(hazardComponent = state.adminHydroHazardComponent) {
  const component = normalizeHazardComponent(hazardComponent);
  if (component === 'wind') return ensureAdminVulnerabilityCurvesLoaded();
  if (state.adminHydroVulnerabilityCurves?.[component]) {
    return Promise.resolve(state.adminHydroVulnerabilityCurves[component]);
  }
  if (state.adminHydroVulnerabilityPromises?.[component]) {
    return state.adminHydroVulnerabilityPromises[component];
  }
  state.adminHydroVulnerabilityPromises[component] = fetchAdminVulnerabilityCurves(component)
    .then((payload) => {
      state.adminHydroVulnerabilityCurves[component] = payload;
      return payload;
    })
    .finally(() => {
      state.adminHydroVulnerabilityPromises[component] = null;
    });
  return state.adminHydroVulnerabilityPromises[component];
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

async function fetchCaseStudyCompleteAnalysis(territory = 'guadeloupe') {
  const base = caseStudyFileBase(territory);
  const url = new URL(`/data/${base}-complete-analysis.json`, window.location.origin).toString();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  return ensureResultShape(payload);
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


  function ensureCaseStudyCompleteAnalysisLoaded(territory = 'guadeloupe') {
    const key = normalizeCaseStudyTerritory(territory);
    if (!state.caseStudyCache[key]) state.caseStudyCache[key] = {};
    const cache = state.caseStudyCache[key];
    if (cache.completeAnalysis) {
      if (normalizeCaseStudyTerritory(state.caseStudyTerritory) === key) {
        state.completeAnalysis = cache.completeAnalysis;
      }
      return Promise.resolve(cache.completeAnalysis);
    }
    if (cache.completeAnalysisPromise) return cache.completeAnalysisPromise;
    cache.completeAnalysisPromise = fetchCaseStudyCompleteAnalysis(key)
      .then((payload) => {
        cache.completeAnalysis = payload;
        if (normalizeCaseStudyTerritory(state.caseStudyTerritory) === key) {
          state.completeAnalysis = payload;
          state.caseStudyScenarioSocialSummary = null;
          if (state.page1Analysis) {
            renderSocialImpactTable(state.page1Analysis);
            renderPage1Conclusion(state.page1Analysis);
          }
          updateMetaBadges();
        }
        return payload;
      })
      .catch((err) => {
        console.warn('Case-study complete analysis could not be loaded', err);
        return null;
      })
      .finally(() => {
        cache.completeAnalysisPromise = null;
      });
    return cache.completeAnalysisPromise;
  }
function resetCaseStudyMapLayers() {
  windMapRef.storm.hasFitted = false;
  windMapRef.storm_cmcc.hasFitted = false;
  clearHazardMapLayers('storm');
  clearHazardMapLayers('storm_cmcc');
  if (waterMapRef.instance) {
    waterMapRef.layersByType.forEach((entry) => {
      if (entry?.layer && waterMapRef.instance.hasLayer(entry.layer)) waterMapRef.instance.removeLayer(entry.layer);
    });
  }
  waterMapRef.layersByType.clear();
  waterMapRef.order = [];
  waterMapRef.hasFitted = false;
  if (waterMapRef.instance && waterMapRef.populationOverlayLayer && waterMapRef.instance.hasLayer(waterMapRef.populationOverlayLayer)) {
    waterMapRef.instance.removeLayer(waterMapRef.populationOverlayLayer);
  }
  if (waterMapRef.instance && waterMapRef.populationLegendControl && waterMapRef.populationLegendControl._map) {
    waterMapRef.instance.removeControl(waterMapRef.populationLegendControl);
  }
  waterMapRef.populationOverlayLayer = null;
  waterMapRef.populationLegendControl = null;
  waterMapRef.populationOverlayUrl = '';
  if (networkMapRef.instance) {
    networkMapRef.layersByType.forEach((entry) => {
      if (entry?.layer && networkMapRef.instance.hasLayer(entry.layer)) networkMapRef.instance.removeLayer(entry.layer);
    });
  }
  networkMapRef.layersByType.clear();
  networkMapRef.order = [];
  networkMapRef.hasFitted = false;
  state.caseStudyScenarioSocialSummary = null;
}

async function ensureCaseStudyLoaded(territory) {
  const key = normalizeCaseStudyTerritory(territory);
  if (state.caseStudyCache[key]?.ready) {
    ensureCaseStudyCompleteAnalysisLoaded(key);
    return state.caseStudyCache[key];
  }
  if (!state.caseStudyCache[key]) state.caseStudyCache[key] = {};
  const cache = state.caseStudyCache[key];
  if (cache.promise) return cache.promise;
  cache.promise = Promise.all([
    fetchWindMaps(key),
    fetchLandslideMaps(key),
    fetchWaterInfra(key),
    fetchPage1Analysis(key),
    fetchNetworkStates(key),
    fetchCaseStudyMultiHazardProxy(key)
  ]).then(([windMaps, landslideMaps, waterInfra, analysis, networkStates, multiHazardProxy]) => {
    validateCaseStudyArtifactsCoherence(key, windMaps, landslideMaps, analysis, multiHazardProxy);
    cache.windMaps = windMaps;
    cache.landslideMaps = landslideMaps;
    cache.waterInfra = waterInfra;
    cache.analysis = analysis;
    cache.networkStates = networkStates;
    cache.multiHazardProxy = multiHazardProxy;
    cache.ready = true;
    ensureCaseStudyCompleteAnalysisLoaded(key);
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
  state.landslideMaps = payload?.landslideMaps || null;
  state.waterInfra = payload?.waterInfra || null;
  state.completeAnalysis = payload?.completeAnalysis || state.caseStudyCache[key]?.completeAnalysis || null;
  state.page1Analysis = payload?.analysis || null;
  state.networkStates = payload?.networkStates || null;
  state.caseStudyScenarioSocialSummary = null;
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
    setSelectedHazardComponent('wind');
    resetHazardMapFitState();
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
  if (els.hazardLayerWind) {
    els.hazardLayerWind.addEventListener('change', () => {
      if (!els.hazardLayerWind.checked) return;
      setSelectedHazardComponent('wind');
      resetHazardMapFitState();
      renderWindMaps();
      renderPage1Hazard(state.page1Analysis || {});
    });
  }
  if (els.hazardLayerRain) {
    els.hazardLayerRain.addEventListener('change', () => {
      if (!els.hazardLayerRain.checked) return;
      setSelectedHazardComponent('rain');
      resetHazardMapFitState();
      renderWindMaps();
      renderPage1Hazard(state.page1Analysis || {});
    });
  }
  if (els.hazardLayerSurge) {
    els.hazardLayerSurge.addEventListener('change', () => {
      if (!els.hazardLayerSurge.checked) return;
      setSelectedHazardComponent('surge');
      resetHazardMapFitState();
      renderWindMaps();
      renderPage1Hazard(state.page1Analysis || {});
    });
  }
  if (els.hazardLayerLandslide) {
    els.hazardLayerLandslide.addEventListener('change', () => {
      if (!els.hazardLayerLandslide.checked) return;
      setSelectedHazardComponent('landslide');
      resetHazardMapFitState();
      renderWindMaps();
      renderPage1Hazard(state.page1Analysis || {});
    });
  }
  if (els.caseStudyVisuHazardSelect) {
    els.caseStudyVisuHazardSelect.value = normalizeAdminVisuHazard(state.caseStudyVisuHazard);
    els.caseStudyVisuHazardSelect.addEventListener('change', () => {
      state.caseStudyVisuHazard = normalizeAdminVisuHazard(els.caseStudyVisuHazardSelect.value);
      renderCaseStudyVisuCard();
    });
  }
  if (els.caseStudyVisuScenarioSelect) {
    els.caseStudyVisuScenarioSelect.value = normalizeCaseStudyVisuScenario(state.caseStudyVisuScenario);
    els.caseStudyVisuScenarioSelect.addEventListener('change', () => {
      state.caseStudyVisuScenario = normalizeCaseStudyVisuScenario(els.caseStudyVisuScenarioSelect.value);
      renderCaseStudyVisuCard();
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
  (els.adminVisuBasinSelects || []).forEach((select, idx) => {
    if (!select) return;
    select.value = normalizeAdminVisuBasin(state.adminVisuCards[idx]?.basin, state.adminVisuMaps);
    select.addEventListener('change', () => {
      state.adminVisuCards[idx] = {
        ...(state.adminVisuCards[idx] || {}),
        basin: normalizeAdminVisuBasin(select.value, state.adminVisuMaps),
        hazard: normalizeAdminVisuHazard(state.adminVisuCards[idx]?.hazard),
        scenario: normalizeAdminVisuScenario(state.adminVisuCards[idx]?.scenario)
      };
      renderAdminVisuCard(idx);
    });
  });
  (els.adminVisuHazardSelects || []).forEach((select, idx) => {
    if (!select) return;
    select.value = normalizeAdminVisuHazard(state.adminVisuCards[idx]?.hazard);
    select.addEventListener('change', () => {
      state.adminVisuCards[idx] = {
        ...(state.adminVisuCards[idx] || {}),
        basin: normalizeAdminVisuBasin(state.adminVisuCards[idx]?.basin, state.adminVisuMaps),
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
        basin: normalizeAdminVisuBasin(state.adminVisuCards[idx]?.basin, state.adminVisuMaps),
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
  if (els.adminHydroHazardSelect) {
    els.adminHydroHazardSelect.value = normalizeHazardComponent(state.adminHydroHazardComponent);
    els.adminHydroHazardSelect.addEventListener('change', () => {
      state.adminHydroHazardComponent = normalizeHazardComponent(els.adminHydroHazardSelect.value);
      ensureAdminHydroVulnerabilityCurvesLoaded(state.adminHydroHazardComponent)
        .then(() => {
          renderAdminHydroVulnerabilityCurves();
        })
        .catch((err) => {
          setStatus(`Courbes pluie/submersion indisponibles: ${err.message}`, 'error');
        });
    });
  }

  if (els.impactTableScenarioSelect) {
    els.impactTableScenarioSelect.value = normalizeImpactTableScenario(state.impactTableScenario);
    els.impactTableScenarioSelect.addEventListener('change', () => {
      state.impactTableScenario = normalizeImpactTableScenario(els.impactTableScenarioSelect.value);
      renderPage1Impact(state.page1Analysis || {});
    });
  }
  if (els.impactTableModeButtons) {
    updateImpactTableModeUi();
    els.impactTableModeButtons.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const btn = target ? target.closest('button[data-impact-table-mode]') : null;
      if (!btn) return;
      const mode = normalizeImpactTableDisplayMode(btn.getAttribute('data-impact-table-mode'));
      if (mode === normalizeImpactTableDisplayMode(state.impactTableDisplayMode)) return;
      state.impactTableDisplayMode = mode;
      updateImpactTableModeUi();
      renderPage1Impact(state.page1Analysis || {});
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

  if (els.waterPopulationToggle) {
    updateWaterPopulationToggleUi();
    els.waterPopulationToggle.addEventListener('click', () => {
      state.caseStudyPopulationVisible = !state.caseStudyPopulationVisible;
      updateWaterPopulationToggleUi();
      renderCaseStudyPopulationOverlay();
    });
  }

  if (els.conclusionModeButtons) {
    updateConclusionModeUi();
    els.conclusionModeButtons.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const btn = target ? target.closest('button[data-conclusion-mode]') : null;
      if (!btn) return;
      const mode = normalizeConclusionDisplayMode(btn.getAttribute('data-conclusion-mode'));
      if (mode === normalizeConclusionDisplayMode(state.conclusionDisplayMode)) return;
      state.conclusionDisplayMode = mode;
      updateConclusionModeUi();
      renderPage1Conclusion(state.page1Analysis || {});
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
      Promise.all([
        ensureAdminVulnerabilityCurvesLoaded(),
        ensureAdminHydroVulnerabilityCurvesLoaded('rain'),
        ensureAdminHydroVulnerabilityCurvesLoaded('surge')
      ])
        .then(() => {
          if (state.currentPage === 'page5') renderAdminVulnerabilityOverviewCurves();
        })
        .catch((err) => {
          console.warn('Admin vulnerability curves preload failed', err);
          if (state.currentPage === 'page5') {
            setStatus(`Courbes de vulnerabilite indisponibles: ${err.message}`, 'error');
          }
        });
      ensureAdminHydroVulnerabilityCurvesLoaded('landslide')
        .then(() => {
          if (state.currentPage === 'page5') renderAdminLandslideVulnerabilityCurves();
        })
        .catch((err) => {
          console.warn('Admin landslide curves preload failed', err);
          if (state.currentPage === 'page5') {
            setStatus(`Courbes de mouvements de terrain indisponibles: ${err.message}`, 'error');
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
