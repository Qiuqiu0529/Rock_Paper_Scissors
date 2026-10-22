from __future__ import annotations

from copy import deepcopy
import csv
from decimal import Decimal, getcontext, localcontext
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE/'outputs'/'rps_simulator.py'
spec = importlib.util.spec_from_file_location('configurable_under_test',SCRIPT)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
checks = 0

def check(value,message):
    global checks
    assert value,message
    checks += 1

def equal(a,b,message):
    if isinstance(a,float) and isinstance(b,float):
        check(abs(a-b)<1e-10,message)
    else:
        check(a==b,f'{message}: {a!r} vs {b!r}')

def rates(w,d,l,hands):
    n = w+d+l
    return {'win_rate':w/n if n else None,'draw_rate':d/n if n else None,
            'loss_rate':l/n if n else None,'non_draw_win_rate':w/(w+l) if w+l else None,
            **{key+'_rate':hands[i]/n if n else None for i,key in enumerate(m.HANDS)}}

def assert_rates(row,data):
    for key,value in rates(data['wins'],data['draws'],data['losses'],data['hands']).items():
        equal(row[key],value,'rate '+key)

def empty():
    return {'points':Decimal(0),'wins':0,'draws':0,'losses':0,'hands':[0,0,0]}

def plus(a,b):
    return {key:a[key]+b[key] for key in ['points','wins','draws','losses']}|{'hands':[x+y for x,y in zip(a['hands'],b['hands'])]}

def assert_tally(actual,expected,label):
    for key in ['points','wins','draws','losses','hands']:
        equal(getattr(actual,key),expected[key],label+' '+key)
    equal(actual.games,sum(expected[key] for key in ['wins','draws','losses']),label+' games')

def build(groups,stages,**kwargs):
    return {'name':'test','seed':183,'runs':7,'groups':groups,'stages':stages,**kwargs}

PURE = [{'name':'same','count':100,'strategy':{'type':'fixed','hand':'scissors'}}]
THREE = [{'name':'A','rounds':1,'advance':60,'reset_scores':True},
         {'name':'B','rounds':2,'advance':20,'reset_scores':True},
         {'name':'C','rounds':3,'advance':1,'reset_scores':False}]

