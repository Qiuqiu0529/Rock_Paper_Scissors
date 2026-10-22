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
spec = importlib.util.spec_from_file_location('rps_tournament', SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

checks = 0

def check(condition, message):
    global checks
    assert condition, message
    checks += 1

def players(groups):
    result = []
    for name, count, hand in groups:
        probs = tuple(float(i == hand) for i in range(3))
        for _ in range(count):
            result.append(mod.Player(f'P{len(result)+1:03d}', name, probs))
    return result

def invariants(tournament, bonus=1):
    standings = tournament.rankings
    check(len(standings) == 100, '100 standings')
    check(len({s.player.player_id for s in standings}) == 100, 'unique IDs')
    check(len(tournament.match_records) == 4950, '4950 match records')
    check(len(tournament.round_records) == 99, '99 round records')
    check(sum(s.wins for s in standings) == sum(s.losses for s in standings), 'win/loss totals')
    check(sum(s.draws for s in standings) % 2 == 0, 'draw parity')
    check(math.isclose(sum(s.points(bonus) for s in standings),
          9900 + bonus * sum(s.hand_counts[1] for s in standings)), 'point conservation')
    for s in standings:
        check(s.wins+s.draws+s.losses == 99, '99 outcomes per player')
        check(sum(s.hand_counts) == 99, '99 hands per player')
    for match in tournament.match_records:
        hands = [match['hand_1'], match['hand_2']]
        check(math.isclose(match['points_1']+match['points_2'],
              2 + bonus * hands.count('剪刀')), 'match point conservation')

# Schedule checks at different even sizes, including all 100 players.
for size in (2, 4, 6, 10, 100):
    for seed in (0, 42, -1):
        schedule = mod.round_robin_schedule(size, random.Random(seed))
        check(len(schedule) == size-1, 'schedule round count')
        all_pairs = set()
        for round_pairs in schedule:
            check(len(round_pairs) == size//2, 'matches per round')
            participants = [p for pair in round_pairs for p in pair]
            check(sorted(participants) == list(range(size)), 'exactly once per round')
            for a, b in round_pairs:
                check(a != b, 'no self match')
                pair = tuple(sorted((a, b)))
                check(pair not in all_pairs, 'no repeated pair')
                all_pairs.add(pair)
        check(len(all_pairs) == size*(size-1)//2, 'all unordered pairs')

# Pure-strategy and mixed deterministic oracles.
for name, hand, expected in [('R',0,99), ('S',1,198), ('P',2,99)]:
    tournament = mod.play_tournament(players([(name,100,hand)]), 42)
    invariants(tournament)
    for standing in tournament.rankings:
        check(standing.points(1) == expected, f'all {name} points')
        check((standing.wins,standing.draws,standing.losses) == (0,99,0), 'pure draws')
        check(standing.hand_counts[hand] == 99, 'pure hand count')

for groups, expected in [
    ([('R',50,0),('S',50,1)], {'R':(149,50,49,0,0), 'S':(148,0,49,50,99)}),
    ([('S',50,1),('P',50,2)], {'S':(248,50,49,0,99), 'P':(49,0,49,50,0)}),
    ([('P',50,2),('R',50,0)], {'P':(149,50,49,0,0), 'R':(49,0,49,50,0)}),
]:
    tournament = mod.play_tournament(players(groups), 56)
    invariants(tournament)
    for s in tournament.rankings:
        check((s.points(1),s.wins,s.draws,s.losses,s.hand_counts[1]) == expected[s.player.strategy],
              'mixed deterministic oracle')
    check(all(s.player.strategy == groups[0][0] for s in tournament.rankings[:10]), 'correct qualifiers')

# Same seed has identical output. The bonus changes no gestures, outcomes, or schedule.
uniform = mod.make_players()
baseline = mod.play_tournament(uniform, 20261022, scissors_bonus=0)
repeat = mod.play_tournament(uniform, 20261022, scissors_bonus=0)
boosted = mod.play_tournament(uniform, 20261022, scissors_bonus=2.5)
check(baseline == repeat, 'same seed full reproducibility')
invariants(baseline, 0)
invariants(boosted, 2.5)
for a,b in zip(baseline.match_records, boosted.match_records):
    check({k:v for k,v in a.items() if not k.startswith('points_')} ==
          {k:v for k,v in b.items() if not k.startswith('points_')}, 'bonus-independent gestures')
    check(b['points_1']-a['points_1'] == 2.5*(a['hand_1']=='剪刀'), 'left bonus delta')
    check(b['points_2']-a['points_2'] == 2.5*(a['hand_2']=='剪刀'), 'right bonus delta')

# Independently reproduce every summary statistic over multiple tournaments.
runs = 12
first, per_player, per_strategy = mod.simulate(uniform, 87, runs, 1)
manual = {p.player_id: {'q':0,'rank':0,'points':0,'wins':0,'scissors':0} for p in uniform}
fingerprints = set()
for run in range(runs):
    tournament = mod.play_tournament(uniform,87,run,1,capture_records=False)
    fingerprints.add(tuple((s.player.player_id,s.wins,s.draws,tuple(s.hand_counts)) for s in tournament.rankings))
    for rank,s in enumerate(tournament.rankings,1):
        t = manual[s.player.player_id]
        t['q'] += int(rank<=10)
        t['rank'] += rank
        t['points'] += s.points(1)
        t['wins'] += s.wins
        t['scissors'] += s.hand_counts[1]
check(len(fingerprints) == runs, 'distinct run random streams')
check(sum(p['qualifications'] for p in per_player) == 10*runs, 'total qualifications')
check(first == mod.play_tournament(uniform,87,0,1), 'first tournament capture')
for row in per_player:
    t = manual[row['player_id']]
    check(row['qualifications']==t['q'], 'qualifications aggregate')
    for field,key in [('average_rank','rank'),('average_points','points'),('average_wins','wins')]:
        check(row[field]==t[key]/runs, field)
    check(row['qualification_rate']==t['q']/runs, 'qualification rate denominator')
    check(row['actual_scissors_rate']==t['scissors']/(99*runs), 'scissors rate denominator')
check(len(per_strategy)==1, 'single uniform strategy')
check(per_strategy[0]['qualification_rate']==0.1, 'aggregate uniform advancement')

# Exact full ties must use a reproducible lottery and vary over repeated runs.
all_rock = players([('R',100,0)])
_, tied_players, _ = mod.simulate(all_rock, 4, 120, 1)
check(sum(p['qualifications'] for p in tied_players)==1200, 'tied qualifications total')
check(len({p['qualifications'] for p in tied_players})>1, 'tie lottery changes by run')
check(sum(p['qualifications']>0 for p in tied_players)>90, 'no stable ID tie-break')

# CLI integration: records cover only the first tournament, summary covers all runs.
out = BASE/'work'/'verify_cli_results'
completed = subprocess.run([sys.executable,str(SCRIPT),'--runs','3','--seed','97',
                           '--probs','0','1','0','--out-dir',str(out)],
                          capture_output=True)
check(completed.returncode==0, f'CLI success: {completed.stderr}')
for name, expected in [('matches.csv',4950),('rounds.csv',99),('rankings.csv',100),
                       ('player_summary.csv',100),('strategy_summary.csv',1)]:
    with (out/name).open(encoding='utf-8-sig',newline='') as stream:
        rows = list(csv.DictReader(stream))
    check(len(rows)==expected, f'{name} rows')
    if name=='player_summary.csv':
        check(sum(int(row['qualifications']) for row in rows)==30, 'CLI multi-run aggregate')
with (out/'summary.json').open(encoding='utf-8') as stream:
    summary = json.load(stream)
check(summary['runs']==3 and len(summary['first_tournament_top_10'])==10, 'JSON metadata')

print(f'PASS: {checks} checks; schedule, all deterministic oracles, conservation, reproducibility, bonus isolation, summaries, lottery, CLI.')
