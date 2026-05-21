import json, random, collections
from collections import Counter

d = json.load(open(r'C:\Users\greg\Desktop\ev-directory\data\installers.json', encoding='utf-8'))['installers']
regions = Counter(x['region'] for x in d)
has_web = sum(1 for x in d if x.get('website') and x['website'] != 'N/A')
has_email = sum(1 for x in d if x.get('email') and x['email'] != 'N/A')
commercial_only = sum(1 for x in d if x.get('services') == ['Commercial'])
print('Total:', len(d))
print('Regions:', regions.most_common())
print('Has website:', has_web)
print('Has email:', has_email)
print('Commercial-only:', commercial_only)

with_web = [x for x in d if x.get('website') and x['website'] != 'N/A' and 'Commercial' in x.get('services', [])]
print('With web + commercial:', len(with_web))

by_region = collections.defaultdict(list)
for x in with_web:
    by_region[x['region']].append(x)

random.seed(42)
sample = []
target_regions = ['London','South East','North West','South West','Scotland','Wales','West Midlands','Yorkshire and The Humber','East of England','North East']
for r in target_regions:
    pool = by_region.get(r, [])
    if pool:
        sample.append(random.choice(pool))
print('\n=== SAMPLE 10 ===')
for s in sample:
    print(f"{s['name']} | {s['region']} | {s['town']} | {s['website']} | {s['email']} | {s['service_text'][:60]}")
