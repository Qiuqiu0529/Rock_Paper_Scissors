'use strict';
(function () {
  const $ = id => document.getElementById(id);
  const clone = value => JSON.parse(JSON.stringify(value));
  const hands = ['rock', 'scissors', 'paper'];
  const handNames = {rock: '石头', scissors: '剪刀', paper: '布'};
  const strategyNames = {random: '按概率随机', fixed: '固定出拳', cycle: '循环出拳', copy_last: '模仿上一场对手', counter_last: '克制上一场对手'};
  const presetData = {"original":{"name":"原始规则：胜2平1负0，无手势奖励","seed":42,"runs":1000,"groups":[{"name":"均匀随机","count":25,"strategy":{"type":"random","probabilities":{"rock":0.3333333333333333,"scissors":0.3333333333333333,"paper":0.3333333333333334}}},{"name":"偏剪刀","count":25,"strategy":{"type":"random","probabilities":{"rock":0.2,"scissors":0.6,"paper":0.2}}},{"name":"偏布","count":25,"strategy":{"type":"random","probabilities":{"rock":0.2,"scissors":0.2,"paper":0.6}}},{"name":"偏石头","count":25,"strategy":{"type":"random","probabilities":{"rock":0.6,"scissors":0.2,"paper":0.2}}}],"scoring":{"win":2,"draw":1,"loss":0,"hand_bonus":{"rock":0,"scissors":0,"paper":0}},"tie_breakers":["wins","random"],"stages":[{"name":"初赛","rounds":9,"group_size":10,"advance":30,"reset_scores":true},{"name":"决赛","rounds":9,"group_size":10,"advance":10,"reset_scores":true}]},"bonus":{"name":"剪刀奖励：胜或平加0.5分，每阶段最多3分","seed":42,"runs":1000,"groups":[{"name":"均匀随机","count":25,"strategy":{"type":"random","probabilities":{"rock":0.3333333333333333,"scissors":0.3333333333333333,"paper":0.3333333333333334}}},{"name":"偏剪刀","count":25,"strategy":{"type":"random","probabilities":{"rock":0.2,"scissors":0.6,"paper":0.2}}},{"name":"偏布","count":25,"strategy":{"type":"random","probabilities":{"rock":0.2,"scissors":0.2,"paper":0.6}}},{"name":"偏石头","count":25,"strategy":{"type":"random","probabilities":{"rock":0.6,"scissors":0.2,"paper":0.2}}}],"scoring":{"win":2,"draw":1,"loss":0,"hand_bonus":{"rock":0,"scissors":0.5,"paper":0},"bonus_outcomes":["win","draw"],"hand_bonus_limit":{"scissors":6},"hand_bonus_cap":{"scissors":3}},"tie_breakers":["wins","scissors_wins","random"],"stages":[{"name":"初赛","rounds":9,"group_size":10,"advance":30,"reset_scores":true},{"name":"决赛","rounds":9,"group_size":10,"advance":10,"reset_scores":true}]},"advanced":{"name":"多策略三阶段示例：结转、清零与阶段策略","seed":20261022,"runs":100,"groups":[{"name":"均匀随机","count":30,"strategy":{"type":"random","probabilities":{"rock":0.3333333333333333,"scissors":0.3333333333333333,"paper":0.3333333333333334}}},{"name":"偏剪刀","count":20,"strategy":{"type":"random","probabilities":{"rock":0.2,"scissors":0.6,"paper":0.2}}},{"name":"固定石头","count":10,"strategy":{"type":"fixed","hand":"rock"}},{"name":"初期固定剪刀，决赛改随机","count":10,"strategy":{"type":"fixed","hand":"scissors"},"stage_strategies":{"决赛":{"type":"random","probabilities":{"rock":0.5,"scissors":0.3,"paper":0.2}}}},{"name":"石剪布循环","count":10,"strategy":{"type":"cycle","sequence":["rock","scissors","paper"],"offset":0,"reset_each_stage":true}},{"name":"模仿上一场对手","count":10,"strategy":{"type":"copy_last","initial":"paper","reset_each_stage":false}},{"name":"克制上一场对手","count":10,"strategy":{"type":"counter_last","initial":"rock","reset_each_stage":true}}],"scoring":{"win":3,"draw":1,"loss":0,"hand_bonus":{"rock":0,"scissors":0.5,"paper":0}},"tie_breakers":["wins","draws","random"],"stages":[{"name":"初赛","rounds":5,"advance":30,"reset_scores":true},{"name":"复赛","rounds":5,"advance":20,"reset_scores":false,"scoring":{"win":2,"draw":1,"loss":0,"hand_bonus":{"rock":0,"scissors":1,"paper":0}},"tie_breakers":["scissors_count","wins","random"]},{"name":"决赛","rounds":7,"advance":10,"reset_scores":true,"scoring":{"win":3,"draw":1,"loss":-0.5,"hand_bonus":{"rock":0,"scissors":0.5,"paper":0.25}}}]}};
  const state = {config: clone(presetData.bonus), activePreset: 'bonus', probabilityModes: [], jsonDirty: false, running: false, worker: null, html: '', result: null, executedFingerprint: '', noticeTimer: null};
  const numberValue = value => value.trim() === '' ? null : Number(value);
  const finite = value => value !== null && value !== '' && Number.isFinite(Number(value));
  const fmt = value => finite(value) ? Number(value).toLocaleString('zh-CN', {maximumFractionDigits: 2}) : '—';
  const create = (tag, className, text) => {const node = document.createElement(tag);if (className) node.className = className;if (text !== undefined) node.textContent = String(text);return node;};
  function notice(message, error = false) {clearTimeout(state.noticeTimer);$('global-notice').textContent = message;$('global-notice').classList.toggle('error', error);$('global-notice').hidden = false;state.noticeTimer = setTimeout(() => {$('global-notice').hidden = true;}, error ? 9000 : 4500);}
  function inputField(labelText, value, onInput, options = {}) {
    const label = create('label', 'field'), caption = create('span', null, labelText), input = create('input');
    input.type = options.type || 'text';input.value = value ?? '';input.setAttribute('aria-label', options.ariaLabel || labelText);
    if (options.min !== undefined) input.min = String(options.min);if (options.step !== undefined) input.step = String(options.step);if (options.inputMode) input.inputMode = options.inputMode;if (options.className) input.className = options.className;
    input.oninput = () => onInput(input.value);label.append(caption, input);if (options.help) label.append(create('small', null, options.help));return label;
  }
  function selectField(labelText, value, entries, onChange) {
    const label = create('label', 'field'), select = create('select');select.setAttribute('aria-label', labelText);
    entries.forEach(([v, text]) => {const option = create('option', null, text);option.value = v;select.append(option);});select.value = value;select.onchange = () => onChange(select.value);label.append(create('span', null, labelText), select);return label;
  }
  function checkbox(labelText, checked, onChange) {const label = create('label', 'checkbox-line'), input = create('input');input.type = 'checkbox';input.checked = checked;input.onchange = () => onChange(input.checked);label.append(input, document.createTextNode(labelText));return label;}
  function removeButton(title, onClick) {const button = create('button', 'icon-button', '×');button.type = 'button';button.title = title;button.setAttribute('aria-label', title);button.onclick = onClick;return button;}
  function syncJson(force = false) {if (!state.jsonDirty || force) {$('config-json').value = JSON.stringify(state.config, null, 2);state.jsonDirty = false;$('json-status').textContent = '与表单同步';}}
  function markChanged() {state.activePreset = '';updatePresetStyles();syncJson();refreshValidation();updateStale();}
  function updatePresetStyles() {['original', 'bonus', 'advanced'].forEach(key => {$('preset-' + key).classList.toggle('selected', state.activePreset === key);});if (!state.activePreset) $('preset-notice').textContent = '正在使用自定义配置';}
  function updateStale() {$('results-stale').hidden = !state.html || (!state.jsonDirty && JSON.stringify(state.config) === state.executedFingerprint);}
  function renderGroups() {
    const root = $('group-list');root.replaceChildren();
    (state.config.groups || []).forEach((group, index) => {
      const card = create('article', 'group-card');card.dataset.groupIndex = index;
      const head = create('div', 'group-header');head.append(create('span', 'card-number', String(index + 1).padStart(2, '0')), create('span', 'group-title', '策略组'));
      head.append(removeButton('删除策略组 ' + (index + 1), () => {state.config.groups.splice(index, 1);state.probabilityModes.splice(index, 1);renderGroups();markChanged();}));card.append(head);
      const fields = create('div', 'field-grid group-fields');
      fields.append(inputField('组名', group.name, value => {group.name = value;markChanged();}, {className: 'group-name', ariaLabel: '第 ' + (index + 1) + ' 组名称'}), inputField('人数', group.count, value => {group.count = numberValue(value);markChanged();}, {type: 'number', min: 1, step: 1, className: 'group-count', ariaLabel: '第 ' + (index + 1) + ' 组人数'}));
      const strategy = group.strategy || (group.probabilities ? {type: 'random', probabilities: group.probabilities} : (group.strategy = {type: 'random', probabilities: {rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3}}));
      if (!strategy.type) strategy.type = 'random';
      fields.append(selectField('出拳策略', strategy.type, Object.entries(strategyNames), value => {const reset = strategy.reset_each_stage !== false;delete group.probabilities;group.strategy = value === 'random' ? {type: value, probabilities: {rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3}, reset_each_stage: reset} : value === 'fixed' ? {type: value, hand: 'rock', reset_each_stage: reset} : value === 'cycle' ? {type: value, sequence: ['rock', 'scissors', 'paper'], offset: 0, reset_each_stage: reset} : {type: value, initial: 'rock', reset_each_stage: reset};renderGroups();markChanged();}));card.append(fields);
      const details = create('div', 'group-details');
      if (strategy.type === 'random') {
        const probabilities = strategy.probabilities || (strategy.probabilities = {rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3});
        const mode = state.probabilityModes[index] || 'percent', h = create('div', 'strategy-parameter-head');h.append(create('span', null, '每一局的出拳概率'));
        const modeSelect = create('select', 'probability-mode');modeSelect.setAttribute('aria-label', '第 ' + (index + 1) + ' 组概率单位');[['percent', '百分比 · 0–100'], ['decimal', '小数 · 0–1']].forEach(([v, text]) => {const o = create('option', null, text);o.value = v;modeSelect.append(o);});modeSelect.value = mode;modeSelect.onchange = () => {state.probabilityModes[index] = modeSelect.value;renderGroups();};h.append(modeSelect);details.append(h);
        const grid = create('div', 'parameter-grid'), total = create('div', 'prob-total');
        const updateTotal = () => {const valid = hands.every(k => finite(probabilities[k])), sum = valid ? hands.reduce((n, k) => n + Number(probabilities[k]), 0) : null;total.textContent = sum === null ? '请填写完整的三项概率' : '概率合计 ' + fmt(sum * 100) + '%';total.classList.toggle('invalid', sum === null || Math.abs(sum - 1) > 1e-9);};
        hands.forEach(hand => {const n = Number(probabilities[hand]), displayed = finite(probabilities[hand]) ? String(Number((n * (mode === 'percent' ? 100 : 1)).toPrecision(13))) : '';
          const field = inputField(handNames[hand] + (mode === 'percent' ? ' (%)' : ''), displayed, value => {const raw = value.trim();probabilities[hand] = raw === '' ? null : Number(raw.replace(/%$/, '')) / (raw.endsWith('%') || mode === 'percent' ? 100 : 1);updateTotal();markChanged();}, {inputMode: 'decimal', className: 'probability-input', ariaLabel: '第 ' + (index + 1) + ' 组' + handNames[hand] + '概率'});const dot = create('i', 'hand-dot ' + hand);field.firstChild.prepend(dot);grid.append(field);});details.append(grid, total);updateTotal();
      } else if (strategy.type === 'fixed') {details.append(selectField('固定出拳', strategy.hand || 'rock', hands.map(k => [k, handNames[k]]), value => {strategy.hand = value;markChanged();}));}
      else if (strategy.type === 'cycle') {
        details.append(inputField('循环顺序', (strategy.sequence || ['rock', 'scissors', 'paper']).map(k => handNames[k] || k).join('，'), value => {const aliases = {石头: 'rock', 剪刀: 'scissors', 布: 'paper'};strategy.sequence = value.split(/[，,、\s]+/).filter(Boolean).map(v => aliases[v] || v);markChanged();}, {help: '按顺序重复，可用中文或 rock、scissors、paper。'}), inputField('起始偏移', strategy.offset ?? 0, value => {strategy.offset = numberValue(value);markChanged();}, {type: 'number', step: 1, min: 0}));
      } else {details.append(selectField('首场初始出拳', strategy.initial || 'rock', hands.map(k => [k, handNames[k]]), value => {strategy.initial = value;markChanged();}));}
      if (strategy.type !== 'random' && strategy.type !== 'fixed') details.append(checkbox('每阶段重置策略记忆 / 循环位置', strategy.reset_each_stage !== false, value => {strategy.reset_each_stage = value;markChanged();}));
      card.append(details);const overrides = Object.keys(group.stage_strategies || {});if (overrides.length) card.append(create('span', 'override-label', '含 ' + overrides.length + ' 项阶段策略 · 可在完整 JSON 中编辑'));root.append(card);
    });
    if (!(state.config.groups || []).length) root.append(create('p', 'panel-copy', '还没有策略组，点击“添加组”创建。'));
  }
  function renderStages() {
    const root = $('stage-list');root.replaceChildren();let entrants = (state.config.groups || []).reduce((n, g) => n + (Number(g.count) || 0), 0);
    (state.config.stages || []).forEach((stage, index) => {
      if (stage.name === undefined) stage.name = '第' + (index + 1) + '阶段';
      const card = create('article', 'stage-card');card.dataset.stageIndex = index;const head = create('div', 'stage-topline');head.append(create('span', 'card-number', String(index + 1).padStart(2, '0')), create('span', 'stage-path', fmt(entrants) + ' 人参赛 → ' + fmt(stage.advance) + ' 人' + (index === state.config.stages.length - 1 ? '最终入选' : '晋级')), removeButton('删除阶段 ' + (index + 1), () => {const name = stage.name;state.config.stages.splice(index, 1);(state.config.groups || []).forEach(group => {if (group.stage_strategies) delete group.stage_strategies[name];});renderGroups();renderStages();markChanged();}));card.append(head);
      const fields = create('div', 'field-grid stage-fields');fields.append(inputField('阶段名称', stage.name, value => {const oldName = stage.name;stage.name = value;(state.config.groups || []).forEach(g => {if (g.stage_strategies && Object.hasOwn(g.stage_strategies, oldName) && !Object.hasOwn(g.stage_strategies, value)) {Object.defineProperty(g.stage_strategies, value, {value: g.stage_strategies[oldName], enumerable: true, writable: true, configurable: true});delete g.stage_strategies[oldName];}});markChanged();}, {className: 'stage-name'}), inputField('每人场数', stage.rounds, value => {stage.rounds = numberValue(value);markChanged();}, {type: 'number', min: 1, step: 1, className: 'stage-rounds'}), inputField('晋级人数', stage.advance, value => {stage.advance = numberValue(value);markChanged();}, {type: 'number', min: 1, step: 1, className: 'stage-advance'}), inputField('每个赛程组人数', stage.group_size ?? '', value => {stage.group_size = value.trim() === '' ? null : numberValue(value);markChanged();}, {type: 'number', min: 2, step: 2, className: 'stage-group-size', help: '留空为全阶段随机匹配；设置 10 且每人 9 场即组内循环赛。'}));card.append(fields, checkbox('本阶段积分清零', stage.reset_scores !== false, value => {stage.reset_scores = value;markChanged();}));
      if (stage.scoring || stage.tie_breakers) card.append(create('span', 'override-label', '本阶段含独立' + (stage.scoring ? '积分' : '') + (stage.scoring && stage.tie_breakers ? ' / ' : '') + (stage.tie_breakers ? '同分' : '') + '规则 · 在完整 JSON 中编辑'));
      root.append(card);entrants = Number(stage.advance) || 0;
    });
    if (!(state.config.stages || []).length) root.append(create('p', 'panel-copy', '还没有比赛阶段，点击“添加阶段”创建。'));
  }
  function renderGlobals() {
    const scoring = state.config.scoring || (state.config.scoring = {win: 2, draw: 1, loss: 0, hand_bonus: {rock: 0, scissors: 0, paper: 0}});scoring.hand_bonus ||= {rock: 0, scissors: 0, paper: 0};
    const effective = window.RPS.normalizeConfig(clone(state.config)).scoring;
    ['win', 'draw', 'loss'].forEach(k => {$('score-' + k).value = scoring[k] ?? effective[k];$('score-' + k).oninput = event => {scoring[k] = event.target.value.trim();markChanged();};});hands.forEach(k => {$('bonus-' + k).value = scoring.hand_bonus[k] ?? effective.hand_bonus[k];$('bonus-' + k).oninput = event => {scoring.hand_bonus[k] = event.target.value.trim();markChanged();};});
    ['win', 'draw', 'loss'].forEach(k => {const el = $('bonus-on-' + k);el.checked = (scoring.bonus_outcomes || effective.bonus_outcomes).includes(k);el.onchange = () => {scoring.bonus_outcomes = ['win', 'draw', 'loss'].filter(outcome => $('bonus-on-' + outcome).checked);markChanged();};});
    for (const field of ['hand_bonus_limit', 'hand_bonus_cap']) hands.forEach(k => {const el = $(field + '-' + k);el.value = scoring[field]?.[k] ?? effective[field][k] ?? '';el.oninput = () => {scoring[field] ||= {};scoring[field][k] = el.value.trim() === '' ? null : field === 'hand_bonus_limit' ? numberValue(el.value) : el.value.trim();markChanged();};});
    $('config-name').value = state.config.name ?? '石头剪刀布模拟';$('config-name').oninput = event => {state.config.name = event.target.value;markChanged();};
    $('config-runs').value = state.config.runs ?? 1;$('config-runs').oninput = event => {state.config.runs = numberValue(event.target.value);markChanged();};
    $('config-seed').value = state.config.seed ?? 42;$('config-seed').oninput = event => {state.config.seed = numberValue(event.target.value);markChanged();};
    $('tie-breakers').value = (state.config.tie_breakers || ['wins', 'random']).join(', ');$('tie-breakers').oninput = event => {state.config.tie_breakers = event.target.value.split(/[,，\s]+/).filter(Boolean);markChanged();};
  }
  function refreshValidation() {
    let canonical = null, error = '';
    try {if (!window.RPS || typeof window.RPS.normalizeConfig !== 'function') throw new Error('模拟引擎尚未准备好，请刷新页面重试。');canonical = window.RPS.normalizeConfig(clone(state.config));} catch (e) {error = e.message || String(e);}
    const cfg = canonical || state.config, groups = Array.isArray(cfg.groups) ? cfg.groups : [], stages = Array.isArray(cfg.stages) ? cfg.stages : [], players = groups.reduce((n, g) => n + (Number(g.count) || 0), 0);let entrants = players, rounds = 0, matches = 0;
    stages.forEach(s => {rounds += Number(s.rounds) || 0;matches += entrants * (Number(s.rounds) || 0) / 2;entrants = Number(s.advance) || 0;});
    $('summary-players').textContent = fmt(players);$('summary-qualifiers').textContent = stages.length ? fmt(stages[stages.length - 1].advance) : '—';$('summary-rounds').textContent = fmt(rounds) + ' 轮';$('summary-matches').textContent = fmt(matches) + ' 局';$('summary-runs').textContent = fmt(cfg.runs ?? 1) + ' 届';$('summary-total').textContent = fmt(matches * Number(cfg.runs ?? 1)) + ' 局';
    const flow = $('summary-flow');flow.replaceChildren(create('strong', null, fmt(players)));stages.forEach(s => {flow.append(create('b', null, '→'));const x = create('span');x.append(create('strong', null, fmt(s.advance)));x.title = s.name;flow.append(x);});
    let pathEntrants = players;document.querySelectorAll('.stage-card').forEach((card, index) => {const stage = stages[index];if (!stage) return;const path = card.querySelector('.stage-path');if (path) path.textContent = fmt(pathEntrants) + ' 人参赛 → ' + fmt(stage.advance) + ' 人' + (index === stages.length - 1 ? '最终入选' : '晋级');pathEntrants = Number(stage.advance) || 0;});
    const badge = $('valid-badge'), box = $('validation-box');badge.textContent = state.jsonDirty ? 'JSON 待应用' : error ? '需调整' : '配置有效';badge.classList.toggle('invalid', !!error || state.jsonDirty);box.classList.toggle('visible', !!error || state.jsonDirty);box.textContent = state.jsonDirty ? 'JSON 有尚未应用的修改；点击开始模拟时会先应用并验证。' : error;
    $('run-simulation').disabled = state.running || (!!error && !state.jsonDirty);return {canonical, error};
  }
  function renderAll() {const normalized = window.RPS.normalizeConfig(clone(state.config));if (!Object.hasOwn(state.config, 'groups')) state.config.groups = clone(normalized.groups);if (!Object.hasOwn(state.config, 'stages')) state.config.stages = normalized.stages.map(stage => ({name: stage.name, rounds: stage.rounds, group_size: stage.group_size, advance: stage.advance, reset_scores: stage.reset_scores}));renderGroups();renderStages();renderGlobals();syncJson(true);updatePresetStyles();refreshValidation();updateStale();}
  function applyJson(quiet = false) {
    try {const raw = JSON.parse($('config-json').value);window.RPS.normalizeConfig(clone(raw));state.config = raw;state.jsonDirty = false;state.activePreset = '';state.probabilityModes = [];renderAll();if (!quiet) notice('JSON 配置已应用，阶段规则与策略选项已完整保留。');return true;}
    catch (e) {$('json-status').textContent = '应用失败：' + (e.message || String(e));$('advanced-details').open = true;notice('配置未应用：' + (e.message || String(e)), true);return false;}
  }
  function switchView(result) {if (result && !state.html) return;$('setup-view').hidden = result;$('results-view').hidden = !result;$('tab-setup').classList.toggle('active', !result);$('tab-results').classList.toggle('active', result);$('tab-setup').setAttribute('aria-selected', String(!result));$('tab-results').setAttribute('aria-selected', String(result));window.scrollTo({top: 0, behavior: 'smooth'});}
  function showReport(html) {
    // Give every run a new browsing context. Reusing a hidden srcdoc frame can
    // leave its previous document's paint/scroll state until the tab is toggled.
    const previous = $('result-frame'), frame = previous.cloneNode(false);
    frame.removeAttribute('srcdoc');
    switchView(true);
    previous.replaceWith(frame);
    window.requestAnimationFrame(() => {
      if (frame.isConnected && $('result-frame') === frame) frame.srcdoc = html;
    });
  }
  function download(content, filename, mime) {const blob = new Blob([content], {type: mime}), url = URL.createObjectURL(blob), a = create('a');a.href = url;a.download = filename;document.body.append(a);a.click();a.remove();setTimeout(() => URL.revokeObjectURL(url), 30000);}
  function setBusy(busy) {state.running = busy;$('stop-simulation').hidden = !busy;$('run-simulation').firstElementChild.textContent = busy ? '正在模拟…' : '开始模拟';refreshValidation();}
  function stopWorker() {if (state.worker) state.worker.terminate();state.worker = null;setBusy(false);}
  async function runSimulation() {
    if (state.running) return;if (state.jsonDirty && !applyJson(true)) return;const checked = refreshValidation();if (checked.error) {notice(checked.error, true);return;}
    const config = clone(checked.canonical), fingerprint = JSON.stringify(state.config);let worker;
    try {worker = window.RPSCreateWorker ? window.RPSCreateWorker() : new Worker('worker.js');} catch (e) {notice('无法启动模拟线程：' + e.message, true);return;}
    state.worker = worker;setBusy(true);$('progress-box').hidden = false;$('progress-label').textContent = '正在准备比赛…';$('progress-percent').textContent = '0%';$('simulation-progress').max = 100;$('simulation-progress').value = 0;
    worker.onmessage = async event => {
      if (state.worker !== worker) return;const msg = event.data || {};
      if (msg.type === 'progress') {const total = Number(msg.total) || 1, completed = Number(msg.completed) || 0;$('simulation-progress').max = total;$('simulation-progress').value = completed;$('progress-percent').textContent = (completed / total * 100).toFixed(completed < total ? 1 : 0) + '%';$('progress-label').textContent = '已完成 ' + fmt(completed) + ' / ' + fmt(total) + ' 局';}
      else if (msg.type === 'error') {stopWorker();$('progress-label').textContent = '本次模拟未完成';notice(msg.message || '模拟发生错误，请检查配置。', true);}
      else if (msg.type === 'result') {
        $('progress-label').textContent = '模拟完成，正在生成报告…';$('progress-percent').textContent = '100%';$('simulation-progress').value = $('simulation-progress').max;
        try {if (!window.RPSReport || typeof window.RPSReport.render !== 'function') throw new Error('报告组件没有加载成功。');const html = await window.RPSReport.render(msg.data);if (state.worker !== worker) return;
          state.html = html;state.result = msg.data;state.executedFingerprint = fingerprint;$('tab-results').disabled = false;$('result-badge').hidden = false;$('download-report').disabled = false;
          const meta = msg.data.meta || {}, name = meta.title || config.name || '比赛分析报告';$('executed-name').textContent = name;$('executed-meta').textContent = '已执行配置 · ' + fmt(meta.players ?? config.groups.reduce((n, g) => n + g.count, 0)) + ' 人 / 届 · ' + fmt(meta.runs ?? config.runs) + ' 届 · 随机种子 ' + String(meta.seed ?? config.seed);$('result-success').textContent = '模拟已完成。策略与晋级统计汇总全部 ' + fmt(meta.runs ?? config.runs) + ' 届；逐轮过程和玩家排名展示首届比赛。';updateStale();stopWorker();$('progress-label').textContent = '模拟与可视化报告已完成';showReport(html);notice('报告已生成，可交互查看或下载离线保存。');
        } catch (e) {stopWorker();$('progress-label').textContent = '报告生成失败';notice('报告生成失败：' + (e.message || String(e)), true);}
      }
    };
    worker.onerror = event => {if (state.worker !== worker) return;stopWorker();$('progress-label').textContent = '模拟线程已停止';notice('模拟线程发生错误：' + (event.message || '请重新运行。'), true);};
    worker.postMessage({type: 'run', config});
  }
  $('add-group').onclick = () => {state.config.groups ||= [];state.config.groups.push({name: '策略组 ' + (state.config.groups.length + 1), count: 10, strategy: {type: 'random', probabilities: {rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3}}});renderGroups();renderStages();markChanged();};
  $('add-stage').onclick = () => {state.config.stages ||= [];const prev = state.config.stages.length ? state.config.stages[state.config.stages.length - 1].advance : (state.config.groups || []).reduce((n, g) => n + Number(g.count), 0);state.config.stages.push({name: '阶段 ' + (state.config.stages.length + 1), rounds: Math.min(5, Math.max(1, Number(prev) - 1)), advance: Math.max(1, Math.floor(Number(prev) / 4) * 2), reset_scores: true});renderStages();markChanged();};
  ['original', 'bonus', 'advanced'].forEach(key => {$('preset-' + key).onclick = () => {state.config = clone(presetData[key]);state.activePreset = key;state.probabilityModes = [];state.jsonDirty = false;renderAll();$('preset-notice').textContent = '已加载' + ({original: '原始规则', bonus: '剪刀奖励', advanced: '进阶实验'}[key]) + '预设';notice('预设已加载，可继续修改后开始模拟。');};});
  $('config-json').oninput = () => {state.jsonDirty = true;$('json-status').textContent = '有尚未应用的修改';refreshValidation();updateStale();};$('apply-json').onclick = () => applyJson();$('sync-json').onclick = () => {syncJson(true);refreshValidation();updateStale();notice('已用当前表单配置更新 JSON。');};
  $('import-config').onchange = async event => {const file = event.target.files[0];if (!file) return;try {if (file.size > 2 * 1024 * 1024) throw new Error('配置文件超过 2 MB，请检查文件内容。');const raw = JSON.parse(await file.text());window.RPS.normalizeConfig(clone(raw));state.config = raw;state.activePreset = '';state.probabilityModes = [];state.jsonDirty = false;renderAll();$('preset-notice').textContent = '已导入 ' + file.name;notice('配置文件已导入。');} catch (e) {notice('导入失败：' + (e.message || String(e)), true);}event.target.value = '';};
  $('export-config').onclick = () => {if (state.jsonDirty && !applyJson(true)) return;const checked = refreshValidation();if (checked.error) {notice('请先修正配置：' + checked.error, true);return;}download(JSON.stringify(state.config, null, 2) + '\n', 'rps-config.json', 'application/json;charset=utf-8');notice('配置已导出，可再次导入网页版模拟器。');};
  $('run-simulation').onclick = runSimulation;$('stop-simulation').onclick = () => {stopWorker();$('progress-label').textContent = '本次模拟已停止';notice(state.html ? '已停止计算，上一次完成的结果仍可查看。' : '已停止计算。调整设置后可重新开始。');};
  $('tab-setup').onclick = () => switchView(false);$('tab-results').onclick = () => switchView(true);$('edit-settings').onclick = () => switchView(false);$('download-report').onclick = () => {if (state.html) download(state.html, 'rps-report.html', 'text/html;charset=utf-8');};
  renderAll();window.RPSApp = {getConfig: () => clone(state.config), getResult: () => state.result, run: runSimulation, applyJson};window.appReady = true;
})();
