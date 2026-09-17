/**
 * ICT TradingView Native Chart Engine
 * Built with the official Lightweight Charts Series Primitive API (attachPrimitive)
 * Featuring ResizeObserver, robust zOrder functions, and full Pine Script visual parity.
 */

class ICTPrimitive {
  constructor(chartObj) {
    this._owner = chartObj;
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
  }

  attached({ chart, series, requestUpdate }) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
  }

  detached() {
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
  }

  updateAllViews() {}

  paneViews() {
    return [
      {
        zOrder: () => 'normal',
        renderer: () => ({
          draw: (target) => {
            try {
              target.useMediaCoordinateSpace((scope) => {
                this._draw(scope.context, scope.mediaSize.width, scope.mediaSize.height);
              });
            } catch (err) {
              console.warn('ICTPrimitive draw exception:', err);
            }
          }
        })
      }
    ];
  }

  _draw(ctx, width, height) {
    const chart = this._chart;
    const series = this._series;
    const ind = this._owner.indicators;
    const opts = this._owner.options;
    const candles = this._owner.candles;

    if (!chart || !series || !ind || !candles || candles.length === 0) return;

    const n = candles.length;
    const timeScale = chart.timeScale();

    // Robust bar-to-X coordinate with offscreen linear fallback
    const refBar = n - 1;
    const refX = timeScale.logicalToCoordinate(refBar);
    const refXPrev = timeScale.logicalToCoordinate(refBar - 1);
    const estBarSpacing = (refX !== null && refXPrev !== null && Math.abs(refX - refXPrev) > 0.1)
      ? (refX - refXPrev)
      : 18;

    const barToX = idx => {
      const x = timeScale.logicalToCoordinate(idx);
      if (x !== null && !isNaN(x)) return x;
      if (refX !== null) return refX + (idx - refBar) * estBarSpacing;
      return null;
    };
    
    // Robust price-to-Y coordinate with offscreen linear fallback
    const lastPrice = candles[n - 1].close;
    const refY = series.priceToCoordinate(lastPrice);
    const refYPlus = series.priceToCoordinate(lastPrice + 50);
    const priceScale = (refY !== null && refYPlus !== null) ? (refYPlus - refY) / 50 : -1;

    const priceToY = price => {
      const y = series.priceToCoordinate(price);
      if (y !== null && !isNaN(y)) return y;
      if (refY !== null) return refY + (price - lastPrice) * priceScale;
      return null;
    };

    // =========================================================================
    // 0. BIAS BACKGROUND TINT (Section 5b of Pine Script)
    // =========================================================================
    const biasState = ind.dashboard ? ind.dashboard.bias_state : 'NEUTRAL';
    if (biasState === 'BULLISH') {
      ctx.save();
      ctx.fillStyle = 'rgba(8, 153, 129, 0.04)';
      ctx.fillRect(0, 0, width, height);
      ctx.restore();
    } else if (biasState === 'BEARISH') {
      ctx.save();
      ctx.fillStyle = 'rgba(242, 54, 69, 0.04)';
      ctx.fillRect(0, 0, width, height);
      ctx.restore();
    }

    // =========================================================================
    // 1. FAIR VALUE GAPS (FVG Boxes + 3-Candle Outline Boxes)
    // =========================================================================
    if (opts.showFVG && ind.fvg_zones) {
      for (const fvg of ind.fvg_zones) {
        const startBar = fvg.start_bar !== undefined ? fvg.start_bar : Math.max(0, fvg.bar_index - 2);
        const endBar = fvg.end_bar !== undefined ? fvg.end_bar : Math.min(n + 25, fvg.bar_index + 20);

        const x1 = barToX(startBar);
        const x2 = barToX(endBar);
        const yTop = priceToY(fvg.top);
        const yBot = priceToY(fvg.bottom);

        if (x1 === null || x2 === null || yTop === null || yBot === null) continue;

        const boxX = Math.min(x1, x2);
        const boxW = Math.max(Math.abs(x2 - x1), 15);
        const boxY = Math.min(yTop, yBot);
        const boxH = Math.max(Math.abs(yBot - yTop), 3);

        if (boxX + boxW < -200 || boxX > width + 200) continue;

        ctx.save();
        if (fvg.mitigated) {
          ctx.fillStyle = 'rgba(120, 123, 134, 0.1)';
          ctx.strokeStyle = 'rgba(120, 123, 134, 0.4)';
        } else if (fvg.excluded_fake) {
          ctx.fillStyle = 'rgba(120, 123, 134, 0.08)';
          ctx.strokeStyle = 'rgba(120, 123, 134, 0.3)';
        } else if (fvg.is_bullish) {
          ctx.fillStyle = 'rgba(8, 153, 129, 0.18)';
          ctx.strokeStyle = 'rgba(8, 153, 129, 0.8)';
        } else {
          ctx.fillStyle = 'rgba(242, 54, 69, 0.18)';
          ctx.strokeStyle = 'rgba(242, 54, 69, 0.8)';
        }

        ctx.lineWidth = 1;
        ctx.fillRect(boxX, boxY, boxW, boxH);
        ctx.strokeRect(boxX, boxY, boxW, boxH);

        // 50% Consequent Encroachment (CE) Dotted Midpoint Line
        const yCE = (yTop + yBot) / 2;
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = fvg.is_bullish ? 'rgba(8, 153, 129, 0.6)' : 'rgba(242, 54, 69, 0.6)';
        ctx.beginPath();
        ctx.moveTo(boxX, yCE);
        ctx.lineTo(boxX + boxW, yCE);
        ctx.stroke();

        // Label inside box
        ctx.setLineDash([]);
        ctx.font = 'bold 9px -apple-system, sans-serif';
        ctx.fillStyle = fvg.mitigated || fvg.excluded_fake ? '#787b86' : (fvg.is_bullish ? '#26a69a' : '#ef5350');
        const tag = fvg.mitigated ? 'Mitigated FVG' : fvg.excluded_fake ? 'Fake FVG' : (fvg.is_bullish ? 'Bullish FVG' : 'Bearish FVG') + ' (' + fvg.tier + ')';
        ctx.fillText(tag, boxX + 6, boxY + Math.min(boxH - 3, 11));

        // Highlight the 3 forming candles with dashed yellow box (Pine Script feature)
        if (fvg.c1_high && fvg.c3_high) {
          const c1X = barToX(startBar);
          const c3X = barToX(fvg.bar_index);
          const cTopY = priceToY(Math.max(fvg.c1_high, fvg.c3_high));
          const cBotY = priceToY(Math.min(fvg.c1_low, fvg.c3_low));
          if (c1X !== null && c3X !== null && cTopY !== null && cBotY !== null) {
            ctx.strokeStyle = 'rgba(255, 214, 0, 0.4)';
            ctx.setLineDash([2, 2]);
            ctx.strokeRect(c1X - 6, cTopY - 2, (c3X - c1X) + 12, (cBotY - cTopY) + 4);
            ctx.fillStyle = '#ffd600';
            ctx.font = '8px -apple-system, sans-serif';
            ctx.fillText('① ② ③ FVG', c1X - 4, cTopY - 4);
          }
        }
        ctx.restore();
      }
    }

    // =========================================================================
    // 2. ORDER BLOCKS & BREAKER BLOCKS
    // =========================================================================
    if (opts.showOB && ind.order_blocks) {
      for (const ob of ind.order_blocks) {
        const startBar = ob.start_bar !== undefined ? ob.start_bar : ob.bar_index;
        const endBar = ob.end_bar !== undefined ? ob.end_bar : Math.min(n + 25, ob.bar_index + 20);

        const x1 = barToX(startBar);
        const x2 = barToX(endBar);
        const yTop = priceToY(ob.top);
        const yBot = priceToY(ob.bottom);

        if (x1 === null || x2 === null || yTop === null || yBot === null) continue;

        const boxX = Math.min(x1, x2);
        const boxW = Math.max(Math.abs(x2 - x1), 15);
        const boxY = Math.min(yTop, yBot);
        const boxH = Math.max(Math.abs(yBot - yTop), 3);

        if (boxX + boxW < -200 || boxX > width + 200) continue;

        ctx.save();
        if (ob.is_breaker) {
          ctx.fillStyle = 'rgba(156, 39, 176, 0.18)';
          ctx.strokeStyle = 'rgba(186, 104, 200, 0.85)';
        } else if (ob.is_bullish) {
          ctx.fillStyle = 'rgba(41, 98, 255, 0.18)';
          ctx.strokeStyle = 'rgba(41, 98, 255, 0.85)';
        } else {
          ctx.fillStyle = 'rgba(255, 109, 0, 0.18)';
          ctx.strokeStyle = 'rgba(255, 109, 0, 0.85)';
        }

        ctx.lineWidth = 1;
        ctx.fillRect(boxX, boxY, boxW, boxH);
        ctx.strokeRect(boxX, boxY, boxW, boxH);

        ctx.font = 'bold 9px -apple-system, sans-serif';
        ctx.fillStyle = ob.is_breaker ? '#ce93d8' : ob.is_bullish ? '#82b1ff' : '#ffb74d';
        const label = ob.is_breaker ? ((ob.is_bullish ? 'Bullish' : 'Bearish') + ' Breaker') : ((ob.is_bullish ? 'Bullish' : 'Bearish') + ' OB');
        ctx.fillText(label, boxX + 6, boxY + Math.min(boxH - 3, 11));
        ctx.restore();
      }
    }

    // =========================================================================
    // 3. LIQUIDITY POOLS (EQH / EQL / BSL / SSL Dotted Lines)
    // =========================================================================
    if (opts.showLiq && ind.liquidity_levels) {
      for (const lq of ind.liquidity_levels) {
        const startBar = lq.start_bar !== undefined ? lq.start_bar : lq.bar_index;
        const endBar = lq.end_bar !== undefined ? lq.end_bar : Math.min(n + 25, lq.bar_index + 20);

        const x1 = barToX(startBar);
        const x2 = barToX(endBar);
        const y = priceToY(lq.price);

        if (x1 === null || x2 === null || y === null) continue;

        ctx.save();
        ctx.strokeStyle = lq.is_eq ? '#ffd600' : (lq.tier === 'BSL' ? '#e040fb' : '#00e5ff');
        ctx.lineWidth = lq.is_eq ? 1.5 : 1;
        ctx.setLineDash([4, 4]);

        ctx.beginPath();
        ctx.moveTo(x1, y);
        ctx.lineTo(x2, y);
        ctx.stroke();

        ctx.setLineDash([]);
        ctx.font = 'bold 9px -apple-system, sans-serif';
        ctx.fillStyle = lq.is_eq ? '#ffd600' : '#d1d4dc';
        ctx.fillText(lq.tier + ' (' + lq.price.toFixed(1) + ')', x1 + 4, y - 3);
        ctx.restore();
      }
    }

    // =========================================================================
    // 4. PREDICTIVE SIGNALS & TARGET LINES (SL & TP)
    // =========================================================================
    if (opts.showSignals && ind.signals) {
      for (const s of ind.signals) {
        const x = barToX(s.bar_index);
        const yEntry = priceToY(s.entry_price);
        const ySL = priceToY(s.sl_price);
        const yTP = priceToY(s.tp_price);
        const xEnd = barToX(s.bar_index + 15) || (x + 120);

        if (x === null || yEntry === null) continue;

        const isBuy = s.signal === 'BUY';
        ctx.save();

        // Signal Arrow & Pill Badge
        ctx.fillStyle = isBuy ? '#089981' : '#f23645';
        const tagY = isBuy ? yEntry + 32 : yEntry - 32;

        ctx.beginPath();
        ctx.roundRect(x - 48, tagY - 10, 96, 20, 4);
        ctx.fill();

        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 9px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(s.signal + ' [' + s.model + ']', x, tagY + 3);

        // SL Line (Dotted Red)
        if (ySL !== null) {
          ctx.strokeStyle = '#f23645';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(x, ySL);
          ctx.lineTo(xEnd, ySL);
          ctx.stroke();

          ctx.fillStyle = '#f23645';
          ctx.textAlign = 'left';
          ctx.fillText('SL: ' + s.sl_price.toFixed(1), xEnd + 4, ySL + 3);
        }

        // TP Line (Dotted Green)
        if (yTP !== null) {
          ctx.strokeStyle = '#089981';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(x, yTP);
          ctx.lineTo(xEnd, yTP);
          ctx.stroke();

          ctx.fillStyle = '#089981';
          ctx.fillText('TP: ' + s.tp_price.toFixed(1) + ' (2:1)', xEnd + 4, yTP + 3);
        }
        ctx.restore();
      }
    }

    // =========================================================================
    // 5. SILVER BULLET MODEL (Dedicated Entries & Win/Loss Badges)
    // =========================================================================
    if (opts.showSignals && ind.silver_bullet_events) {
      for (const ev of ind.silver_bullet_events) {
        const x = barToX(ev.bar_index);
        const y = priceToY(ev.price);
        if (x === null || y === null) continue;

        ctx.save();
        if (ev.type.includes('BUY') || ev.type.includes('SELL')) {
          ctx.fillStyle = '#00f0ff';
          ctx.beginPath();
          ctx.arc(x, y, 5, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = '#00f0ff';
          ctx.font = 'bold 9px -apple-system, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('🥈 SB ' + (ev.type.includes('BUY') ? 'BUY' : 'SELL'), x, y - 10);
        } else if (ev.type === 'TP_HIT') {
          ctx.fillStyle = '#089981';
          ctx.font = 'bold 9px -apple-system, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('🥈 TP HIT (WIN) 🎯', x, y - 8);
        } else if (ev.type === 'SL_HIT') {
          ctx.fillStyle = '#f23645';
          ctx.font = 'bold 9px -apple-system, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('🥈 SL HIT (LOSS) 🛑', x, y + 14);
        } else if (ev.type === 'TIME_BOXED_EXIT') {
          ctx.fillStyle = '#ff9800';
          ctx.font = 'bold 9px -apple-system, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('🥈 Killzone Ended ⏱️', x, y - 8);
        }
        ctx.restore();
      }
    }
  }
}

