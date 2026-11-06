const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync('site/index.html', 'utf8');
const app = fs.readFileSync('site/assets/app.js', 'utf8');
function values(pattern){ return Array.from(html.matchAll(pattern), match => match[1]); }

const ids = values(/\sid="([^"]+)"/g);
assert.equal(new Set(ids).size, ids.length, 'HTML IDs must be unique');
for(const id of values(/\saria-controls="([^"]+)"/g)){
  assert.ok(ids.includes(id), `aria-controls points to a missing element: ${id}`);
}
for(const match of app.matchAll(/getElementById\('([^']+)'\)/g)){
  assert.ok(ids.includes(match[1]), `app.js expects a missing element: ${match[1]}`);
}

const scripts = values(/<script\s+src="([^"]+)"/g);
assert.ok(scripts.indexOf('assets/app.js') > scripts.indexOf('assets/i18n.js'));
assert.ok(scripts.indexOf('assets/app.js') > scripts.indexOf('assets/filters.js'));
assert.ok(scripts.indexOf('assets/app.js') > scripts.indexOf('assets/analysis.js'));
const staticFiles = scripts.concat(values(/<link\s+rel="stylesheet"\s+href="([^"]+)"/g), ['data/catalog.json']);
for(const file of staticFiles){
  assert.ok(fs.statSync(path.join('site', file)).isFile(), `Missing site asset: ${file}`);
}

const context = {window: {}};
vm.runInNewContext(fs.readFileSync('site/assets/i18n.js', 'utf8'), context);
const strings = context.window.TOPK_I18N(2000);
const keys = values(/\sdata-i18n(?:-placeholder|-aria|-title|-html)?="([^"]+)"/g);
for(const key of keys){
  assert.ok(key in strings.en && key in strings.zh, `Missing translation: ${key}`);
}
assert.deepEqual(Object.keys(strings.en).sort(), Object.keys(strings.zh).sort());
console.log('Site structure checks passed');
