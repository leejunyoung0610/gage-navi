"""W0 자리 이력 신호 검증 (2026-10-08 실행본, 로직 수정 금지 — docs/10 §7.4 재현 기준)
정정 2026-10-13 (T-020): 소재지면적의 천 단위 쉼표를 떼고 읽는다. 원 실행본은 쉼표가 든 면적 880건(1,000㎡ 이상 점포)을 숫자가 아닌 값으로 읽어 빠뜨렸다. 다른 로직은 그대로다.

입력: 서울 일반음식점 인허가 CSV를 UTF-8로 변환한 파일
  iconv -f CP949 -t UTF-8 식품_일반음식점_서울특별시.csv > seoul.csv
실행: python3 -I w0_location_signal.py seoul.csv
의존: pandas, numpy, statsmodels
기준일(AS_OF)은 2026-10-08로 고정되어 있다.
"""
import sys, re, time
import numpy as np, pandas as pd
import statsmodels.formula.api as smf

t0 = time.time()
AS_OF = pd.Timestamp('2026-10-08')
usecols = ['관리번호','인허가일자','영업상태명','폐업일자','소재지면적','사업장명','업태구분명',
           '지번주소','도로명주소','좌표정보(X)','좌표정보(Y)']
df = pd.read_csv(sys.argv[1], dtype=str, keep_default_na=False, usecols=usecols)
for c in usecols: df[c] = df[c].str.strip()
print('rows', len(df), '| 관리번호 고유', df['관리번호'].nunique())

df['start'] = pd.to_datetime(df['인허가일자'], errors='coerce')
df['end_raw'] = pd.to_datetime(df['폐업일자'], errors='coerce')
df['closed'] = df['영업상태명'].eq('폐업')
df['end'] = df['end_raw'].where(df['closed'], AS_OF)
print('영업상태:', df['영업상태명'].value_counts().to_dict())
print('폐업인데 날짜 없음', (df.closed & df.end_raw.isna()).sum(), '| 날짜 역전', (df.end < df.start).sum())

# ---- 주소 파싱 ----
J = df['지번주소'].str.extract(r'서울특별시\s+(\S+구)\s+(\S+)\s+(산\s*)?(\d+)(?:-(\d+))?(.*)$')
J.columns = ['gu','dong','san','main','sub','tail']
df['gu'] = J.gu
sub = J['sub'].where(~J['sub'].isin(['0', np.nan]), '')
sub = np.where(sub == '', '', '-' + sub.astype(str))
df['B'] = np.where(J.main.notna(), J.gu + ' ' + J.dong + ' ' + np.where(J.san.notna(), '산', '') + J.main.fillna('') + sub, None)
road_tail = df['도로명주소'].str.split(',', n=1).str[1].fillna('')
detail = J['tail'].fillna('') + ' ' + road_tail

FLOOR = [(r'지하\s*(\d+)\s*층', 'B'), (r'(지하층|지층)', 'B1'), (r'\bB\s*(\d+)\b', 'B'),
         (r'(?:지상\s*|제\s*)?(\d+)\s*층', ''), (r'(\d+)\s*F\b', '')]
fl = pd.Series(None, index=df.index, dtype=object)
for rx, pre in FLOOR:
    m = detail.str.extract(rx, flags=re.I)[0]
    val = (pre + m) if pre != 'B1' else m.where(m.isna(), 'B1')
    fl = fl.fillna(val)
df['floor'] = fl
df['ho'] = detail.str.extract(r'(\d+)\s*호')[0]
df['U'] = np.where(df.B.notna() & df.floor.notna(), df.B.astype(str) + '|' + df.floor.astype(str), None)
df['area'] = pd.to_numeric(df['소재지면적'].str.replace(',', ''), errors='coerce')

print('\n== 주소 품질 ==')
print('구 파싱 %.1f%% | 건물키 %.1f%% | 층 %.1f%% | 호 %.1f%%' % tuple(100*x for x in (
    df.gu.notna().mean(), df.B.notna().mean(), df.floor.notna().mean(), df.ho.notna().mean())))
post05 = df.start >= '2005-01-01'
print('2005년 이후 개업분 층 정보 %.1f%%' % (100*df.loc[post05,'floor'].notna().mean()))
fq = df[post05].groupby('gu')['floor'].apply(lambda s: 100*s.notna().mean())
print('구별 층 정보(2005~) 최저 %.1f%% (%s) / 최고 %.1f%% (%s)' % (fq.min(), fq.idxmin(), fq.max(), fq.idxmax()))

# ---- 자리 이력 분포 (벡터화) ----
def days(s): return ((s - pd.Timestamp('1900-01-01')).dt.days).astype('float')
df['sd'] = days(df.start); df['ed'] = days(df.end)
def history(key):
    d = df.dropna(subset=[key,'sd']).sort_values([key,'sd'])
    size = d.groupby(key)[key].transform('size')
    prev_max_end = d.groupby(key)['ed'].transform(lambda x: x.cummax().shift())
    ov = (d.sd < prev_max_end - 1)
    sizes = d.groupby(key).size()
    return {'자리': len(sizes), '업소': len(d), '2개+%': round(100*(sizes>=2).mean(),1),
            '3개+%': round(100*(sizes>=3).mean(),1), '겹침%': round(100*ov[size>=2].mean(),1)}
print('\n== 자리 이력 ==')
print('건물', history('B')); print('건물+층', history('U'))

