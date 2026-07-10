#!/usr/bin/env python3
"""2026 世界杯淘汰赛量化预测模型。

方法:
  1. 队伍强度用 eloratings.net 的 World Football Elo Ratings(state.json 中的快照,
     由 update.py 在赛期定时刷新)。
  2. 单场胜负期望 We = 1 / (1 + 10^(-d/400)),d 为 Elo 差。
     在本国境内比赛的球队按 eloratings.net 惯例加 100 Elo 主场分。
  3. 比分模型为双泊松:以 90 分钟总进球期望 TOTAL_GOALS 为基准,用二分法解出两队
     进球期望 λ1、λ2,使双泊松给出的期望积分 P(胜) + 0.5*P(平) 恰好等于 Elo
     胜负期望;极端 Elo 差不可表达时,仅提高该场总进球期望至可解最小值。比分分布因此
     与 Elo 完全自洽,没有自由拍定的强度参数。
  4. 平局进入加时,加时进球率为常规时间的 1/3(30 分钟)。仍平则点球,
     按 50/50 处理(点球结果在统计上接近随机)。
  5. 从当前真实对阵状态(state.json 的已赛结果)出发,Monte Carlo 模拟
     N_SIMS 次整个剩余赛程,统计每队进八强/四强/决赛/夺冠概率。
  6. 每场确定对阵的比分概率分布用双泊松网格解析计算,不靠抽样。

数据输入只有两样:各队 Elo 与已赛结果。不含任何媒体预测、伤停新闻或主观调整。

运行: python3 simulate.py  → 生成 data.js(网站数据)并打印摘要。
"""

import json
import math
import random

from bracket import TEAMS, ALL_MATCHES, R16, QF, SF, ROUND_OF, ROUND_ZH, resolve_team

random.seed(20260702)

N_SIMS = 100_000
TOTAL_GOALS = 2.6          # 90 分钟两队合计进球期望(国际大赛长期均值)
HOME_BONUS = 100           # 本国境内作赛的 Elo 主场加成
MAX_GOALS = 10             # 泊松分布至少计算到的进球数
PMF_TAIL_EPSILON = 1e-12   # 自适应截断后的最大遗漏概率
TOTAL_GOALS_MARGIN = 1e-4  # 极端 Elo 差下确保二分目标落在开区间内
SPECIAL_FLAGS = {
    "EN": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
}

with open("state.json", encoding="utf-8") as f:
    STATE = json.load(f)
ELO = STATE["elo"]
RESULTS = STATE["results"]
PREDICTION_HISTORY = STATE.setdefault("predictionHistory", {})

def flag_emoji(code):
    """ISO 两字码转国旗 emoji;英格兰单独处理。"""
    if code in SPECIAL_FLAGS:
        return SPECIAL_FLAGS[code]
    if len(code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)

# ---------------------------------------------------------------- 数学核心

def win_expectancy(d):
    return 1.0 / (1.0 + 10.0 ** (-d / 400.0))

def poisson_pmf(lam, kmin=MAX_GOALS):
    """泊松概率质量函数,自适应延长至剩余尾部可忽略。"""
    if lam < 0:
        raise ValueError("Poisson lambda must be non-negative")
    p = [math.exp(-lam)]
    total = p[0]
    k = 0
    while k < kmin or 1.0 - total > PMF_TAIL_EPSILON:
        k += 1
        p.append(p[-1] * lam / k)
        total += p[-1]
    return p

def outcome_probs(l1, l2):
    """双泊松下 (P胜, P平, P负)。"""
    p1 = poisson_pmf(l1)
    p2 = poisson_pmf(l2)
    w = d = 0.0
    p2_below = 0.0
    for i, p in enumerate(p1):
        if i:
            p2_below += p2[i - 1] if i - 1 < len(p2) else 0.0
        w += p * p2_below
        if i < len(p2):
            d += p * p2[i]
    return w, d, 1.0 - w - d

