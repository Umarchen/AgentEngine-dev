---
name: web_calc_skill
description: 数值汇总技能。触发条件：需要对一组数字做 count/sum/avg/max/min 统计，或需要生成可复用的统计脚本输出。
version: 0.1.0
---

# web_calc_skill

这是一个符合 openjiuwen v0.1.7 Agent Skills 规范的示例 skill。

## 1) 触发与目标

在以下场景触发本 skill：

1. 用户提供数字列表并要求统计结果；
2. 需要将统计逻辑以脚本形式复用；
3. 需要参考统计口径说明或输出模板。

## 2) 执行步骤

1. 优先读取 `scripts/calc_summary.py`，调用其中 `summarize_numbers`；
2. 如需理解统计口径，读取 `references/stat_rules.md`；
3. 如需生成报告，参考 `assets/output_template.md` 组织输出。

## 3) 目录说明

- `scripts/`：可直接复用的脚本。
- `references/`：按需加载的参考资料。
- `assets/`：静态模板资产。

## 4) 输入输出

- 输入：数字列表，例如 `[1, 2, 3, 4]`
- 输出：`count/sum/avg/max/min`
