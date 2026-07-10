# 🏆 2026 世界杯淘汰赛量化预测 / World Cup 2026 Knockout Predictions

一个纯量化的世界杯淘汰赛预测站：以 Elo 等级分为唯一强度输入，双泊松模型出比分分布，
Monte Carlo 模拟出晋级与夺冠概率。淘汰赛到决赛期间由 GitHub Actions 每天 6 次自动抓取最新赛果，
有新比赛完赛就重算并重新发布。网站会保存赛前预测快照，赛后展示预测比分、
实际比分以及晋级方和比分命中率。预测比分按 90 分钟含补时计算，赛后回测也优先用
ESPN linescores 拆出的 90 分钟比分，避免加时赛和点球把比分口径混在一起。

在线页面 / Live site: https://yingwang.github.io/worldcup-predictions/

网站支持中文和英文切换，并在所有球队名称前显示国旗。

The site supports Chinese and English, with flags shown next to every team.

## 中文说明

### 方法

模型的输入只有两类：各队在 [eloratings.net](https://eloratings.net) 的
World Football Elo Ratings，以及截至数据日期的真实赛果与对阵表
（来自 Wikipedia 的淘汰赛页面，并用 ESPN soccer API 的 linescores 补充 90 分钟、
加时和点球拆分）。不使用任何媒体预测、伤停消息或人工调整。

单场比赛由 Elo 差 d 给出胜负期望 We = 1/(1+10^(−d/400))，在本国境内比赛的球队
加 100 Elo 主场分，这与 eloratings.net 的惯例一致。比分层面以 90 分钟两队合计
进球期望 2.6 为基础，用二分法解出双方进球率 λ₁ 与 λ₂，使双泊松比分分布给出的期望积分
恰好等于 We。若极端 Elo 差无法由该总进球数表达，模型仅对该场提高总进球期望至可解的最小值。
比分分布因此始终与 Elo 一致，模型中没有额外的自由参数。

淘汰赛推进规则：90 分钟战平进入加时，加时进球率取常规时间的三分之一；仍平则点球，
按五五开处理，这是有意的保守选择。从当前真实对阵状态出发，对剩余赛程做十万次
Monte Carlo 模拟，统计各队进八强、四强、决赛与夺冠的概率；每场确定对阵的比分分布
则用双泊松网格解析计算，不依赖抽样。

### 文件

| 文件 | 作用 |
| --- | --- |
| `bracket.py` | 对阵树与球队表，包含静态赛制事实 |
| `state.json` | 当前状态：各队 Elo 与已赛结果，由 `update.py` 维护 |
| `update.py` | 赛期刷新：解析 Wikipedia 赛果、ESPN 90 分钟比分与 eloratings.net Elo |
| `simulate.py` | 模型本体：解析比分分布 + Monte Carlo，保存赛前预测快照并生成 `data.js` |
| `index.html` + `data.js` | 静态页面，支持中英文、球队旗帜与预测准确率展示 |
| `.github/workflows/update.yml` | 淘汰赛到决赛期间每天 6 次自动更新，无新赛果不提交 |

本地重跑：

```bash
python3 update.py     # 刷新 state.json，可跳过，直接用现有快照
python3 simulate.py   # 重算并生成 data.js
```

### 免责声明

本项目仅供娱乐与方法演示，预测不构成任何形式的保证，也不建议据此参与任何博彩活动。

## English

### Method

This is a purely quantitative World Cup knockout prediction site. The only strength input is each
team's [eloratings.net](https://eloratings.net) World Football Elo Rating. Match score distributions
come from a double-Poisson model, and advancement/title probabilities come from Monte Carlo simulation.
The site refreshes six times per day through GitHub Actions during the knockout run through the final,
and republishes when completed matches change the state.
It also stores pre-match prediction snapshots and compares them with actual scores after matches finish.
Predicted scores are 90-minute scores including stoppage time; post-match score accuracy is evaluated
against 90-minute scores enriched from ESPN linescores when available, so extra time and penalties do
not blur the score definition.

The model uses only two inputs: Elo ratings and the real bracket/results as of the data date, parsed from
the Wikipedia knockout-stage page and enriched with ESPN soccer API linescores for 90-minute, extra-time,
and penalty splits. It does not use media forecasts, injuries, squad news, or manual adjustments.

For a single match, Elo difference d gives win expectancy We = 1/(1+10^(−d/400)). A team playing inside
its own country receives a 100-point Elo home bonus, matching the convention used by eloratings.net.
The model uses 2.6 total expected 90-minute goals as its baseline, then solves λ₁ and λ₂ by bisection
so the double-Poisson grid has the same expected result as Elo. If an extreme Elo gap cannot be
represented at that total, it raises the total for that match only to the minimum solvable value. The
score distribution is therefore tied directly to Elo and has no additional fitted strength parameter.

A 90-minute draw goes to extra time, with extra-time scoring rates set to one third of normal time.
If still level, penalties are treated as 50/50. Starting from the current real bracket, the model runs
100,000 Monte Carlo simulations of the remaining tournament and reports quarterfinal, semifinal, final,
and title probabilities. Individual score grids are computed analytically, not sampled.

### Files

| File | Purpose |
| --- | --- |
| `bracket.py` | Static bracket and team table |
| `state.json` | Current state: Elo ratings, completed results, and archived pre-match predictions |
| `update.py` | Tournament refresh: parses Wikipedia results, ESPN 90-minute scores, and eloratings.net Elo |
| `simulate.py` | Model core: score grids + Monte Carlo, archives pre-match predictions and writes `data.js` |
| `index.html` + `data.js` | Static GitHub Pages site, bilingual with team flags and prediction accuracy |
| `.github/workflows/update.yml` | Six scheduled refreshes per day through the final; commits only when data changes |

Run locally:

```bash
python3 update.py     # refresh state.json, optional if using the checked-in snapshot
python3 simulate.py   # recompute predictions and write data.js
```

### Disclaimer

This project is for entertainment and method demonstration only. It is not a guarantee and should not
be used for betting.

## Teams / 球队

| Flag | Code | English | 中文 |
| --- | --- | --- | --- |
| 🇦🇷 | AR | Argentina | 阿根廷 |
| 🇪🇸 | ES | Spain | 西班牙 |
| 🇫🇷 | FR | France | 法国 |
| 🏴󠁧󠁢󠁥󠁮󠁧󠁿 | EN | England | 英格兰 |
| 🇧🇷 | BR | Brazil | 巴西 |
| 🇨🇴 | CO | Colombia | 哥伦比亚 |
| 🇵🇹 | PT | Portugal | 葡萄牙 |
| 🇲🇽 | MX | Mexico | 墨西哥 |
| 🇳🇴 | NO | Norway | 挪威 |
| 🇨🇭 | CH | Switzerland | 瑞士 |
| 🇧🇪 | BE | Belgium | 比利时 |
| 🇭🇷 | HR | Croatia | 克罗地亚 |
| 🇲🇦 | MA | Morocco | 摩洛哥 |
| 🇦🇹 | AT | Austria | 奥地利 |
| 🇵🇾 | PY | Paraguay | 巴拉圭 |
| 🇦🇺 | AU | Australia | 澳大利亚 |
| 🇺🇸 | US | United States | 美国 |
| 🇩🇿 | DZ | Algeria | 阿尔及利亚 |
| 🇨🇦 | CA | Canada | 加拿大 |
| 🇪🇬 | EG | Egypt | 埃及 |
| 🇨🇻 | CV | Cape Verde | 佛得角 |
| 🇬🇭 | GH | Ghana | 加纳 |
| 🇳🇱 | NL | Netherlands | 荷兰 |
| 🇩🇪 | DE | Germany | 德国 |
| 🇯🇵 | JP | Japan | 日本 |
| 🇪🇨 | EC | Ecuador | 厄瓜多尔 |
| 🇸🇳 | SN | Senegal | 塞内加尔 |
| 🇸🇪 | SE | Sweden | 瑞典 |
| 🇨🇮 | CI | Ivory Coast | 科特迪瓦 |
| 🇨🇩 | CD | DR Congo | 刚果民主共和国 |
| 🇧🇦 | BA | Bosnia and Herzegovina | 波黑 |
| 🇿🇦 | ZA | South Africa | 南非 |

## 测试 / Tests

数学核心与解析逻辑有单元测试(纯标准库 + pytest),覆盖 Elo 到双泊松的反解、
比分翻转、Wikipedia 模板解析,以及一条「解析到的完赛场次少于已知值就报错」的
下界断言 —— 用来把 Wikipedia 模板变更导致的静默失效变成一次响亮的失败,而不是
悄悄冻结在旧数据上。

```bash
python3 -m pytest -q
```

每次推送到 `main` 时 `.github/workflows/tests.yml` 会自动跑这些测试。

The math core and parsing logic are covered by unit tests (standard library +
pytest): the Elo-to-double-Poisson inversion, score orientation, Wikipedia
template parsing, and a lower-bound guard that fails loudly when the number of
parsed finished matches drops below what is already known. Tests run on every
push via `.github/workflows/tests.yml`.

## License / 授权

代码使用 MIT 许可证,见 [LICENSE](LICENSE)。

The source code is released under the MIT License; see [LICENSE](LICENSE).
