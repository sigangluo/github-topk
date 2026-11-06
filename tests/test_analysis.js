const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = {window: {}};
vm.runInNewContext(fs.readFileSync('site/assets/analysis.js', 'utf8'), context);
const analysis = context.window.TOPK_ANALYSIS;
const referenceDate = '2026-11-06';
assert.equal(analysis.median([], 'watching'), 0);
assert.equal(analysis.median([{watching:4}, {watching:10}], 'watching'), 7);
assert.equal(analysis.median([{forks:9}, {forks:1}, {forks:5}], 'forks'), 5);
assert.deepEqual(Array.from(analysis.languageCounts([
  {stack:'Python / Shell'}, {stack:'Python / Python'}, {stack:'Rust'},
], 2), row => [row.key, row.count]), [['Python',2], ['Rust',1]]);
function daysAgo(days){
  return new Date(Date.parse(referenceDate + 'T00:00:00Z') - days * 86400000).toISOString().slice(0, 10);
}
const sample = [7, 8, 30, 31, 90, 91, 365, 366].map((days, i) => ({
  created: i === 0 ? '2016-12-31' : i === 1 ? '2017-01-01' : '2026-04-01',
  pushed: daysAgo(days),
}));
sample.push({created:'', pushed:''});

const years = analysis.creationYears(sample, referenceDate);
const pushes = analysis.pushRecency(sample, referenceDate);
assert.equal(years.find(row => row.key === 'earlier').count, 1);
assert.equal(years.find(row => row.key === '2017').count, 1);
assert.equal(years.find(row => row.key === '2026').count, 6);
assert.equal(years.find(row => row.key === 'unknown').count, 1);
assert.deepEqual(Array.from(pushes, row => [row.key, row.count]), [
  ['7',1], ['30',2], ['90',2], ['365',2], ['older',1], ['unknown',1],
]);

const catalog = JSON.parse(fs.readFileSync('site/data/catalog.json', 'utf8'));
assert.ok(catalog.metadata_reference_date >= catalog.metadata_as_of);
for(const view of Object.values(catalog.views)){
  const ranked = view.projects.filter(project => project.rank != null);
  const created = analysis.creationYears(ranked, catalog.metadata_reference_date);
  const pushed = analysis.pushRecency(ranked, catalog.metadata_reference_date);
  assert.equal(created.reduce((total, row) => total + row.count, 0), ranked.length);
  assert.equal(pushed.reduce((total, row) => total + row.count, 0), ranked.length);
  const languages = analysis.languageCounts(ranked, 1000);
  const languageMentions = languages.reduce((total, row) => total + row.count, 0);
  assert.ok(languageMentions >= ranked.length && languageMentions <= ranked.length * 2);
  const recent = pushed[0].count + pushed[1].count;
  assert.equal(recent, ranked.filter(project => daysAgoFrom(catalog.metadata_reference_date, project.pushed) <= 30).length);
}
function daysAgoFrom(reference, date){ return (Date.parse(reference + 'T00:00:00Z') - Date.parse(date + 'T00:00:00Z')) / 86400000; }
console.log('Analysis distribution checks passed');
