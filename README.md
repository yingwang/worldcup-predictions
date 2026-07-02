# 2026 世界杯淘汰赛量化预测

一个纯量化的世界杯淘汰赛预测站:以 Elo 等级分为唯一强度输入,双泊松模型出比分分布,
Monte Carlo 模拟出晋级与夺冠概率。每天由 GitHub Actions 自动抓取最新赛果,
有新比赛完赛就重算并重新发布。

在线页面: https://yingwang.github.io/worldcup-predictions/

## 方法

模型的输入只有两类:各队在 [eloratings.net](https://eloratings.net) 的
World Football Elo Ratings,以及截至数据日期的真实赛果与对阵表
(来自 Wikipedia 的淘汰赛页面)。不使用任何媒体预测、伤停消息或人工调整。

单场比赛由 Elo 差 d 给出胜负期望 We = 1/(1+10^(−d/400)),在本国境内比赛的球队
加 100 Elo 主场分,这与 eloratings.net 的惯例一致。比分层面固定 90 分钟两队合计
进球期望为 2.6,用二分法解出双方进球率 λ₁ 与 λ₂,使双泊松比分分布给出的期望积分
恰好等于 We。比分分布因此与 Elo 完全自洽,模型中没有额外的自由参数。

淘汰赛推进规则:90 分钟战平进入加时,加时进球率取常规时间的三分之一;仍平则点球,
按五五开处理(点球结果在统计上接近随机,这是有意的保守选择)。从当前真实对阵状态
出发,对剩余赛程做十万次 Monte Carlo 模拟,统计各队进八强、四强、决赛与夺冠的
概率;每场确定对阵的比分分布则用双泊松网格解析计算,不依赖抽样。

## 文件

| 文件 | 作用 |
| --- | --- |
| `bracket.py` | 对阵树与球队表(静态赛制事实) |
| `state.json` | 当前状态:各队 Elo 与已赛结果,由 `update.py` 维护 |
| `update.py` | 每日刷新:解析 Wikipedia 赛果与 eloratings.net Elo |
| `simulate.py` | 模型本体:解析比分分布 + Monte Carlo,生成 `data.js` |
| `index.html` + `data.js` | 静态页面(GitHub Pages) |
| `.github/workflows/update.yml` | 每日 07:17 UTC 自动更新,无新赛果不提交 |

本地重跑:

```bash
python3 update.py     # 刷新 state.json(可跳过,用现有快照)
python3 simulate.py   # 重算并生成 data.js
```

## 免责声明

本项目仅供娱乐与方法演示,预测不构成任何形式的保证,也不建议据此参与任何博彩活动。
