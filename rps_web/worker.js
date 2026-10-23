'use strict';
importScripts('engine.js');
self.onmessage = async function (event) {
  if (!event.data || event.data.type !== 'run') return;
  try {
    const data = await RPS.simulate(event.data.config, function (completed, total) {
      self.postMessage({type: 'progress', completed, total});
    });
    self.postMessage({type: 'result', data});
  } catch (error) {
    self.postMessage({type: 'error', message: error && error.message ? error.message : String(error)});
  }
};
