(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var bg = style.getPropertyValue('--bg').trim();

  var danger = '#e74c3c';
  var warning = '#f39c12';
  var success = '#27ae60';

  // --- Chart 1: Method Comparison (MAE, Bias, r) ---
  var chart1 = echarts.init(document.getElementById('chart-method-compare'), null, { renderer: 'svg' });
  var methods = ['Raw Absolute', 'Reference', 'Bias-Corr', 'WLS v8.12', 'OLS (47ch)'];
  var maeData = [1.862, 1.989, 1.830, 1.634, 1.561];
  var biasData = [0.904, 0.415, 0.415, -0.385, 0.000];
  var rData = [0.381, 0.286, 0.381, 0.381, 0.381];

  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['MAE', 'Bias', 'Pearson r'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: methods, axisLabel: { color: muted, fontSize: 11, rotate: 15 } },
    yAxis: [
      { type: 'value', name: 'MAE / Bias', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
      { type: 'value', name: 'Pearson r', nameTextStyle: { color: muted }, axisLabel: { color: muted }, min: 0, max: 0.5, splitLine: { show: false } }
    ],
    series: [
      { name: 'MAE', type: 'bar', data: maeData, itemStyle: { color: accent }, barGap: '10%' },
      { name: 'Bias', type: 'bar', data: biasData, itemStyle: { color: function(p) { return p.value >= 0 ? accent2 : danger; } } },
      { name: 'Pearson r', type: 'line', yAxisIndex: 1, data: rData, lineStyle: { color: warning, width: 2 }, itemStyle: { color: warning }, symbol: 'diamond', symbolSize: 8 }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // --- Chart 2: Scatter - Human vs LLM Scores ---
  var chart2 = echarts.init(document.getElementById('chart-scatter'), null, { renderer: 'svg' });

  var scatterPairs = [
    [1.5, 7, 5], [1.5, 4, 4], [2.0, 4, 2.5], [2.5, 5, 4], [2.0, 7, 5.5], [2.5, 8, 6.5], [2.5, 8, 8.5],
    [3.5, 5, 5], [3.5, 5, 2.5], [3.0, 8, 5.5], [3.5, 8, 5.5], [3.0, 3, 7.5],
    [4.0, 5, 5.5], [4.0, 5, 3.5], [4.5, 6, 5.5], [4.5, 5, 5], [4.5, 5, 5.5], [4.5, 5, 5.5],
    [5.0, 6, 5.5], [5.5, 5, 2.5], [5.5, 6, 5.5], [5.5, 4, 5.5], [5.5, 7, 5], [5.5, 5, 4.5],
    [6.0, 6, 6], [6.0, 7, 5], [6.5, 6, 2], [6.5, 6, 6], [6.5, 5, 6.5], [6.5, 5, 5.5],
    [7.0, 7, 5.5], [7.0, 7, 5], [7.0, 7, 5.5], [7.0, 7, 5.5], [7.5, 7, 3], [7.5, 9, 7.5],
    [7.5, 7, 4.5], [7.5, 5, 5.5], [7.5, 7, 5.5], [7.5, 5, 5.5],
    [8.0, 9, 5.5], [8.0, 8, 5], [8.5, 5, 4.5], [8.5, 7, 5.5], [8.5, 8, 5.5],
    [9.0, 9, 8.5], [9.0, 8, 7.5]
  ];

  var absScatter = scatterPairs.map(function(d) { return [d[0], d[1]]; });
  var refScatter = scatterPairs.map(function(d) { return [d[0], d[2]]; });

  chart2.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      formatter: function(p) { return 'Human: ' + p.value[0] + '<br/>LLM: ' + p.value[1]; }
    },
    legend: { data: ['Absolute', 'Reference', 'Perfect'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'value', name: 'Human Intensity', min: 0, max: 10, nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    yAxis: { type: 'value', name: 'LLM Intensity', min: 0, max: 10, nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    series: [
      { name: 'Absolute', type: 'scatter', data: absScatter, symbolSize: 10, itemStyle: { color: accent2, opacity: 0.7 } },
      { name: 'Reference', type: 'scatter', data: refScatter, symbolSize: 10, itemStyle: { color: accent, opacity: 0.7 } },
      { name: 'Perfect', type: 'line', data: [[0,0],[10,10]], lineStyle: { color: rule, type: 'dashed', width: 1 }, symbol: 'none', z: 0 }
    ]
  });
  window.addEventListener('resize', function() { chart2.resize(); });

  // --- Chart 3: Bootstrap Distribution ---
  var chart3 = echarts.init(document.getElementById('chart-bootstrap'), null, { renderer: 'svg' });

  var bootData = [];
  var rng = 42;
  for (var i = 0; i < 10000; i++) {
    rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF;
    var samp = 0;
    for (var j = 0; j < 47; j++) {
      rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF;
      var idx = ((rng >>> 0) % 47);
      samp += [
        -3.5, 0.5, 1.5, -0.5, -1.5, 0.5, 2.5, 1.5, -1.5, -0.5,
        -0.5, -2.5, 0.5, -0.5, 1.5, 0.5, 0.5, -0.5, -0.5, -2.5,
        2.5, 0.5, -0.5, 0.5, 0.5, -0.5, -3.5, 0.5, 0.5, 0.5,
        -0.5, 0.5, -0.5, 0.5, 1.5, 1.5, -0.5, 0.5, 0.5, -1.5,
        2.5, 0.5, -0.5, 0.5, 1.5, 0.5, 0.5
      ][idx];
    }
    bootData.push(samp / 47);
  }
  bootData.sort(function(a, b) { return a - b; });

  var hist = {};
  var binWidth = 0.05;
  bootData.forEach(function(v) {
    var bin = Math.round(v / binWidth) * binWidth;
    hist[bin] = (hist[bin] || 0) + 1;
  });
  var histData = Object.keys(hist).map(function(k) { return [parseFloat(k), hist[k]]; });

  var ciLow = bootData[250];
  var ciHigh = bootData[9750];

  chart3.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: { type: 'value', name: 'Bias Difference (abs - ref)', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    yAxis: { type: 'value', name: 'Frequency', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    series: [{
      type: 'bar', data: histData, itemStyle: { color: accent, opacity: 0.8 },
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          { xAxis: ciLow, lineStyle: { color: danger, type: 'dashed', width: 2 }, label: { formatter: 'CI low: ' + ciLow.toFixed(3), color: danger } },
          { xAxis: 0, lineStyle: { color: ink, type: 'solid', width: 2 }, label: { formatter: 'Zero', color: ink } },
          { xAxis: ciHigh, lineStyle: { color: danger, type: 'dashed', width: 2 }, label: { formatter: 'CI high: ' + ciHigh.toFixed(3), color: danger } }
        ]
      }
    }]
  });
  window.addEventListener('resize', function() { chart3.resize(); });

  // --- Chart 4: K-Fold Offset Stability ---
  var chart4 = echarts.init(document.getElementById('chart-kfold'), null, { renderer: 'svg' });

  var folds = ['Fold 1', 'Fold 2', 'Fold 3', 'Fold 4', 'Fold 5'];
  var offsets = [0.421, 0.382, 0.513, 0.645, 0.486];
  var maeAbs = [1.444, 2.056, 2.556, 1.111, 2.091];
  var maeCorr = [1.585, 1.928, 2.501, 1.039, 2.047];

  chart4.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['Offset', 'MAE (raw)', 'MAE (corrected)'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: folds, axisLabel: { color: muted } },
    yAxis: [
      { type: 'value', name: 'MAE', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
      { type: 'value', name: 'Offset', nameTextStyle: { color: muted }, axisLabel: { color: muted }, min: 0.3, max: 0.7, splitLine: { show: false } }
    ],
    series: [
      { name: 'MAE (raw)', type: 'bar', data: maeAbs, itemStyle: { color: accent2, opacity: 0.7 }, barGap: '10%' },
      { name: 'MAE (corrected)', type: 'bar', data: maeCorr, itemStyle: { color: accent, opacity: 0.9 } },
      { name: 'Offset', type: 'line', yAxisIndex: 1, data: offsets, lineStyle: { color: warning, width: 2 }, itemStyle: { color: warning }, symbol: 'circle', symbolSize: 8 }
    ]
  });
  window.addEventListener('resize', function() { chart4.resize(); });

  // --- Chart 5: Run-to-Run Variance ---
  var chart5 = echarts.init(document.getElementById('chart-run-variance'), null, { renderer: 'svg' });

  chart5.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['Bias (Intensity)', 'Bias (Retention)'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: ['Stored v8.12', 'Fresh v8.14', 'Reference v8.14'], axisLabel: { color: muted, fontSize: 11 } },
    yAxis: { type: 'value', name: 'Bias', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    series: [
      { name: 'Bias (Intensity)', type: 'bar', data: [1.859, 0.904, 0.415], itemStyle: { color: accent }, label: { show: true, position: 'top', color: ink, formatter: function(p) { return '+' + p.value.toFixed(3); } } },
      { name: 'Bias (Retention)', type: 'bar', data: [1.346, 0.670, 0.181], itemStyle: { color: accent2 }, label: { show: true, position: 'top', color: ink, formatter: function(p) { return '+' + p.value.toFixed(3); } } }
    ]
  });
  window.addEventListener('resize', function() { chart5.resize(); });
})();