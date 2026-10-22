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
SCRIPT = BASE/'outputs'/'rps_original.py'
spec = importlib.util.spec_from_file_location('original_under_test',SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
checks = 0

def check(value,message):
    global checks
    assert value,message
    checks += 1

def same(a,b,message):
    if a is None or b is None:
        check(a is b,message)
    else:
        check(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10),f'{message}: {a} vs {b}')

def pure(groups,shift=0):
    result = []
    for name,count,hand in groups:
        probabilities = tuple(float(i==(hand+shift)%3) for i in range(3))
        for _ in range(count):
            result.append(mod.Player(f'P{len(result)+1:03d}',name,probabilities))
    return result

def expected_rates(w,d,l):
    n = w+d+l
    return {'win_rate':w/n if n else None,'draw_rate':d/n if n else None,
            'loss_rate':l/n if n else None,'non_draw_win_rate':w/(w+l) if w+l else None}

def check_rates(row,w,d,l,prefix=''):
    for key,value in expected_rates(w,d,l).items():
        same(row[prefix+key],value,'rate '+prefix+key)

def record_counts(t):
    counts = {p.player.player_id:{1:[0,0,0,0],2:[0,0,0,0]} for p in t.rankings}
    for match in t.match_records:
        for side in (1,2):
            pid = match[f'player_{side}']
            c = counts[pid][match['stage']]
            c[1 if match['winner']=='draw' else 0 if match['winner']==pid else 2] += 1
            c[3] += match[f'hand_{side}']=='剪刀'
    return counts