def solve_lambdas(we, total=TOTAL_GOALS):
    """解出 (λ1, λ2),使双泊松的期望积分等于 Elo 胜负期望。

    TOTAL_GOALS 是基础值。若极端 Elo 差在该固定总进球数下不可表达,则提高
    该场总进球期望至刚好可解,避免静默地把胜负期望钳制在边界上。
    """
    if not 0.0 < we < 1.0:
        raise ValueError("Win expectancy must be strictly between zero and one")

    # 一方 λ=0 时,最大(或最小)可达的期望积分为 1-0.5*exp(-total)
    # (或 0.5*exp(-total));不足时必须提高总进球期望才能保留 Elo 目标。
    min_total = -math.log(2.0 * min(we, 1.0 - we)) + TOTAL_GOALS_MARGIN
    total = max(total, min_total)
    lo, hi = -total, total
    for _ in range(60):
        g = (lo + hi) / 2
        l1, l2 = (total + g) / 2, (total - g) / 2
        w, d, _ = outcome_probs(l1, l2)
        if w + 0.5 * d < we:
            lo = g
        else:
            hi = g
    g = (lo + hi) / 2
    return (total + g) / 2, (total - g) / 2

_pair_cache = {}

def match_model(a, b, venue):
    """一场淘汰赛的完整解析模型(按对阵缓存)。"""
    key = (a, b, venue)
    if key in _pair_cache:
        return _pair_cache[key]
    country_a = a          # 球队代码即国家代码
    country_b = b
    ea = ELO[a] + (HOME_BONUS if country_a == venue else 0)
    eb = ELO[b] + (HOME_BONUS if country_b == venue else 0)
    d = ea - eb
    we = win_expectancy(d)
    l1, l2 = solve_lambdas(we)
    w90, d90, loss90 = outcome_probs(l1, l2)
    wet, det, _ = outcome_probs(l1 / 3.0, l2 / 3.0)      # 加时 30 分钟
    adv = w90 + d90 * (wet + det * 0.5)                   # 含点球 50/50
    p1 = poisson_pmf(l1)
    p2 = poisson_pmf(l2)
    scores = []
    for i in range(6):
        for j in range(6):
            scores.append({"s": f"{i}-{j}", "p": p1[i] * p2[j]})
    scores.sort(key=lambda x: -x["p"])
    res = {
        "a": a, "b": b, "venue": venue,
        "eloA": ea, "eloB": eb, "we": we,
        "lambdaA": l1, "lambdaB": l2,
        "pWin90": w90, "pDraw90": d90, "pLoss90": loss90,
        "pAdvance": adv,
        "topScores": scores[:5],
    }
    _pair_cache[key] = res
    return res

# ---------------------------------------------------------- Monte Carlo 模拟

def simulate_once():
    winners = {}
    losers = {}
    for m in ALL_MATCHES:
        mid = m["id"]
        a = resolve_team(m["a"], winners, losers)
        b = resolve_team(m["b"], winners, losers)
        r = RESULTS.get(mid)
        if r is not None:
            win = r["winner"]
        else:
            mm = match_model(a, b, m["venue"])
            win = a if random.random() < mm["pAdvance"] else b
        winners[mid] = win
        losers[mid] = b if win == a else a
    return winners

def run_simulation():
    counts = {code: {"QF": 0, "SF": 0, "F": 0, "C": 0} for code in TEAMS}
    final_pairs = {}
    for _ in range(N_SIMS):
        winners = simulate_once()
        for m in R16:
            counts[winners[m["id"]]]["QF"] += 1
        for m in QF:
            counts[winners[m["id"]]]["SF"] += 1
        for m in SF:
            counts[winners[m["id"]]]["F"] += 1
        counts[winners["F"]]["C"] += 1
        pair = tuple(sorted([winners["SF1"], winners["SF2"]]))
        final_pairs[pair] = final_pairs.get(pair, 0) + 1
    return counts, final_pairs

# ------------------------------------------------------------ 最可能路径

