/* Browser RPS simulator. Scores use exact BigInt decimal arithmetic.
 * Seeded xmur-style hashing + mulberry32 streams are reproducible within this
 * JavaScript engine, but deliberately do not reproduce Python's Random stream.
 * Progress reports completed matches / total matches, across all runs.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RPS = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const HANDS = ['rock', 'scissors', 'paper'];
  const BEATS = [1, 2, 0], COUNTER = [2, 0, 1];
  const LIMITS = Object.freeze({ players: 1000, runs: 10000, matches: 20000000 });
  const TIE_KEYS = new Set(['wins', 'scissors_wins', 'draws', 'rock_count', 'scissors_count', 'paper_count', 'random']);
  const POWERS = [1n];
  const ZERO = Object.freeze({ u: 0n, s: 0 });
  const DEFAULT_CONFIG = {
    name: '原始规则两阶段比赛', seed: 42, runs: 1,
    groups: [
      { name: '均匀随机', count: 25, strategy: { type: 'random', probabilities: { rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3 } } },
      { name: '偏剪刀', count: 25, strategy: { type: 'random', probabilities: { rock: .2, scissors: .6, paper: .2 } } },
      { name: '偏布', count: 25, strategy: { type: 'random', probabilities: { rock: .2, scissors: .2, paper: .6 } } },
      { name: '偏石头', count: 25, strategy: { type: 'random', probabilities: { rock: .6, scissors: .2, paper: .2 } } }
    ],
    scoring: { win: 2, draw: 1, loss: 0, hand_bonus: { rock: 0, scissors: 0, paper: 0 } },
    tie_breakers: ['wins', 'random'],
    stages: [{ name: '初赛', rounds: 9, group_size: 10, advance: 30, reset_scores: true }, { name: '决赛', rounds: 9, group_size: 10, advance: 10, reset_scores: true }]
  };
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const get = (o, k, fallback) => own(o, k) ? o[k] : fallback;
  const fail = message => { throw new Error(message); };
  function obj(value, allowed, path) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail(path + ' 必须是对象。');
    const unknown = Object.keys(value).filter(k => !allowed.includes(k));
    if (unknown.length) fail(path + ' 存在未知字段：' + unknown.join('、'));
    return value;
  }
  function integer(value, path, minimum = 1) {
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum) fail(path + ' 必须是大于等于 ' + minimum + ' 的安全整数。');
    return value;
  }
  function bool(value, path) {
    if (typeof value !== 'boolean') fail(path + ' 必须是 true 或 false。');
    return value;
  }
  function name(value, path) {
    if (typeof value !== 'string' || !value.trim()) fail(path + ' 必须是非空字符串。');
    return value.trim();
  }
  function hand(value, path) {
    if (typeof value !== 'string' || !HANDS.includes(value)) fail(path + ' 必须是 rock、scissors 或 paper。');
    return HANDS.indexOf(value);
  }
  function pow10(n) {
    while (POWERS.length <= n) POWERS.push(POWERS[POWERS.length - 1] * 10n);
    return POWERS[n];
  }
  function decimal(u, s) {
    if (!u) return ZERO;
    while (u % 10n === 0n) { u /= 10n; s--; }
    return { u, s };
  }
  function parseDecimal(value, path = '积分') {
    if ((typeof value !== 'string' && typeof value !== 'number') || (typeof value === 'number' && !Number.isFinite(value))) fail(path + ' 必须是有限数值或十进制字符串。');
    if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) fail(path + ' 大整数请使用十进制字符串，以保留精确值。');
    const text = String(value).trim(), match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(text);
    if (!match) fail(path + ' 不是有效的有限十进制数。');
    const fraction = match[3] !== undefined ? match[3] : (match[4] || '');
    let digits = ((match[2] || '') + fraction).replace(/^0+/, '');
    if (!digits) return ZERO;
    const exponent = Number(match[5] || 0);
    if (!Number.isSafeInteger(exponent)) fail(path + ' 数量级超出支持范围。');
    let scale = fraction.length - exponent;
    const adjusted = digits.length - scale - 1;
    if (Math.abs(adjusted) > 100) fail(path + ' 数量级须在 10^-100 至 10^100 内（0 除外）。');
    // Insignificant trailing zeroes are removed, making canonical reload stable.
    while (digits.endsWith('0')) { digits = digits.slice(0, -1); scale--; }
    if (digits.length > 28) fail(path + ' 最多支持 28 位有效数字。');
    return { u: BigInt((match[1] === '-' ? '-' : '') + digits), s: scale };
  }
  function decimalString(value) {
    if (!value.u) return '0';
    const negative = value.u < 0n, digits = (negative ? -value.u : value.u).toString();
    let result;
    if (value.s <= 0) result = digits + '0'.repeat(-value.s);
    else if (digits.length > value.s) result = digits.slice(0, -value.s) + '.' + digits.slice(-value.s);
    else result = '0.' + '0'.repeat(value.s - digits.length) + digits;
    return (negative ? '-' : '') + result;
  }
  function add(a, b) {
    if (!a.u) return b;
    if (!b.u) return a;
    const scale = Math.max(a.s, b.s);
    return decimal(a.u * pow10(scale - a.s) + b.u * pow10(scale - b.s), scale);
  }
  function subtract(a, b) { return add(a, { u: -b.u, s: b.s }); }
  function compare(a, b) {
    const scale = Math.max(a.s, b.s), x = a.u * pow10(scale - a.s), y = b.u * pow10(scale - b.s);
    return x < y ? -1 : x > y ? 1 : 0;
  }
  function meanDecimal(value, count) {
    if (!count) return null;
    if (!value.u) return '0';
    const negative = value.u < 0n, u = negative ? -value.u : value.u, denominator = BigInt(count);
    let order = u.toString().length - denominator.toString().length;
    if ((order >= 0 ? u < denominator * pow10(order) : u * pow10(-order) < denominator)) order--;
    const targetScale = 255 - (order - value.s), shift = targetScale - value.s;
    const numerator = shift >= 0 ? u * pow10(shift) : u;
    const divisor = shift >= 0 ? denominator : denominator * pow10(-shift);
    let quotient = numerator / divisor;
    const remainder = numerator % divisor;
    if (remainder * 2n > divisor || (remainder * 2n === divisor && quotient % 2n !== 0n)) quotient++;
    return decimalString(decimal(negative ? -quotient : quotient, targetScale));
  }
  function scoring(raw, base, path) {
    obj(raw, ['win', 'draw', 'loss', 'hand_bonus', 'bonus_outcomes', 'hand_bonus_limit', 'hand_bonus_cap'], path);
    const bonuses = get(raw, 'hand_bonus', {});
    obj(bonuses, HANDS, path + '.hand_bonus');
    const result = {};
    ['win', 'draw', 'loss'].forEach(k => { result[k] = decimalString(parseDecimal(get(raw, k, base[k]), path + '.' + k)); });
    result.hand_bonus = {};
    HANDS.forEach(k => { result.hand_bonus[k] = decimalString(parseDecimal(get(bonuses, k, base.hand_bonus[k]), path + '.hand_bonus.' + k)); });
    const outcomes = get(raw, 'bonus_outcomes', base.bonus_outcomes);
    if (!Array.isArray(outcomes) || outcomes.some(k => !['win', 'draw', 'loss'].includes(k)) || new Set(outcomes).size !== outcomes.length) fail(path + '.bonus_outcomes 只能由 win、draw、loss 组成且不可重复。');
    result.bonus_outcomes = outcomes.slice();
    result.hand_bonus_limit = {};
    result.hand_bonus_cap = {};
    for (const field of ['hand_bonus_limit', 'hand_bonus_cap']) {
      const values = get(raw, field, {}); obj(values, HANDS, path + '.' + field);
      HANDS.forEach(k => {
        const value = get(values, k, base[field][k]);
        if (field === 'hand_bonus_limit') result[field][k] = value === null ? null : integer(value, path + '.' + field + '.' + k, 0);
        else { const parsed = value === null ? null : parseDecimal(value, path + '.' + field + '.' + k); if (parsed !== null && compare(parsed, ZERO) < 0) fail(path + '.' + field + '.' + k + ' 不得为负数。'); result[field][k] = parsed === null ? null : decimalString(parsed); }
      });
    }
    return result;
  }
  function ties(raw, path) {
    if (!Array.isArray(raw) || raw.some(k => typeof k !== 'string' || !TIE_KEYS.has(k))) fail(path + ' 仅支持 wins/scissors_wins/draws/rock_count/scissors_count/paper_count/random。');
    if (new Set(raw).size !== raw.length || (raw.includes('random') && raw[raw.length - 1] !== 'random')) fail(path + ' 不可重复，random 必须位于最后。');
    return raw.includes('random') ? raw.slice() : [...raw, 'random'];
  }
  function strategy(raw, path) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(path + ' 必须是策略对象。');
    const type = get(raw, 'type', 'random');
    const allowed = { random: ['probabilities'], fixed: ['hand'], cycle: ['sequence', 'offset'], copy_last: ['initial'], counter_last: ['initial'] };
    if (typeof type !== 'string' || !own(allowed, type)) fail(path + '.type 必须是 random/fixed/cycle/copy_last/counter_last。');
    obj(raw, ['type', 'reset_each_stage', ...allowed[type]], path);
    const result = { type, reset_each_stage: bool(get(raw, 'reset_each_stage', true), path + '.reset_each_stage') };
    if (type === 'random') {
      const values = get(raw, 'probabilities', { rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3 });
      obj(values, HANDS, path + '.probabilities');
      if (HANDS.some(k => !own(values, k) || typeof values[k] !== 'number' || !Number.isFinite(values[k]) || values[k] < 0 || values[k] > 1)) fail(path + '.probabilities 必须包含三个 0 到 1 之间的有限数值。');
      const total = HANDS.reduce((sum, k) => sum + values[k], 0);
      if (Math.abs(total - 1) > 1e-9) fail(path + '.probabilities 之和必须为 1，当前为 ' + total + '。');
      result.probabilities = {};
      HANDS.forEach(k => { result.probabilities[k] = Math.abs(total - 1) <= 1e-15 ? values[k] : values[k] / total; });
    } else if (type === 'fixed') { hand(raw.hand, path + '.hand'); result.hand = raw.hand; }
    else if (type === 'cycle') {
      if (!Array.isArray(raw.sequence) || !raw.sequence.length) fail(path + '.sequence 必须是非空手势数组。');
      raw.sequence.forEach(h => hand(h, path + '.sequence'));
      result.sequence = raw.sequence.slice();
      result.offset = integer(get(raw, 'offset', 0), path + '.offset', 0);
    } else { result.initial = get(raw, 'initial', 'rock'); hand(result.initial, path + '.initial'); }
    return result;
  }
  function normalizeConfig(raw = {}) {
    obj(raw, ['name', 'seed', 'runs', 'groups', 'scoring', 'tie_breakers', 'stages'], '配置');
    const seed = get(raw, 'seed', 42);
    if (typeof seed !== 'number' || !Number.isSafeInteger(seed)) fail('seed 必须是安全整数。');
    const runs = integer(get(raw, 'runs', 1), 'runs');
    if (runs > LIMITS.runs) fail('浏览器最多支持 ' + LIMITS.runs + ' 届；请减少 runs。');
    const baseScoring = scoring(get(raw, 'scoring', {}), { win: '2', draw: '1', loss: '0', hand_bonus: { rock: '0', scissors: '0', paper: '0' }, bonus_outcomes: ['win', 'draw', 'loss'], hand_bonus_limit: {rock: null, scissors: null, paper: null}, hand_bonus_cap: {rock: null, scissors: null, paper: null} }, 'scoring');
    const baseTies = ties(get(raw, 'tie_breakers', ['wins', 'random']), 'tie_breakers');
    const rawGroups = get(raw, 'groups', DEFAULT_CONFIG.groups);
    if (!Array.isArray(rawGroups) || !rawGroups.length) fail('groups 必须是非空数组。');
    const names = new Set();
    let count = 0;
    const groups = rawGroups.map((entry, i) => {
      const path = 'groups[' + (i + 1) + ']';
      obj(entry, ['name', 'count', 'strategy', 'probabilities', 'stage_strategies'], path);
      const groupName = name(entry.name, path + '.name');
      if (names.has(groupName)) fail('策略组名称重复：' + groupName);
      names.add(groupName);
      if (own(entry, 'strategy') && own(entry, 'probabilities')) fail(path + ' 不能同时设置 strategy 和 probabilities。');
      const groupCount = integer(entry.count, path + '.count'); count += groupCount;
      if (count > LIMITS.players) fail('浏览器最多支持 ' + LIMITS.players + ' 人。');
      const rawStrategy = get(entry, 'strategy', { type: 'random', probabilities: get(entry, 'probabilities', { rock: 1 / 3, scissors: 1 / 3, paper: 1 / 3 }) });
      const overrides = get(entry, 'stage_strategies', {});
      if (!overrides || typeof overrides !== 'object' || Array.isArray(overrides)) fail(path + '.stage_strategies 必须是阶段名到策略的对象。');
      const stageStrategies = Object.create(null);
      Object.keys(overrides).forEach(k => { stageStrategies[k] = strategy(overrides[k], path + '.stage_strategies.' + k); });
      return { name: groupName, count: groupCount, strategy: strategy(rawStrategy, path + '.strategy'), stage_strategies: stageStrategies };
    });
    if (count < 2 || count % 2) fail('参赛总人数必须是大于等于 2 的偶数，不使用轮空。');
    const rawStages = get(raw, 'stages', DEFAULT_CONFIG.stages);
    if (!Array.isArray(rawStages) || !rawStages.length) fail('stages 必须是非空数组。');
    const stageNames = new Set(); let entrants = count, matches = 0;
    const stages = rawStages.map((entry, i) => {
      const path = 'stages[' + (i + 1) + ']';
      obj(entry, ['name', 'rounds', 'group_size', 'advance', 'reset_scores', 'scoring', 'tie_breakers'], path);
      const stageName = name(get(entry, 'name', '第' + (i + 1) + '阶段'), path + '.name');
      if (stageNames.has(stageName)) fail('阶段名称重复：' + stageName);
      stageNames.add(stageName);
      const rounds = integer(entry.rounds, path + '.rounds'), advance = integer(entry.advance, path + '.advance');
      const groupSize = get(entry, 'group_size', null);
      if (groupSize !== null && (integer(groupSize, path + '.group_size', 2) % 2 || entrants % groupSize || rounds >= groupSize)) fail(path + '.group_size 须为可整除参赛人数的偶数，且每人场数须小于每组人数。');
      if (entrants % 2 || rounds >= entrants) fail(path + ' 参赛人数须为偶数，每人场次须在 1 到 ' + (entrants - 1) + ' 之间。');
      if (advance > entrants || (i < rawStages.length - 1 && (advance < 2 || advance % 2))) fail(path + '.advance 不可超过参赛人数；非末阶段须为大于等于 2 的偶数。');
      matches += entrants * rounds / 2;
      if (matches * runs > LIMITS.matches) fail('浏览器工作量超过 ' + LIMITS.matches.toLocaleString('zh-CN') + ' 局；请减少人数、轮数或届数。');
      entrants = advance;
      return { name: stageName, rounds, group_size: groupSize, advance, reset_scores: bool(get(entry, 'reset_scores', true), path + '.reset_scores'), scoring: scoring(get(entry, 'scoring', {}), baseScoring, path + '.scoring'), tie_breakers: ties(get(entry, 'tie_breakers', baseTies), path + '.tie_breakers') };
    });
    groups.forEach(group => Object.keys(group.stage_strategies).forEach(k => { if (!stageNames.has(k)) fail('组 ' + group.name + ' 的 stage_strategies 引用了未知阶段：' + k); }));
    return { name: name(get(raw, 'name', '石头剪刀布模拟'), 'name'), seed, runs, groups, scoring: baseScoring, tie_breakers: baseTies, stages };
  }
  function seeded(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    let a = h >>> 0;
    return function () { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  function shuffle(values, rng) {
    for (let i = values.length - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [values[i], values[j]] = [values[j], values[i]]; }
    return values;
  }
  function scheduleRounds(count, rounds, rng) {
    if (!Number.isSafeInteger(count) || count < 2 || count % 2 || !Number.isSafeInteger(rounds) || rounds < 1 || rounds >= count) fail('赛程须为偶数人数，轮数在 1 到人数减 1 之间。');
    const order = shuffle(Array.from({ length: count }, (_, i) => i), rng), anchor = order[0], tail = order.slice(1);
    const shifts = shuffle(Array.from({ length: count - 1 }, (_, i) => i), rng).slice(0, rounds);
    return shifts.map(shift => {
      const rotated = [anchor, ...(shift ? [...tail.slice(-shift), ...tail.slice(0, -shift)] : tail)];
      return Array.from({ length: count / 2 }, (_, i) => [rotated[i], rotated[count - 1 - i]]);
    });
  }
  function newTally() { return { points: ZERO, wins: 0, scissors_wins: 0, draws: 0, losses: 0, hands: [0, 0, 0], games: 0 }; }
  function copyTally(t) { return { points: t.points, wins: t.wins, scissors_wins: t.scissors_wins, draws: t.draws, losses: t.losses, hands: t.hands.slice(), games: t.games }; }
  function addTally(to, from) { to.points = add(to.points, from.points); to.wins += from.wins; to.scissors_wins += from.scissors_wins; to.draws += from.draws; to.losses += from.losses; to.games += from.games; for (let i = 0; i < 3; i++) to.hands[i] += from.hands[i]; }
  function record(tally, chosen, outcome, points) { tally.points = add(tally.points, points); tally[outcome === 'win' ? 'wins' : outcome === 'draw' ? 'draws' : 'losses']++; if (outcome === 'win' && chosen === 1) tally.scissors_wins++; tally.hands[chosen]++; tally.games++; }
  function metric(tally, key) { return key.endsWith('_count') ? tally.hands[HANDS.indexOf(key.slice(0, -6))] : tally[key]; }
  function choose(strategyValue, history, rng) {
    switch (strategyValue.type) {
      case 'fixed': return HANDS.indexOf(strategyValue.hand);
      case 'cycle': {
        const length = strategyValue.sequence.length;
        return HANDS.indexOf(strategyValue.sequence[(history.index % length + strategyValue.offset % length) % length]);
      }
      case 'copy_last': return history.opponent === null ? HANDS.indexOf(strategyValue.initial) : history.opponent;
      case 'counter_last': return history.opponent === null ? HANDS.indexOf(strategyValue.initial) : COUNTER[history.opponent];
      default: { const u = rng(), p = strategyValue.probabilities; return u < p.rock ? 0 : u < p.rock + p.scissors ? 1 : 2; }
    }
  }
  function createPlayers(config) {
    const count = config.groups.reduce((sum, g) => sum + g.count, 0), width = Math.max(3, String(count).length), players = [];
    config.groups.forEach(group => { for (let i = 0; i < group.count; i++) players.push({ player_id: 'P' + String(players.length + 1).padStart(width, '0'), group }); });
    return players;
  }
  function compile(config) {
    const players = createPlayers(config); let entrants = players.length, matches = 0;
    const stages = config.stages.map(s => { const result = { ...s, entrants, baseAwards: {}, bonuses: HANDS.map(k => parseDecimal(s.scoring.hand_bonus[k])), caps: HANDS.map(k => s.scoring.hand_bonus_cap[k] === null ? null : parseDecimal(s.scoring.hand_bonus_cap[k])) }; entrants = s.advance; ['win', 'draw', 'loss'].forEach(o => { result.baseAwards[o] = parseDecimal(s.scoring[o]); }); matches += result.entrants * result.rounds / 2; return result; });
    return { config, players, stages, matches };
  }
  function* tournamentGenerator(engine, runIndex, capture) {
    const config = engine.config, totals = new Map(), histories = new Map();
    engine.players.forEach(p => { totals.set(p.player_id, newTally()); histories.set(p.player_id, { index: 0, opponent: null }); });
    let active = engine.players.slice(), previous = new Map(), overallRound = 0, completed = 0, yielded = 0;
    const results = [], eliminated = [], matches = [], roundRecords = [];
    for (let stageIndex = 1; stageIndex <= engine.stages.length; stageIndex++) {
      const spec = engine.stages[stageIndex - 1]; active.sort((a, b) => a.player_id.localeCompare(b.player_id));
      const prefix = config.seed + ':' + runIndex + ':' + stageIndex;
      const scheduleRng = seeded(prefix + ':schedule'), lotteryRng = seeded(prefix + ':lottery');
      const strategies = new Map(), rngs = new Map(), local = new Map(), carried = new Map(), bonusUsage = new Map();
      active.forEach(p => {
        const s = own(p.group.stage_strategies, spec.name) ? p.group.stage_strategies[spec.name] : p.group.strategy;
        strategies.set(p.player_id, s); rngs.set(p.player_id, seeded(prefix + ':hands:' + p.player_id)); local.set(p.player_id, newTally());
        carried.set(p.player_id, spec.reset_scores || stageIndex === 1 ? newTally() : copyTally(previous.get(p.player_id)));
        bonusUsage.set(p.player_id, HANDS.map(() => ({count: 0, points: ZERO})));
        if (s.reset_each_stage) histories.set(p.player_id, { index: 0, opponent: null });
      });
      const lottery = shuffle(active.map(p => p.player_id), lotteryRng), lotteryOrder = new Map(lottery.map((id, i) => [id, i]));
      const matchGroups = new Map(); let rounds;
      if (spec.group_size === null) {
        active.forEach(p => matchGroups.set(p.player_id, null));
        rounds = scheduleRounds(active.length, spec.rounds, scheduleRng);
      } else {
        const order = shuffle(Array.from({length: active.length}, (_, i) => i), scheduleRng);
        rounds = Array.from({length: spec.rounds}, () => []);
        for (let start = 0; start < order.length; start += spec.group_size) {
          const members = order.slice(start, start + spec.group_size), groupNumber = start / spec.group_size + 1;
          members.forEach(i => matchGroups.set(active[i].player_id, groupNumber));
          scheduleRounds(spec.group_size, spec.rounds, scheduleRng).forEach((pairs, ri) => {
            rounds[ri].push(...pairs.map(([a, b]) => [members[a], members[b]]));
          });
        }
      }
      for (let ri = 0; ri < rounds.length; ri++) {
        const roundHands = [0, 0, 0]; let drawMatches = 0;
        for (let mi = 0; mi < rounds[ri].length; mi++) {
          const pair = rounds[ri][mi].map(i => active[i]), moves = pair.map(p => choose(strategies.get(p.player_id), histories.get(p.player_id), rngs.get(p.player_id)));
          let outcomes, winner;
          if (moves[0] === moves[1]) { outcomes = ['draw', 'draw']; winner = 'draw'; drawMatches++; }
          else if (BEATS[moves[0]] === moves[1]) { outcomes = ['win', 'loss']; winner = pair[0].player_id; }
          else { outcomes = ['loss', 'win']; winner = pair[1].player_id; }
          const bonuses = outcomes.map((o, i) => {
            if (!spec.scoring.bonus_outcomes.includes(o)) return ZERO;
            const chosen = moves[i], key = HANDS[chosen], value = spec.bonuses[chosen], usage = bonusUsage.get(pair[i].player_id)[chosen];
            const limit = spec.scoring.hand_bonus_limit[key], cap = spec.caps[chosen];
            if (!value.u || (limit !== null && usage.count >= limit)) return ZERO;
            let awarded = value;
            if (cap !== null && compare(value, ZERO) > 0) {
              const remaining = subtract(cap, usage.points);
              if (compare(remaining, ZERO) <= 0) return ZERO;
              if (compare(awarded, remaining) > 0) awarded = remaining;
            }
            usage.count++; usage.points = add(usage.points, awarded);
            return awarded;
          });
          const points = outcomes.map((o, i) => add(spec.baseAwards[o], bonuses[i]));
          pair.forEach((p, i) => {
            record(local.get(p.player_id), moves[i], outcomes[i], points[i]); record(totals.get(p.player_id), moves[i], outcomes[i], points[i]);
            const h = histories.get(p.player_id); h.index++; h.opponent = moves[1 - i]; roundHands[moves[i]]++;
          });
          if (capture) matches.push({ stage: stageIndex, stage_name: spec.name, match_group: matchGroups.get(pair[0].player_id), round: ri + 1, overall_round: overallRound + ri + 1, match: mi + 1,
            player_1: pair[0].player_id, group_1: pair[0].group.name, strategy_1: strategies.get(pair[0].player_id).type, hand_1: HANDS[moves[0]],
            player_2: pair[1].player_id, group_2: pair[1].group.name, strategy_2: strategies.get(pair[1].player_id).type, hand_2: HANDS[moves[1]], winner,
            base_points_1: spec.scoring[outcomes[0]], bonus_1: decimalString(bonuses[0]), points_1: decimalString(points[0]),
            base_points_2: spec.scoring[outcomes[1]], bonus_2: decimalString(bonuses[1]), points_2: decimalString(points[1]) });
          completed++; if (completed % 2000 === 0) { yielded = completed; yield completed; }
        }
        if (capture) {
          let highest = null; const leaders = [];
          active.forEach(p => { const value = add(carried.get(p.player_id).points, local.get(p.player_id).points), c = highest === null ? 1 : compare(value, highest); if (c > 0) { highest = value; leaders.length = 0; leaders.push(p.player_id); } else if (!c) leaders.push(p.player_id); });
          roundRecords.push({ stage: stageIndex, stage_name: spec.name, round: ri + 1, overall_round: overallRound + ri + 1, matches: rounds[ri].length,
            rock_count: roundHands[0], scissors_count: roundHands[1], paper_count: roundHands[2], draw_matches: drawMatches, highest_ranking_points: decimalString(highest), leaders: leaders.join(';') });
        }
      }
      const standings = active.map(player => { const ranking = copyTally(carried.get(player.player_id)); addTally(ranking, local.get(player.player_id)); return { player, stage_index: stageIndex, stage_name: spec.name, match_group: matchGroups.get(player.player_id), stage: copyTally(local.get(player.player_id)), ranking, total: copyTally(totals.get(player.player_id)), strategy_type: strategies.get(player.player_id).type, rank: 0 }; });
      standings.sort((a, b) => {
        const pointsCompare = compare(b.ranking.points, a.ranking.points); if (pointsCompare) return pointsCompare;
        for (const key of spec.tie_breakers) if (key !== 'random') { const d = metric(b.ranking, key) - metric(a.ranking, key); if (d) return d; }
        return lotteryOrder.get(a.player.player_id) - lotteryOrder.get(b.player.player_id);
      });
      standings.forEach((s, i) => { s.rank = i + 1; });
      const publicSpec = { ...config.stages[stageIndex - 1], entrants: spec.entrants };
      results.push({ spec: publicSpec, standings });
      if (stageIndex < engine.stages.length) eliminated.push(standings.slice(spec.advance));
      previous = new Map(standings.map(s => [s.player.player_id, s.ranking]));
      active = standings.slice(0, spec.advance).map(s => s.player); overallRound += spec.rounds;
      if (yielded !== completed) { yielded = completed; yield completed; }
    }
    return { rankings: [...results[results.length - 1].standings, ...eliminated.reverse().flat()], stages: results, totals, winners: new Set(active.map(p => p.player_id)), matches, rounds: roundRecords };
  }
  function publicTally(t) { return { ...t, points: decimalString(t.points), hands: t.hands.slice() }; }
  function publicStanding(s) { return { ...s, stage: publicTally(s.stage), ranking: publicTally(s.ranking), total: publicTally(s.total) }; }
  function publicTournament(t) { return { ...t, rankings: t.rankings.map(publicStanding), stages: t.stages.map(r => ({ spec: r.spec, standings: r.standings.map(publicStanding) })), totals: Object.fromEntries([...t.totals].map(([id, tally]) => [id, publicTally(tally)])) }; }
  function runTournament(raw, runIndex = 0, capture = true) {
    integer(runIndex, 'runIndex', 0);
    const config = normalizeConfig(raw), gen = tournamentGenerator(compile(config), runIndex, capture);
    let next; do { next = gen.next(); } while (!next.done);
    return publicTournament(next.value);
  }
  const ratio = (a, b) => b ? a / b : null;
  function tallyFields(t, prefix = '') { const row = { [prefix + 'points']: decimalString(t.points), [prefix + 'games']: t.games, [prefix + 'wins']: t.wins, [prefix + 'scissors_wins']: t.scissors_wins, [prefix + 'draws']: t.draws, [prefix + 'losses']: t.losses }; HANDS.forEach((h, i) => { row[prefix + h + '_count'] = t.hands[i]; }); return row; }
  function rateFields(t) { const row = { win_rate: ratio(t.wins, t.games), draw_rate: ratio(t.draws, t.games), loss_rate: ratio(t.losses, t.games), non_draw_win_rate: ratio(t.wins, t.wins + t.losses) }; HANDS.forEach((h, i) => { row[h + '_rate'] = ratio(t.hands[i], t.games); }); return row; }
  function standingFields(s) { return { player_id: s.player.player_id, group: s.player.group.name, stage: s.stage_index, stage_name: s.stage_name, match_group: s.match_group, stage_rank: s.rank, strategy_type: s.strategy_type, ...tallyFields(s.stage, 'stage_'), ...tallyFields(s.ranking, 'ranking_'), ...tallyFields(s.total, 'total_') }; }
  function aggregate() { return { entries: 0, advances: 0, rankSum: 0, rankingPoints: ZERO, tally: newTally() }; }
  function addAggregate(to, s, advanced) { to.entries++; to.advances += Number(advanced); to.rankSum += s.rank; to.rankingPoints = add(to.rankingPoints, s.ranking.points); addTally(to.tally, s.stage); }
  function mergeAggregate(to, from) { to.entries += from.entries; to.advances += from.advances; to.rankSum += from.rankSum; to.rankingPoints = add(to.rankingPoints, from.rankingPoints); addTally(to.tally, from.tally); }
  function aggregateFields(a, initialEntries) { return { entries: a.entries, advances: a.advances, reach_rate: ratio(a.entries, initialEntries), advance_rate: ratio(a.advances, a.entries), average_stage_rank: ratio(a.rankSum, a.entries), average_stage_points: meanDecimal(a.tally.points, a.entries), average_ranking_points: meanDecimal(a.rankingPoints, a.entries), ...tallyFields(a.tally, 'total_'), ...rateFields(a.tally) }; }
  async function simulate(raw, onProgress) {
    const config = normalizeConfig(raw), engine = compile(config), totalMatches = engine.matches * config.runs;
    const overall = new Map(engine.players.map(p => [p.player_id, { rankSum: 0, qualifications: 0, tally: newTally() }]));
    const perStage = new Map(engine.players.map(p => [p.player_id, engine.stages.map(() => aggregate())]));
    let first = null, lastYield = Date.now();
    if (typeof onProgress === 'function') onProgress(0, totalMatches);
    for (let runIndex = 0; runIndex < config.runs; runIndex++) {
      const gen = tournamentGenerator(engine, runIndex, runIndex === 0); let next;
      do {
        next = gen.next();
        if (!next.done) {
          if (typeof onProgress === 'function') onProgress(runIndex * engine.matches + next.value, totalMatches);
          if (Date.now() - lastYield >= 12) { await new Promise(resolve => setTimeout(resolve, 0)); lastYield = Date.now(); }
        }
      } while (!next.done);
      const t = next.value; if (first === null) first = t;
      t.rankings.forEach((s, i) => { const a = overall.get(s.player.player_id); a.rankSum += i + 1; a.qualifications += Number(t.winners.has(s.player.player_id)); addTally(a.tally, t.totals.get(s.player.player_id)); });
      t.stages.forEach((result, i) => result.standings.forEach(s => addAggregate(perStage.get(s.player.player_id)[i], s, s.rank <= result.spec.advance)));
    }
    const players = engine.players.map(p => {
      const a = overall.get(p.player_id), row = { player_id: p.player_id, group: p.group.name, strategy_type: p.group.strategy.type, runs: config.runs, qualifications: a.qualifications, qualification_rate: ratio(a.qualifications, config.runs), average_overall_rank: ratio(a.rankSum, config.runs), average_total_points: meanDecimal(a.tally.points, config.runs), average_games: ratio(a.tally.games, config.runs), ...tallyFields(a.tally, 'total_'), ...rateFields(a.tally) };
      perStage.get(p.player_id).forEach((aStage, i) => { const fields = aggregateFields(aStage, config.runs); ['entries', 'advances', 'reach_rate', 'advance_rate', 'average_stage_points', 'average_ranking_points'].forEach(key => { row['stage_' + (i + 1) + '_' + key] = fields[key]; }); });
      return row;
    });
    const groups = config.groups.map(group => {
      const members = engine.players.filter(p => p.group.name === group.name), tally = newTally(); let qualifications = 0, rankSum = 0;
      members.forEach(p => { const a = overall.get(p.player_id); addTally(tally, a.tally); qualifications += a.qualifications; rankSum += a.rankSum; });
      const entries = members.length * config.runs;
      return { group: group.name, strategy_type: group.strategy.type, players: members.length, runs: config.runs, qualifications, qualification_rate: ratio(qualifications, entries), average_overall_rank: ratio(rankSum, entries), average_total_points: meanDecimal(tally.points, entries), average_games: ratio(tally.games, entries), ...tallyFields(tally, 'total_'), ...rateFields(tally) };
    });
    const stageSummary = [];
    config.stages.forEach((s, i) => {
      [null, ...config.groups].forEach(group => {
        const members = engine.players.filter(p => group === null || p.group.name === group.name), a = aggregate();
        members.forEach(p => mergeAggregate(a, perStage.get(p.player_id)[i]));
        stageSummary.push({ scope: group === null ? 'all' : 'group', group: group === null ? '' : group.name, stage: i + 1, stage_name: s.name, ...aggregateFields(a, members.length * config.runs) });
      });
    });
    const rankings = first.rankings.map((s, i) => ({ rank: i + 1, qualified: first.winners.has(s.player.player_id), ...standingFields(s) }));
    const stageRankings = first.stages.flatMap(r => r.standings.map(s => ({ advanced: s.rank <= r.spec.advance, ...standingFields(s) })));
    if (typeof onProgress === 'function') onProgress(totalMatches, totalMatches);
    return { meta: { title: config.name, seed: config.seed, runs: config.runs, players: engine.players.length, final_qualifiers: config.stages[config.stages.length - 1].advance, rounds_per_tournament: config.stages.reduce((sum, s) => sum + s.rounds, 0), matches_per_tournament: engine.matches }, config,
      groups, stage_summary: stageSummary, players, rankings, stage_rankings: stageRankings, matches: first.matches, rounds: first.rounds };
  }
  return { normalizeConfig, simulate, runTournament, DEFAULT_CONFIG: JSON.parse(JSON.stringify(DEFAULT_CONFIG)), LIMITS, scheduleRounds, seeded,
    decimal: { parse: parseDecimal, add: (a, b) => decimalString(add(parseDecimal(a), parseDecimal(b))), compare: (a, b) => compare(parseDecimal(a), parseDecimal(b)), mean: (a, n) => meanDecimal(parseDecimal(a), n) } };
});
