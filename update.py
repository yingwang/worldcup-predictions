#!/usr/bin/env python3
"""每日数据刷新:抓最新赛果与 Elo,写回 state.json。

数据源:
  1. 赛果: Wikipedia「2026 FIFA World Cup knockout stage」页面的 wikitext,
     解析 footballbox 模板(team1 / score / team2 / penaltyscore)。
  2. Elo: eloratings.net World.tsv。

只在状态真的变化(有新赛果或参赛队 Elo 更新)时改写 state.json 并更新
dataDate;没有变化则不落盘,配合 CI 里的「无 diff 不提交」实现
「有比赛才更新」。任何一路抓取或解析失败都保留旧状态,绝不写坏数据。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

from bracket import TEAMS, ALL_MATCHES, resolve_team

WIKI_API = ("https://en.wikipedia.org/w/api.php?action=parse"
            "&page=2026_FIFA_World_Cup_knockout_stage"
            "&prop=wikitext&formatversion=2&format=json")
ELO_TSV = "https://eloratings.net/World.tsv"
UA = {"User-Agent": "worldcup-predictions/1.0 (github.com; daily elo+results refresh)"}

# Wikipedia 使用 FIFA 三字码,映射到本仓库的 ISO 两字码
FIFA_TO_ISO = {
    "ARG": "AR", "ESP": "ES", "FRA": "FR", "ENG": "EN", "BRA": "BR",
    "COL": "CO", "POR": "PT", "MEX": "MX", "NOR": "NO", "SUI": "CH",
    "BEL": "BE", "CRO": "HR", "MAR": "MA", "AUT": "AT", "PAR": "PY",
    "AUS": "AU", "USA": "US", "ALG": "DZ", "CAN": "CA", "EGY": "EG",
    "CPV": "CV", "GHA": "GH", "NED": "NL", "GER": "DE", "JPN": "JP",
    "ECU": "EC", "SEN": "SN", "SWE": "SE", "CIV": "CI", "COD": "CD",
    "BIH": "BA", "RSA": "ZA",
}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# bracket 模板里每场比赛一行:
# |June 29 – [[Foxborough...]]|{{#invoke:flag|fb|GER}}|1 (3)|{{#invoke:flag|fb|PAR}} {{pso}}|1 (4)
# 括号数字是点球比分;{{aet}}/{{pso}} 标记加时或点球;未赛则比分为空
_LINE = re.compile(
    r"^\|[^|\n]+[–—-]\s*\[\[[^\]]+\]\]"
    r"\|\{\{#invoke:flag\|fb\|([A-Z]{3})\}\}(\s*\{\{(?:pso|aet)\}\})?"
    r"\|(\d+)(?:\s*\((\d+)\))?\s*"
    r"\|\{\{#invoke:flag\|fb\|([A-Z]{3})\}\}(\s*\{\{(?:pso|aet)\}\})?"
    r"\|(\d+)(?:\s*\((\d+)\))?\s*$",
    re.M)

def parse_wiki_results():
    """从 wikitext 的对阵树模板解析已完赛场次,返回 {frozenset(两队): 结果}。"""
    wikitext = json.loads(fetch(WIKI_API))["parse"]["wikitext"]
    by_pair = {}
    for m in _LINE.finditer(wikitext):
        t1, tag1, s1, p1, t2, tag2, s2, p2 = m.groups()
        a = FIFA_TO_ISO.get(t1)
        b = FIFA_TO_ISO.get(t2)
        if a is None or b is None:
            continue
        s1, s2 = int(s1), int(s2)
        aet = "aet" in ((tag1 or "") + (tag2 or ""))
        if s1 > s2:
            winner, note = a, ("加时" if aet else "")
        elif s2 > s1:
            winner, note = b, ("加时" if aet else "")
        elif p1 is not None and p2 is not None:
            pp1, pp2 = int(p1), int(p2)
            winner = a if pp1 > pp2 else b
            note = f"点球 {pp1}-{pp2}"
        else:
            continue                      # 平局但无点球信息,视为数据未完整
        by_pair[frozenset((a, b))] = {"a": a, "b": b, "score": [s1, s2],
                                      "note": note, "winner": winner}
    return by_pair


def map_results_to_bracket(by_pair, old_results):
    """沿对阵树推进,把按队伍对解析出的结果对应到比赛编号。

    从已知结果出发解析出下一轮对阵,再在解析结果里找同一对球队,循环
    直至不再有新增。以旧结果为起点保证解析失败时状态只增不减。
    """
    results = dict(old_results)
    changed = True
    while changed:
        changed = False
        winners = {mid: r["winner"] for mid, r in results.items()}
        losers = {}
        # ALL_MATCHES 本身是拓扑序:一趟循环里,前面比赛解析出的 losers
        # 已足够解析后面(季军赛)的参与方
        for m in ALL_MATCHES:
            mid = m["id"]
            a = resolve_team(m["a"], winners, losers)
            b = resolve_team(m["b"], winners, losers)
            if a is None or b is None:
                continue
            if mid in results:
                losers[mid] = b if results[mid]["winner"] == a else a
                continue
            hit = by_pair.get(frozenset((a, b)))
            if hit is None:
                continue
            # 统一为对阵树中的主客顺序
            score = hit["score"] if hit["a"] == a else [hit["score"][1], hit["score"][0]]
            note = hit["note"]
            if hit["a"] != a and note.startswith("点球"):
                p = note.split()[1].split("-")
                note = f"点球 {p[1]}-{p[0]}"
            results[mid] = {"score": score, "note": note, "winner": hit["winner"]}
            winners[mid] = hit["winner"]
            losers[mid] = b if hit["winner"] == a else a
            changed = True
    return results


def parse_elo(old_elo):
    tsv = fetch(ELO_TSV)
    new_elo = dict(old_elo)
    for line in tsv.splitlines():
        parts = line.split("\t")
        if len(parts) > 3 and parts[2] in new_elo:
            try:
                new_elo[parts[2]] = int(parts[3])
            except ValueError:
                pass
    return new_elo


def main():
    with open("state.json", encoding="utf-8") as f:
        state = json.load(f)

    changed = False

    try:
        by_pair = parse_wiki_results()
        new_results = map_results_to_bracket(by_pair, state["results"])
        if new_results != state["results"]:
            state["results"] = new_results
            changed = True
        print(f"results: parsed {len(by_pair)} finished matches, "
              f"mapped {len(new_results)} into bracket")
    except Exception as e:                              # 解析失败保留旧状态
        print(f"results: FAILED ({e}), keeping previous", file=sys.stderr)

    try:
        new_elo = parse_elo(state["elo"])
        if new_elo != state["elo"]:
            state["elo"] = new_elo
            changed = True
        print("elo: refreshed")
    except Exception as e:
        print(f"elo: FAILED ({e}), keeping previous", file=sys.stderr)

    if changed:
        state["dataDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open("state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("state.json updated")
    else:
        print("no changes")


if __name__ == "__main__":
    main()