class ICTChart {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.chart = null;
    this.candleSeries = null;
    this.priceLines = [];
    this.candles = [];
    this.indicators = null;
    this.options = {
      showFVG: true,
      showOB: true,
      showLiq: true,
      showSignals: true
    };

    this.initChart();
  }

  initChart() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || (window.innerHeight - 80);

    this.chart = LightweightCharts.createChart(this.container, {
      width: width,
      height: height,
      layout: {
        background: { color: '#131722' },
        textColor: '#d1d4dc',
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, sans-serif"
      },
      grid: {
        vertLines: { color: 'rgba(42, 46, 57, 0.4)' },
        horzLines: { color: 'rgba(42, 46, 57, 0.4)' }
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: '#758696', width: 1, style: 3, labelBackgroundColor: '#2a2e39' },
        horzLine: { color: '#758696', width: 1, style: 3, labelBackgroundColor: '#2a2e39' }
      },
      rightPriceScale: {
        borderColor: '#2a2e39',
        visible: true,
        scaleMargins: { top: 0.12, bottom: 0.12 },
        autoScale: true,
        alignLabels: true
      },
      timeScale: {
        borderColor: '#2a2e39',
        timeVisible: true,
        secondsVisible: false,
        barSpacing: 18,
        minBarSpacing: 3,
        rightOffset: 12,
        shiftVisibleRangeOnNewBar: true,
        allowBoldLabels: true
      }
    });

    // Bright, high-contrast, thick TradingView candlesticks
    this.candleSeries = this.chart.addCandlestickSeries({
      upColor: '#089981',
      downColor: '#f23645',
      borderVisible: true,
      borderUpColor: '#089981',
      borderDownColor: '#f23645',
      wickVisible: true,
      wickUpColor: '#089981',
      wickDownColor: '#f23645'
    });

    // Attach native series primitive safely
    try {
      this.primitive = new ICTPrimitive(this);
      this.candleSeries.attachPrimitive(this.primitive);
    } catch (err) {
      console.warn('attachPrimitive fallback:', err);
    }

    // Modern ResizeObserver with change threshold to prevent micro-jitter during wheel zooms
    if (window.ResizeObserver) {
      let prevW = 0, prevH = 0;
      const ro = new ResizeObserver(entries => {
        for (const entry of entries) {
          const cr = entry.contentRect;
          const w = Math.round(cr.width);
          const h = Math.round(cr.height);
          if (w > 0 && h > 0 && (Math.abs(w - prevW) > 2 || Math.abs(h - prevH) > 2)) {
            prevW = w;
            prevH = h;
            this.chart.applyOptions({ width: w, height: h });
          }
        }
      });
      ro.observe(this.container);
    } else {
      window.addEventListener('resize', () => {
        if (this.chart && this.container) {
          this.chart.applyOptions({
            width: this.container.clientWidth,
            height: this.container.clientHeight
          });
        }
      });
    }
  }

  setChartData({ candles, indicators, isInitial = false, options = {} }) {
    if (!candles || candles.length === 0) return;

    // 1. Remove ALL existing price lines FIRST before setting candle data!
    for (const pl of this.priceLines) {
      try {
        this.candleSeries.removePriceLine(pl);
      } catch (e) {}
    }
    this.priceLines = [];

    // 2. Synchronize indicators & options
    if (indicators) this.indicators = indicators;
    this.options = { ...this.options, ...options };

    // 3. Sort and set candles
    this.candles = [...candles].sort((a, b) => a.time - b.time);
    const n = this.candles.length;
    this.candleSeries.setData(this.candles);

    // 4. Force right price scale to auto-scale cleanly to the new asset
    this.chart.priceScale('right').applyOptions({
      autoScale: true
    });

    // 5. Handle horizontal logical time scale
    if (isInitial) {
      this.chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, n - 70),
        to: n + 10
      });
    } else {
      const currentRange = this.chart.timeScale().getVisibleLogicalRange();
      if (currentRange) {
        this.chart.timeScale().setVisibleLogicalRange(currentRange);
      }
    }

    // 6. Add NEW price lines for the new asset (PDH / PDL)
    if (this.options.showLiq && this.indicators) {
      if (this.indicators.pdh) {
        const pdhLine = this.candleSeries.createPriceLine({
          price: this.indicators.pdh,
          color: 'rgba(179, 136, 255, 0.9)',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'PDH'
        });
        this.priceLines.push(pdhLine);
      }
      if (this.indicators.pdl) {
        const pdlLine = this.candleSeries.createPriceLine({
          price: this.indicators.pdl,
          color: 'rgba(179, 136, 255, 0.9)',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'PDL'
        });
        this.priceLines.push(pdlLine);
      }
    }

    // 7. Repaint primitives with matching data and price scale
    if (this.primitive && this.primitive._requestUpdate) {
      this.primitive._requestUpdate();
    }
  }

  setData(candles, isInitial = false) {
    this.setChartData({ candles, indicators: this.indicators, isInitial, options: this.options });
  }

  zoomIn() {
    const range = this.chart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const span = range.to - range.from;
    const newSpan = Math.max(10, span * 0.75);
    const center = (range.from + range.to) / 2;
    this.chart.timeScale().setVisibleLogicalRange({
      from: center - newSpan / 2,
      to: center + newSpan / 2
    });
  }

  zoomOut() {
    const range = this.chart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const span = range.to - range.from;
    const newSpan = span * 1.35;
    const center = (range.from + range.to) / 2;
    this.chart.timeScale().setVisibleLogicalRange({
      from: center - newSpan / 2,
      to: center + newSpan / 2
    });
  }

  resetZoom() {
    const n = this.candles.length;
    if (n === 0) return;
    this.chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, n - 70),
      to: n + 10
    });
  }

  renderICTOverlays(indicators, options = {}) {
    this.indicators = indicators;
    this.options = { ...this.options, ...options };

    // Clear old price lines
    for (const pl of this.priceLines) {
      try {
        this.candleSeries.removePriceLine(pl);
      } catch (e) {}
    }
    this.priceLines = [];

    // PDH / PDL Steplines
    if (this.options.showLiq && indicators) {
      if (indicators.pdh) {
        const pdhLine = this.candleSeries.createPriceLine({
          price: indicators.pdh,
          color: 'rgba(179, 136, 255, 0.9)',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'PDH'
        });
        this.priceLines.push(pdhLine);
      }
      if (indicators.pdl) {
        const pdlLine = this.candleSeries.createPriceLine({
          price: indicators.pdl,
          color: 'rgba(179, 136, 255, 0.9)',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'PDL'
        });
        this.priceLines.push(pdlLine);
      }
    }

    if (this.primitive && this.primitive._requestUpdate) {
      this.primitive._requestUpdate();
    }
  }
}

window.ICTChart = ICTChart;
