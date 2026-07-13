// assets/charts.js
(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Chart 1: Risk Assessment Summary ---
  var riskEl = document.getElementById('chart-risk-summary');
  if (riskEl) {
    var chart1 = echarts.init(riskEl, null, { renderer: 'svg' });
    chart1.setOption({
      title: {
        text: '10项风险评估对比',
        left: 'center',
        textStyle: { color: ink, fontSize: 14, fontFamily: 'Instrument Sans' }
      },
      tooltip: { trigger: 'axis', appendToBody: true },
      legend: {
        top: 30,
        data: ['审计评级', '本次评级'],
        textStyle: { color: muted }
      },
      grid: { left: '15%', right: '10%', top: '18%', bottom: '8%' },
      xAxis: {
        type: 'category',
        data: [
          'R1 GLM循环论证', 'R2 末日乐园S级', 'R3 长夜余火S级', 'R4 T1采样率',
          'R5 signing循环', 'R6 OLS slope', 'R7 TOP1-2验证', 'R8 Rhythm传导',
          'R9 Borda权重', 'R10 golden重复'
        ],
        axisLabel: { rotate: 45, fontSize: 11, color: muted }
      },
      yAxis: {
        type: 'value',
        name: '风险等级',
        min: 0, max: 4,
        interval: 1,
        axisLabel: {
          formatter: function(v) {
            return { 0: '极低', 1: '低', 2: '中', 3: '高', 4: '极高' }[v] || '';
          }
        },
        nameTextStyle: { color: muted }
      },
      series: [
        {
          name: '审计评级',
          type: 'bar',
          data: [3, 3, 2, 2, 2, 2, 2, 1, 1, 1],
          itemStyle: { color: muted },
          barGap: '10%'
        },
        {
          name: '本次评级',
          type: 'bar',
          data: [3, 2, 2, 3, 1, 3, 2, 1, 1, 0.5],
          itemStyle: { color: accent }
        }
      ],
      animation: false
    });
    window.addEventListener('resize', function() { chart1.resize(); });
  }

  // --- Chart 2: T1 Sampling Rate Distribution ---
  var sampleEl = document.getElementById('chart-t1-sampling');
  if (sampleEl) {
    var chart2 = echarts.init(sampleEl, null, { renderer: 'svg' });
    var books = ['第九特区', '末日乐园', '末日蟑螂', '限制级末日症候', '末世魔神游戏', '废土崛起', '末世大回炉', '灵异怪谈', '异兽迷城', '黑暗血时代', '第一序列', '全球进化', '末世超级商人', '神秘尽头', '蹉跎', '黑暗末日', '重卡战车', '恐慌沸腾', '地球游戏场', '黑暗文明', '末日拼图游戏', '黑暗王者', '世界末日', '从红月开始', '我在末世种田', '我的末世领地', '我在末世有套房', '狩魔手记', '末世召唤狂潮', '第九特区2', '我的女友', '灾厄纪元', '末世之三宫'];
    var rates = [30.6, 27.0, 26.8, 25.3, 22.0, 21.5, 21.7, 10.0, 10.0, 10.0, 10.0, 10.0, 0.9, 3.3, 4.1, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0];

    chart2.setOption({
      title: {
        text: 'T1采样率分布 (设计目标10%)',
        left: 'center',
        textStyle: { color: ink, fontSize: 14, fontFamily: 'Instrument Sans' }
      },
      tooltip: { trigger: 'axis', appendToBody: true },
      grid: { left: '8%', right: '5%', top: '15%', bottom: '8%' },
      xAxis: {
        type: 'category',
        data: books,
        axisLabel: { rotate: 60, fontSize: 10, color: muted }
      },
      yAxis: {
        type: 'value',
        name: '采样率 (%)',
        nameTextStyle: { color: muted },
        axisLabel: { formatter: '{value}%' }
      },
      series: [
        {
          type: 'bar',
          data: rates.map(function(r) {
            return {
              value: r,
              itemStyle: {
                color: r > 15 ? accent2 : r < 5 ? accent2 : accent
              }
            };
          }),
          markLine: {
            data: [{ yAxis: 10, name: '目标10%', label: { formatter: '目标10%' } }],
            lineStyle: { color: muted, type: 'dashed' }
          }
        }
      ],
      animation: false
    });
    window.addEventListener('resize', function() { chart2.resize(); });
  }

  // --- Chart 3: OLS Slope Comparison ---
  var olsEl = document.getElementById('chart-ols');
  if (olsEl) {
    var chart3 = echarts.init(olsEl, null, { renderer: 'svg' });
    chart3.setOption({
      title: {
        text: 'OLS校准斜率对比',
        left: 'center',
        textStyle: { color: ink, fontSize: 14, fontFamily: 'Instrument Sans' }
      },
      tooltip: { trigger: 'axis', appendToBody: true },
      grid: { left: '10%', right: '10%', top: '15%', bottom: '8%' },
      xAxis: {
        type: 'category',
        data: ['slope', '通胀率', 'R²'],
        axisLabel: { color: muted }
      },
      yAxis: {
        type: 'value',
        name: '值',
        nameTextStyle: { color: muted }
      },
      series: [
        {
          name: '纯人工(30章)',
          type: 'bar',
          data: [
            { value: 0.762, itemStyle: { color: accent } },
            { value: 0.31, itemStyle: { color: accent } },
            { value: 0.224, itemStyle: { color: accent } }
          ],
          label: { show: true, position: 'top', fontSize: 11 },
          barGap: '10%'
        },
        {
          name: '混合(125章)',
          type: 'bar',
          data: [
            { value: 0.463, itemStyle: { color: accent2 } },
            { value: 1.16, itemStyle: { color: accent2 } },
            { value: 0.319, itemStyle: { color: accent2 } }
          ],
          label: { show: true, position: 'top', fontSize: 11 }
        }
      ],
      animation: false
    });
    window.addEventListener('resize', function() { chart3.resize(); });
  }

  // --- Chart 4: Borda Ranking Dimension Breakdown ---
  var bordaEl = document.getElementById('chart-borda');
  if (bordaEl) {
    var chart4 = echarts.init(bordaEl, null, { renderer: 'svg' });
    chart4.setOption({
      title: {
        text: 'S级书Borda排名维度雷达图',
        left: 'center',
        textStyle: { color: ink, fontSize: 14, fontFamily: 'Instrument Sans' }
      },
      tooltip: { appendToBody: true },
      legend: {
        bottom: 0,
        data: ['全球变异', '末世大回炉', '黑暗血时代', '末日乐园', '长夜余火'],
        textStyle: { color: muted }
      },
      radar: {
        center: ['50%', '55%'],
        radius: '60%',
        indicator: [
          { name: 'signing', max: 33 },
          { name: 'retention', max: 33 },
          { name: 'diversity', max: 33 },
          { name: 'bt_rank', max: 33 },
          { name: 'webnovel8', max: 33 }
        ],
        axisName: { color: muted }
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: [25, 20, 19, 29, 30],
              name: '全球变异',
              lineStyle: { color: accent },
              areaStyle: { color: accent + '22' }
            },
            {
              value: [20, 9, 26, 27, 29],
              name: '末世大回炉',
              lineStyle: { color: '#059669' },
              areaStyle: { color: '#05966922' }
            },
            {
              value: [28, 3, 25, 28, 23],
              name: '黑暗血时代',
              lineStyle: { color: '#d97706' },
              areaStyle: { color: '#d9770622' }
            },
            {
              value: [14, 18, 0, 22, 6],
              name: '末日乐园',
              lineStyle: { color: accent2 },
              areaStyle: { color: accent2 + '22' }
            },
            {
              value: [9, 19, 28, 17, 17],
              name: '长夜余火',
              lineStyle: { color: '#7c3aed' },
              areaStyle: { color: '#7c3aed22' }
            }
          ]
        }
      ],
      animation: false
    });
    window.addEventListener('resize', function() { chart4.resize(); });
  }
})();