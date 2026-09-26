const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function quoteHelper(items) {
  const context = {
    module: { exports: {} }, process: { env: {} },
    console: { log() {}, error(message) { throw Error(message); } },
    Math: { random: () => 0.999, floor: Math.floor },
    require(name) {
      if (name.endsWith('btcQuotes.js')) return { items };
      return { init() {} };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'overlay/b3-bootstrap.js'), 'utf8'), context);
  const app = { locals: {}, use() {} };
  context.module.exports(app, { baseUrl: '/' });
  return app.locals.b3FooterQuote;
}

test('footer quote skips duplicates and retains the original quote link index', () => {
  const selected = quoteHelper([{ text: 'one' }, { duplicateIndex: 0 }, { text: 'three' }, { duplicateIndex: 2 }])();
  assert.equal(selected.index, 2);
  assert.equal(selected.quote.text, 'three');
});

test('empty quote collection omits the widget instead of breaking the page', () => {
  assert.equal(quoteHelper([])(), null);
});
