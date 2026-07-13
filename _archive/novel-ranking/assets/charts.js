// 末世小说排名图表 - 30本
const RANKING_DATA = [
  { name: "末世大回炉", total: 80.3, opening: 59.9, sustained: 97.3, commercial: 96.9, market: 58.6, hook3: 2.44, pleasure3: 4.57, borda_rank: 3, rank: 1, change: 2, tier: "S" },
  { name: "神秘尽头", total: 73.3, opening: 62.0, sustained: 75.0, commercial: 100.0, market: 41.4, hook3: 4.12, pleasure3: 2.83, borda_rank: 6, rank: 2, change: 4, tier: "S" },
  { name: "末世之深渊召唤师", total: 66.7, opening: 55.7, sustained: 54.8, commercial: 96.9, market: 65.5, hook3: 1.61, pleasure3: 2.93, borda_rank: 2, rank: 3, change: -1, tier: "S" },
  { name: "地球游戏场", total: 64.2, opening: 48.2, sustained: 54.9, commercial: 87.5, market: 89.7, hook3: 1.63, pleasure3: 2.8, borda_rank: 1, rank: 4, change: -3, tier: "S" },
  { name: "全球变异", total: 58.4, opening: 51.2, sustained: 63.0, commercial: 78.1, market: 20.7, hook3: 2.49, pleasure3: 2.53, borda_rank: 14, rank: 5, change: 9, tier: "A" },
  { name: "末日拼图游戏", total: 58.1, opening: 60.5, sustained: 48.6, commercial: 68.8, market: 51.7, hook3: 2.21, pleasure3: 3.13, borda_rank: 12, rank: 6, change: 6, tier: "A" },
  { name: "从红月开始", total: 57.8, opening: 47.5, sustained: 55.7, commercial: 59.4, market: 96.6, hook3: 2.88, pleasure3: 2.3, borda_rank: 8, rank: 7, change: 1, tier: "A" },
  { name: "我的末世领地", total: 57.7, opening: 56.8, sustained: 48.7, commercial: 62.5, market: 75.9, hook3: 1.42, pleasure3: 5.4, borda_rank: 7, rank: 8, change: -1, tier: "A" },
  { name: "世界末日从考试不及格开始", total: 50.3, opening: 42.2, sustained: 40.8, commercial: 53.1, market: 100.0, hook3: 2.42, pleasure3: 2.23, borda_rank: 9, rank: 9, change: 0, tier: "A" },
  { name: "黑暗血时代", total: 48.9, opening: 57.4, sustained: 20.5, commercial: 90.6, market: 0.0, hook3: 2.46, pleasure3: 2.77, borda_rank: 16, rank: 10, change: 6, tier: "A" },
  { name: "异兽迷城", total: 47.9, opening: 34.8, sustained: 42.1, commercial: 59.4, market: 82.8, hook3: 1.85, pleasure3: 2.53, borda_rank: 4, rank: 11, change: -7, tier: "A" },
  { name: "狩魔手记", total: 47.7, opening: 37.8, sustained: 48.9, commercial: 75.0, market: 10.3, hook3: 1.35, pleasure3: 2.7, borda_rank: 15, rank: 12, change: 3, tier: "A" },
  { name: "末世魔神游戏", total: 44.7, opening: 28.5, sustained: 40.0, commercial: 68.8, market: 55.2, hook3: 1.1, pleasure3: 2.6, borda_rank: 5, rank: 13, change: -8, tier: "B+" },
  { name: "废土崛起", total: 44.6, opening: 25.4, sustained: 45.9, commercial: 53.1, market: 86.2, hook3: 1.11, pleasure3: 2.87, borda_rank: 13, rank: 14, change: -1, tier: "B+" },
  { name: "我的女友是丧尸", total: 44.1, opening: 27.7, sustained: 47.4, commercial: 53.1, market: 69.0, hook3: 0.66, pleasure3: 1.83, borda_rank: 20, rank: 15, change: 5, tier: "B+" },
  { name: "灾厄纪元", total: 40.7, opening: 27.1, sustained: 44.7, commercial: 53.1, market: 44.8, hook3: 2.18, pleasure3: 1.63, borda_rank: 21, rank: 16, change: 5, tier: "B" },
  { name: "黑暗文明", total: 39.5, opening: 25.8, sustained: 56.1, commercial: 53.1, market: 3.4, hook3: 0.95, pleasure3: 2.2, borda_rank: 18, rank: 17, change: 1, tier: "B" },
  { name: "黑暗王者", total: 38.5, opening: 20.2, sustained: 52.5, commercial: 53.1, market: 24.1, hook3: 1.79, pleasure3: 1.3, borda_rank: 22, rank: 18, change: 4, tier: "B" },
  { name: "末世召唤狂潮", total: 37.9, opening: 41.3, sustained: 13.1, commercial: 53.1, market: 62.1, hook3: 0.91, pleasure3: 2.73, borda_rank: 11, rank: 19, change: -8, tier: "B" },
  { name: "全球进化", total: 37.7, opening: 27.9, sustained: 17.9, commercial: 53.1, market: 93.1, hook3: 0.99, pleasure3: 2.4, borda_rank: 10, rank: 20, change: -10, tier: "B" },
  { name: "恐慌沸腾", total: 37.2, opening: 16.9, sustained: 33.4, commercial: 53.1, market: 79.3, hook3: 1.07, pleasure3: 1.33, borda_rank: 19, rank: 21, change: -2, tier: "B" },
  { name: "我在末世有套房", total: 36.8, opening: 25.3, sustained: 24.6, commercial: 53.1, market: 72.4, hook3: 0.55, pleasure3: 1.9, borda_rank: 17, rank: 22, change: -5, tier: "B" },
  { name: "限制级末日症候", total: 34.7, opening: 32.9, sustained: 30.8, commercial: 53.1, market: 6.9, hook3: 1.15, pleasure3: 1.93, borda_rank: 29, rank: 23, change: 6, tier: "B-" },
  { name: "重卡战车在末世", total: 33.1, opening: 15.1, sustained: 38.2, commercial: 53.1, market: 31.0, hook3: 0.98, pleasure3: 1.3, borda_rank: 23, rank: 24, change: -1, tier: "B-" },
  { name: "我在末世种个田", total: 32.4, opening: 12.2, sustained: 43.8, commercial: 53.1, market: 17.2, hook3: 0.8, pleasure3: 1.67, borda_rank: 28, rank: 25, change: 3, tier: "B-" },
  { name: "末日蟑螂", total: 32.2, opening: 12.0, sustained: 32.8, commercial: 53.1, market: 48.3, hook3: 0.31, pleasure3: 1.43, borda_rank: 24, rank: 26, change: -2, tier: "B-" },
  { name: "末世超级商人", total: 29.5, opening: 17.8, sustained: 28.7, commercial: 53.1, market: 13.8, hook3: 0.86, pleasure3: 1.73, borda_rank: 26, rank: 27, change: -1, tier: "B-" },
  { name: "黑暗末日", total: 25.8, opening: 26.0, sustained: 46.4, commercial: 0.0, market: 27.6, hook3: 1.74, pleasure3: 1.87, borda_rank: 30, rank: 28, change: 2, tier: "C" },
  { name: "第九特区", total: 21.7, opening: 2.8, sustained: 12.3, commercial: 53.1, market: 37.9, hook3: 0.56, pleasure3: 1.0, borda_rank: 25, rank: 29, change: -4, tier: "C" },
  { name: "蹉跎", total: 20.2, opening: 17.1, sustained: 27.9, commercial: 9.4, market: 34.5, hook3: 1.05, pleasure3: 1.6, borda_rank: 27, rank: 30, change: -3, tier: "C" },
];

