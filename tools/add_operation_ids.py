import re

OP_IDS = {
    ('/auth/bootstrap', 'post'): 'bootstrapSession',
    ('/auth/refresh', 'post'): 'refreshSession',
    ('/auth/logout', 'post'): 'logout',
    ('/me', 'get'): 'getCurrentUser',
    ('/me/profile', 'patch'): 'updateMyProfile',
    ('/me/demands', 'get'): 'listMyDemands',
    ('/me/achievements', 'get'): 'listMyAchievements',
    ('/me/favorites', 'get'): 'listMyFavorites',
    ('/me/cooperations', 'get'): 'listMyCooperations',
    ('/achievements', 'get'): 'listAchievements',
    ('/achievements', 'post'): 'createAchievement',
    ('/achievements/{id}', 'get'): 'getAchievement',
    ('/achievements/{id}', 'patch'): 'updateAchievement',
    ('/achievements/{id}/submit', 'post'): 'submitAchievement',
    ('/achievements/{id}/offline', 'post'): 'offlineAchievement',
    ('/achievements/{id}/evaluations', 'get'): 'listAchievementEvaluations',
    ('/achievements/{id}/patents', 'get'): 'listAchievementPatents',
    ('/achievements/{id}/patents', 'post'): 'attachAchievementPatent',
    ('/achievements/{id}/patents/{patentId}', 'delete'): 'detachAchievementPatent',
    ('/demands', 'get'): 'listDemands',
    ('/demands', 'post'): 'createDemand',
    ('/demands/{id}', 'get'): 'getDemand',
    ('/demands/{id}', 'patch'): 'updateDemand',
    ('/demands/{id}/submit', 'post'): 'submitDemand',
    ('/demands/{id}/cancel', 'post'): 'cancelDemand',
    ('/demands/{id}/close', 'post'): 'closeDemand',
    ('/demands/{id}/matches', 'get'): 'listDemandMatches',
    ('/favorites/{targetType}/{targetId}', 'put'): 'addFavorite',
    ('/favorites/{targetType}/{targetId}', 'delete'): 'removeFavorite',
    ('/cooperations', 'post'): 'createCooperation',
    ('/cooperations/{id}', 'get'): 'getCooperation',
    ('/cooperations/{id}/accept', 'post'): 'acceptCooperation',
    ('/cooperations/{id}/reject', 'post'): 'rejectCooperation',
    ('/cooperations/{id}/confirm', 'post'): 'confirmCooperation',
    ('/cooperations/{id}/cancel', 'post'): 'cancelCooperation',
    ('/cooperations/{id}/complete', 'post'): 'completeCooperation',
    ('/cooperations/{id}/events', 'get'): 'listCooperationEvents',
    ('/search', 'get'): 'search',
    ('/ai/match-tasks', 'post'): 'createMatchTask',
    ('/ai/match-tasks/{taskId}', 'get'): 'getMatchTask',
    ('/ai/evaluation-tasks', 'post'): 'createEvaluationTask',
    ('/ai/evaluation-tasks/{taskId}', 'get'): 'getEvaluationTask',
    ('/capital/platforms', 'get'): 'listCapitalPlatforms',
    ('/capital/platforms/{id}', 'get'): 'getCapitalPlatform',
    ('/capital/investment-organizations', 'get'): 'listInvestmentOrganizations',
    ('/capital/financial-organizations', 'get'): 'listFinancialOrganizations',
    ('/capital/service-organizations', 'get'): 'listServiceOrganizations',
    ('/patents', 'get'): 'listPatents',
    ('/patents/{id}', 'get'): 'getPatent',
    ('/uploads/presign', 'post'): 'presignUpload',
    ('/uploads/{uploadId}/complete', 'post'): 'completeUpload',
    ('/admin/achievements/review-queue', 'get'): 'listAchievementReviewQueue',
    ('/admin/achievements/{id}/approve', 'post'): 'approveAchievement',
    ('/admin/achievements/{id}/reject', 'post'): 'rejectAchievement',
    ('/admin/demands/review-queue', 'get'): 'listDemandReviewQueue',
    ('/admin/demands/{id}/approve', 'post'): 'approveDemand',
    ('/admin/demands/{id}/reject', 'post'): 'rejectDemand',
    ('/admin/audit-logs', 'get'): 'listAuditLogs',
}

path = r'c:\Users\admin\Desktop\南山小程序\docs\architecture\openapi.yaml'
lines = open(path, encoding='utf-8').read().split('\n')

current_path = None
inserted = []
out = []
i = 0
while i < len(lines):
    line = lines[i]
    m = re.match(r'^  (/[a-zA-Z0-9/{}\-_]+):\s*$', line)
    if m:
        current_path = m.group(1)
    m2 = re.match(r'^    (get|post|put|patch|delete):\s*$', line)
    if m2 and current_path in {p for p, _ in OP_IDS}:
        key = (current_path, m2.group(1))
        if key in OP_IDS:
            # already has operationId? look ahead inside this operation block
            block_end = i + 1
            has_oid = False
            while block_end < len(lines) and re.match(r'^    \S', lines[block_end]) is None and lines[block_end].strip() != '':
                if re.match(r'^\s+operationId:', lines[block_end]):
                    has_oid = True
                    break
                block_end += 1
            out.append(line)
            if not has_oid:
                out.append(f'      operationId: {OP_IDS[key]}')
                inserted.append(key)
            i += 1
            continue
    out.append(line)
    i += 1

open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
print(f'插入 operationId: {len(inserted)} 个')
missing = [k for k in OP_IDS if k not in inserted and k[0] != '/auth/refresh' and k[0] != '/auth/logout']
existing = set()
# count how many ops actually in file
cp = None
for l in out:
    m = re.match(r'^  (/[a-zA-Z0-9/{}\-_]+):\s*$', l)
    if m: cp = m.group(1)
    m2 = re.match(r'^    (get|post|put|patch|delete):\s*$', l)
    if m2 and cp: existing.add((cp, m2.group(1)))
print(f'文件中操作总数: {len(existing)}')
no_oid = []
cp = None
cur_method = None
for idx, l in enumerate(out):
    m = re.match(r'^  (/[a-zA-Z0-9/{}\-_]+):\s*$', l)
    if m: cp = m.group(1)
    m2 = re.match(r'^    (get|post|put|patch|delete):\s*$', l)
    if m2 and cp:
        cur_method = (cp, m2.group(1))
        # scan block
        j = idx + 1
        found = False
        while j < len(out) and (out[j].startswith('      ') or out[j].strip() == ''):
            if re.match(r'^      operationId:', out[j]):
                found = True
                break
            if re.match(r'^    [a-z]', out[j]):
                break
            j += 1
        if not found:
            no_oid.append(cur_method)
print(f'仍缺 operationId 的操作: {len(no_oid)}')
for x in no_oid:
    print('  MISSING:', x)
