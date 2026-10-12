"""W0 호실 연결 기준선 (2026-10-12 실행본) — docs/10 §8.2

신고된 호수를 정답 라벨로, 같은 층 기록을 "시간 겹침 금지 + 면적 유사" 탐욕 연결로 묶었을 때의
쌍 정밀도·재현율을 측정한다. 실행: python3 -I unit_chain_baseline.py seoul.csv
"""
import sys, re, numpy as np, pandas as pd, itertools
AS_OF = pd.Timestamp('2026-10-08')
usecols = ['관리번호','인허가일자','영업상태명','폐업일자','소재지면적','지번주소','도로명주소']
df = pd.read_csv(sys.argv[1], dtype=str, keep_default_na=False, usecols=usecols)
for c in usecols: df[c] = df[c].str.strip()
df['start'] = pd.to_datetime(df['인허가일자'], errors='coerce')
df['closed'] = df['영업상태명'].eq('폐업')
df['end'] = pd.to_datetime(df['폐업일자'], errors='coerce').where(df.closed, AS_OF)
J = df['지번주소'].str.extract(r'서울특별시\s+(\S+구)\s+(\S+)\s+(산\s*)?(\d+)(?:-(\d+))?(.*)$')
J.columns = ['gu','dong','san','main','sub','tail']
df['B'] = J.gu + ' ' + J.dong + ' ' + J.san.notna().map({True:'산',False:''}) + J.main.fillna('') + '-' + J['sub'].fillna('0')
detail = J['tail'].fillna('') + ' ' + df['도로명주소'].str.split(',', n=1).str[1].fillna('')
FLOOR = [(r'지하\s*(\d+)\s*층', 'B'), (r'(지하층|지층)', 'B1'), (r'\bB\s*(\d+)\b', 'B'),
         (r'(?:지상\s*|제\s*)?(\d+)\s*층', ''), (r'(\d+)\s*F\b', '')]
fl = pd.Series(None, index=df.index, dtype=object)
for rx, pre in FLOOR:
    m = detail.str.extract(rx, flags=re.I)[0]
    fl = fl.fillna((pre + m) if pre != 'B1' else m.where(m.isna(), 'B1'))
df['floor'] = fl
df['ho'] = detail.str.extract(r'(\d+)\s*호')[0]
df['area'] = pd.to_numeric(df['소재지면적'], errors='coerce')
d = df.dropna(subset=['B','floor','ho','start','area']).copy()
d = d[(d.area > 0) & (d.start >= '2000-01-01')]
d['F'] = d.B + '|' + d.floor
# 평가 대상: 층 그룹에 2개 이상 레코드, 전부 호 정보 보유
g = d.groupby('F').size(); d = d[d.F.isin(g[g >= 2].index)]
print('평가 레코드', len(d), '층그룹', d.F.nunique(), '진짜 호실', d.groupby(['F','ho']).ngroups)

def chain(grp, tol=30, ratio=0.25, maxgap=730):
    grp = grp.sort_values('start'); chains = []  # [last_end, last_area, id]
    lab = {}
    for idx, s, e, a in zip(grp.index, grp.start, grp.end, grp.area):
        best, bc = None, 1e9
        for ci, (le, la) in enumerate(chains):
            gap = (s - le).days
            if gap < -tol or gap > maxgap: continue
            r = abs(np.log(a / la))
            if r > np.log(1 + ratio): continue
            cost = r + max(gap, 0) / 365
            if cost < bc: best, bc = ci, cost
        if best is None:
            chains.append((e, a)); best = len(chains) - 1
        else:
            chains[best] = (max(chains[best][0], e), a)
        lab[idx] = best
    return pd.Series(lab)

def pairwise(pred_key):
    tp = fp = fn = 0
    for F, grp in d.groupby('F'):
        t = grp.ho.values; p = pred_key.loc[grp.index].values
        for i, j in itertools.combinations(range(len(grp)), 2):
            same_t, same_p = t[i] == t[j], p[i] == p[j]
            tp += same_t and same_p; fp += (not same_t) and same_p; fn += same_t and (not same_p)
    P = tp / (tp + fp) if tp + fp else float('nan'); R = tp / (tp + fn)
    return P, R, 2*P*R/(P+R)

floor_only = pd.Series(0, index=d.index)
print('층 단위(전부 같은 자리로): P=%.3f R=%.3f F1=%.3f' % pairwise(floor_only))
for ratio in [0.10, 0.25, 0.5]:
    lab = pd.concat([chain(grp, ratio=ratio) for _, grp in d.groupby('F')])
    print('시간겹침+면적(±%d%%) 체인: P=%.3f R=%.3f F1=%.3f' % ((ratio*100,) + pairwise(lab)))

print('\n== 진단 ==')
units_per_floor = d.groupby('F').ho.nunique()
print('층당 실제 호실 수 분포:', units_per_floor.describe(percentiles=[.5,.75,.9,.99]).round(1).to_dict())
d2 = d.sort_values(['F','ho','start']).copy()
d2['pe'] = d2.groupby(['F','ho']).end.shift(); d2['pa'] = d2.groupby(['F','ho']).area.shift()
pr = d2.dropna(subset=['pe'])
gap = (pr.start - pr.pe).dt.days; ar = np.abs(np.log(pr.area/pr.pa))
print('같은 호 연속쌍', len(pr), '| 겹침(gap<-30) %.1f%% | gap>730 %.1f%% | 면적차>25%% %.1f%% | 면적 완전일치 %.1f%%' % (
    100*(gap<-30).mean(), 100*(gap>730).mean(), 100*(ar>np.log(1.25)).mean(), 100*(ar<1e-9).mean()))
ov = pr[gap < -30]
print('겹침 쌍 예시 (같은 호, 동시 영업):'); print(ov[['F','ho','start','end','area']].head(6).to_string())
small = units_per_floor[units_per_floor <= 6].index
d = d[d.F.isin(small)]
print('\n[소형 층(호실 6개 이하)만] 레코드', len(d), '층', d.F.nunique())
print('층 단위: P=%.3f R=%.3f F1=%.3f' % pairwise(pd.Series(0, index=d.index)))
for tol in [30, 3650*10]:
    lab = pd.concat([chain(grp, ratio=0.25, tol=tol, maxgap=3650) for _, grp in d.groupby('F')])
    print('체인(±25%%, 겹침허용 %d일, 공백≤10년): P=%.3f R=%.3f F1=%.3f' % ((tol,) + pairwise(lab)))