// 等级颜色
const TIER_COLORS = {
  "S": "#c0392b",
  "A": "#e67e22",
  "B+": "#f1c40f",
  "B": "#95a5a6",
  "B-": "#7f8c8d",
  "C": "#555555"
};

// 填充排名表
function fillRankTable() {
  const tbody = document.getElementById('rank-tbody');
  if (!tbody) return;
  const rows = RANKING_DATA.map(b => {
    const tierClass = {
      "S": "tier-s-bg", "A": "tier-a-bg", "B+": "tier-bp-bg",
      "B": "tier-b-bg", "B-": "tier-bm-bg", "C": "tier-c-bg"
    }[b.tier];
    const rowClass = b.tier === "S" ? "s-tier-row" : (b.tier === "A" ? "a-tier-row" : "");
    let changeHtml;
    if (b.change > 0) {
      changeHtml = `<span class="rank-change-up">+${b.change} ★</span>`;
    } else if (b.change < 0) {
      changeHtml = `<span class="rank-change-down">${b.change} ★</span>`;
    } else {
      changeHtml = `<span class="rank-change-same">0</span>`;
    }
    return `
    <tr class="${rowClass}">
      <td class="rank-col">${b.rank}</td>
      <td class="book-name" style="padding-left:1rem;">${b.name}</td>
      <td><span class="tier-badge ${tierClass}">${b.tier}</span></td>
      <td class="num" style="font-weight:700;">${b.total.toFixed(1)}</td>
      <td class="num">${b.opening.toFixed(1)}</td>
      <td class="num">${b.sustained.toFixed(1)}</td>
      <td class="num">${b.commercial.toFixed(1)}</td>
      <td class="num">${b.market.toFixed(1)}</td>
      <td class="num">${b.hook3.toFixed(2)}</td>
      <td class="num">${b.pleasure3.toFixed(2)}</td>
      <td class="num">#${b.borda_rank}</td>
      <td>${changeHtml}</td>
    </tr>`;
  }).join('');
  tbody.innerHTML = rows;
}

