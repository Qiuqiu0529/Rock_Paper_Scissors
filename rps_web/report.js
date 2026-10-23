'use strict';
(function () {
  let templatePromise;
  const marker = '__RPS_REPORT_DATA__';
  function embeddedJSON(data) {
    return JSON.stringify(data).replace(/[<>&\u2028\u2029]/g, function (character) {
      return '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0');
    });
  }
  window.RPSReport = {
    render: async function (data) {
      if (!templatePromise) {
        const embedded = document.getElementById('embedded-report-template');
        templatePromise = embedded ? Promise.resolve(JSON.parse(embedded.textContent)) : fetch('report-template.html').then(function (response) {
          if (!response.ok) throw new Error('结果报告模板读取失败，请刷新页面后重试。');
          return response.text();
        }).catch(function (error) { templatePromise = undefined; throw error; });
      }
      const template = await templatePromise;
      if (template.split(marker).length !== 2) throw new Error('结果报告模板不完整。');
      return template.replace(marker, function () { return embeddedJSON(data); });
    }
  };
})();
