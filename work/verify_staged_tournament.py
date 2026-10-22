from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path
import random
import subprocess
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / 'outputs' / 'rps_tournament.py'
spec = importlib.util.spec_from_file_location('rps_staged_under_test', SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
checks = 0

def check(value, message):
    global checks
    assert value, message
    checks += 1

def same(a, b, message):
    if a is None or b is None:
        check(a is b, message)
    else:
        check(math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-11), message)

def pure_players(groups):
    result = []
    for name, count, hand in groups:
        probs = tuple(float(i == hand) for i in range(3))
        for _ in range(count):
            result.append(mod.Player(f'P{len(result)+1:03d}', name, probs))
    return result

def verify_tournament(t, bonus=1, prelim_rounds=5, finalists=30, final_rounds=9):
    check(len(t.stages)==2, 'two stages')
    check(len(t.rankings)==100, '100 overall ranks')
    check(len({s.player.player_id for s in t.rankings})==100, 'unique overall IDs')
    prelim, final = t.stages
    initial_ids = {s.player.player_id for s in prelim.rankings[:finalists]}
    final_ids = {s.player.player_id for s in final.rankings}
    check(initial_ids==final_ids, 'advance only preliminary top finalists')
    check(t.rankings[:finalists]==final.rankings, 'overall rank starts with final rank')
    check(t.rankings[finalists:]==prelim.rankings[finalists:], 'eliminated preliminary order')
    check(len(t.match_records)==(100*prelim_rounds+finalists*final_rounds)//2, 'total matches')
    check(len(t.round_records)==prelim_rounds+final_rounds, 'total rounds')
    check([r['overall_round'] for r in t.round_records]==list(range(1,prelim_rounds+final_rounds+1)), 'overall round numbering')
    for stage, size, rounds, quota in [(prelim,100,prelim_rounds,finalists),(final,finalists,final_rounds,10)]:
        check(len(stage.rankings)==size and stage.rounds==rounds and stage.qualifier_count==quota, 'stage metadata')
        ids = {s.player.player_id for s in stage.rankings}
        records = [m for m in t.match_records if m['stage']==stage.stage]
        check(len(records)==size*rounds//2, 'stage match count')
        pairs = set()
        outcomes = {pid:{'wins':0,'draws':0,'losses':0,'hands':[0,0,0],'points':0} for pid in ids}
        for r in range(1,rounds+1):
            matches = [m for m in records if m['round']==r]
            people = [m[key] for m in matches for key in ('player_1','player_2')]
            check(len(people)==size and set(people)==ids, 'one game per person per stage round')
            check([m['match'] for m in matches]==list(range(1,size//2+1)), 'match numbers')
        for m in records:
            a,b = m['player_1'],m['player_2']
            pair = frozenset((a,b))
            check(len(pair)==2 and pair not in pairs, 'no self match or repeated stage opponent')
            pairs.add(pair)
            h1,h2 = [mod.HAND_NAMES.index(m[f'hand_{i}']) for i in (1,2)]
            expected_winner = ('draw' if h1==h2 else a if mod.BEATS[h1]==h2 else b)
            check(m['winner']==expected_winner, 'standard RPS winner')
            for index,pid,hand in [(1,a,h1),(2,b,h2)]:
                o = outcomes[pid]
                o['hands'][hand] += 1
                outcome = 'draws' if expected_winner=='draw' else 'wins' if expected_winner==pid else 'losses'
                o[outcome] += 1
                expected_points = (1 if outcome=='draws' else 2 if outcome=='wins' else 0)+bonus*(hand==1)
                same(m[f'points_{index}'],expected_points,'per-hand score')
                o['points'] += m[f'points_{index}']
        for s in stage.rankings:
            o = outcomes[s.player.player_id]
            check((s.wins,s.draws,s.losses)==(o['wins'],o['draws'],o['losses']), 'stage independent outcome count')
            check(s.hand_counts==o['hands'], 'stage independent hand count')
            check(sum(s.hand_counts)==rounds, 'stage games')
            same(s.points(bonus),o['points'],'stage points equal only stage records')
        same(sum(s.points(bonus) for s in stage.rankings),
             size*rounds+bonus*sum(s.hand_counts[1] for s in stage.rankings),'stage conservation')
    for pid,s in t.total_standings.items():
        expected_games = prelim_rounds+(final_rounds if pid in final_ids else 0)
        check(sum(s.hand_counts)==expected_games, '5/14 games or custom format')
        constituents = [st for stage in t.stages for st in stage.rankings if st.player.player_id==pid]
        check(s.hand_counts==[sum(st.hand_counts[i] for st in constituents) for i in range(3)], 'total hand counters')
        same(s.points(bonus),sum(st.points(bonus) for st in constituents),'total points are sum of stages')
    same(sum(s.points(bonus) for s in t.total_standings.values()),
         100*prelim_rounds+finalists*final_rounds+bonus*sum(s.hand_counts[1] for s in t.total_standings.values()),'whole tournament conservation')
    rows = mod.ranking_rows(t,bonus)
    check(sum(r['qualified'] for r in rows)==10, '10 final qualifiers')
    check(sum(r['reached_final'] for r in rows)==finalists, 'finalist count in rows')
    for r in rows:
        check(r['stage_games']==(final_rounds if r['reached_final'] else prelim_rounds), 'rank row stage games')
        check(r['total_games']==prelim_rounds+(final_rounds if r['reached_final'] else 0), 'rank row total games')
        check(r['stage_wins']+r['stage_draws']+r['stage_losses']==r['stage_games'], 'stage row outcomes')

# Partial-round schedules are regular, simple matchings.
for n,k in [(2,1),(4,3),(30,9),(30,29),(100,5),(100,99)]:
    for seed in [0,42,71]:
        schedule = mod.partial_schedule(n,k,random.Random(seed))
        check(len(schedule)==k,'partial schedule rounds')
        pairs = set()
        for matches in schedule:
            check(sorted(p for match in matches for p in match)==list(range(n)), 'partial schedule everyone exactly once')
            for a,b in matches:
                pair = tuple(sorted((a,b)))
                check(a!=b and pair not in pairs,'partial schedule unique pairs')
                pairs.add(pair)

# All pure strategies: points reset between stages.
for name,hand,per_game in [('R',0,1),('S',1,2),('P',2,1)]:
    ps = pure_players([(name,100,hand)])
    t = mod.play_tournament(ps,42)
    verify_tournament(t)
    for stage in t.stages:
        for s in stage.rankings:
            check((s.wins,s.draws,s.losses)==(0,stage.rounds,0),'pure strategy all draws')
            check(s.points(1)==per_game*stage.rounds,'pure strategy points')
    for r in mod.ranking_rows(t,1):
        check(r['stage_points']==per_game*(9 if r['reached_final'] else 5),'final points reset')
        check(r['total_points']==per_game*(14 if r['reached_final'] else 5),'total pure points')

# Mixed deterministic stages: every scissors player advances, every paper player is eliminated.
mixed = pure_players([('S',30,1),('P',70,2)])
mt = mod.play_tournament(mixed,89)
verify_tournament(mt)
check(all(s.player.strategy=='S' for s in mt.stages[1].rankings),'30 S all advance')
check(all(s.points(1)==18 for s in mt.stages[1].rankings),'mixed final clear-score oracle')

# Reproducibility and independent first-stage random streams across bonus values.
uniform = mod.make_players()
t = mod.play_tournament(uniform,883)
check(t==mod.play_tournament(uniform,883),'same seed identical')
reordered = list(reversed(uniform))
check(t==mod.play_tournament(reordered,883),'input order independent')
boosted = mod.play_tournament(uniform,883,scissors_bonus=2.5)
verify_tournament(t)
verify_tournament(boosted,bonus=2.5)
base_matches = [m for m in t.match_records if m['stage']==1]
boost_matches = [m for m in boosted.match_records if m['stage']==1]
for a,b in zip(base_matches,boost_matches):
    check({k:v for k,v in a.items() if not k.startswith('points_')}==
          {k:v for k,v in b.items() if not k.startswith('points_')},'first-stage bonus-independent gestures')
    for side in (1,2):
        same(b[f'points_{side}']-a[f'points_{side}'],1.5*(a[f'hand_{side}']=='剪刀'),'bonus delta')

# Custom formats, including full round robins in both stages.
for pr,fs,fr in [(1,12,1),(7,20,19),(99,30,29)]:
    verify_tournament(mod.play_tournament(uniform,19,prelim_rounds=pr,finalists=fs,final_rounds=fr),
                      prelim_rounds=pr,finalists=fs,final_rounds=fr)

# Independently aggregate multiple runs, with a group that never reaches the final.
runs = 17
first, prows, grows = mod.simulate(mixed,998,runs,1)
manual = {p.player_id:{'pq':0,'q':0,'rank':0,'pre':0,'final':0,'total':0,'games':0,'wins':0,'scissors':0} for p in mixed}
for run in range(runs):
    tt = mod.play_tournament(mixed,998,run,capture_records=False)
    check(not tt.match_records and not tt.round_records,'no records on noncaptured runs')
    for rank,s in enumerate(tt.rankings,1):
        total = tt.total_standings[s.player.player_id]
        d = manual[s.player.player_id]
        d['q'] += int(rank<=10); d['rank'] += rank
        d['total'] += total.points(1); d['wins'] += total.wins
        d['games'] += sum(total.hand_counts); d['scissors'] += total.hand_counts[1]
    for s in tt.stages[0].rankings:
        manual[s.player.player_id]['pre'] += s.points(1)
    for s in tt.stages[1].rankings:
        d = manual[s.player.player_id]
        d['pq'] += 1; d['final'] += s.points(1)
check(first==mod.play_tournament(mixed,998),'captured tournament is run zero')
check(sum(r['prelim_qualifications'] for r in prows)==30*runs,'30 advancements per run')
check(sum(r['qualifications'] for r in prows)==10*runs,'10 qualifiers per run')
for row in prows:
    d = manual[row['player_id']]
    check(row['prelim_qualifications']==d['pq'] and row['qualifications']==d['q'],'qualification counts')
    for field,key,denom in [('prelim_qualification_rate','pq',runs),('qualification_rate','q',runs),
                           ('average_rank','rank',runs),('average_prelim_points','pre',runs),
                           ('average_total_points','total',runs),('average_games','games',runs),
                           ('average_wins','wins',runs),('actual_scissors_rate','scissors',d['games'])]:
        same(row[field],d[key]/denom,'player summary '+field)
    same(row['average_final_points'],d['final']/d['pq'] if d['pq'] else None,'conditional final points denominator')
    same(row['conditional_final_qualification_rate'],d['q']/d['pq'] if d['pq'] else None,'conditional final qualification denominator')
for row in grows:
    ids = [p.player_id for p in mixed if p.strategy==row['strategy']]
    ds = [manual[pid] for pid in ids]
    denom = len(ids)*runs
    pq = sum(d['pq'] for d in ds)
    q = sum(d['q'] for d in ds)
    same(row['prelim_qualification_rate'],pq/denom,'group prelim denominator')
    same(row['qualification_rate'],q/denom,'group qualification denominator')
    same(row['conditional_final_qualification_rate'],q/pq if pq else None,'group conditional denominator')
    same(row['average_final_points'],sum(d['final'] for d in ds)/pq if pq else None,'group conditional points denominator')
    same(row['actual_scissors_rate'],sum(d['scissors'] for d in ds)/sum(d['games'] for d in ds),'group rate is weighted by games')

# Fair exact ties use a different reproducible lottery for each run.
_, tie_players,_ = mod.simulate(pure_players([('R',100,0)]),441,150,1)
check(sum(r['qualifications']>0 for r in tie_players)==100,'no fixed ID preference in all-tie final')
check(sum(r['prelim_qualifications'] for r in tie_players)==4500,'tie preliminary total')
check(sum(r['qualifications'] for r in tie_players)==1500,'tie final total')

# Real CLI export checks: default and custom format, plus invalid format arguments.
def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))

for label,params,expected_matches,expected_rounds,expected_stage_rows in [
    ('default',[],385,14,130),
    ('custom',['--prelim-rounds','7','--finalists','20','--final-rounds','19'],540,26,120),
]:
    out = BASE/'work'/('verify_staged_cli_'+label)
    completed = subprocess.run([sys.executable,str(SCRIPT),'--runs','3','--seed','97',
                               '--probs','0','1','0','--out-dir',str(out),'--show-rounds']+params,
                              capture_output=True)
    check(completed.returncode==0,f'CLI {label} exit: {completed.stderr!r}')
    for name,n in [('matches.csv',expected_matches),('rounds.csv',expected_rounds),
                   ('rankings.csv',100),('stage_rankings.csv',expected_stage_rows),
                   ('player_summary.csv',100),('strategy_summary.csv',1)]:
        check(len(read_csv(out/name))==n,f'CLI {name} row count')
    rows = read_csv(out/'player_summary.csv')
    check(sum(int(r['qualifications']) for r in rows)==30,'CLI summary all 3 runs')
    with (out/'summary.json').open(encoding='utf-8') as stream:
        summary = json.load(stream)
    check(summary['scores_reset_between_stages'] is True,'CLI reset metadata')
    check(summary['matches_per_tournament']==expected_matches,'CLI match metadata')
    check(summary['rounds_per_tournament']==expected_rounds,'CLI round metadata')
    check(len(summary['first_tournament_top_10'])==10,'CLI top 10')
for params in [['--prelim-rounds','0'],['--prelim-rounds','100'],['--finalists','10'],
               ['--finalists','11'],['--finalists','100'],['--final-rounds','0'],['--final-rounds','30']]:
    completed = subprocess.run([sys.executable,str(SCRIPT)]+params,capture_output=True)
    check(completed.returncode==2,'invalid CLI format cleanly rejected')
    check(b'Traceback' not in completed.stderr,'invalid CLI no traceback')

print(f'PASS: {checks} checks; stage schedules, advancement, resets, 5/14 games, pure/mixed oracles, reproducibility, bonus isolation, summary denominators and CLI exports.')