// 图1: 排名对比图
function initRankCompareChart() {
  const el = document.getElementById('chart-rank-compare');
  if (!el || !window.echarts) return;
  const chart = echarts.init(el, null, { renderer: 'svg' });

  const names = RANKING_DATA.map(b => b.name);
  const newRanks = RANKING_DATA.map(b => b.rank);
  const oldRanks = RANKING_DATA.map(b => b.borda_rank);
  const changes = RANKING_DATA.map(b => b.change);
  const colors = RANKING_DATA.map(b => TIER_COLORS[b.tier]);

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: function(params) {
        const name = params[0].name;
        const book = RANKING_DATA.find(b => b.name === name);
        return `<strong>${name}</strong><br/>
          新排名: #${book.rank} (${book.tier}级, ${book.total}分)<br/>
          原Borda: #${book.borda_rank}<br/>
          变动: ${book.change > 0 ? '+' + book.change : book.change} 名`;
      }
    },
    legend: {
      data: ['新排名', '原Borda排名', '排名变动'],
      top: 0,
      textStyle: { fontSize: 12 }
    },
    grid: { top: 45, bottom: 90, left: 45, right: 55 },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: {
        rotate: 40,
        fontSize: 11,
        interval: 0,
        formatter: function(val) {
          if (val.length > 6) return val.substring(0, 6) + '..';
          return val;
        }
      },
      axisLine: { lineStyle: { color: '#999' } }
    },
    yAxis: [
      {
        type: 'value',
        name: '排名（越小越好）',
        nameTextStyle: { fontSize: 11 },
        inverse: true,
        min: 1,
        max: 30,
        splitLine: { lineStyle: { type: 'dashed', color: '#eee' } }
      },
      {
        type: 'value',
        name: '变动',
        nameTextStyle: { fontSize: 11 },
        splitLine: { show: false },
        axisLabel: {
          formatter: function(v) {
            return v > 0 ? '+' + v : v;
          }
        }
      }
    ],
    series: [
      {
        name: '新排名',
        type: 'line',
        data: newRanks,
        yAxisIndex: 0,
        lineStyle: { color: '#8b3a3a', width: 2.5 },
        itemStyle: { color: '#8b3a3a' },
        symbol: 'circle',
        symbolSize: 7,
        smooth: false
      },
      {
        name: '原Borda排名',
        type: 'line',
        data: oldRanks,
        yAxisIndex: 0,
        lineStyle: { color: '#2c5f6f', width: 2, type: 'dashed' },
        itemStyle: { color: '#2c5f6f' },
        symbol: 'diamond',
        symbolSize: 7,
        smooth: false
      },
      {
        name: '排名变动',
        type: 'bar',
        data: changes.map((v, i) => ({
          value: v,
          itemStyle: { color: v > 0 ? '#27ae60' : (v < 0 ? '#e74c3c' : '#999') }
        })),
        yAxisIndex: 1,
        barWidth: 12,
        tooltip: {
          formatter: function(p) {
            const v = p.value;
            return `排名变动: ${v > 0 ? '+' + v : v} 名`;
          }
        }
      }
    ]
  };

  chart.setOption(option);
  window.addEventListener('resize', () => chart.resize());
}

