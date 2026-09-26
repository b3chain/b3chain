// Behavioural checks for theme redraws without replacing the user's chart data or filters.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(file) {
  const charts = [], observers = [];
  let light = false, fetches = 0;
  const canvas = { getContext: () => ({}) };
  const list = { children: [], style: {}, appendChild() {} };
  const document = {
    documentElement: { getAttribute: () => light ? 'light' : 'dark' }, querySelectorAll: () => [],
    getElementById: id => id === 'feeLevelChart' ? canvas : list,
  };
  const context = {
    document, console, setTimeout() {}, setInterval() {}, clearInterval() {},
    EventSource: class { addEventListener() {} },
    getComputedStyle: () => ({ getPropertyValue: key => ({
      '--b3-accent': light ? '#2457b2' : '#8eb4ff',
      '--b3-accent-soft': light ? '#e7eefb' : '#243656',
      '--b3-muted': light ? '#5c6b7e' : '#8b9bb0',
      '--b3-border': light ? '#d5deea' : '#314155',
    })[key] }),
    MutationObserver: class { constructor(fn) { observers.push(fn); } observe() {} },
    Chart: class {
      constructor(ctx, cfg) { this.data = cfg.data; this.options = cfg.options; charts.push(this); }
      destroy() { this.destroyed = true; }
      update() { this.updates = (this.updates || 0) + 1; }
    },
    fetch: async () => { fetches++; return { ok: true, json: async () => ({ series: [
      { x: 1, y: 10 }, { x: 864001, y: 20 }, { x: 950401, y: 30 },
    ] }) }; },
  };
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'overlay/public/js', file), 'utf8'), context);
  return { context, charts, canvas, fetches: () => fetches,
    toggle: () => { light = !light; observers.forEach(fn => fn()); } };
}

test('chart theme redraw preserves selected range and log scale without refetch', async () => {
  const h = harness('b3-charts.js');
  h.context.B3Charts.fetchAndRender({ chartId: 'hash-rate', canvas: h.canvas });
  await new Promise(resolve => setImmediate(resolve));
  h.context.B3Charts.setRange(7);
  h.context.B3Charts.setScale('log');
  const before = h.charts.at(-1);
  h.toggle();
  const after = h.charts.at(-1);
  assert.equal(h.fetches(), 1);
  assert.equal(after.data.datasets[0].data.length, 2);
  assert.equal(after.options.scales.y.type, 'logarithmic');
  assert.equal(after.options.scales.x.ticks.color, '#5c6b7e');
  assert.equal(after.data.datasets[0].borderColor, '#2457b2');
  assert.ok(before.destroyed);
  h.toggle();
  assert.equal(h.charts.at(-1).options.scales.x.ticks.color, '#8b9bb0');
});

test('mempool theme redraw preserves live data and updates both axes', () => {
  const h = harness('b3-mempool-live.js');
  h.context.B3LiveMempool.init({ initial: { txs: [], info: {}, feeHistogram: { labels: ['1', '2'], bytes: [50, 90] } } });
  const chart = h.charts[0];
  assert.equal(chart.options.scales.x.ticks.color, '#8b9bb0');
  h.toggle();
  assert.equal(h.charts.length, 1);
  assert.equal(chart.data.datasets[0].data[1], 90);
  assert.equal(chart.options.scales.y.ticks.color, '#5c6b7e');
  assert.equal(chart.options.scales.x.grid.color, '#d5deea');
  assert.equal(chart.data.datasets[0].backgroundColor, '#2457b2');
});
