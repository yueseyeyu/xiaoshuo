(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var danger = '#e74c3c';
  var warning = '#f39c12';
  var success = '#2ecc71';

  // Chart 1: Temperature Effect - Bias comparison
  var chart1 = echarts.init(document.getElementById('chart-temp-effect'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['Bias_I', 'MAE_I', 'Pearson r'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: ['Stored v8.12\n(temp=?)', 'v8.14 Fresh\n(temp=0.1)', 'v8.14 Reference\n(temp=0.0)', 'v8.15 Absolute\n(temp=0.0)'], axisLabel: { color: muted, fontSize: 10 } },
    yAxis: [
      { type: 'value', name: 'MAE / Bias', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
      { type: 'value', name: 'Pearson r', nameTextStyle: { color: muted }, axisLabel: { color: muted }, min: 0, max: 0.6, splitLine: { show: false } }
    ],
    series: [
      { name: 'Bias_I', type: 'bar', data: [1.859, 0.904, 0.415, -0.181], barGap: '15%',
        itemStyle: { color: function(p) { return p.value >= 0 ? accent2 : success; } },
        label: { show: true, position: 'top', color: ink, fontSize: 10, formatter: function(p) { return (p.value >= 0 ? '+' : '') + p.value.toFixed(3); } } },
      { name: 'MAE_I', type: 'bar', data: [2.141, 1.862, 1.989, 1.628],
        itemStyle: { color: accent + '99' },
        label: { show: true, position: 'top', color: ink, fontSize: 10, formatter: '{c:.3f}' } },
      { name: 'Pearson r', type: 'line', yAxisIndex: 1, data: [0.462, 0.381, 0.286, 0.494],
        lineStyle: { color: warning, width: 2.5 }, itemStyle: { color: warning }, symbol: 'diamond', symbolSize: 10,
        label: { show: true, color: warning, fontSize: 10, formatter: '{c:.3f}', distance: 10 } }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // Chart 2: Fair Comparison at temp=0.0
  var chart2 = echarts.init(document.getElementById('chart-fair-compare'), null, { renderer: 'svg' });
  chart2.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['Bias_I', 'MAE_I', 'Pearson r'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: ['Absolute (temp=0.0)\nv8.15', 'Reference (temp=0.0)\nv8.14'], axisLabel: { color: muted, fontSize: 10 } },
    yAxis: [
      { type: 'value', name: 'MAE / Bias', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
      { type: 'value', name: 'Pearson r', nameTextStyle: { color: muted }, axisLabel: { color: muted }, min: 0, max: 0.6, splitLine: { show: false } }
    ],
    series: [
      { name: 'Bias_I', type: 'bar', data: [-0.181, 0.415], barGap: '30%',
        itemStyle: { color: function(p) { return p.value >= 0 ? accent2 : success; } },
        label: { show: true, position: 'top', color: ink, fontSize: 11, formatter: function(p) { return (p.value >= 0 ? '+' : '') + p.value.toFixed(3); } } },
      { name: 'MAE_I', type: 'bar', data: [1.628, 1.989],
        itemStyle: { color: accent + '99' },
        label: { show: true, position: 'top', color: ink, fontSize: 11, formatter: '{c:.3f}' } },
      { name: 'Pearson r', type: 'line', yAxisIndex: 1, data: [0.494, 0.286],
        lineStyle: { color: warning, width: 2.5 }, itemStyle: { color: warning }, symbol: 'diamond', symbolSize: 12,
        label: { show: true, color: warning, fontSize: 11, formatter: '{c:.3f}', distance: 12 } }
    ]
  });
  window.addEventListener('resize', function() { chart2.resize(); });

  // Chart 3: Decomposition of Bias change
  var chart3 = echarts.init(document.getElementById('chart-decomposition'), null, { renderer: 'svg' });
  chart3.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['Bias Value'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: ['Stored v8.12', 'temp=0.0 effect\n(-1.085)', 'v8.15 Absolute\n(temp=0.0)', 'Reference\nchanges\n(+0.596)', 'v8.14 Reference\n(temp=0.0)'], axisLabel: { color: muted, fontSize: 9 } },
    yAxis: { type: 'value', name: 'Bias_I', nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    series: [{
      type: 'waterfall',
      data: [
        { name: 'Stored', value: 1.859 },
        { name: 'Temp effect', value: -1.085 },
        { name: 'v8.15 Abs', value: -0.181 },
        { name: 'Ref change', value: 0.596 },
        { name: 'v8.14 Ref', value: 0.415 }
      ].map(function(d, i) {
        return {
          name: d.name,
          value: d.value,
          itemStyle: { color: d.value >= 0 ? accent2 : success }
        };
      }),
      label: { show: true, position: 'top', color: ink, fontSize: 10, formatter: function(p) { return (p.value >= 0 ? '+' : '') + p.value.toFixed(3); } },
      barWidth: '50%'
    }]
  });
  window.addEventListener('resize', function() { chart3.resize(); });

  // Chart 4: Scatter - Human vs LLM at temp=0.0
  var chart4 = echarts.init(document.getElementById('chart-scatter-temp0'), null, { renderer: 'svg' });

  // v8.15 per-chapter data (from the JSON)
  var v15Pairs = [
    [1.5, 4], [1.5, 4], [2.0, 4], [2.5, 5], [2.0, 5], [2.5, 5], [2.5, 5], [3.5, 5], [3.5, 5],
    [3.0, 5], [3.5, 5], [3.0, 5], [4.0, 5], [4.0, 5], [4.5, 5], [4.5, 5], [4.5, 5],
    [5.0, 5], [5.5, 5], [5.5, 5], [5.5, 5], [5.5, 5], [5.5, 5], [6.0, 5], [6.0, 5],
    [6.5, 5], [6.5, 7], [6.5, 7], [6.5, 8], [7.0, 7], [7.0, 7], [7.0, 7], [7.0, 7],
    [7.5, 7], [7.5, 9], [7.5, 7], [7.5, 7], [7.5, 7], [8.0, 7], [8.0, 9],
    [8.5, 7], [8.5, 7], [8.5, 7], [9.0, 7], [9.0, 9]
  ];

  var v14RefPairs = [
    [1.5, 5], [1.5, 4], [2.0, 2.5], [2.5, 4], [2.0, 5.5], [2.5, 6.5], [2.5, 8.5],
    [3.5, 5], [3.5, 2.5], [3.0, 5.5], [3.5, 5.5], [3.0, 7.5], [4.0, 5.5], [4.0, 3.5],
    [4.5, 5.5], [4.5, 5], [4.5, 5.5], [4.5, 5.5], [5.0, 5.5], [5.5, 2.5], [5.5, 5.5],
    [5.5, 5.5], [5.5, 5], [5.5, 4.5], [6.0, 6], [6.0, 5], [6.5, 2], [6.5, 6],
    [6.5, 6.5], [6.5, 5.5], [7.0, 5.5], [7.0, 5], [7.0, 5.5], [7.0, 5.5], [7.5, 3],
    [7.5, 7.5], [7.5, 4.5], [7.5, 5.5], [7.5, 5.5], [8.0, 5.5], [8.0, 5],
    [8.5, 4.5], [8.5, 5.5], [8.5, 5.5], [9.0, 8.5], [9.0, 7.5]
  ];

  chart4.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      formatter: function(p) { return 'Human: ' + p.value[0] + ' / LLM: ' + p.value[1]; }
    },
    legend: { data: ['Absolute (temp=0.0)', 'Reference (temp=0.0)', 'Perfect'], textStyle: { color: muted }, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
    xAxis: { type: 'value', name: 'Human Intensity', min: 0, max: 10, nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    yAxis: { type: 'value', name: 'LLM Intensity', min: 0, max: 10, nameTextStyle: { color: muted }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    series: [
      { name: 'Absolute (temp=0.0)', type: 'scatter', data: v15Pairs, symbolSize: 10, itemStyle: { color: success, opacity: 0.7 } },
      { name: 'Reference (temp=0.0)', type: 'scatter', data: v14RefPairs, symbolSize: 8, itemStyle: { color: accent2, opacity: 0.5 } },
      { name: 'Perfect', type: 'line', data: [[0,0],[10,10]], lineStyle: { color: rule, type: 'dashed', width: 1 }, symbol: 'none', z: 0 }
    ]
  });
  window.addEventListener('resize', function() { chart4.resize(); });
})();