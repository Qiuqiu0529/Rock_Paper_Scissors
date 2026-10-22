from __future__ import annotations

from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import random
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prob_roundtrip_under_test', BASE/'outputs'/'rps_simulator.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
checks = 0

def check(value,message):
    global checks
    assert value,message
    checks += 1

fixtures = [
    (.4637670984023892,.2661653318268128,.2700675697707981),
    (.2,.3,.5000000001),
    (.2,.3,.4999999999),
    (.2,.3,.5000000000000004),
    (.9999999995,0.,0.),
    (1/3,1/3,1/3),
    (Decimal('.2'),Decimal('.3'),Decimal('.5000000001')),
]
rng = random.Random(20261022)
for i in range(1200):
    raw = [rng.random() for _ in range(3)]
    normalized = [value/sum(raw) for value in raw]
    scale = 1 if i%3==0 else 1+rng.uniform(-8.9e-10,8.9e-10)
    fixtures.append(tuple(value*scale for value in normalized))

for start in range(0,len(fixtures),3):
    subset = fixtures[start:start+3]
    raw = {
        'groups':[{'name':f'g{i}','count':2,'strategy':{'type':'random',
                    'probabilities':dict(zip(m.HANDS,probabilities))}}
                  for i,probabilities in enumerate(subset)],
        'stages':[{'name':'one','rounds':1,'advance':1}],
    }
    baseline = m.parse_config(raw)
    settings = baseline
    for iteration in range(20):
        settings = m.parse_config(m.config_dict(settings))
        check(settings==baseline,f'config_dict drift batch {start}, iteration {iteration}')
        encoded = json.dumps(m.config_dict(settings),default=m.json_decimal,allow_nan=False)
        decoded = json.loads(encoded,parse_float=Decimal)
        settings = m.parse_config(decoded)
        check(settings==baseline,f'JSON drift batch {start}, iteration {iteration}')
    for group in baseline.groups:
        check(abs(sum(group.strategy.probabilities)-1)<=1e-15,'normalized probability total tolerance')

original = fixtures[0]
strategy = m.parse_strategy({'type':'random','probabilities':dict(zip(m.HANDS,original))},'fixture')
check(strategy.probabilities==original,'machine-precision tuple is preserved exactly')
offset = m.parse_strategy({'type':'random','probabilities':dict(zip(m.HANDS,(.2,.3,.5000000001)))},'fixture')
check(offset.probabilities!=(.2,.3,.5000000001),'larger accepted discrepancy is normalized once')
print(f'PASS: {checks} targeted checks; {len(fixtures)} probability fixtures, 20 config/JSON reload cycles each, exact Settings idempotence.')
