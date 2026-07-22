"""World Cup 预测模型纯函数的单元测试。

在仓库根目录运行:

    python3 -m pytest -q

覆盖三块:
  1. 数学核心 —— Elo 胜负期望、双泊松比分分布、由 Elo 反解进球期望;
  2. 对阵树与赛果解析 —— 参与方引用解析、Wikipedia 模板解析、比分翻转;
  3. 下界断言 —— 把「解析到的完赛场次少于已知值」这种静默失效变成响亮失败。

这些都是纯函数,不联网,便于回归保护。
"""

import math

import pytest

import bracket
import simulate
import update


# ------------------------------------------------------------ 数学核心

def test_win_expectancy_symmetry_and_monotonicity():
    assert simulate.win_expectancy(0) == pytest.approx(0.5)
    # 领先 d 与落后 d 的胜负期望相加恒为 1
    for d in (50, 200, 400, 800):
        assert simulate.win_expectancy(d) + simulate.win_expectancy(-d) == pytest.approx(1.0)
    # Elo 差越大,胜负期望越高
    vals = [simulate.win_expectancy(d) for d in range(-400, 401, 100)]
    assert all(b > a for a, b in zip(vals, vals[1:]))
    assert simulate.win_expectancy(2000) > 0.99


def test_poisson_pmf_is_a_distribution():
    for lam in (0.2, 1.3, 2.6):
        pmf = simulate.poisson_pmf(lam)
        assert pmf[0] == pytest.approx(math.exp(-lam))
        # 自适应截断后,遗漏尾部应可忽略
        assert sum(pmf) == pytest.approx(1.0, abs=simulate.PMF_TAIL_EPSILON * 2)
        assert all(p >= 0 for p in pmf)


def test_outcome_probs_normalized_and_symmetric():
    w, d, l = simulate.outcome_probs(1.6, 1.0)
    assert w + d + l == pytest.approx(1.0)
    assert w > l  # 进球期望更高的一方更可能取胜
    # 交换两队:胜负互换;平局保持不变。
    w2, d2, l2 = simulate.outcome_probs(1.0, 1.6)
    assert w2 == pytest.approx(l, abs=1e-10)
    assert l2 == pytest.approx(w, abs=1e-10)
    assert d2 == pytest.approx(d, abs=1e-10)
    # 势均力敌:胜负对称
    we, de, le = simulate.outcome_probs(1.3, 1.3)
    assert we == pytest.approx(le, abs=1e-4)


def test_solve_lambdas_matches_target_expectancy():
    total = simulate.TOTAL_GOALS
    for we in (0.40, 0.50, 0.60, 0.75):
        l1, l2 = simulate.solve_lambdas(we)
        # 约束一:两队进球期望之和等于固定总进球
        assert l1 + l2 == pytest.approx(total)
        # 约束二:双泊松积分期望 P胜 + 0.5*P平 命中目标 We
        w, d, _ = simulate.outcome_probs(l1, l2)
        assert w + 0.5 * d == pytest.approx(we, abs=1e-3)
    # We=0.5 时两队进球期望相等
    l1, l2 = simulate.solve_lambdas(0.5)
    assert l1 == pytest.approx(l2, abs=1e-6)
    # We 越大,己方进球期望越高
    assert simulate.solve_lambdas(0.70)[0] > simulate.solve_lambdas(0.55)[0]


def test_solve_lambdas_matches_extreme_elo_expectancy():
    for d in (-1200, -800, 537, 617, 800, 1200):
        we = simulate.win_expectancy(d)
        l1, l2 = simulate.solve_lambdas(we)
        w, draw, _ = simulate.outcome_probs(l1, l2)
        assert w + 0.5 * draw == pytest.approx(we, abs=1e-9)
        assert l1 + l2 >= simulate.TOTAL_GOALS


# --------------------------------------------------------- 对阵树解析

def test_resolve_team():
    # 直接给定球队代码,原样返回
    assert bracket.resolve_team("FR", {}, {}) == "FR"
    # 胜者引用:已知则返回,未知则 None
    assert bracket.resolve_team(("W", "R32_A"), {"R32_A": "ZA"}, {}) == "ZA"
    assert bracket.resolve_team(("W", "R32_A"), {}, {}) is None
    # 负者引用(季军赛用)
    assert bracket.resolve_team(("L", "SF1"), {}, {"SF1": "BR"}) == "BR"


# ------------------------------------------------- Wikipedia 结果解析

WIKITEXT_SAMPLE = """
some preamble
|July 4 – [[Houston, Texas|Houston]]|{{#invoke:flag|fb|MAR}}|3|{{#invoke:flag|fb|CAN}}|0
|July 4 – [[Philadelphia]]|{{#invoke:flag|fb|FRA}}|1|{{#invoke:flag|fb|PAR}}|0
|July 5 – [[East Rutherford, New Jersey|East Rutherford]]|{{#invoke:flag|fb|BRA}} {{aet}}|2|{{#invoke:flag|fb|NOR}}|1
|July 6 – [[Mexico City]]|{{#invoke:flag|fb|MEX}}|1 (2)|{{#invoke:flag|fb|ENG}} {{pso}}|1 (4)
trailing text
"""


