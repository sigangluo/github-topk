/* Pure matching rules shared by project cards and analysis. */
(function(){
  window.TOPK_MATCH_QUERY = function(project, query, scope){
    var terms = String(query || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    if(!terms.length) return true;
    var text = scope === 'name'
      ? project.name
      : project.name + ' ' + project.summary + ' ' + project.summary_en;
    var haystack = text.toLowerCase();
    return terms.every(function(term){ return haystack.includes(term); });
  };

  window.TOPK_MATCH_FILTERS = function(project, filters, scope){
    if(filters.status.has('official') && !project.official) return false;
    if(filters.status.has('archived') && !project.archived) return false;
    if(filters.status.has('website') && !project.website) return false;
    // Relative dates use the saved metadata date, so a published snapshot does not drift daily.
    function ageInDays(value){
      if(!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
      var age = (Date.parse(filters.referenceDate + 'T00:00:00Z') - Date.parse(value + 'T00:00:00Z')) / 86400000;
      return Number.isFinite(age) && age >= 0 ? age : null;
    }
    function matchesAge(value, choice){
      if(!choice) return true;
      var age = ageInDays(value);
      if(age === null) return false;
      if(choice === '3y' || choice === 'older3y'){
        var cutoff = new Date(filters.referenceDate + 'T00:00:00Z');
        cutoff.setUTCFullYear(cutoff.getUTCFullYear() - 3);
        return choice === '3y' ? Date.parse(value + 'T00:00:00Z') >= cutoff : Date.parse(value + 'T00:00:00Z') < cutoff;
      }
      return choice.slice(0, 5) === 'older' ? age > Number(choice.slice(5)) : age <= Number(choice);
    }
    if(!matchesAge(project.created, filters.createdWindow)) return false;
    if(!matchesAge(project.pushed, filters.pushedWindow)) return false;
    if(filters.rankMax && (project.rank == null || project.rank > filters.rankMax)) return false;
    if(filters.categories.size && !filters.categories.has(project.category)) return false;
    if(filters.langs.size && !project.stacks.some(function(lang){ return filters.langs.has(lang); })) return false;
    var license = project.license && project.license !== 'NOASSERTION' ? project.license : 'unknown';
    if(filters.licenses.size && !filters.licenses.has(license)) return false;
    if(filters.orgs.size && !filters.orgs.has(project.org)) return false;
    return window.TOPK_MATCH_QUERY(project, filters.q, scope);
  };
})();