def modal_path():
    """已赛按真实结果,未赛每场取晋级概率更高的一方,推演完整赛果。"""
    winners = {}
    losers = {}
    path = []
    for m in ALL_MATCHES:
        mid = m["id"]
        a = resolve_team(m["a"], winners, losers)
        b = resolve_team(m["b"], winners, losers)
        r = RESULTS.get(mid)
        if r is not None:
            winners[mid] = r["winner"]
            losers[mid] = b if r["winner"] == a else a
            row = {
                "id": mid, "round": ROUND_OF[mid], "roundZh": ROUND_ZH[ROUND_OF[mid]],
                "date": m["date"], "city": m["city"],
                "a": a, "b": b, "winner": r["winner"],
                "played": True,
                "score": f'{r["score"][0]}-{r["score"][1]}',
                "note": r["note"],
            }
            if r.get("score90") is not None:
                row["score90"] = f'{r["score90"][0]}-{r["score90"][1]}'
            if r.get("scoreET") is not None:
                row["scoreET"] = f'{r["scoreET"][0]}-{r["scoreET"][1]}'
            if r.get("penaltyScore") is not None:
                row["penaltyScore"] = f'{r["penaltyScore"][0]}-{r["penaltyScore"][1]}'
            pred = PREDICTION_HISTORY.get(mid)
            if pred and pred.get("a") == a and pred.get("b") == b:
                row["prediction"] = pred
            path.append(row)
            continue
        mm = match_model(a, b, m["venue"])
        win = a if mm["pAdvance"] >= 0.5 else b
        winners[mid] = win
        losers[mid] = b if win == a else a
        top = mm["topScores"][0]
        s_i, s_j = map(int, top["s"].split("-"))
        path.append({
            "id": mid, "round": ROUND_OF[mid], "roundZh": ROUND_ZH[ROUND_OF[mid]],
            "date": m["date"], "city": m["city"],
            "a": a, "b": b, "winner": win,
            "played": False,
            "pAdvance": mm["pAdvance"] if win == a else 1 - mm["pAdvance"],
            "score": top["s"], "scoreP": top["p"],
            "note": "加时/点球" if s_i == s_j else "",
            "pWin90": mm["pWin90"], "pDraw90": mm["pDraw90"], "pLoss90": mm["pLoss90"],
            "topScores": mm["topScores"],
            "eloA": mm["eloA"], "eloB": mm["eloB"],
        })
    return path


def prediction_snapshot(m, a, b):
    """当前模型对一场已知对阵的赛前预测快照。"""
    mm = match_model(a, b, m["venue"])
    win = a if mm["pAdvance"] >= 0.5 else b
    top = mm["topScores"][0]
    s_i, s_j = map(int, top["s"].split("-"))
    return {
        "archivedDate": STATE["dataDate"],
        "a": a,
        "b": b,
        "winner": win,
        "pAdvance": mm["pAdvance"] if win == a else 1 - mm["pAdvance"],
        "score": top["s"],
        "scoreP": top["p"],
        "note": "加时/点球" if s_i == s_j else "",
        "pWin90": mm["pWin90"],
        "pDraw90": mm["pDraw90"],
        "pLoss90": mm["pLoss90"],
        "topScores": mm["topScores"],
        "eloA": mm["eloA"],
        "eloB": mm["eloB"],
    }


def archive_current_predictions():
    """冻结赛前预测。

    只保存已经由真实赛果确定参与方、但本场尚未开赛的比赛。这样后续赛果进来时,
    页面展示的是当时真正可见的对阵预测,而不是用预测路径推出来的假赛前记录。
    """
    changed = False
    winners = {}
    losers = {}
    for m in ALL_MATCHES:
        mid = m["id"]
        a = resolve_team(m["a"], winners, losers)
        b = resolve_team(m["b"], winners, losers)
        if a is None or b is None:
            continue
        r = RESULTS.get(mid)
        if r is not None:
            winners[mid] = r["winner"]
            losers[mid] = b if r["winner"] == a else a
            continue
        pred = PREDICTION_HISTORY.get(mid)
        if pred and pred.get("a") == a and pred.get("b") == b:
            continue
        PREDICTION_HISTORY[mid] = prediction_snapshot(m, a, b)
        changed = True
    return changed


def accuracy_summary(path):
    rows = []
    for p in path:
        if not p.get("played") or "prediction" not in p:
            continue
        pred = p["prediction"]
        actual_score = p["score"]
        actual_score90 = p.get("score90")
        score_evaluated = actual_score90 is not None
        row = {
            "id": p["id"],
            "round": p["round"],
            "roundZh": p["roundZh"],
            "date": p["date"],
            "city": p["city"],
            "a": p["a"],
            "b": p["b"],
            "prediction": pred,
            "actual": {
                "winner": p["winner"],
                "score": actual_score,
                "score90": actual_score90,
                "scoreET": p.get("scoreET"),
                "penaltyScore": p.get("penaltyScore"),
                "note": p["note"],
            },
            "winnerCorrect": pred["winner"] == p["winner"],
            "scoreEvaluated": score_evaluated,
            "scoreCorrect": score_evaluated and pred["score"] == actual_score90,
        }
        rows.append(row)

    total = len(rows)
    winner_correct = sum(1 for r in rows if r["winnerCorrect"])
    score_evaluated = sum(1 for r in rows if r["scoreEvaluated"])
    score_correct = sum(1 for r in rows if r["scoreCorrect"])
    return {
        "total": total,
        "winnerCorrect": winner_correct,
        "scoreEvaluated": score_evaluated,
        "scoreCorrect": score_correct,
        "winnerRate": winner_correct / total if total else None,
        "scoreRate": score_correct / score_evaluated if score_evaluated else None,
        "rows": rows,
    }

