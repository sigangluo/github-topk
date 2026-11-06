/* Snapshot-based distributions used by the analysis view. */
(function(){
  function daysBetween(referenceDate, value){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
    var days = (Date.parse(referenceDate + 'T00:00:00Z') - Date.parse(value + 'T00:00:00Z')) / 86400000;
    return Number.isFinite(days) && days >= 0 ? days : null;
  }

  window.TOPK_ANALYSIS = {
    median: function(items, field){
      if(!items.length) return 0;
      var values = items.map(function(project){ return project[field]; }).sort(function(a, b){ return a - b; });
      return (values[Math.floor((values.length - 1) / 2)] + values[Math.floor(values.length / 2)]) / 2;
    },
    languageCounts: function(items, limit){
      var counts = {};
      items.forEach(function(project){
        var languages = project.stacks || (project.stack || '').split(' / ').filter(Boolean);
        new Set(languages).forEach(function(language){ counts[language] = (counts[language] || 0) + 1; });
      });
      return Object.keys(counts).sort(function(a, b){ return counts[b] - counts[a] || a.localeCompare(b); })
        .slice(0, limit).map(function(key){ return {key:key, count:counts[key]}; });
    },
    creationYears: function(items, referenceDate){
      var lastYear = Number(referenceDate.slice(0, 4));
      var firstYear = lastYear - 9;
      var rows = [{key:'earlier', count:0}];
      for(var year = firstYear; year <= lastYear; year++) rows.push({key:String(year), count:0});
      var unknown = 0;
      items.forEach(function(project){
        var createdYear = Number((project.created || '').slice(0, 4));
        if(!/^\d{4}-\d{2}-\d{2}$/.test(project.created || '') || !Number.isInteger(createdYear) || createdYear > lastYear){
          unknown++;
          return;
        }
        rows[createdYear < firstYear ? 0 : createdYear - firstYear + 1].count++;
      });
      if(unknown) rows.push({key:'unknown', count:unknown});
      return rows;
    },
    pushRecency: function(items, referenceDate){
      var rows = ['7', '30', '90', '365', 'older', 'unknown'].map(function(key){ return {key:key, count:0}; });
      items.forEach(function(project){
        var age = daysBetween(referenceDate, project.pushed);
        var index = age === null ? 5 : age <= 7 ? 0 : age <= 30 ? 1 : age <= 90 ? 2 : age <= 365 ? 3 : 4;
        rows[index].count++;
      });
      return rows.filter(function(row){ return row.key !== 'unknown' || row.count > 0; });
    }
  };
})();
