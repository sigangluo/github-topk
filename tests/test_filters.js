const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = {window: {}};
vm.runInNewContext(fs.readFileSync('site/assets/filters.js', 'utf8'), context);
const matches = context.window.TOPK_MATCH_QUERY;
const matchesFilters = context.window.TOPK_MATCH_FILTERS;
const project = {
  name: 'example/clear-project',
  summary: '帮助开发者构建数据看板。',
  summary_en: 'Builds data dashboards for developers.',
  official: true, fresh: true, archived: false, website: 'https://example.org',
  category: 'dashboard', stacks: ['TypeScript', 'CSS'], license: 'MIT', org: 'example',
  created: '2026-04-14', pushed: '2026-11-06', rank: 5,
};

assert.equal(matches(project, 'clear', 'name'), true);
assert.equal(matches(project, 'dashboard', 'name'), false);
assert.equal(matches(project, 'dashboard', 'all'), true);
assert.equal(matches(project, '数据', 'all'), true);
assert.equal(matches(project, 'EXAMPLE project', 'name'), true);
assert.equal(matches(project, '', 'name'), true);

function emptyFilters(){
  return {q:'', status:new Set(), categories:new Set(), langs:new Set(), licenses:new Set(), orgs:new Set(),
    createdWindow:'', pushedWindow:'', rankMax:0, referenceDate:'2026-11-06'};
}
let filters = emptyFilters();
filters.q = 'dashboard';
assert.equal(matchesFilters(project, filters, 'name'), false);
assert.equal(matchesFilters(project, filters, 'all'), true);
filters = emptyFilters();
filters.categories.add('other');
filters.categories.add('dashboard');
filters.langs.add('Python');
filters.langs.add('TypeScript');
filters.licenses.add('MIT');
filters.status.add('official');
filters.status.add('website');
assert.equal(matchesFilters(project, filters, 'all'), true);
filters.status.add('archived');
assert.equal(matchesFilters(project, filters, 'all'), false);
filters = emptyFilters();
filters.licenses.add('unknown');
assert.equal(matchesFilters({...project, license:'NOASSERTION'}, filters, 'all'), true);
filters = emptyFilters();
filters.createdWindow = '365';
assert.equal(matchesFilters({...project, created:'2025-11-06'}, filters, 'all'), true);
assert.equal(matchesFilters({...project, created:'2025-11-05'}, filters, 'all'), false);
filters.createdWindow = '3y';
assert.equal(matchesFilters({...project, created:'2023-11-06'}, filters, 'all'), true);
assert.equal(matchesFilters({...project, created:'2023-11-05'}, filters, 'all'), false);
filters.createdWindow = 'older3y';
assert.equal(matchesFilters({...project, created:'2023-11-06'}, filters, 'all'), false);
assert.equal(matchesFilters({...project, created:'2023-11-05'}, filters, 'all'), true);
filters = emptyFilters();
filters.pushedWindow = '30';
assert.equal(matchesFilters({...project, pushed:'2026-10-07'}, filters, 'all'), true);
assert.equal(matchesFilters({...project, pushed:'2026-10-06'}, filters, 'all'), false);
filters.pushedWindow = 'older365';
assert.equal(matchesFilters({...project, pushed:'2025-11-05'}, filters, 'all'), true);
assert.equal(matchesFilters({...project, pushed:'2025-11-06'}, filters, 'all'), false);
filters = emptyFilters();
filters.rankMax = 100;
filters.status.add('official');
filters.categories.add('dashboard');
filters.pushedWindow = '7';
assert.equal(matchesFilters(project, filters, 'name'), true);
assert.equal(matchesFilters({...project, rank:101}, filters, 'name'), false);
assert.equal(matchesFilters({...project, rank:null}, filters, 'name'), false);
assert.equal(matchesFilters({...project, pushed:'2026-10-20'}, filters, 'name'), false);
assert.equal(matchesFilters({...project, official:false}, filters, 'name'), false);
console.log('Search and filter checks passed');