def verify(settings,t,run_index=0):
    n = len(settings.players)
    equal(len(t.rankings),n,'overall size')
    equal(len({s.player.player_id for s in t.rankings}),n,'unique overall IDs')
    equal(len(t.winners),settings.stages[-1].advance,'winner count')
    equal({s.player.player_id for s in t.rankings[:len(t.winners)]},t.winners,'winner rank prefix')
    equal(len(t.matches),sum(s.entrants*s.rounds//2 for s in settings.stages),'match count')
    equal(len(t.rounds),sum(s.rounds for s in settings.stages),'round count')
    totals = {p.player_id:empty() for p in settings.players}
    previous,history = {},{p.player_id:{'index':0,'opponent':None} for p in settings.players}
    eliminated = []
    prior_ids = {p.player_id for p in settings.players}
    for stage_index,result in enumerate(t.stages,1):
        spec = result.spec
        ids = {s.player.player_id for s in result.standings}
        equal(ids,prior_ids,'stage entrants follow advance')
        equal(len(ids),spec.entrants,'entrants spec')
        local = {pid:empty() for pid in ids}
        hand_rng = {pid:random.Random(f'{settings.seed}:{run_index}:{stage_index}:hands:{pid}') for pid in ids}
        lookup = {s.player.player_id:s.player for s in result.standings}
        for pid in ids:
            if lookup[pid].strategy_for(spec.name).reset_each_stage:
                history[pid] = {'index':0,'opponent':None}
        matches = [r for r in t.matches if r['stage']==stage_index]
        pairs = set()
        for round_number in range(1,spec.rounds+1):
            round_matches = [r for r in matches if r['round']==round_number]
            people = [r[f'player_{side}'] for r in round_matches for side in (1,2)]
            check(len(people)==len(ids) and set(people)==ids,'exactly once every round')
        for record in matches:
            pair = frozenset((record['player_1'],record['player_2']))
            check(len(pair)==2 and pair not in pairs,'no repeat or self pair')
            pairs.add(pair)
            actual = [m.HANDS.index(record[f'hand_{side}']) for side in (1,2)]
            expected = []
            for side in (1,2):
                pid = record[f'player_{side}']
                strategy,h = lookup[pid].strategy_for(spec.name),history[pid]
                if strategy.kind=='fixed':
                    chosen = strategy.fixed_hand
                elif strategy.kind=='cycle':
                    chosen = strategy.sequence[(h['index']+strategy.offset)%len(strategy.sequence)]
                elif strategy.kind in ('copy_last','counter_last'):
                    chosen = strategy.initial if h['opponent'] is None else h['opponent'] if strategy.kind=='copy_last' else (2,0,1)[h['opponent']]
                else:
                    u = hand_rng[pid].random()
                    chosen = 0 if u<strategy.probabilities[0] else 1 if u<sum(strategy.probabilities[:2]) else 2
                expected.append(chosen)
            equal(actual,expected,'strategy reads only preceding-game history')
            winner = 'draw' if actual[0]==actual[1] else record['player_1'] if (actual[0],actual[1]) in [(0,1),(1,2),(2,0)] else record['player_2']
            equal(record['winner'],winner,'standard outcome')
            for side in (1,2):
                pid,chosen = record[f'player_{side}'],actual[side-1]
                outcome = 'draw' if winner=='draw' else 'win' if winner==pid else 'loss'
                award = getattr(spec.scoring,outcome)+spec.scoring.bonuses[chosen]
                equal(record[f'points_{side}'],award,'stage scoring applied')
                equal(record[f'base_points_{side}'],getattr(spec.scoring,outcome),'base award')
                equal(record[f'bonus_{side}'],spec.scoring.bonuses[chosen],'hand bonus')
                for data in (local[pid],totals[pid]):
                    data['points'] += award
                    data[{'win':'wins','draw':'draws','loss':'losses'}[outcome]] += 1
                    data['hands'][chosen] += 1
                history[pid] = {'index':history[pid]['index']+1,'opponent':actual[2-side]}
        ranking = {}
        for standing in result.standings:
            pid = standing.player.player_id
            expected_ranking = local[pid] if stage_index==1 or spec.reset_scores else plus(previous[pid],local[pid])
            assert_tally(standing.stage,local[pid],'local tally')
            assert_tally(standing.ranking,expected_ranking,'ranking carry/reset tally')
            assert_tally(standing.total,totals[pid],'historical total tally')
            ranking[pid] = expected_ranking
            equal(standing.stage.games,spec.rounds,'stage games equal')
        keys = [(-s.ranking.points,*(-s.ranking.metric(key) for key in spec.tie_breakers if key!='random')) for s in result.standings]
        equal(keys,sorted(keys),'configured descending keys')
        previous = ranking
        prior_ids = {s.player.player_id for s in result.standings[:spec.advance]}
        if stage_index<len(t.stages):
            eliminated.append(result.standings[spec.advance:])
    equal(t.rankings,t.stages[-1].standings+[s for batch in reversed(eliminated) for s in batch],'multi-stage overall rank ordering')
    for pid,data in totals.items():
        assert_tally(t.totals[pid],data,'overall accumulated tally')
    return totals

# Arbitrary stages, odd last quota, reset then carry must not revive first score.
settings = m.parse_config(build(PURE,THREE))
t = m.play_tournament(settings)
verify(settings,t)
for stage,raw,rank,total in zip(t.stages,[1,2,3],[1,2,5],[1,3,6]):
    for s in stage.standings:
        equal((s.stage.points,s.ranking.points,s.total.points),(raw,rank,total),'three different point scopes')

# A new scoring table affects only new games, never reprices carried games.
scoring_stages = deepcopy(THREE)
scoring_stages[0]['scoring'] = {'draw':'10','hand_bonus':{'scissors':'0.1'}}
scoring_stages[1]['scoring'] = {'draw':'-1','hand_bonus':{'scissors':'0.2'}}
scoring_stages[2]['scoring'] = {'draw':'3','hand_bonus':{'scissors':'-0.5'}}
settings2 = m.parse_config(build(PURE,scoring_stages))
t2 = m.play_tournament(settings2)
verify(settings2,t2)
for stage,expected in zip(t2.stages,[('10.1','10.1','10.1'),('-1.6','-1.6','8.5'),('7.5','5.9','16.0')]):
    for s in stage.standings:
        equal((s.stage.points,s.ranking.points,s.total.points),tuple(Decimal(x) for x in expected),'score overrides retain historical values')

# Exact decimal awards with extremes and a deliberately low caller context.
large_config = build([{'name':'same','count':2,'strategy':{'type':'fixed','hand':'rock'}}],
    [{'name':'A','rounds':1,'advance':2},
     {'name':'B','rounds':1,'advance':1,'reset_scores':False,'scoring':{'draw':'1e-100','hand_bonus':{'rock':'0.2'}}}],
    scoring={'draw':'1e100','hand_bonus':{'rock':'0.1'}})
large = m.parse_config(large_config)
with localcontext() as ctx:
    ctx.prec = 256
    expected = Decimal('1e100')+Decimal('.3')+Decimal('1e-100')
before = getcontext().copy()
with localcontext() as ctx:
    ctx.prec = 8
    lt = m.play_tournament(large)
    equal(ctx.prec,8,'play preserves caller precision')
    check(all(s.ranking.points==expected for s in lt.stages[1].standings),'large plus tiny decimal remains exact')
    m.simulate(large)
    equal(ctx.prec,8,'simulate preserves caller precision')
equal(getcontext().prec,before.prec,'no global context pollution')

# All five strategies, stage replacements, history reset and continued cycles.
mixed_groups = [
    {'name':'random','count':8,'strategy':{'type':'random','probabilities':{'rock':.2,'scissors':.5,'paper':.3}}},
    {'name':'fixed','count':8,'strategy':{'type':'fixed','hand':'rock'},'stage_strategies':{'C':{'type':'counter_last','initial':'paper'}}},
    {'name':'cycle','count':8,'strategy':{'type':'cycle','sequence':['rock','scissors','paper'],'offset':1,'reset_each_stage':False}},
    {'name':'copy','count':8,'strategy':{'type':'copy_last','initial':'paper'},'stage_strategies':{'B':{'type':'cycle','sequence':['paper','rock'],'offset':2,'reset_each_stage':False}}},
    {'name':'counter','count':8,'strategy':{'type':'counter_last','initial':'scissors','reset_each_stage':False}},
]
mixed_stages = [{'name':'A','rounds':5,'advance':24},
                {'name':'B','rounds':7,'advance':12,'reset_scores':False,'tie_breakers':['scissors_count','wins']},
                {'name':'C','rounds':5,'advance':3,'reset_scores':True,'scoring':{'win':'1.5','draw':'0.1','loss':'-0.2','hand_bonus':{'rock':'.3','paper':'-.1'}}}]
mixed = m.parse_config(build(mixed_groups,mixed_stages))
for run in range(3):
    verify(mixed,m.play_tournament(mixed,run),run)
equal(m.play_tournament(mixed),m.play_tournament(mixed),'same seed all state reproducibility')
hidden = m.play_tournament(mixed,capture=False)
visible = m.play_tournament(mixed)
equal(hidden.rankings,visible.rankings,'capture does not alter results')
check(not hidden.matches and not hidden.rounds,'capture suppresses only records')

# Replay all runs and independently sum every player and conditional stage aggregate.
first,player_rows,group_rows,stage_rows = m.simulate(mixed)
manual = {p.player_id:{'rank':0,'q':0,'all':empty(),'stage':{i:{'entries':0,'advances':0,'points':Decimal(0),'ranking':Decimal(0),'tally':empty()} for i in range(1,4)}} for p in mixed.players}
for run in range(mixed.runs):
    tt = m.play_tournament(mixed,run)
    real = verify(mixed,tt,run)
    for rank,standing in enumerate(tt.rankings,1):
        d = manual[standing.player.player_id]
        d['rank'] += rank; d['q'] += standing.player.player_id in tt.winners
        d['all'] = plus(d['all'],real[standing.player.player_id])
    for i,result in enumerate(tt.stages,1):
        for s in result.standings:
            d = manual[s.player.player_id]['stage'][i]
            d['entries'] += 1; d['advances'] += s.rank<=result.spec.advance
            d['points'] += s.stage.points; d['ranking'] += s.ranking.points
            stage_data = {'points':s.stage.points,'wins':s.stage.wins,'draws':s.stage.draws,'losses':s.stage.losses,'hands':s.stage.hands}
            d['tally'] = plus(d['tally'],stage_data)
for row in player_rows:
    d = manual[row['player_id']]
    equal(row['qualifications'],d['q'],'player qualifications')
    equal(row['qualification_rate'],d['q']/mixed.runs,'player qualification denominator')
    assert_rates(row,d['all'])
    for i,stage in d['stage'].items():
        prefix = f'stage_{i}_'
        equal(row[prefix+'entries'],stage['entries'],'player stage entries')
        equal(row[prefix+'reach_rate'],stage['entries']/mixed.runs,'player stage reach denominator')
        equal(row[prefix+'advance_rate'],stage['advances']/stage['entries'] if stage['entries'] else None,'player conditional advance denominator')
        # Decimal means are rounded at the engine's documented 256-digit precision.
        with localcontext() as ctx:
            ctx.prec = 256
            equal(row[prefix+'average_stage_points'],stage['points']/stage['entries'] if stage['entries'] else None,'player conditional stage mean')
            equal(row[prefix+'average_ranking_points'],stage['ranking']/stage['entries'] if stage['entries'] else None,'player conditional ranking mean')
for row in group_rows:
    ids = [p.player_id for p in mixed.players if p.group.name==row['group']]
    total = empty()
    for pid in ids: total = plus(total,manual[pid]['all'])
    assert_rates(row,total)
    equal(row['qualification_rate'],sum(manual[pid]['q'] for pid in ids)/(len(ids)*mixed.runs),'group per-player denominator')
for row in stage_rows:
    ids = [p.player_id for p in mixed.players if row['scope']=='all' or p.group.name==row['group']]
    data = [manual[pid]['stage'][row['stage']] for pid in ids]
    entries,advances = sum(x['entries'] for x in data),sum(x['advances'] for x in data)
    equal(row['entries'],entries,'group stage entry count')
    equal(row['advances'],advances,'group stage advance count')
    equal(row['reach_rate'],entries/(len(ids)*mixed.runs),'group stage reach denominator')
    equal(row['advance_rate'],advances/entries if entries else None,'group stage conditional denominator')
    total = empty()
    for x in data: total = plus(total,x['tally'])
    assert_rates(row,total)
equal(sum(r['qualifications'] for r in player_rows),3*mixed.runs,'odd final quota conservation')
for i,spec in enumerate(mixed.stages,1):
    equal(sum(r[f'stage_{i}_entries'] for r in player_rows),spec.entrants*mixed.runs,'stage entries conservation')
    equal(sum(r[f'stage_{i}_advances'] for r in player_rows),spec.advance*mixed.runs,'stage advances conservation')

# Export precision, first-run scope and the saved config's ability to reload.
out = BASE/'work'/'verify_configurable_results'
m.export_results(mixed,out,first,player_rows,group_rows,stage_rows)
def read_csv(name):
    with (out/name).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))