def test_parse_wiki_text():
    by_pair = update.parse_wiki_text(WIKITEXT_SAMPLE)
    assert len(by_pair) == 4
    # 常规胜负
    reg = by_pair[frozenset(("MA", "CA"))]
    assert reg["winner"] == "MA" and reg["score"] == [3, 0] and reg["note"] == ""
    # 加时
    aet = by_pair[frozenset(("BR", "NO"))]
    assert aet["winner"] == "BR" and aet["note"] == "加时"
    # 点球:90 分钟 1-1,点球 2-4,英格兰胜
    pen = by_pair[frozenset(("MX", "EN"))]
    assert pen["winner"] == "EN" and pen["note"] == "点球 2-4"


def test_orient_result_flips_scores():
    hit = {"a": "FR", "b": "MA", "score": [2, 1], "score90": [2, 1],
           "note": "", "winner": "FR"}
    # 同序:去掉 a/b,其余不变
    same = update.orient_result(hit, "FR", "MA")
    assert "a" not in same and same["score"] == [2, 1] and same["winner"] == "FR"
    # 反序:比分翻转,胜者不变
    flipped = update.orient_result(hit, "MA", "FR")
    assert flipped["score"] == [1, 2] and flipped["score90"] == [1, 2]
    assert flipped["winner"] == "FR"
    # 点球备注与点球比分也要翻转
    pen = {"a": "MX", "b": "EN", "score": [1, 1], "note": "点球 2-4",
           "penaltyScore": [2, 4], "winner": "EN"}
    fp = update.orient_result(pen, "EN", "MX")
    assert fp["note"] == "点球 4-2" and fp["penaltyScore"] == [4, 2]


def test_map_results_propagates_corrected_winner_to_later_round():
    old_results = {
        "R32_A": {"score": [0, 1], "note": "", "winner": "ZA"},
        "R32_D": {"score": [1, 0], "note": "", "winner": "MA"},
    }
    by_pair = {
        frozenset(("ZA", "CA")): {"a": "ZA", "b": "CA", "score": [0, 1], "note": "", "winner": "CA"},
        frozenset(("NL", "MA")): {"a": "NL", "b": "MA", "score": [1, 0], "note": "", "winner": "MA"},
        frozenset(("CA", "MA")): {"a": "CA", "b": "MA", "score": [2, 0], "note": "", "winner": "CA"},
    }

    results = update.map_results_to_bracket(by_pair, old_results)

    assert results["R32_A"]["winner"] == "CA"
    assert results["R16_1"]["winner"] == "CA"


def _seed_results_through_qf():
    """构造一套打满 R32/R16/QF 的结果(每场都由 a 方获胜),返回 (results, QF 胜者)。"""
    results = {}
    winners = {}
    for m in bracket.R32 + bracket.R16 + bracket.QF:
        a = bracket.resolve_team(m["a"], winners, {})
        results[m["id"]] = {"score": [1, 0], "note": "", "winner": a}
        winners[m["id"]] = a
    return results, [winners[mid] for mid in ("QF1", "QF2", "QF3", "QF4")]


def test_semifinal_crossing_maps_sf_tp_and_final():
    # 2026 实际赛制:SF1 = QF1 胜者 × QF3 胜者,SF2 = QF2 胜者 × QF4 胜者。
    # 回归保护:此前 bracket 误写成 QF1×QF2 / QF3×QF4,导致真实半决赛
    # 挂不上对阵树、季军赛和决赛又被错挂到半决赛槽位上。
    results, (w1, w2, w3, w4) = _seed_results_through_qf()
    by_pair = {
        frozenset((w1, w3)): {"a": w1, "b": w3, "score": [0, 2], "note": "", "winner": w3},
        frozenset((w2, w4)): {"a": w2, "b": w4, "score": [1, 2], "note": "", "winner": w4},
        frozenset((w1, w2)): {"a": w1, "b": w2, "score": [4, 6], "note": "", "winner": w2},  # 季军赛
        frozenset((w3, w4)): {"a": w3, "b": w4, "score": [1, 0], "note": "加时", "winner": w3},  # 决赛
    }
    mapped = update.map_results_to_bracket(by_pair, results)
    assert mapped["SF1"]["winner"] == w3
    assert mapped["SF2"]["winner"] == w4
    assert mapped["TP"]["winner"] == w2
    assert mapped["F"]["winner"] == w3
    assert update.unmatched_pairs(by_pair, mapped) == set()


def test_unmatched_pairs_flags_results_that_do_not_fit_bracket():
    results, (w1, w2, w3, w4) = _seed_results_through_qf()
    # 一场真实半决赛 + 一对按错误交叉(QF1×QF2)虚构的对阵
    by_pair = {
        frozenset((w1, w3)): {"a": w1, "b": w3, "score": [0, 2], "note": "", "winner": w3},
        frozenset((w1, w2)): {"a": w1, "b": w2, "score": [2, 1], "note": "", "winner": w1},
    }
    mapped = update.map_results_to_bracket(by_pair, results)
    assert update.unmatched_pairs(by_pair, mapped) == {frozenset((w1, w2))}


# ---------------------------------------- 下界断言(防静默冻结)

def test_assert_result_count_guard():
    # 赛事尚未开打(已知 0 场):任何解析结果都不报警
    update.assert_result_count(0, 0)
    # 解析数 >= 已知数:正常
    update.assert_result_count(5, 3)
    update.assert_result_count(3, 3)
    # 解析数 < 已知数:解析器或数据源疑似回归,必须抛错
    with pytest.raises(update.ResultsParseError):
        update.assert_result_count(2, 5)
    with pytest.raises(update.ResultsParseError):
        update.assert_result_count(0, 8)