# ---- 과거 폐업 횟수 (같은 키, 개업일 이전 폐업) ----
bulk = df.loc[df.closed,'end'].value_counts(); bulk_dates = set(bulk[bulk >= 100].index)
print('\n하루 100건+ 일괄 폐업일 수:', len(bulk_dates), '| 해당 건수:', int(bulk[bulk>=100].sum()))
BIG = 1e6
def prior_closures(key):
    d = df[[key,'sd','ed','closed']].dropna(subset=[key,'sd'])
    code = pd.factorize(d[key])[0].astype(float)
    ends = np.sort((code*BIG + d.ed.values)[d.closed.values & ~np.isnan(d.ed.values)])
    q = code*BIG + d.sd.values
    cnt = np.searchsorted(ends, q, 'left') - np.searchsorted(ends, code*BIG - 1, 'left')
    return pd.Series(cnt, index=d.index)
df['kU'] = prior_closures('U'); df['kB'] = prior_closures('B')

m = df[df.start.between('2005-01-01','2023-10-08') & df.kU.notna() & df.area.gt(0)].copy()
m = m[~(m.closed & m.end.isin(bulk_dates))]
m['dead3'] = (m.closed & ((m.end - m.start).dt.days <= 365*3)).astype(int)
m['k'] = m.kU.clip(upper=5)
m['kBx'] = (m.kB - m.kU).clip(lower=0, upper=20)  # 같은 건물 다른 층의 과거 폐업
m['area_l'] = np.log(m.area)
m['yr'] = m.start.dt.year
top = m['업태구분명'].value_counts().index[:10]
m['biz'] = m['업태구분명'].where(m['업태구분명'].isin(top), '기타')
m['basement'] = m.floor.str.startswith('B').astype(int)
m['upper'] = m.floor.str.fullmatch(r'\d+').fillna(False) & (pd.to_numeric(m.floor, errors='coerce') >= 2)
m['upper'] = m.upper.astype(int)
print('\n분석 표본:', len(m), '| 3년 내 폐업률 %.1f%%' % (100*m.dead3.mean()))

tab = m.groupby(m.kU.clip(upper=4))['dead3'].agg(['size','mean']); tab['mean'] = (100*tab['mean']).round(1)
print('\n== 과거 폐업 횟수(건물+층)별 3년 내 폐업률 ==' ); print(tab.to_string())

def fit(formula, data, label):
    r = smf.logit(formula, data=data).fit(disp=0, cov_type='cluster', cov_kwds={'groups': pd.factorize(data.U)[0]})
    out = {}
    for v in ['k','kBx']:
        if v in r.params:
            b, se = r.params[v], r.bse[v]
            out[v] = 'OR %.3f (%.3f~%.3f) p=%.1e' % (np.exp(b), np.exp(b-1.96*se), np.exp(b+1.96*se), r.pvalues[v])
    print(f'[{label}] n={int(r.nobs)}', out); return r

base = 'C(yr) + C(biz) + area_l + C(gu) + basement + upper'
print('\n== 로지스틱 (자리 단위 클러스터 표준오차) ==')
r1 = fit(f'dead3 ~ k + {base}', m, '기본: 연도·업종·면적·구·층위치 통제')
r2 = fit(f'dead3 ~ k + kBx + {base}', m, '+ 같은 건물 다른 층 폐업 통제')

print('\n== 구별 재현 (각 구 따로 적합) ==')
rows = []
for gu, g in m.groupby('gu'):
    try:
        r = smf.logit('dead3 ~ k + C(yr) + C(biz) + area_l + basement + upper', data=g).fit(disp=0)
        b, se = r.params['k'], r.bse['k']
        rows.append((gu, len(g), np.exp(b), np.exp(b-1.96*se), np.exp(b+1.96*se)))
    except Exception as e:
        rows.append((gu, len(g), np.nan, np.nan, np.nan))
rg = pd.DataFrame(rows, columns=['gu','n','OR','lo','hi']).sort_values('OR')
print(rg.round(3).to_string(index=False))
print('OR>1: %d/%d구 | 95%%CI 하한>1: %d구 | 상한<1: %d구' % ((rg.OR>1).sum(), len(rg), (rg.lo>1).sum(), (rg.hi<1).sum()))

print('\n== 시간 외 검증: 2005-2014로 학습 → 2015-2020 개업 예측 ==')
tr = m[m.yr <= 2014]; te = m[(m.yr >= 2015) & (m.yr <= 2020)].copy()
fb = 'C(biz) + area_l + C(gu) + basement + upper + yr'
def auc(y, p):
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p)+1)
    pos = y == 1; return (ranks[pos].sum() - pos.sum()*(pos.sum()+1)/2) / (pos.sum()*(~pos).sum())
for label, f in [('통제변수만', fb), ('+ 자리 폐업이력', fb + ' + k')]:
    r = smf.logit('dead3 ~ ' + f, data=tr).fit(disp=0)
    p = r.predict(te).values
    print(f'{label}: AUC {auc(te.dead3.values, p):.4f}')
te['decile_k'] = te.k
print('검증기간 실제 3년 내 폐업률 (과거 폐업 0회 vs 3회+): %.1f%% vs %.1f%%' % (
    100*te.loc[te.k==0,'dead3'].mean(), 100*te.loc[te.k>=3,'dead3'].mean()))
print('\n소요 %.0f초' % (time.time()-t0))