// 图2: TOP10 雷达图
function initRadarChart() {
  const el = document.getElementById('chart-radar-top10');
  if (!el || !window.echarts) return;
  const chart = echarts.init(el, null, { renderer: 'svg' });

  const top10 = RANKING_DATA.slice(0, 10);
  const indicator = [
    { name: '开篇质量', max: 100 },
    { name: '持续质量', max: 100 },
    { name: '商业评分', max: 100 },
    { name: '市场验证', max: 100 }
  ];

  const colors = [
    '#c0392b', '#e74c3c', '#e67e22', '#f39c12',
    '#27ae60', '#2ecc71', '#2c5f6f', '#3498db',
    '#8e44ad', '#e91e63'
  ];

  const seriesData = top10.map((b, i) => ({
    value: [b.opening, b.sustained, b.commercial, b.market],
    name: `#${b.rank} ${b.name} (${b.total}分)`,
    lineStyle: { color: colors[i], width: 1.5 },
    itemStyle: { color: colors[i] },
    areaStyle: { color: colors[i] + '15' }
  }));

  const option = {
    tooltip: {
      trigger: 'item'
    },
    legend: {
      data: top10.map(b => `#${b.rank} ${b.name} (${b.total}分)`),
      type: 'scroll',
      bottom: 0,
      textStyle: { fontSize: 11 }
    },
    radar: {
      indicator: indicator,
      shape: 'polygon',
      radius: '62%',
      center: ['50%', '45%'],
      axisName: {
        fontSize: 12,
        fontWeight: 600,
        color: '#333'
      },
      splitArea: {
        areaStyle: {
          color: ['#fafaf7', '#f5f2ea']
        }
      },
      axisLine: { lineStyle: { color: '#ddd' } },
      splitLine: { lineStyle: { color: '#ddd' } }
    },
    series: [{
      type: 'radar',
      data: seriesData,
      emphasis: {
        lineStyle: { width: 3 }
      }
    }]
  };

  chart.setOption(option);
  window.addEventListener('resize', () => chart.resize());
}

// 图3: 分数分布柱状图
function initScoreDistChart() {
  const el = document.getElementById('chart-score-dist');
  if (!el || !window.echarts) return;
  const chart = echarts.init(el, null, { renderer: 'svg' });

  const names = RANKING_DATA.map(b => b.name);
  const scores = RANKING_DATA.map(b => ({
    value: b.total,
    itemStyle: { color: TIER_COLORS[b.tier] }
  }));

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: function(params) {
        const name = params[0].name;
        const book = RANKING_DATA.find(b => b.name === name);
        return `<strong>${name}</strong><br/>
          总分: ${book.total}<br/>
          等级: ${book.tier}<br/>
          开篇: ${book.opening.toFixed(1)} · 持续: ${book.sustained.toFixed(1)}<br/>
          商业: ${book.commercial.toFixed(1)} · 市场: ${book.market.toFixed(1)}`;
      }
    },
    grid: { top: 30, bottom: 100, left: 45, right: 25 },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: {
        rotate: 40,
        fontSize: 11,
        interval: 0,
        formatter: function(val) {
          if (val.length > 6) return val.substring(0, 6) + '..';
          return val;
        }
      },
      axisLine: { lineStyle: { color: '#999' } }
    },
    yAxis: {
      type: 'value',
      name: '总分',
      nameTextStyle: { fontSize: 11 },
      max: 100,
      splitLine: { lineStyle: { type: 'dashed', color: '#eee' } }
    },
    series: [
      {
        type: 'bar',
        data: scores,
        barWidth: '65%',
        label: {
          show: true,
          position: 'top',
          fontSize: 10,
          fontWeight: 600,
          formatter: function(p) {
            const book = RANKING_DATA[p.dataIndex];
            return book.tier;
          },
          color: function(p) {
            return TIER_COLORS[RANKING_DATA[p.dataIndex].tier];
          }
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { type: 'dashed', color: '#666', width: 1 },
          label: { position: 'end', fontSize: 10, formatter: '{b}' },
          data: [
            { yAxis: 64.2, name: 'S线(64.2)' },
            { yAxis: 47.7, name: 'A线(47.7)' },
            { yAxis: 29.5, name: 'B线(29.5)' }
          ]
        }
      }
    ]
  };

  chart.setOption(option);
  window.addEventListener('resize', () => chart.resize());
}

// 初始化
document.addEventListener('DOMContentLoaded', function() {
  fillRankTable();
  initRankCompareChart();
  initRadarChart();
  initScoreDistChart();
});