def verify(t,pr=5,fs=30,fr=9):
    check(len(t.rankings)==100 and len(t.total_standings)==100,'all players retained')
    check(len({s.player.player_id for s in t.rankings})==100,'unique ranks')
    a,b = t.stages
    check({s.player.player_id for s in a.rankings[:fs]}=={s.player.player_id for s in b.rankings},'advancement chain')
    check(t.rankings==b.rankings+a.rankings[fs:],'overall ranking by stage')
    check(len(t.match_records)==(100*pr+fs*fr)//2,'385 or custom matches')
    check(len(t.round_records)==pr+fr,'14 or custom rounds')
    for stage,n,k in [(a,100,pr),(b,fs,fr)]:
        matches = [m for m in t.match_records if m['stage']==stage.stage]
        check(len(matches)==n*k//2,'stage match count')
        ids = {s.player.player_id for s in stage.rankings}
        pairs = set()
        for r in range(1,k+1):
            people = [m[f'player_{i}'] for m in matches if m['round']==r for i in (1,2)]
            check(len(people)==n and set(people)==ids,'one game each player each round')
        for m in matches:
            pair = frozenset((m['player_1'],m['player_2']))
            check(len(pair)==2 and pair not in pairs,'stage opponents distinct')
            pairs.add(pair)
            h1,h2 = (mod.HAND_NAMES.index(m[f'hand_{i}']) for i in (1,2))
            winner = 'draw' if h1==h2 else m['player_1'] if (h1,h2) in [(0,1),(1,2),(2,0)] else m['player_2']
            check(m['winner']==winner,'ordinary winner')
            check((m['points_1'],m['points_2'])==((1,1) if winner=='draw' else (2,0) if winner==m['player_1'] else (0,2)),'no gesture bonus')
        check(sum(s.points() for s in stage.rankings)==n*k,'stage score conservation')
        check(all(s.wins+s.draws+s.losses==k for s in stage.rankings),'stage game count')
    check(sum(s.points() for s in t.total_standings.values())==100*pr+fs*fr,'whole score conservation')
    counts = record_counts(t)
    rows = mod.ranking_rows(t)
    check(sum(r['qualified'] for r in rows)==10,'top 10')
    check(sum(r['reached_final'] for r in rows)==fs,'30 finalists')
    for row in rows:
        c = counts[row['player_id']]
        w,d,l = [c[1][i]+c[2][i] for i in range(3)]
        last = c[2] if row['reached_final'] else c[1]
        check(row['total_games']==sum((w,d,l))==pr+(fr if row['reached_final'] else 0),'5/14 games')
        check(row['stage_points']==2*last[0]+last[1],'stage points reset')
        check(row['total_points']==2*w+d,'total points')
        check_rates(row,*last[:3],'stage_')
        check_rates(row,w,d,l,'overall_')
        same(row['actual_scissors_rate'],(c[1][3]+c[2][3])/(w+d+l),'actual scissors denominator')
    for row in mod.stage_ranking_rows(t):
        c = counts[row['player_id']][row['stage']]
        check_rates(row,*c[:3])
    return counts

# Formulas checked by independently enumerating all nine gesture pairs.
rng = random.Random(14)
distributions = [(1,0,0),(0,1,0),(0,0,1),(1/3,)*3,(.2,.6,.2)]
for _ in range(30):
    values = [rng.random() for _ in range(3)]
    distributions.append(tuple(v/sum(values) for v in values))
for own in distributions:
    for other in distributions:
        expected = [0.,0.,0.]
        for h1 in range(3):
            for h2 in range(3):
                index = 1 if h1==h2 else 0 if (h1,h2) in [(0,1),(1,2),(2,0)] else 2
                expected[index] += own[h1]*other[h2]
        calculated = mod.outcome_probabilities(own,other)
        for x,y in zip(calculated,expected):
            same(x,y,'probability formula')
        same(sum(calculated),1,'probability sum')
for w,d,l in [(0,0,0),(0,5,0),(2,3,5),(9,0,1)]:
    for prefix in ['', 'x_']:
        check_rates(mod.outcome_rates(w,d,l,prefix),w,d,l,prefix)

# Pure hands all behave identically; scissors receive exactly 5/9 stage points.
for hand in range(3):
    ps = pure([('same',100,hand)])
    tournament = mod.play_tournament(ps,42)
    verify(tournament)
    for stage in tournament.stages:
        check(all(s.points()==stage.rounds for s in stage.rankings),'pure hand no bonus')
    for row in mod.ranking_rows(tournament):
        check(row['stage_non_draw_win_rate'] is None and row['overall_non_draw_win_rate'] is None,'all-draw rates undefined')

# Cyclic relabeling leaves scores and complete tournament rankings unchanged.
groups = [('g1',30,0),('g2',30,1),('g3',40,2)]
for seed in [0,42,719]:
    baseline = mod.play_tournament(pure(groups),seed)
    verify(baseline)
    for shift in (1,2):
        renamed = mod.play_tournament(pure(groups,shift),seed)
        check([s.player.player_id for s in baseline.rankings]==[s.player.player_id for s in renamed.rankings],'cyclic renaming same complete ranks')
        for a,b in zip(baseline.match_records,renamed.match_records):
            check({k:v for k,v in a.items() if not k.startswith('hand_')}==
                  {k:v for k,v in b.items() if not k.startswith('hand_')},'cyclic renaming same matches/outcomes/points')
            for side in (1,2):
                check(mod.HAND_NAMES[(mod.HAND_NAMES.index(a[f'hand_{side}'])+shift)%3]==b[f'hand_{side}'],'cyclic hand mapping')

# Exclude oneself from expected opponent composition, including unique outliers.
outlier = pure([('single R',1,0),('other S',99,1)])
theory = mod.theoretical_preliminary(outlier)
same(theory['P001']['theoretical_prelim_win_rate'],1,'exclude outlier itself')
same(theory['P002']['theoretical_prelim_draw_rate'],98/99,'exclude same-type self')
same(theory['P002']['theoretical_prelim_loss_rate'],1/99,'include unique opponent')
random_players = [mod.Player(f'P{i+1:03d}',f'g{i%5}',distributions[5+i%30]) for i in range(100)]
theory = mod.theoretical_preliminary(random_players)
for player in random_players:
    others = [q for q in random_players if q.player_id!=player.player_id]
    # Explicit opponent-by-opponent sum, no averaging helper from the target.
    expected = [0.,0.,0.]
    for other in others:
        for h1 in range(3):
            for h2 in range(3):
                i = 1 if h1==h2 else 0 if (h1,h2) in [(0,1),(1,2),(2,0)] else 2
                expected[i] += player.probabilities[h1]*other.probabilities[h2]/99
    row = theory[player.player_id]
    for key,value in zip(['win','draw','loss'],expected):
        same(row[f'theoretical_prelim_{key}_rate'],value,'explicit excluded-self theory')
    same(row['theoretical_prelim_points_per_game'],2*expected[0]+expected[1],'theoretical expected points')
for probabilities in distributions:
    ps = mod.make_players(probabilities)
    for row in mod.theoretical_preliminary(ps).values():
        same(row['theoretical_prelim_win_rate'],row['theoretical_prelim_loss_rate'],'identical nonuniform symmetry')
        same(row['theoretical_prelim_points_per_game'],1,'identical nonuniform expected score')

# Every theoretical strategy matchup, including pure ties.
matchups = mod.strategy_matchup_rows(pure(groups))
check(len(matchups)==9,'all ordered strategy matchups')
for row in matchups:
    i = int(row['strategy'][-1])-1
    j = int(row['opponent_strategy'][-1])-1
    win = int((i,j) in [(0,1),(1,2),(2,0)])
    draw = int(i==j)
    loss = 1-win-draw
    check_rates(row,win,draw,loss)
    same(row['expected_points_per_game'],2*win+draw,'matchup points')

# Real multi-run aggregates independently reconstructed from every match record.
ps = pure([('S',30,1),('P',70,2)])
runs = 19
first,prows,grows = mod.simulate(ps,213,runs)
manual = {p.player_id:{'c':{1:[0,0,0,0],2:[0,0,0,0]},'pq':0,'q':0,'rank':0} for p in ps}
for run in range(runs):
    t = mod.play_tournament(ps,213,run)
    counts = record_counts(t)
    for rank,s in enumerate(t.rankings,1):
        d = manual[s.player.player_id]
        d['rank'] += rank; d['pq'] += rank<=30; d['q'] += rank<=10
        for stage in (1,2):
            for index in range(4):
                d['c'][stage][index] += counts[s.player.player_id][stage][index]
check(first==mod.play_tournament(ps,213),'first captured run reproducibility')
check(first==mod.play_tournament(list(reversed(ps)),213),'input order independence')
for row in prows:
    d = manual[row['player_id']]
    c1,c2 = d['c'][1],d['c'][2]
    totals = [c1[i]+c2[i] for i in range(4)]
    n = sum(totals[:3])
    check_rates(row,*totals[:3],'overall_')
    check_rates(row,*c1[:3],'prelim_')
    check_rates(row,*c2[:3],'final_')
    check((row['total_wins'],row['total_draws'],row['total_losses'],row['total_games'])==(*totals[:3],n),'player actual counts')
    same(row['qualification_rate'],d['q']/runs,'player qualification denominator')
    same(row['prelim_qualification_rate'],d['pq']/runs,'player advancement denominator')
    same(row['conditional_final_qualification_rate'],d['q']/d['pq'] if d['pq'] else None,'conditional qualification denominator')
    same(row['average_final_points'],(2*c2[0]+c2[1])/d['pq'] if d['pq'] else None,'conditional final points denominator')
    same(row['actual_scissors_rate'],totals[3]/n,'player scissors denominator')
    same(row['average_total_points'],(2*totals[0]+totals[1])/runs,'player average points')
for row in grows:
    ds = [manual[p.player_id] for p in ps if p.strategy==row['strategy']]
    sums = {stage:[sum(d['c'][stage][i] for d in ds) for i in range(4)] for stage in (1,2)}
    total = [sums[1][i]+sums[2][i] for i in range(4)]
    check_rates(row,*total[:3],'overall_')
    check_rates(row,*sums[1][:3],'prelim_')
    check_rates(row,*sums[2][:3],'final_')
    same(row['qualification_rate'],sum(d['q'] for d in ds)/(len(ds)*runs),'group qualification denominator')
    same(row['actual_scissors_rate'],total[3]/sum(total[:3]),'group weighted rate')
check(sum(r['qualifications'] for r in prows)==10*runs,'total qualifications')
check(sum(r['prelim_qualifications'] for r in prows)==30*runs,'total advancements')
_,_,zero_final_groups = mod.simulate(ps,213,2,prelim_rounds=99)
check(next(r for r in zero_final_groups if r['strategy']=='P')['final_non_draw_win_rate'] is None,'never-final group empty decisive rate')
check(next(r for r in zero_final_groups if r['strategy']=='P')['final_win_rate'] is None,'never-final group no final games')

# All previous format and schedule properties in configurable modes.
uniform = mod.make_players()
for pr,fs,fr in [(1,12,1),(7,20,19),(99,30,29)]:
    verify(mod.play_tournament(uniform,99,prelim_rounds=pr,finalists=fs,final_rounds=fr),pr,fs,fr)

# CLI creates standalone, correctly scoped CSV/JSON deliverables.
out = BASE/'work'/'verify_original_cli'
result = subprocess.run([sys.executable,'-B',str(SCRIPT),'--probs','0','1','0',
                         '--runs','3','--out-dir',str(out),'--show-rounds'],capture_output=True)
check(result.returncode==0,f'CLI success {result.stderr!r}')
def read_csv(name):
    with (out/name).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))
