"""2026 世界杯淘汰赛对阵树与球队表(simulate.py 与 update.py 共用)。

对阵树是赛制事实,写死在代码里;比分、胜者、Elo 属于随时间变化的状态,
放在 state.json 里,由 update.py 每日刷新。

参与方写法:
  "CA"            确定的球队代码(ISO 3166-1 alpha-2)
  ("W", "R32_A")  该场胜者
  ("L", "SF1")    该场负者(季军赛用)
"""

# 32 强全部球队。Elo 数值不放这里(在 state.json),这里只有静态属性。
TEAMS = {
    "AR": {"zh": "阿根廷",     "en": "Argentina"},
    "ES": {"zh": "西班牙",     "en": "Spain"},
    "FR": {"zh": "法国",       "en": "France"},
    "EN": {"zh": "英格兰",     "en": "England"},
    "BR": {"zh": "巴西",       "en": "Brazil"},
    "CO": {"zh": "哥伦比亚",   "en": "Colombia"},
    "PT": {"zh": "葡萄牙",     "en": "Portugal"},
    "MX": {"zh": "墨西哥",     "en": "Mexico"},
    "NO": {"zh": "挪威",       "en": "Norway"},
    "CH": {"zh": "瑞士",       "en": "Switzerland"},
    "BE": {"zh": "比利时",     "en": "Belgium"},
    "HR": {"zh": "克罗地亚",   "en": "Croatia"},
    "MA": {"zh": "摩洛哥",     "en": "Morocco"},
    "AT": {"zh": "奥地利",     "en": "Austria"},
    "PY": {"zh": "巴拉圭",     "en": "Paraguay"},
    "AU": {"zh": "澳大利亚",   "en": "Australia"},
    "US": {"zh": "美国",       "en": "United States"},
    "DZ": {"zh": "阿尔及利亚", "en": "Algeria"},
    "CA": {"zh": "加拿大",     "en": "Canada"},
    "EG": {"zh": "埃及",       "en": "Egypt"},
    "CV": {"zh": "佛得角",     "en": "Cape Verde"},
    "GH": {"zh": "加纳",       "en": "Ghana"},
    # 已在 32 强出局
    "NL": {"zh": "荷兰",       "en": "Netherlands"},
    "DE": {"zh": "德国",       "en": "Germany"},
    "JP": {"zh": "日本",       "en": "Japan"},
    "EC": {"zh": "厄瓜多尔",   "en": "Ecuador"},
    "SN": {"zh": "塞内加尔",   "en": "Senegal"},
    "SE": {"zh": "瑞典",       "en": "Sweden"},
    "CI": {"zh": "科特迪瓦",   "en": "Ivory Coast"},
    "CD": {"zh": "刚果民主共和国", "en": "DR Congo"},
    "BA": {"zh": "波黑",       "en": "Bosnia and Herzegovina"},
    "ZA": {"zh": "南非",       "en": "South Africa"},
}

# venue 为比赛所在国(主场加成判断用)
R32 = [
    {"id": "R32_A", "a": "ZA", "b": "CA", "venue": "US", "date": "06-28", "city": "Inglewood"},
    {"id": "R32_B", "a": "BR", "b": "JP", "venue": "US", "date": "06-29", "city": "Houston"},
    {"id": "R32_C", "a": "DE", "b": "PY", "venue": "US", "date": "06-29", "city": "Foxborough"},
    {"id": "R32_D", "a": "NL", "b": "MA", "venue": "MX", "date": "06-29", "city": "Guadalupe"},
    {"id": "R32_E", "a": "CI", "b": "NO", "venue": "US", "date": "06-30", "city": "Arlington"},
    {"id": "R32_F", "a": "FR", "b": "SE", "venue": "US", "date": "06-30", "city": "East Rutherford"},
    {"id": "R32_G", "a": "MX", "b": "EC", "venue": "MX", "date": "06-30", "city": "Mexico City"},
    {"id": "R32_H", "a": "EN", "b": "CD", "venue": "US", "date": "07-01", "city": "Atlanta"},
    {"id": "R32_I", "a": "BE", "b": "SN", "venue": "US", "date": "07-01", "city": "Seattle"},
    {"id": "R32_J", "a": "US", "b": "BA", "venue": "US", "date": "07-01", "city": "Santa Clara"},
    {"id": "R32_K", "a": "ES", "b": "AT", "venue": "US", "date": "07-02", "city": "Inglewood"},
    {"id": "R32_L", "a": "CH", "b": "DZ", "venue": "CA", "date": "07-02", "city": "Vancouver"},
    {"id": "R32_M", "a": "PT", "b": "HR", "venue": "CA", "date": "07-02", "city": "Toronto"},
    {"id": "R32_N", "a": "AU", "b": "EG", "venue": "US", "date": "07-03", "city": "Arlington"},
    {"id": "R32_O", "a": "AR", "b": "CV", "venue": "US", "date": "07-03", "city": "Miami"},
    {"id": "R32_P", "a": "CO", "b": "GH", "venue": "US", "date": "07-03", "city": "Kansas City"},
]

