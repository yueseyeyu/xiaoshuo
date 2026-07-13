// assets/charts.js — 质量分级审视报告图表
(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var sColor = '#c0392b';
  var aColor = '#e67e22';
  var bColor = '#f1c40f';
  var cColor = '#7f8c8d';

  // ========== Chart 1: S级雷达图 ==========
  var radarEl = document.getElementById('chart-s-tier-radar');
  if (radarEl) {
    var chart1 = echarts.init(radarEl, null, { renderer: 'svg' });
    chart1.setOption({
      animation: false,
      tooltip: { appendToBody: true },
      legend: {
        data: ['地球游戏场', '末世之深渊召唤师', '末世大回炉', '异兽迷城', '末世魔神游戏', '神秘尽头'],
        textStyle: { color: muted, fontSize: 11 },
        top: 0,
        type: 'scroll'
      },
      radar: {
        indicator: [
          { name: 'Borda排名(逆)', max: 30 },
          { name: '签约潜力(逆)', max: 30 },
          { name: '留存率(逆)', max: 30 },
          { name: 'hook3(×10)', max: 45 },
          { name: 'pleasure3(×5)', max: 30 },
          { name: '商业评分', max: 80 }
        ],
        center: ['50%', '58%'],
        radius: '62%',
        axisName: {
          color: ink,
          fontSize: 11,
          fontWeight: 500
        },
        splitLine: { lineStyle: { color: rule } },
        splitArea: { areaStyle: { color: [bg2, 'transparent'] } },
        axisLine: { lineStyle: { color: rule } }
      },
      series: [{
        type: 'radar',
        data: [
          {
            value: [29, 29, 22, 16.3, 14.0, 71],
            name: '地球游戏场',
            lineStyle: { color: sColor, width: 2 },
            itemStyle: { color: sColor },
            areaStyle: { color: sColor + '22' }
          },
          {
            value: [28, 24, 28, 16.1, 14.7, 74],
            name: '末世之深渊召唤师',
            lineStyle: { color: '#e74c3c', width: 2 },
            itemStyle: { color: '#e74c3c' },
            areaStyle: { color: '#e74c3c22' }
          },
          {
            value: [27, 28, 24, 24.4, 22.9, 74],
            name: '末世大回炉',
            lineStyle: { color: accent2, width: 2 },
            itemStyle: { color: accent2 },
            areaStyle: { color: accent2 + '22' }
          },
          {
            value: [26, 19, 19, 18.5, 12.7, 62],
            name: '异兽迷城',
            lineStyle: { color: '#2980b9', width: 2 },
            itemStyle: { color: '#2980b9' },
            areaStyle: { color: '#2980b922' }
          },
          {
            value: [25, 16, 27, 11.0, 13.0, 65],
            name: '末世魔神游戏',
            lineStyle: { color: aColor, width: 2, type: 'dashed' },
            itemStyle: { color: aColor },
            areaStyle: { color: aColor + '22' }
          },
          {
            value: [24, 23, 29, 41.2, 14.2, 75],
            name: '神秘尽头',
            lineStyle: { color: '#8e44ad', width: 2 },
            itemStyle: { color: '#8e44ad' },
            areaStyle: { color: '#8e44ad22' }
          }
        ]
      }]
    });
    window.addEventListener('resize', function() { chart1.resize(); });
  }

  // ========== Chart 2: Borda总分分布 ==========
  var distEl = document.getElementById('chart-borda-distribution');
  if (distEl) {
    var chart2 = echarts.init(distEl, null, { renderer: 'svg' });

    var books = [
      { name: '地球游戏场', score: 20, tier: 'S' },
      { name: '末世之深渊召唤师', score: 34, tier: 'S' },
      { name: '末世大回炉', score: 40, tier: 'S' },
      { name: '异兽迷城', score: 43, tier: 'S' },
      { name: '末世魔神游戏', score: 47, tier: 'S' },
      { name: '神秘尽头', score: 49, tier: 'S' },
      { name: '我的末世领地', score: 49, tier: 'A' },
      { name: '从红月开始', score: 50, tier: 'A' },
      { name: '世界末日从考试不及格开始', score: 52, tier: 'A' },
      { name: '全球进化', score: 66, tier: 'A' },
      { name: '末世召唤狂潮', score: 66, tier: 'A' },
      { name: '末日拼图游戏', score: 70, tier: 'A' },
      { name: '废土崛起', score: 70, tier: 'A' },
      { name: '全球变异', score: 77, tier: 'A' },
      { name: '狩魔手记', score: 77, tier: 'B' },
      { name: '黑暗血时代', score: 79, tier: 'B' },
      { name: '我在末世有套房', score: 79, tier: 'B' },
      { name: '黑暗文明', score: 85, tier: 'B' },
      { name: '恐慌沸腾', score: 91, tier: 'B' },
      { name: '我的女友是丧尸', score: 93, tier: 'B' },
      { name: '灾厄纪元', score: 94, tier: 'B' },
      { name: '黑暗王者', score: 96, tier: 'B' },
      { name: '重卡战车在末世', score: 97, tier: 'B' },
      { name: '末日蟑螂', score: 105, tier: 'B' },
      { name: '第九特区', score: 109, tier: 'B' },
      { name: '末世超级商人', score: 112, tier: 'B' },
      { name: '蹉跎', score: 113, tier: 'B' },
      { name: '我在末世种个田', score: 117, tier: 'B' },
      { name: '限制级末日症候', score: 122, tier: 'B' },
      { name: '黑暗末日', score: 123, tier: 'B' }
    ];

    var tierColor = { 'S': sColor, 'A': aColor, 'B': bColor, 'C': cColor };

    var barData = books.map(function(b) {
      return {
        value: b.score,
        itemStyle: { color: tierColor[b.tier] }
      };
    });

    chart2.setOption({
      animation: false,
      tooltip: {
        appendToBody: true,
        trigger: 'axis',
        formatter: function(params) {
          var p = params[0];
          var b = books[p.dataIndex];
          return b.name + '<br/>Borda分: ' + b.score + '<br/>等级: ' + b.tier;
        }
      },
      grid: { left: 50, right: 20, top: 30, bottom: 70 },
      xAxis: {
        type: 'category',
        data: books.map(function(b) { return b.name; }),
        axisLabel: {
          color: muted,
          fontSize: 9,
          rotate: 45,
          interval: 0
        },
        axisLine: { lineStyle: { color: rule } }
      },
      yAxis: {
        type: 'value',
        name: 'Borda总分',
        nameTextStyle: { color: muted, fontSize: 11 },
        axisLabel: { color: muted, fontSize: 10 },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } }
      },
      series: [{
        type: 'bar',
        data: barData,
        barWidth: '65%',
        markLine: {
          silent: true,
          lineStyle: { color: ink, type: 'solid', width: 1 },
          label: { fontSize: 10, color: ink, fontWeight: 600 },
          data: [
            { xAxis: 5.5, label: { formatter: 'S/A分界', position: 'insideEndTop' } },
            { xAxis: 13.5, label: { formatter: 'A/B分界', position: 'insideEndTop' } },
            { xAxis: 29.5, label: { formatter: 'B/C分界', position: 'insideEndTop' } }
          ]
        }
      }],
      graphic: [
        {
          type: 'text',
          left: '10%',
          top: 5,
          style: { text: 'S级 (6本)', fill: sColor, fontSize: 11, fontWeight: 700 }
        },
        {
          type: 'text',
          left: '30%',
          top: 5,
          style: { text: 'A级 (8本)', fill: aColor, fontSize: 11, fontWeight: 700 }
        },
        {
          type: 'text',
          left: '65%',
          top: 5,
          style: { text: 'B级 (16本)', fill: '#b8960b', fontSize: 11, fontWeight: 700 }
        }
      ]
    });
    window.addEventListener('resize', function() { chart2.resize(); });
  }

})();