for name,count in [('matches.csv',385),('rounds.csv',14),('rankings.csv',100),('stage_rankings.csv',130),
                   ('player_summary.csv',100),('strategy_summary.csv',1),('strategy_matchups.csv',1)]:
    check(len(read_csv(name))==count,'CLI '+name+' row count')
check(all(r['overall_non_draw_win_rate']=='' for r in read_csv('rankings.csv')),'undefined rate empty in CSV')
check(all(float(r['stage_points'])==float(r['stage_games']) for r in read_csv('rankings.csv')),'CSV no scissors reward')
check(sum(int(r['qualifications']) for r in read_csv('player_summary.csv'))==30,'CLI all runs summarized')
with (out/'summary.json').open(encoding='utf-8') as stream:
    summary = json.load(stream)
check(summary['scoring']['scissors_bonus']==0,'JSON zero bonus')
check('scissors count descending' not in summary['ranking_order'],'JSON no hand tie breaker')
check(summary['strategies'][0]['overall_non_draw_win_rate'] is None,'JSON undefined rate null')
check(summary['strategies'][0]['overall_draw_rate']==1,'JSON all ties')
result = subprocess.run([sys.executable,'-B',str(SCRIPT),'--scissors-bonus','1'],capture_output=True)
check(result.returncode==2,'original CLI rejects bonus parameter')

print(f'PASS: {checks} checks; ordinary scoring, cyclic-hand symmetry, formulas, excluded-self theory, rate denominators, staged schedule/advancement, reproducibility, summaries and CLI.')
