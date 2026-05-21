import json, re, collections
data = json.load(open(r'C:\Users\greg\Desktop\ev-directory\data\installers.json', encoding='utf-8'))['installers']

suspicious = []
for x in data:
    e = (x.get('email') or '').lower()
    w = (x.get('website') or '').lower()
    if not e or e == 'n/a': continue
    dom = re.sub(r'^https?://(www\.)?', '', w).split('/')[0]
    local, _, edom = e.partition('@')
    if edom == 'email.com':
        suspicious.append(('email.com', x['name'], e, w))
    elif dom and local == edom.split('.')[0]:
        # e.g. lavelle@lavelle-elec.com — local matches edom root
        suspicious.append(('local==edom-root', x['name'], e, w))

print(f'Suspicious emails: {len(suspicious)}')
for s in suspicious[:30]:
    print(s)

# Also: how many emails share local part == "info" or generic?
locals_ = collections.Counter()
for x in data:
    e = (x.get('email') or '').lower()
    if e and e != 'n/a':
        locals_[e.split('@')[0]] += 1
print('\nTop 15 email locals:')
for k,v in locals_.most_common(15):
    print(f'  {v:4d}  {k}')
