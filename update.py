#!/usr/bin/env python3
"""赛期数据刷新:抓最新赛果与 Elo,写回 state.json。

数据源:
  1. 赛果基础: Wikipedia「2026 FIFA World Cup knockout stage」页面的 wikitext,
     解析 footballbox 模板(team1 / score / team2 / penaltyscore)。
  2. 90 分钟比分补充: ESPN soccer API 的 linescores,用于区分常规时间、
     加时和点球。
  3. Elo: eloratings.net World.tsv。

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
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={date}"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={event_id}"
UA = {"User-Agent": "worldcup-predictions/1.0 (github.com; tournament elo+results refresh)"}

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
ESPN_TO_ISO = FIFA_TO_ISO | {
    "ESP": "ES",
    "ENG": "EN",
    "GER": "DE",
    "NED": "NL",
    "SUI": "CH",
}


class ResultsParseError(Exception):
    """抓取成功、但解析出的完赛场次数少于已知值 —— 基本可以断定是解析器或数据源
    回归(例如 Wikipedia 模板变了、正则匹配到 0 场),而不是「暂时还没有新赛果」。
    用它把这种静默失效变成一次响亮的失败,而不是悄悄冻结在旧状态上。"""


def assert_result_count(parsed_count, known_count):
    """下界断言:完赛场次只会累积,绝不会变少。

    一次成功的抓取所解析出的完赛场次,不应少于 state.json 里已经记录的数目;
    每一场已知的完赛,数据源理应仍然报告为已完赛。如果反而更少,几乎等同于
    解析静默失效,应当抛错、保留旧状态,并让 CI 响亮地失败。

    权衡:极少数情况下(某场原本只由 ESPN 提供、随后 ESPN 临时失败而 Wikipedia
    尚未更新)可能误报一次,但这类抖动会在下一次运行自愈,远好过无限静默冻结。
    """
    if known_count > 0 and parsed_count < known_count:
        raise ResultsParseError(
            f"解析到 {parsed_count} 场完赛,但 state 里已有 {known_count} 场;"
            "Wikipedia/ESPN 解析很可能已失效")


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

def parse_wiki_text(wikitext):
    """从 wikitext 的对阵树模板解析已完赛场次,返回 {frozenset(两队): 结果}。

    纯函数(不联网),便于单元测试与离线校验解析逻辑。
    """
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


def parse_wiki_results():
    """抓取 Wikipedia 淘汰赛页面并解析其中的已完赛场次。"""
    wikitext = json.loads(fetch(WIKI_API))["parse"]["wikitext"]
    return parse_wiki_text(wikitext)


def int_score(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_linescore_score(competitor, periods):
    lines = competitor.get("linescores") or []
    if len(lines) < periods:
        return None
    scores = []
    for line in lines[:periods]:
        v = int_score(line.get("value", line.get("displayValue")))
        if v is None:
            return None
        scores.append(v)
    return sum(scores)


def parse_espn_summary(event_id):
    data = json.loads(fetch(ESPN_SUMMARY.format(event_id=event_id)))
    comp = data.get("header", {}).get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    if len(competitors) != 2:
        return None

    teams = []
    for c in competitors:
        abbr = c.get("team", {}).get("abbreviation", "")
        code = ESPN_TO_ISO.get(abbr)
        final_score = int_score(c.get("score"))
        if code is None or final_score is None:
            return None
        teams.append({
            "code": code,
            "winner": bool(c.get("winner")),
            "scoreFinal": final_score,
            "score90": parse_linescore_score(c, 2),
            "scoreET": parse_linescore_score(c, 4),
            "penalty": int_score(c.get("shootoutScore")),
        })

    a, b = teams
    status_name = comp.get("status", {}).get("type", {}).get("name", "")
    penalty_score = None
    note = ""
    if "PEN" in status_name and a["penalty"] is not None and b["penalty"] is not None:
        penalty_score = [a["penalty"], b["penalty"]]
        note = f"点球 {a['penalty']}-{b['penalty']}"
    elif "AET" in status_name:
        note = "加时"

    winner = a["code"] if a["winner"] else b["code"] if b["winner"] else None
    if winner is None:
        if a["scoreFinal"] > b["scoreFinal"]:
            winner = a["code"]
        elif b["scoreFinal"] > a["scoreFinal"]:
            winner = b["code"]
        elif penalty_score:
            winner = a["code"] if penalty_score[0] > penalty_score[1] else b["code"]
        else:
            return None

    result = {
        "a": a["code"],
        "b": b["code"],
        "score": [a["scoreFinal"], b["scoreFinal"]],
        "score90": [a["score90"], b["score90"]] if a["score90"] is not None and b["score90"] is not None else None,
        "note": note,
        "winner": winner,
    }
    if a["scoreET"] is not None and b["scoreET"] is not None:
        result["scoreET"] = [a["scoreET"], b["scoreET"]]
    if penalty_score:
        result["penaltyScore"] = penalty_score
    return result


def parse_espn_results():
    by_pair = {}
    dates = sorted({"2026" + m["date"].replace("-", "") for m in ALL_MATCHES})
    for date in dates:
        data = json.loads(fetch(ESPN_SCOREBOARD.format(date=date)))
        for event in data.get("events", []):
            status = event.get("status", {}).get("type", {})
            if not status.get("completed"):
                continue
            result = parse_espn_summary(event["id"])
            if result is None:
                continue
            by_pair[frozenset((result["a"], result["b"]))] = result
    return by_pair


def merge_result_sources(wiki_results, espn_results):
    merged = dict(wiki_results)
    for pair, espn in espn_results.items():
        if pair in merged:
            old = merged[pair]
            merged[pair] = {**old, **{k: v for k, v in espn.items() if v is not None}}
        else:
            merged[pair] = espn
    return merged


def orient_result(hit, a, b):
    """把来源结果转成对阵树中的 a/b 顺序。"""
    if hit["a"] == a and hit["b"] == b:
        return {k: v for k, v in hit.items() if k not in {"a", "b"}}
    flipped = {}
    for k, v in hit.items():
        if k in {"a", "b"}:
            continue
        if k in {"score", "score90", "scoreET", "penaltyScore"} and isinstance(v, list) and len(v) == 2:
            flipped[k] = [v[1], v[0]]
        elif k == "note" and isinstance(v, str) and v.startswith("点球 "):
            p = v.split()[1].split("-")
            flipped[k] = f"点球 {p[1]}-{p[0]}"
        else:
            flipped[k] = v
    return flipped


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
            hit = by_pair.get(frozenset((a, b)))
            if mid in results:
                if hit is not None:
                    oriented = orient_result(hit, a, b)
                    if {**results[mid], **oriented} != results[mid]:
                        results[mid] = {**results[mid], **oriented}
                losers[mid] = b if results[mid]["winner"] == a else a
                continue
            if hit is None:
                continue
            results[mid] = orient_result(hit, a, b)
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

    data_changed = False
    results_checked = False
    elo_checked = False

    results_parser_broken = False
    try:
        wiki_results = parse_wiki_results()
        try:
            espn_results = parse_espn_results()
            by_pair = merge_result_sources(wiki_results, espn_results)
            print(f"espn: enriched {len(espn_results)} finished matches")
        except Exception as e:
            by_pair = wiki_results
            print(f"espn: FAILED ({e}), using Wikipedia only", file=sys.stderr)
        # 下界断言:抓取成功却比已知完赛数还少 -> 解析器回归,响亮失败而非静默冻结
        assert_result_count(len(by_pair), len(state["results"]))
        new_results = map_results_to_bracket(by_pair, state["results"])
        if new_results != state["results"]:
            state["results"] = new_results
            data_changed = True
        results_checked = True
        print(f"results: parsed {len(by_pair)} finished matches, "
              f"mapped {len(new_results)} into bracket")
    except ResultsParseError as e:
        print(f"results: PARSER REGRESSION ({e});保留旧状态并以非零码退出",
              file=sys.stderr)
        results_parser_broken = True
    except Exception as e:                              # 网络/临时失败:保留旧状态,不误报
        print(f"results: FAILED ({e}), keeping previous", file=sys.stderr)

    try:
        new_elo = parse_elo(state["elo"])
        if new_elo != state["elo"]:
            state["elo"] = new_elo
            data_changed = True
        elo_checked = True
        print("elo: refreshed")
    except Exception as e:
        print(f"elo: FAILED ({e}), keeping previous", file=sys.stderr)

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state_changed = data_changed
    if results_checked and elo_checked and state.get("lastChecked") != checked_at:
        state["lastChecked"] = checked_at
        state_changed = True

    if data_changed:
        state["dataDate"] = checked_at

    if state_changed:
        with open("state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("state.json updated")
    else:
        print("no changes")

    if results_parser_broken:
        # 解析器回归:上面已保留旧状态,这里以非零码退出让 workflow 变红并通知
        sys.exit(1)


if __name__ == "__main__":
    main()