# ---------------------------------------------------------------- 主流程

def main():
    predictions_changed = archive_current_predictions()
    counts, final_pairs = run_simulation()
    path = modal_path()
    accuracy = accuracy_summary(path)

    alive = {p["a"] for p in path if not p["played"]} | {p["b"] for p in path if not p["played"]}
    alive |= {p["winner"] for p in path}

    champ_table = sorted(
        ({"code": c,
          "zh": TEAMS[c]["zh"],
          "en": TEAMS[c]["en"],
          "elo": ELO[c],
          "pQF": counts[c]["QF"] / N_SIMS,
          "pSF": counts[c]["SF"] / N_SIMS,
          "pF": counts[c]["F"] / N_SIMS,
          "pC": counts[c]["C"] / N_SIMS}
         for c in TEAMS if counts[c]["QF"] > 0 or counts[c]["C"] > 0),
        key=lambda x: (-x["pC"], -x["pF"], -x["pSF"]))

    pairs_table = sorted(
        ({"pair": [p[0], p[1]],
          "zh": f'{TEAMS[p[0]]["zh"]} vs {TEAMS[p[1]]["zh"]}',
          "p": n / N_SIMS}
         for p, n in final_pairs.items()),
        key=lambda x: -x["p"])[:8]

    data = {
        "dataDate": STATE["dataDate"],
        "lastChecked": STATE.get("lastChecked", STATE["dataDate"]),
        "nSims": N_SIMS,
        "teams": {c: {"zh": t["zh"], "en": t["en"], "elo": ELO[c], "flag": flag_emoji(c)}
                  for c, t in TEAMS.items()},
        "modalPath": path,
        "accuracy": accuracy,
        "champTable": champ_table,
        "finalPairs": pairs_table,
        "params": {"totalGoals": TOTAL_GOALS, "homeBonus": HOME_BONUS},
    }
    with open("data.js", "w", encoding="utf-8") as f:
        f.write("const DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write(";\n")

    if predictions_changed:
        with open("state.json", "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("predictionHistory updated")

    print("=== 夺冠概率 Top 10 ===")
    for row in champ_table[:10]:
        print(f'{row["zh"]:6s} Elo {row["elo"]}  冠军 {row["pC"]*100:5.1f}%  '
              f'决赛 {row["pF"]*100:5.1f}%  四强 {row["pSF"]*100:5.1f}%')
    print("\n=== 最可能路径(未赛部分) ===")
    for p in path:
        if p["played"]:
            continue
        note = f' ({p["note"]})' if p["note"] else ""
        print(f'{p["roundZh"]:3s} {p["date"]} {TEAMS[p["a"]]["zh"]} vs {TEAMS[p["b"]]["zh"]}: '
              f'{p["score"]}{note} → {TEAMS[p["winner"]]["zh"]} 晋级 (p={p["pAdvance"]:.2f})')
    print("\n=== 最可能决赛 ===")
    for row in pairs_table[:5]:
        print(f'{row["zh"]}: {row["p"]*100:.1f}%')
    if accuracy["total"]:
        print("\n=== 赛前预测回测 ===")
        score_rate = accuracy["scoreRate"] * 100 if accuracy["scoreRate"] is not None else 0
        print(f'晋级方命中 {accuracy["winnerCorrect"]}/{accuracy["total"]} '
              f'({accuracy["winnerRate"]*100:.1f}%), '
              f'90分钟比分命中 {accuracy["scoreCorrect"]}/{accuracy["scoreEvaluated"]} '
              f'({score_rate:.1f}%)')

if __name__ == "__main__":
    main()
