/**
 * TradingView UI Controller
 * Synchronizes user interactions, instrument selection, timeframe switching,
 * crosshair OHLC inspections, zoom controls, live market session status (IST),
 * and live Pine Script table metrics.
 */

document.addEventListener('DOMContentLoaded', async () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const chart = new ICTChart('tradingviewChart');

  const urlParams = new URLSearchParams(window.location.search);
  let currentInstrument = urlParams.get('symbol') || 'NSE_INDEX|Nifty 50';
  let currentInstrumentName = 'NIFTY 50';
  if (currentInstrument.includes('Bank') || currentInstrument.includes('BANK')) {
    currentInstrumentName = 'BANK NIFTY';
  } else if (currentInstrument.includes('SENSEX')) {
    currentInstrumentName = 'SENSEX';
  }
  let currentTimeframe = urlParams.get('tf') || '5m';
  let cachedIndicators = null;
  let lastCandles = [];
  let isFirstLoad = true;
  let activeAbortController = null;

  // DOM Elements
  const activeTickerTitle = document.getElementById('activeTickerTitle');
  const activePrice = document.getElementById('activePrice');
  const priceChange = document.getElementById('priceChange');
  const activeTimeframeBadge = document.getElementById('activeTimeframeBadge');
  const refreshBtn = document.getElementById('refreshBtn');
  const indicesButtons = document.querySelectorAll('#indicesButtons .tv-tool-btn');
  const tfButtons = document.querySelectorAll('#tfButtons .tv-tf-btn');
  const stocksSelect = document.getElementById('stocksSelect');
  const chartLoadingBar = document.getElementById('chartLoadingBar');

  // Market Status Badge Elements
  const marketStatusBadge = document.getElementById('marketStatusBadge');
  const marketStatusText = document.getElementById('marketStatusText');
  const marketStatusSub = document.getElementById('marketStatusSub');
  const dashMarketStatus = document.getElementById('dashMarketStatus');

  // Zoom controls
  const zoomInBtn = document.getElementById('zoomInBtn');
  const zoomOutBtn = document.getElementById('zoomOutBtn');
  const resetZoomBtn = document.getElementById('resetZoomBtn');
  const floatZoomIn = document.getElementById('floatZoomIn');
  const floatZoomOut = document.getElementById('floatZoomOut');
  const floatResetZoom = document.getElementById('floatResetZoom');

  if (zoomInBtn) zoomInBtn.addEventListener('click', () => chart.zoomIn());
  if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => chart.zoomOut());
  if (resetZoomBtn) resetZoomBtn.addEventListener('click', () => chart.resetZoom());
  if (floatZoomIn) floatZoomIn.addEventListener('click', () => chart.zoomIn());
  if (floatZoomOut) floatZoomOut.addEventListener('click', () => chart.zoomOut());
  if (floatResetZoom) floatResetZoom.addEventListener('click', () => chart.resetZoom());

  // OHLC elements
  const barO = document.getElementById('barO');
  const barH = document.getElementById('barH');
  const barL = document.getElementById('barL');
  const barC = document.getElementById('barC');

  // Toggles
  const toggleFVG = document.querySelector('#toggleFVG input');
  const toggleOB = document.querySelector('#toggleOB input');
  const toggleLiq = document.querySelector('#toggleLiq input');
  const toggleSignals = document.querySelector('#toggleSignals input');

  function getOverlayOptions() {
    return {
      showFVG: toggleFVG ? toggleFVG.checked : true,
      showOB: toggleOB ? toggleOB.checked : true,
      showLiq: toggleLiq ? toggleLiq.checked : true,
      showSignals: toggleSignals ? toggleSignals.checked : true
    };
  }

  // Pine Script Floating Table DOM
  const dashSignalBadge = document.getElementById('dashSignalBadge');
  const dashSignal = document.getElementById('dashSignal');
  const dashIPDA = document.getElementById('dashIPDA');
  const dashModel = document.getElementById('dashModel');
  const dashCISD = document.getElementById('dashCISD');
  const dashBullSweep = document.getElementById('dashBullSweep');
  const dashBearSweep = document.getElementById('dashBearSweep');
  const dashPDHPDL = document.getElementById('dashPDHPDL');
  const dashKZ = document.getElementById('dashKZ');
  const dashSB = document.getElementById('dashSB');
  const dashHTFBias = document.getElementById('dashHTFBias');
  const dashMode = document.getElementById('dashMode');
  const signalsFeed = document.getElementById('signalsFeed');

  // Crosshair move handler to show live OHLC
  chart.chart.subscribeCrosshairMove(param => {
    if (!param || !param.time || !param.seriesData || !param.seriesData.get(chart.candleSeries)) {
      if (lastCandles.length > 0) {
        updateOHLC(lastCandles[lastCandles.length - 1]);
      }
      return;
    }
    const data = param.seriesData.get(chart.candleSeries);
    updateOHLC(data);
  });

  function updateOHLC(bar) {
    if (!bar) return;
    barO.textContent = bar.open.toFixed(2);
    barH.textContent = bar.high.toFixed(2);
    barL.textContent = bar.low.toFixed(2);
    barC.textContent = bar.close.toFixed(2);
    barC.style.color = bar.close >= bar.open ? 'var(--tv-bull)' : 'var(--tv-bear)';
  }

  // =========================================================================
  // REAL-TIME INDIAN MARKET HOURS (IST) CALCULATOR
  // Regular Trading Session: Monday - Friday, 09:15 to 15:30 IST
  // =========================================================================
  function getMarketSessionInfo() {
    const now = new Date();
    const options = {
      timeZone: 'Asia/Kolkata',
      hour12: false,
      weekday: 'short',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric'
    };
    const parts = new Intl.DateTimeFormat('en-US', options).formatToParts(now);
    const map = {};
    for (const p of parts) map[p.type] = p.value;

    const weekday = map.weekday;
    const hour = parseInt(map.hour, 10);
    const minute = parseInt(map.minute, 10);
    const second = parseInt(map.second, 10);
    const totalMinutes = hour * 60 + minute;

    const isWeekday = !['Sat', 'Sun'].includes(weekday);
    const isOpen = isWeekday && totalMinutes >= (9 * 60 + 15) && totalMinutes < (15 * 60 + 30);

    let nextOpenDesc = 'Opens Mon 09:15 AM IST';
    if (weekday === 'Fri' && totalMinutes >= (15 * 60 + 30)) {
      nextOpenDesc = 'Opens Mon 09:15 AM IST';
    } else if (['Sat', 'Sun'].includes(weekday)) {
      nextOpenDesc = 'Opens Mon 09:15 AM IST';
    } else if (totalMinutes < (9 * 60 + 15)) {
      nextOpenDesc = 'Opens today 09:15 AM IST';
    } else if (totalMinutes >= (15 * 60 + 30)) {
      nextOpenDesc = 'Opens tomorrow 09:15 AM IST';
    }

    const timeDisplay = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')} IST`;

    return {
      isOpen,
      weekday,
      timeDisplay,
      nextOpenDesc,
      statusText: isOpen ? 'MARKET OPEN' : 'MARKET CLOSED',
      subText: isOpen ? 'Live (Closes 15:30 IST)' : nextOpenDesc
    };
  }

  function updateMarketStatusUI() {
    const info = getMarketSessionInfo();

    if (marketStatusBadge) {
      marketStatusBadge.className = `tv-market-badge ${info.isOpen ? 'open' : 'closed'}`;
    }
    if (marketStatusText) {
      marketStatusText.textContent = info.statusText;
    }
    if (marketStatusSub) {
      marketStatusSub.textContent = info.subText;
    }
    if (dashMarketStatus) {
      dashMarketStatus.textContent = info.isOpen ? 'OPEN (Live)' : `CLOSED (${info.nextOpenDesc})`;
      dashMarketStatus.style.color = info.isOpen ? 'var(--tv-bull)' : 'var(--tv-text-muted)';
    }
  }

  // Update market status immediately and every second
  updateMarketStatusUI();
  setInterval(updateMarketStatusUI, 1000);

  // Fetch instruments list
  async function loadInstruments() {
    try {
      const res = await fetch('/api/instruments');
      const data = await res.json();
      
      stocksSelect.innerHTML = '<option value="">-- Equities --</option>';
      if (data.all_stocks) {
        for (const stock of data.all_stocks) {
          const opt = document.createElement('option');
          opt.value = stock.instrument_key;
          opt.textContent = `${stock.symbol}${!stock.enabled ? ' [Disabled]' : ''}`;
          stocksSelect.appendChild(opt);
        }
      }
    } catch (e) {
      console.error('Failed to load instruments:', e);
    }
  }

  function setLoadingState(isLoading) {
    if (chartLoadingBar) {
      if (isLoading) chartLoadingBar.classList.add('active');
      else chartLoadingBar.classList.remove('active');
    }
    if (activeTickerTitle) {
      if (isLoading) activeTickerTitle.classList.add('loading');
      else activeTickerTitle.classList.remove('loading');
    }
  }

  // Fetch chart data with instant visual feedback and clean synchronization
  async function loadChartData(isInitial = false) {
    if (activeAbortController) {
      activeAbortController.abort();
    }
    activeAbortController = new AbortController();
    const signal = activeAbortController.signal;

    if (isInitial) {
      setLoadingState(true);
    }

    try {
      const url = `/api/chart-data?instrument_key=${encodeURIComponent(currentInstrument)}&timeframe=${currentTimeframe}`;
      const res = await fetch(url, { signal });
      const data = await res.json();

      if (!data.candles || data.candles.length === 0) {
        setLoadingState(false);
        return;
      }

      lastCandles = data.candles;
      const lastCandle = data.candles[data.candles.length - 1];
      const prevCandle = data.candles.length > 1 ? data.candles[data.candles.length - 2] : lastCandle;
      const diff = lastCandle.close - prevCandle.close;
      const pct = (diff / prevCandle.close) * 100;

      activePrice.textContent = lastCandle.close.toFixed(2);
      priceChange.textContent = `${diff >= 0 ? '+' : ''}${diff.toFixed(2)} (${diff >= 0 ? '+' : ''}${pct.toFixed(2)}%)`;
      priceChange.className = `tv-chg-pill ${diff >= 0 ? 'positive' : 'negative'}`;

      updateOHLC(lastCandle);

      // Render chart data and ICT overlays in a single synchronized pass
      const shouldInitRange = isInitial || isFirstLoad;
      isFirstLoad = false;
      cachedIndicators = data.indicators;

      chart.setChartData({
        candles: data.candles,
        indicators: data.indicators,
        isInitial: shouldInitRange,
        options: getOverlayOptions()
      });

      updateDashboard(data.indicators);
      setLoadingState(false);

    } catch (e) {
      if (e.name !== 'AbortError') {
        console.error('Error fetching chart data:', e);
      }
      setLoadingState(false);
    }
  }

  function updateDashboard(ind) {
    if (!ind || !ind.dashboard) return;
    const db = ind.dashboard;

    dashSignal.textContent = db.signal;
    dashIPDA.textContent = db.ipda_phase;
    dashModel.textContent = db.last_model;
    dashCISD.textContent = db.cisd_state;
    dashBullSweep.textContent = db.bull_sweep_active;
    dashBearSweep.textContent = db.bear_sweep_active;
    dashPDHPDL.textContent = db.pdh_pdl;
    dashKZ.textContent = db.in_killzone;
    dashSB.textContent = db.silver_bullet;
    dashHTFBias.textContent = db.htf_bias;
    dashMode.textContent = db.mode;

    // Signal badge color
    const rawSig = db.signal.split(' ')[0];
    dashSignalBadge.textContent = rawSig;
    if (rawSig === 'BUY') {
      dashSignalBadge.className = 'tv-pine-badge buy';
    } else if (rawSig === 'SELL') {
      dashSignalBadge.className = 'tv-pine-badge sell';
    } else {
      dashSignalBadge.className = 'tv-pine-badge hold';
    }

    // Populate bottom alerts ticker
    if (ind.signals && ind.signals.length > 0) {
      signalsFeed.innerHTML = '';
      const recentSignals = ind.signals.slice(-4).reverse();
      for (const sig of recentSignals) {
        const item = document.createElement('span');
        const isBuy = sig.signal === 'BUY';
        item.className = `tv-alert-pill ${isBuy ? 'buy' : 'sell'}`;
        const timeStr = new Date(sig.time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        item.textContent = `${isBuy ? '🟢 BUY' : '🔴 SELL'} ${sig.model} @ ${sig.entry_price.toFixed(2)} [SL: ${sig.sl_price.toFixed(2)} | TP: ${sig.tp_price.toFixed(2)}] • ${timeStr}`;
        signalsFeed.appendChild(item);
      }
    } else {
      signalsFeed.innerHTML = '<span class="tv-alert-empty">Monitoring real-time order flow for liquidity sweeps and FVG touches...</span>';
    }
  }

  // Instrument switcher (NIFTY 50, BANK NIFTY, SENSEX)
  indicesButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      indicesButtons.forEach(b => b.classList.remove('active'));
      stocksSelect.value = '';
      btn.classList.add('active');
      currentInstrument = btn.dataset.symbol;
      currentInstrumentName = btn.textContent.trim();
      activeTickerTitle.textContent = currentInstrumentName;
      isFirstLoad = true;
      loadChartData(true);
    });
  });

  stocksSelect.addEventListener('change', () => {
    if (stocksSelect.value) {
      indicesButtons.forEach(b => b.classList.remove('active'));
      currentInstrument = stocksSelect.value;
      const opt = stocksSelect.options[stocksSelect.selectedIndex];
      currentInstrumentName = opt.textContent.split(' ')[0];
      activeTickerTitle.textContent = currentInstrumentName;
      isFirstLoad = true;
      loadChartData(true);
    }
  });

  // Timeframe switcher (1m, 5m, 15m)
  tfButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      tfButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentTimeframe = btn.dataset.tf;
      activeTimeframeBadge.textContent = currentTimeframe;
      isFirstLoad = true;
      loadChartData(true);
    });
  });

  // Toggles
  [toggleFVG, toggleOB, toggleLiq, toggleSignals].forEach(cb => {
    if (cb) {
      cb.addEventListener('change', () => {
        if (cachedIndicators && lastCandles.length > 0) {
          chart.setChartData({
            candles: lastCandles,
            indicators: cachedIndicators,
            isInitial: false,
            options: getOverlayOptions()
          });
        }
      });
    }
  });

  refreshBtn.addEventListener('click', () => {
    refreshBtn.style.transform = 'rotate(360deg)';
    setTimeout(() => refreshBtn.style.transform = '', 300);
    loadChartData(false);
  });

  // Sync active toolbar button with currentInstrument / currentTimeframe
  indicesButtons.forEach(btn => {
    if (btn.dataset.symbol === currentInstrument) {
      indicesButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }
  });
  tfButtons.forEach(btn => {
    if (btn.dataset.tf === currentTimeframe) {
      tfButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }
  });
  activeTickerTitle.textContent = currentInstrumentName;
  activeTimeframeBadge.textContent = currentTimeframe;

  // Initial load
  await loadInstruments();
  await loadChartData(true);

  if (window.lucide) {
    window.lucide.createIcons();
  }

  // Polling every 4 seconds for live data sync - strictly preserves exact zoom and scroll!
  setInterval(() => {
    loadChartData(false);
  }, 4000);
});
