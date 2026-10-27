# S3 自适应算法离线回放报告

模拟数据：仅验证规则行为

评估版本：`adaptive_eval_v1`；生产算法：`rules_v2`。
数据 SHA256：`9a4aae1808dd88015cd55341488b2163fb94b5ce44703dda359076f19c2901da`。

## 样本量与时间口径

```json
{
  "input_events": 512,
  "first_answers": 480,
  "review_events": 32,
  "learners": 8,
  "observed_topics": 24,
  "catalog_topics": 24,
  "ignored": {}
}
```

所有算法使用相同历史；先冻结当前时间戳的全部决策，再纳入该时间的答案和复习。首次重复提交只取最早记录。
预测目标为当前新题首次正误；至少已有三道不同题目才纳入，冷启动不填 0 或 50%。
知识点排序以之后窗口内实际首次表现作代理标签；结果不反馈算法，且不能证明推荐的因果收益。

## 共同样本上的比较

| 算法 | score-proxy Brier ↓ | AUC ↑ | 排序一致性 ↑ | 趋势方向响应 |
| --- | --- | --- | --- | --- |
| raw_accuracy_v1 | 0.3097 (n=408, learners=8) | 0.3611 (n=408, learners=8) | 0.2914 (n=1208, learners=8) | 1.0000 (n=32, learners=8) |
| recent5_accuracy_v1 | 0.2568 (n=408, learners=8) | 0.6512 (n=408, learners=8) | 0.4570 (n=1208, learners=8) | 1.0000 (n=32, learners=8) |
| rules_v2 | 0.2730 (n=408, learners=8) | 0.5219 (n=408, learners=8) | 0.3833 (n=1208, learners=8) | 1.0000 (n=32, learners=8) |

S2 分数不是校准概率；Brier 仅把分数/100 当作未校准预测代理，不称为能力概率或预测准确率。AUC 还要求正负两类结果。
不足预设样本数或学习者数的指标为 null/不可评估；描述值没有独立样本显著性保证。

## 少样本稳定性与难度动作

| 算法 | 前四题极端分占比 / n | 分数平均绝对跳变 / 对数 | 少于三题升档 / 决策数 | 升档 / 降档 / 总决策 |
| --- | --- | --- | --- | --- |
| raw_accuracy_v1 | 0.750 / 96 | 9.259 / 72 | 21 / 48 | 49 / 108 / 480 |
| recent5_accuracy_v1 | 0.750 / 96 | 9.259 / 72 | 21 / 48 | 112 / 114 / 480 |
| rules_v2 | 0.000 / 96 | 7.722 / 72 | 0 / 48 | 91 / 114 / 480 |

稳定性是分数的描述性性质，不是越平滑越能促进学习；难度动作没有已验证的最优标签。
趋势用相邻、不重叠的五题块正确率变化≥20个百分点作规则响应标签，并非真实能力变化。

## 评估配置

```json
{
  "min_predictions": 20,
  "min_learners": 2,
  "min_history": 3,
  "ranking_horizon": 10,
  "min_future_per_topic": 2,
  "same_timestamp": "all decisions before all outcomes"
}
```

## 解释边界

- Fixed logged actions: counterfactual learning gains are not identifiable.
- rules_v2 score/100 is an uncalibrated score proxy, not an estimated ability probability.
- Overlapping checkpoints and answers within a learner are correlated.
- Future failure rates are observed proxies affected by item difficulty and selection.
- No historical pending-question/recommendation logs; evaluate fresh decisions only.
- Synthetic results validate rules only; real_history is observational, not a randomized trial.