for name,n in [('rankings.csv',40),('stage_rankings.csv',76),('matches.csv',214),('rounds.csv',17),
               ('player_summary.csv',40),('strategy_summary.csv',5),('stage_summary.csv',18)]:
    equal(len(read_csv(name)),n,'CSV '+name+' count')
with (out/'summary.json').open(encoding='utf-8') as stream:
    summary = json.load(stream)
reloaded = m.parse_config(summary['config'])
equal(reloaded,mixed,'summary config round trip')
equal(m.play_tournament(reloaded),first,'saved config reproduces first run')
saved = BASE/'work'/'verify_configurable_saved.json'
saved.write_text(json.dumps(summary['config']),encoding='utf-8')
equal(m.load_config(saved),mixed,'load_config round trip')

# A single stage, two-player minimum, and no-elimination intermediary are valid.
small = m.parse_config(build([{'name':'g','count':2,'strategy':{'type':'fixed','hand':'paper'}}],
                            [{'name':'only','rounds':1,'advance':1}]))
verify(small,m.play_tournament(small))

# Invalid configuration must be rejected with actionable ValueError, not tracebacks.
valid = build(PURE,THREE)
bad_cases = []
def mutation(path,value):
    raw = deepcopy(valid); target = raw
    for key in path[:-1]: target = target[key]
    target[path[-1]] = value
    bad_cases.append(raw)
