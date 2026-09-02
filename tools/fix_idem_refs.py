import re

KEEP = {
    ('/achievements', 'post'),
    ('/demands', 'post'),
    ('/cooperations', 'post'),
    ('/ai/match-tasks', 'post'),
    ('/ai/evaluation-tasks', 'post'),
    ('/uploads/presign', 'post'),
}

path = r'c:\Users\admin\Desktop\南山小程序\docs\architecture\openapi.yaml'
lines = open(path, encoding='utf-8').read().split('\n')

current_path = None
current_method = None
removed = []
out = []
for line in lines:
    m = re.match(r'^  (/[a-zA-Z0-9/{}\-_]+):\s*$', line)
    if m:
        current_path = m.group(1)
    m2 = re.match(r'^    (get|post|put|patch|delete):\s*$', line)
    if m2:
        current_method = m2.group(1)
    if "XIdempotencyKey'" in line and current_path and current_method:
        if (current_path, current_method) not in KEEP:
            removed.append(f'{current_method.upper()} {current_path}')
            continue
    out.append(line)

open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
print(f'移除矩阵外幂等键引用: {len(removed)} 处')
for r in removed:
    print('  -', r)
