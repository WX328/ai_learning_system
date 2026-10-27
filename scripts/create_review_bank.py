"""Create actual AI-authored DRAFT questions. Not a validated real-study bank."""
import argparse
import json
from pathlib import Path
from evaluation.experiment_bank import SCHEMA, prepare_bank, review_packet


def draft_bank():
    # These are proposed content, not approved items or observed participant data.
    rows = [
      # pool, topic, difficulty, family, stem, four choices, answer, explanation
      ("A", "lists", 2, "length_after_pop", "执行 x=[2,4,6]; x.pop() 后，len(x) 是多少？", ["2", "3", "6", "0"], "A", "pop() 删除末项，列表剩下两项。"),
      ("A", "lists", 3, "slice_independent_container", "执行 x=[1,2]; y=x[:]; y.append(3) 后，x 是什么？", ["[1,2,3]", "[1,2]", "[3]", "报错"], "B", "切片创建新的外层列表，向 y 追加元素不改变 x。"),
      ("B", "lists", 2, "nested_index", "x=[[4,5],[6,7]]，x[1][0] 的值是什么？", ["4", "5", "6", "7"], "C", "先取第二项 [6,7]，再取其第一项 6。"),
      ("B", "lists", 3, "extend_versus_append", "执行 x=[1]; x.extend([2,3]) 后，x 是什么？", ["[1,[2,3]]", "[[1],2,3]", "[2,3]", "[1,2,3]"], "D", "extend 逐项追加可迭代对象中的元素。"),
      ("A", "dicts", 2, "get_default", "d={'a':2}，d.get('b',0) 的结果是什么？", ["0", "2", "None", "KeyError"], "A", "get 对缺失键返回指定默认值，不插入键。"),
      ("A", "dicts", 3, "dict_keys_membership", "d={'a':2,'b':3}，表达式 2 in d 的结果是什么？", ["True", "False", "2", "TypeError"], "B", "in 对字典检查键；2 是值而不是键。"),
      ("B", "dicts", 2, "existing_key_replacement", "执行 d={'x':1,'y':2}; d['x']=9 后，len(d) 是多少？", ["1", "3", "2", "9"], "C", "已有键赋值覆盖值，不增加键数。"),
      ("B", "dicts", 3, "pop_return", "执行 d={'x':4,'y':8}; v=d.pop('x') 后，(v,len(d)) 是什么？", ["(None,1)", "(4,2)", "(8,1)", "(4,1)"], "D", "pop 返回被删除键的值，字典剩一个键。"),
      ("learning", "lists", 1, "list_literal", "哪个表达式创建含两个整数的列表？", ["[1,2]", "(1,2)", "{1,2}", "'1,2'"], "A", "方括号创建列表，其他分别是元组、集合和字符串。"),
      ("learning", "lists", 1, "list_zero_index", "列表的第一个有效非负索引是什么？", ["1", "0", "-1", "len(x)"], "B", "Python 序列使用从零开始的非负索引。"),
      ("learning", "lists", 2, "delete_index", "执行 x=['a','b','c']; del x[1] 后，x 是什么？", ["['b','c']", "['a','b']", "['a','c']", "[]"], "C", "索引 1 对应 'b'，删除后剩 'a' 和 'c'。"),
      ("learning", "lists", 2, "negative_index", "x=[10,20,30]，x[-1] 是什么？", ["10", "20", "-1", "30"], "D", "负索引 -1 表示最后一项。"),
      ("learning", "lists", 3, "reverse_slice", "x=[0,1,2]，x[::-1] 是什么？", ["[2,1,0]", "[0,1,2]", "[0,2]", "[]"], "A", "步长 -1 使切片按反向顺序取元素。"),
      ("learning", "lists", 3, "slice_stop_exclusive", "x=[0,1,2,3,4]，x[1:4] 是什么？", ["[1,2,3,4]", "[1,2,3]", "[0,1,2,3]", "[4]"], "B", "切片包含起点索引 1，不含终点索引 4。"),
      ("learning", "lists", 4, "list_alias", "执行 x=[1]; y=x; y[0]=7 后，x[0] 是多少？", ["1", "0", "7", "报错"], "C", "赋值没有复制列表；两个变量引用同一对象。"),
      ("learning", "lists", 4, "sort_returns_none", "执行 x=[3,1]; y=x.sort() 后，y 是什么？", ["[1,3]", "[3,1]", "True", "None"], "D", "sort 原地排序并返回 None。"),
      ("learning", "lists", 5, "nested_shallow_copy", "执行 x=[[1]]; y=x.copy(); y[0].append(2) 后，x 是什么？", ["[[1,2]]", "[[1]]", "[1,2]", "[[2]]"], "A", "浅复制只复制外层；内层列表仍被共享。"),
      ("learning", "lists", 5, "repeated_inner_alias", "执行 x=[[]]*2; x[0].append(9) 后，x 是什么？", ["[[9],[]]", "[[9],[9]]", "[[],[9]]", "[[9]]"], "B", "重复操作复制内层引用，两项指向同一个内层列表。"),
      ("learning", "dicts", 1, "dict_literal", "哪个表达式创建字典？", ["['a',1]", "('a',1)", "{'a':1}", "{'a',1}"], "C", "大括号中的键冒号值构成字典项。"),
      ("learning", "dicts", 1, "dict_value_lookup", "d={'name':'Li'}，d['name'] 的值是什么？", ["name", "['Li']", "None", "Li"], "D", "用已有键索引字典得到其关联值。"),
      ("learning", "dicts", 2, "dict_insert", "执行 d={}; d['a']=1 后，d 是什么？", ["{'a':1}", "['a',1]", "{}", "{1:'a'}"], "A", "给新键赋值将该键值对插入字典。"),
      ("learning", "dicts", 2, "dict_delete", "执行 d={'a':1,'b':2}; del d['a'] 后，d 是什么？", ["{'a':1}", "{'b':2}", "{}", "{'a':None,'b':2}"], "B", "del 删除指定的键值对。"),
      ("learning", "dicts", 3, "dict_values_list", "d={'a':1,'b':2}，list(d.values()) 是什么？", ["['a','b']", "[('a',1),('b',2)]", "[1,2]", "[2,1]"], "C", "values 按插入顺序提供值。此题约定 Python 3.7 及以上。"),
      ("learning", "dicts", 3, "missing_index_error", "d={}，求值 d['missing'] 会怎样？", ["返回 None", "返回 0", "自动插入空值", "引发 KeyError"], "D", "直接索引不存在的键引发 KeyError。"),
      ("learning", "dicts", 4, "setdefault_insert", "执行 d={}; v=d.setdefault('a',[]) ; v.append(1) 后，d 是什么？", ["{'a':[1]}", "{'a':[]}", "{}", "{'a':1}"], "A", "缺失键时 setdefault 插入默认对象并返回同一对象。"),
      ("learning", "dicts", 4, "update_overwrite", "执行 d={'a':1}; d.update({'a':3,'b':2}) 后，d 是什么？", ["{'a':1,'b':2}", "{'a':3,'b':2}", "{'a':[1,3],'b':2}", "{'b':2}"], "B", "update 覆盖已有键并插入新键。"),
      ("learning", "dicts", 5, "dict_shallow_copy", "执行 d={'x':[1]}; e=dict(d); e['x'].append(2) 后，d['x'] 是什么？", ["[1]", "[2]", "[1,2]", "KeyError"], "C", "dict(d) 是浅复制，嵌套列表仍被共享。"),
      ("learning", "dicts", 5, "fromkeys_shared_value", "执行 d=dict.fromkeys(['a','b'],[]); d['a'].append(1) 后，d['b'] 是什么？", ["[]", "None", "KeyError", "[1]"], "D", "fromkeys 将同一个默认值对象关联到所有键。"),
    ]
    items = []
    for pool, topic, difficulty, family, stem, choices, answer, explanation in rows:
        items.append({"item_id": f"{pool}-{topic}-{family}", "topic_id": topic, "pool": pool,
            "difficulty": difficulty, "family_id": family, "stem": stem,
            "options": dict(zip("ABCD", choices)), "answer": answer, "explanation": explanation,
            "provenance": {"kind": "ai_generated", "reference": "Codex-authored draft; Python 3.7+ list/dict semantics; human verification required"},
            "review": {"status": "pending_review"}})
    return prepare_bank({"schema_version": SCHEMA, "bank_id": "python-container-pilot", "version": "draft-1",
        "data_kind": "demo", "topics": {"lists": "列表、索引、切片、可变对象与浅复制", "dicts": "字典键值操作、缺失键与嵌套引用"},
        "instructions": "题目为 AI 编写的待审草案；难度仅为候选标注，A/B 等价性尚未经人验证。适用于四道学习题的流程演示，正式实验需扩充题库。", "items": items})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    bank = draft_bank()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "bank.json").write_text(json.dumps(bank, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (args.output_dir / "review-packet.md").write_text(review_packet(bank), encoding="utf-8")
    (args.output_dir / "participants-demo.json").write_text('["DEMO-01", "DEMO-02", "DEMO-03", "DEMO-04"]\n', encoding="utf-8")
    print("28 actual draft questions; pending human review; demo only; no participant observations.")


if __name__ == "__main__":
    main()
