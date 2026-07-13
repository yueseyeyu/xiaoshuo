// assets/charts.js — 评分系统评审报告图表
(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // ========== Chart 1: 模型规模 vs 评判一致性 ==========
  var chart1 = echarts.init(document.getElementById('chart-model-size'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: {
      data: ['与GPT-4一致性', '传递性一致性(优化后)'],
      textStyle: { color: muted, fontSize: 12 },
      top: 0
    },
    grid: { left: 50, right: 30, top: 50, bottom: 40 },
    xAxis: {
      type: 'category',
      data: ['3B', '7B', '8B', '13B', '32B', '70B'],
      axisLabel: { color: muted, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'value',
      min: 40,
      max: 100,
      name: '一致性 (%)',
      nameTextStyle: { color: muted, fontSize: 11 },
      axisLabel: { color: muted, fontSize: 11 },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } }
    },
    series: [
      {
        name: '与GPT-4一致性',
        type: 'bar',
        data: [55, 78, 80, 86, 90, 93],
        itemStyle: { color: accent2, borderRadius: [4, 4, 0, 0] },
        barWidth: '30%',
        label: {
          show: true,
          position: 'top',
          color: ink,
          fontSize: 11,
          fontWeight: 600,
          formatter: '{c}%'
        }
      },
      {
        name: '传递性一致性(优化后)',
        type: 'line',
        data: [45, 72, 82, 88, 92, 95],
        smooth: true,
        lineStyle: { color: accent, width: 2.5 },
        itemStyle: { color: accent },
        symbol: 'circle',
        symbolSize: 8
      }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // ========== Chart 2: Lost in the Middle U型曲线 ==========
  var chart2 = echarts.init(document.getElementById('chart-lost-in-middle'), null, { renderer: 'svg' });
  chart2.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: {
      data: ['GPT-3.5', '7B小模型(近因偏差为主)', '随机基线'],
      textStyle: { color: muted, fontSize: 12 },
      top: 0
    },
    grid: { left: 55, right: 30, top: 55, bottom: 45 },
    xAxis: {
      type: 'category',
      data: ['位置0%', '位置20%', '位置40%', '位置60%', '位置80%', '位置100%'],
      axisLabel: { color: muted, fontSize: 11 },
      axisLine: { lineStyle: { color: rule } },
      name: '关键信息在上下文中的位置',
      nameTextStyle: { color: muted, fontSize: 11, padding: [10, 0, 0, 0] }
    },
    yAxis: {
      type: 'value',
      min: 30,
      max: 90,
      name: '准确率 (%)',
      nameTextStyle: { color: muted, fontSize: 11 },
      axisLabel: { color: muted, fontSize: 11 },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } }
    },
    series: [
      {
        name: 'GPT-3.5',
        type: 'line',
        data: [82, 70, 54, 58, 72, 80],
        smooth: true,
        lineStyle: { color: accent2, width: 2.5 },
        itemStyle: { color: accent2 },
        symbol: 'circle',
        symbolSize: 7,
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: accent2 + '33' },
              { offset: 1, color: accent2 + '05' }
            ]
          }
        }
      },
      {
        name: '7B小模型(近因偏差为主)',
        type: 'line',
        data: [60, 52, 42, 45, 55, 75],
        smooth: true,
        lineStyle: { color: accent, width: 2.5, type: 'dashed' },
        itemStyle: { color: accent },
        symbol: 'diamond',
        symbolSize: 7
      },
      {
        name: '随机基线',
        type: 'line',
        data: [50, 50, 50, 50, 50, 50],
        lineStyle: { color: muted, width: 1, type: 'dotted' },
        itemStyle: { color: muted },
        symbol: 'none'
      }
    ]
  });
  window.addEventListener('resize', function() { chart2.resize(); });

  // ========== Chart 3: 边际收益曲线 ==========
  var chart3 = echarts.init(document.getElementById('chart-margin-return'), null, { renderer: 'svg' });
  chart3.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: {
      data: ['评分质量', '边际收益', '投入成本'],
      textStyle: { color: muted, fontSize: 12 },
      top: 0
    },
    grid: { left: 55, right: 55, top: 55, bottom: 50 },
    xAxis: {
      type: 'category',
      data: ['v1 原型', 'v3 基础', 'v5 完善', 'v8 优化', 'v10 当前', 'v12 校准', 'v15 天花板'],
      axisLabel: { color: muted, fontSize: 11, rotate: 20 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: [
      {
        type: 'value',
        name: '质量/收益 (0-100)',
        nameTextStyle: { color: muted, fontSize: 11 },
        min: 0, max: 100,
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } }
      },
      {
        type: 'value',
        name: '成本 (人日)',
        nameTextStyle: { color: muted, fontSize: 11 },
        min: 0, max: 100,
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '评分质量',
        type: 'line',
        data: [20, 45, 60, 72, 78, 84, 88],
        smooth: true,
        lineStyle: { color: accent2, width: 3 },
        itemStyle: { color: accent2 },
        symbol: 'circle',
        symbolSize: 8,
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: accent2 + '44' },
              { offset: 1, color: accent2 + '05' }
            ]
          }
        },
        markPoint: {
          data: [
            {
              coord: [4, 78],
              value: '当前位置\nv10=78分',
              symbolSize: 60,
              itemStyle: { color: accent },
              label: { color: '#fff', fontSize: 10, fontWeight: 600 }
            }
          ],
          symbol: 'pin'
        }
      },
      {
        name: '边际收益',
        type: 'line',
        data: [25, 20, 15, 10, 6, 3, 1],
        smooth: true,
        lineStyle: { color: accent, width: 2.5 },
        itemStyle: { color: accent },
        symbol: 'triangle',
        symbolSize: 8
      },
      {
        name: '投入成本',
        type: 'bar',
        yAxisIndex: 1,
        data: [3, 8, 15, 25, 35, 55, 80],
        itemStyle: { color: muted + '44', borderRadius: [3, 3, 0, 0] },
        barWidth: '20%'
      }
    ]
  });
  window.addEventListener('resize', function() { chart3.resize(); });

})();