for path,value in [(['seed'],True),(['runs'],True),(['runs'],0),(['typo'],1),
                   (['groups',0,'count'],True),(['groups',0,'count'],99),
                   (['groups',0,'strategy','hand'],'lizard'),(['groups',0,'strategy','reset_each_stage'],1),
                   (['groups',0,'stage_strategies'],{'missing':{'type':'fixed','hand':'rock'}}),
                   (['stages',0,'rounds'],True),(['stages',0,'rounds'],100),(['stages',0,'advance'],61),
                   (['stages',2,'advance'],21),(['stages',1,'reset_scores'],0),(['stages',1,'name'],'A'),
                   (['tie_breakers'],['random','wins']),(['tie_breakers'],['wins','wins']),
                   (['scoring'],{'win':True}),(['scoring'],{'loss':'NaN'}),(['scoring'],{'win':'1e101'}),
                   (['groups',0,'strategy'],{'type':'cycle','sequence':[]}),
                   (['groups',0,'strategy'],{'type':'random','probabilities':{'rock':True,'scissors':0,'paper':0}}),
                   (['groups',0,'strategy'],{'type':'random','probabilities':{'rock':.2,'scissors':.2,'paper':.2}}),
                   (['groups',0,'strategy'],{'type':'random','probabilities':{'rock':10**400,'scissors':0,'paper':0}}),
                   (['groups',0,'strategy'],{'type':'random','probabilities':{'rock':float('nan'),'scissors':0,'paper':0}})]:
    mutation(path,value)