R16 = [
    {"id": "R16_1", "a": ("W", "R32_A"), "b": ("W", "R32_D"), "venue": "US", "date": "07-04", "city": "Houston"},
    {"id": "R16_2", "a": ("W", "R32_C"), "b": ("W", "R32_F"), "venue": "US", "date": "07-04", "city": "Philadelphia"},
    {"id": "R16_3", "a": ("W", "R32_B"), "b": ("W", "R32_E"), "venue": "US", "date": "07-05", "city": "East Rutherford"},
    {"id": "R16_4", "a": ("W", "R32_G"), "b": ("W", "R32_H"), "venue": "MX", "date": "07-05", "city": "Mexico City"},
    {"id": "R16_5", "a": ("W", "R32_M"), "b": ("W", "R32_K"), "venue": "US", "date": "07-06", "city": "Arlington"},
    {"id": "R16_6", "a": ("W", "R32_J"), "b": ("W", "R32_I"), "venue": "US", "date": "07-06", "city": "Seattle"},
    {"id": "R16_7", "a": ("W", "R32_O"), "b": ("W", "R32_N"), "venue": "US", "date": "07-07", "city": "Atlanta"},
    {"id": "R16_8", "a": ("W", "R32_L"), "b": ("W", "R32_P"), "venue": "CA", "date": "07-07", "city": "Vancouver"},
]

QF = [
    {"id": "QF1", "a": ("W", "R16_1"), "b": ("W", "R16_2"), "venue": "US", "date": "07-09", "city": "Foxborough"},
    {"id": "QF2", "a": ("W", "R16_3"), "b": ("W", "R16_4"), "venue": "US", "date": "07-10", "city": "Inglewood"},
    {"id": "QF3", "a": ("W", "R16_5"), "b": ("W", "R16_6"), "venue": "US", "date": "07-11", "city": "Miami"},
    {"id": "QF4", "a": ("W", "R16_7"), "b": ("W", "R16_8"), "venue": "US", "date": "07-11", "city": "Kansas City"},
]

# 官方赛制的半决赛是跨半区交叉:QF1 胜者对 QF3 胜者、QF2 胜者对 QF4 胜者
# (而不是相邻的 QF1×QF2 / QF3×QF4)。2026-07-14 阿灵顿:法国 0-2 西班牙,
# 2026-07-15 亚特兰大:英格兰 1-2 阿根廷,与此交叉一致。
SF = [
    {"id": "SF1", "a": ("W", "QF1"), "b": ("W", "QF3"), "venue": "US", "date": "07-14", "city": "Arlington"},
    {"id": "SF2", "a": ("W", "QF2"), "b": ("W", "QF4"), "venue": "US", "date": "07-15", "city": "Atlanta"},
]

TP = {"id": "TP", "a": ("L", "SF1"), "b": ("L", "SF2"), "venue": "US", "date": "07-18", "city": "Miami"}
FINAL = {"id": "F", "a": ("W", "SF1"), "b": ("W", "SF2"), "venue": "US", "date": "07-19", "city": "East Rutherford"}

# 模拟顺序:季军赛排在决赛前(都只依赖半决赛)
ALL_MATCHES = R32 + R16 + QF + SF + [TP, FINAL]

ROUND_OF = {}
for _m in R32: ROUND_OF[_m["id"]] = "R32"
for _m in R16: ROUND_OF[_m["id"]] = "R16"
for _m in QF:  ROUND_OF[_m["id"]] = "QF"
for _m in SF:  ROUND_OF[_m["id"]] = "SF"
ROUND_OF["TP"] = "TP"
ROUND_OF["F"] = "F"

ROUND_ZH = {"R32": "32强", "R16": "16强", "QF": "八强", "SF": "半决赛", "TP": "季军赛", "F": "决赛"}


def resolve_team(ref, winners, losers):
    """把参与方引用解析成具体球队代码;解析不出返回 None。"""
    if isinstance(ref, str):
        return ref
    kind, mid = ref
    pool = winners if kind == "W" else losers
    return pool.get(mid)
