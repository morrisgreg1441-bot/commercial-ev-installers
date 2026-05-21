"""
Scoring rubric for Top 50 Featured-listing prospects.

Hard filters: has email, has website, lists Commercial, not a big national,
not a non-EV-vertical firm, not a clearly fabricated email.

Score components (higher = more likely to buy a £49-99 Featured slot):
  Commercial-intent wording (workplace/fleet/depot/business in service_text)
  Healthy SMB profile (Commercial + Residential mix, OR Commercial-only focused)
  Limited company structure (sales-able, has buying authority)
  Own-brand domain (signals website investment they'd protect)
  Mild region-density bonus (capped) — too-high weight crowded everything into
    one region, so we ALSO stratify the final picks (max 6 per region)
Negative: free-host domains (low marketing budget)

Final selection: take top-scoring qualifying installers but cap 6 per region
so outreach is geographically spread across the UK.
"""
import json, csv, re
from collections import Counter, defaultdict

SRC = r'C:\Users\greg\Desktop\ev-directory\data\installers.json'
OUT = r'C:\Users\greg\Desktop\ev-directory\sales\prospects-top50.csv'

data = json.load(open(SRC, encoding='utf-8'))['installers']

BIG_PLAYERS = {
    'pod-point','podpoint','bp-pulse','bppulse','instavolt','osprey',
    'gridserve','chargepoint','mer.eco','mer-uk','evbox','zapmap',
    'shell','octopus','britishgas','mitie','rolec','wallbox','easee',
    'myenergi','andersenev','project-ev','evios','novuna','centrica',
    'eo-charging','eocharging','vattenfall','siemens','abb','tesla',
    'eonext','eon-uk','edf','scottishpower','sse','fastned',
    'connected-kerb','connectedkerb','npower','eonenergy','britishvolt',
    'equans','engie','kier','balfourbeatty','balfour-beatty','mitie',
    'iss','sodexo','amey','interserve','vinci','keppie','morrison',
    'wjgroundwork','nationalgrid','ukpowernetworks','sgn',
}
NON_EV_TOKENS = ('security','cctv','alarm','plumbing','plumber','roof',
                 'handyman','kitchen','bathroom','joiner','carpent','pest',
                 'cleaning','landscap','paint','fence','window','heating')

region_count = Counter(x['region'] for x in data)
max_region = max(region_count.values())

def domain(url):
    if not url or url == 'N/A': return ''
    return re.sub(r'^https?://(www\.)?', '', url).split('/')[0].lower()

def synthetic_email(email):
    return email.lower().endswith('@email.com')

def score(x):
    reasons = []
    pts = 0
    web   = x.get('website',''); email = x.get('email','')
    svcs  = x.get('services',[]); txt = (x.get('service_text','') or '').lower()
    name  = (x.get('name','') or '').lower()
    dom   = domain(web)

    if 'Commercial' not in svcs: return None,'no commercial'
    if not web or web == 'N/A':  return None,'no website'
    if not email or email == 'N/A': return None,'no email'
    if synthetic_email(email):   return None,'synthetic email'
    for bp in BIG_PLAYERS:
        if bp in dom.replace('.','') or bp in name.replace(' ',''):
            return None,'big player'
    for tok in NON_EV_TOKENS:
        if tok in name or tok in dom: return None,f'non-EV vertical ({tok})'

    for kw,p in [('workplace',10),('fleet',10),('depot',8),('business',5),
                 ('destination',4),('hotel',3),('rapid',3),
                 ('commercial install',3)]:
        if kw in txt: pts += p; reasons.append(f'+{p} kw:{kw}')

    # Capped density bonus (max +6 instead of +15)
    dens = region_count[x['region']] / max_region
    rp = round(dens * 6); pts += rp; reasons.append(f'+{rp} density')

    if set(svcs) == {'Commercial','Residential'}:
        pts += 5; reasons.append('+5 SMB mix')
    if svcs == ['Commercial']:
        pts += 12; reasons.append('+12 commercial-only focused')

    if any(s in name for s in (' ltd',' limited',' plc')):
        pts += 3; reasons.append('+3 ltd co')

    nroot = re.sub(r'[^a-z]','',name.split()[0]) if name.split() else ''
    if nroot and dom and len(nroot)>=4 and nroot[:4] in dom:
        pts += 4; reasons.append('+4 own-brand domain')

    if any(h in dom for h in ('wix.com','sites.google','wordpress.com','weebly','godaddy')):
        pts -= 6; reasons.append('-6 free host')

    return pts, '; '.join(reasons)

scored = []
rejected = Counter()
for x in data:
    r = score(x)
    if r[0] is None: rejected[r[1]] += 1; continue
    scored.append((r[0], x, r[1]))

print('Rejected:')
for k,v in rejected.most_common(): print(f'  {v:4d}  {k}')
print(f'Qualifying: {len(scored)}')

scored.sort(key=lambda t:-t[0])

# Stratified pick: max 6 per region, fill in score order
CAP_PER_REGION = 6
picked, by_region = [], defaultdict(int)
for s,x,r in scored:
    if by_region[x['region']] >= CAP_PER_REGION: continue
    picked.append((s,x,r))
    by_region[x['region']] += 1
    if len(picked) == 50: break

# If under 50 (small regions exhausted), top up by raising cap
if len(picked) < 50:
    used = {x['name'] for _,x,_ in picked}
    for s,x,r in scored:
        if x['name'] in used: continue
        picked.append((s,x,r))
        if len(picked) == 50: break

with open(OUT,'w',newline='',encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['rank','score','name','region','town','postcode','phone',
                'email','website','services','service_text','reasons'])
    for i,(s,x,r) in enumerate(picked,1):
        w.writerow([i,s,x['name'],x['region'],x['town'],x['postcode'],
                    x['phone'],x['email'],x['website'],
                    '|'.join(x.get('services',[])),
                    x.get('service_text',''), r])

print(f'\nWrote {OUT}')
print(f'Score range: {picked[0][0]} -> {picked[-1][0]}')
print('\nRegion distribution in Top 50:')
for k,v in Counter(x['region'] for _,x,_ in picked).most_common():
    print(f'  {v:3d}  {k}')
print('\nTop 15 preview:')
for i,(s,x,_) in enumerate(picked[:15],1):
    print(f'{i:2d}. [{s}] {x["name"]} ({x["region"]}, {x["town"]}) - {x["website"]}')
