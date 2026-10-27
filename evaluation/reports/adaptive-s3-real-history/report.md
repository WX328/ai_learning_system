# S3 自适应算法离线回放报告

真实历史：观察性描述，不能推断学习收益

评估版本：`adaptive_eval_v1`；生产算法：`rules_v2`。
数据 SHA256：`7340e20d369ceee2482502c38be6b3fd7f1dd37e497933570d613423c191170e`。

## 样本量与时间口径

```json
{
  "input_events": 10,
  "first_answers": 10,
  "review_events": 0,
  "learners": 2,
  "observed_topics": 5,
  "catalog_topics": 5,
  "ignored": {}
}
```

所有算法使用相同历史；先冻结当前时间戳的全部决策，再纳入该时间的答案和复习。首次重复提交只取最早记录。
预测目标为当前新题首次正误；至少已有三道不同题目才纳入，冷启动不填 0 或 50%。
知识点排序以之后窗口内实际首次表现作代理标签；结果不反馈算法，且不能证明推荐的因果收益。

## 共同样本上的比较

| 算法 | score-proxy Brier ↓ | AUC ↑ | 排序一致性 ↑ | 趋势方向响应 |
| --- | --- | --- | --- | --- |
| raw_accuracy_v1 | 不可评估 (n=2, learners=1; requires n>=20 and learners>=2) | 不可评估 (n=2, learners=1; requires both correct and incorrect outcomes) | 不可评估 (n=0, learners=0; requires n>=20 and learners>=2) | 不可评估 (n=0, learners=0; requires n>=20 and learners>=2) |
| recent5_accuracy_v1 | 不可评估 (n=2, learners=1; requires n>=20 and learners>=2) | 不可评估 (n=2, learners=1; requires both correct and incorrect outcomes) | 不可评估 (n=0, learners=0; requires n>=20 and learners>=2) | 不可评估 (n=0, learners=0; requires n>=20 and learners>=2) |
| rules_v2 | 不可评估 (n=2, learners=1; requires n>=20 and learners>=2) | 不可评估 (n=2, learners=1; requires both correct and incorrect outcomes) | 不可评估 (n=0, learners=0; requires n>=20 and learners>=2) | 不可评估 (n=0, learners=0; requires n>=20 and learners>=2) |

S2 分数不是校准概率；Brier 仅把分数/100 当作未校准预测代理，不称为能力概率或预测准确率。AUC 还要求正负两类结果。
不足预设样本数或学习者数的指标为 null/不可评估；描述值没有独立样本显著性保证。

## 少样本稳定性与难度动作

| 算法 | 前四题极端分占比 / n | 分数平均绝对跳变 / 对数 | 少于三题升档 / 决策数 | 升档 / 降档 / 总决策 |
| --- | --- | --- | --- | --- |
| raw_accuracy_v1 | 0.500 / 8 | 25.000 / 3 | 1 / 2 | 1 / 0 / 10 |
| recent5_accuracy_v1 | 0.500 / 8 | 25.000 / 3 | 1 / 2 | 1 / 0 / 10 |
| rules_v2 | 0.000 / 8 | 12.000 / 3 | 0 / 2 | 0 / 0 / 10 |

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

## 导出覆盖率

```json
{
  "read_rows": {
    "first": 51,
    "review": 5
  },
  "exported_events": 10,
  "skipped": {
    "missing_topic_or_invalid_ownership_or_link": 46
  }
}
```
缺少知识点关联的答题无法参与知识点评估；历史目录采用首次观察时间，无法复原当时未练知识点及待答题状态。