for raw in bad_cases:
    try: m.parse_config(raw)
    except ValueError: checks += 1
    else: raise AssertionError('invalid config accepted: '+repr(raw))

# CLI validate-only writes no output; normal standalone CLI writes all exports.
cli_out = BASE/'work'/'verify_configurable_cli'
result = subprocess.run([sys.executable,'-B',str(SCRIPT),'--config',str(saved),'--validate-only',
                         '--out-dir',str(BASE/'work'/'verify_configurable_should_not_exist')],capture_output=True)
equal(result.returncode,0,'CLI validate-only')
check(not (BASE/'work'/'verify_configurable_should_not_exist').exists(),'validate-only does not write')
result = subprocess.run([sys.executable,'-B',str(SCRIPT),'--config',str(saved),'--runs','2','--seed','99',
                         '--out-dir',str(cli_out),'--show-rounds'],capture_output=True)
equal(result.returncode,0,'CLI execution '+repr(result.stderr))
with (cli_out/'summary.json').open(encoding='utf-8') as stream:
    cli_summary = json.load(stream)
equal(cli_summary['config']['runs'],2,'CLI run override')
equal(cli_summary['config']['seed'],99,'CLI seed override')
equal(cli_summary['final_qualifiers'],3,'CLI odd final quota')

print(f'PASS: {checks} checks; arbitrary stages, carry/reset/scoring scopes, exact decimals, all strategies/history, aggregates, CSV/config round-trip, invalid input and CLI.')
