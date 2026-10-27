# 研究者审题册（含答案；禁止提供给参与者）

题库：python-container-pilot / draft-1；来源：demo。
自动生成内容仍须人工逐题审核；难度与 A/B 等价性不是软件可以证明的。

## A-lists-length_after_pop · A · lists · 难度 2
家族：length_after_pop；审核：pending_review。

执行 x=[2,4,6]; x.pop() 后，len(x) 是多少？

- A: 2
- B: 3
- C: 6
- D: 0

答案：A；解析：pop() 删除末项，列表剩下两项。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## A-lists-slice_independent_container · A · lists · 难度 3
家族：slice_independent_container；审核：pending_review。

执行 x=[1,2]; y=x[:]; y.append(3) 后，x 是什么？

- A: [1,2,3]
- B: [1,2]
- C: [3]
- D: 报错

答案：B；解析：切片创建新的外层列表，向 y 追加元素不改变 x。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## B-lists-nested_index · B · lists · 难度 2
家族：nested_index；审核：pending_review。

x=[[4,5],[6,7]]，x[1][0] 的值是什么？

- A: 4
- B: 5
- C: 6
- D: 7

答案：C；解析：先取第二项 [6,7]，再取其第一项 6。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## B-lists-extend_versus_append · B · lists · 难度 3
家族：extend_versus_append；审核：pending_review。

执行 x=[1]; x.extend([2,3]) 后，x 是什么？

- A: [1,[2,3]]
- B: [[1],2,3]
- C: [2,3]
- D: [1,2,3]

答案：D；解析：extend 逐项追加可迭代对象中的元素。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## A-dicts-get_default · A · dicts · 难度 2
家族：get_default；审核：pending_review。

d={'a':2}，d.get('b',0) 的结果是什么？

- A: 0
- B: 2
- C: None
- D: KeyError

答案：A；解析：get 对缺失键返回指定默认值，不插入键。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## A-dicts-dict_keys_membership · A · dicts · 难度 3
家族：dict_keys_membership；审核：pending_review。

d={'a':2,'b':3}，表达式 2 in d 的结果是什么？

- A: True
- B: False
- C: 2
- D: TypeError

答案：B；解析：in 对字典检查键；2 是值而不是键。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## B-dicts-existing_key_replacement · B · dicts · 难度 2
家族：existing_key_replacement；审核：pending_review。

执行 d={'x':1,'y':2}; d['x']=9 后，len(d) 是多少？

- A: 1
- B: 3
- C: 2
- D: 9

答案：C；解析：已有键赋值覆盖值，不增加键数。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## B-dicts-pop_return · B · dicts · 难度 3
家族：pop_return；审核：pending_review。

执行 d={'x':4,'y':8}; v=d.pop('x') 后，(v,len(d)) 是什么？

- A: (None,1)
- B: (4,2)
- C: (8,1)
- D: (4,1)

答案：D；解析：pop 返回被删除键的值，字典剩一个键。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-list_literal · learning · lists · 难度 1
家族：list_literal；审核：pending_review。

哪个表达式创建含两个整数的列表？

- A: [1,2]
- B: (1,2)
- C: {1,2}
- D: '1,2'

答案：A；解析：方括号创建列表，其他分别是元组、集合和字符串。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-list_zero_index · learning · lists · 难度 1
家族：list_zero_index；审核：pending_review。

列表的第一个有效非负索引是什么？

- A: 1
- B: 0
- C: -1
- D: len(x)

答案：B；解析：Python 序列使用从零开始的非负索引。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-delete_index · learning · lists · 难度 2
家族：delete_index；审核：pending_review。

执行 x=['a','b','c']; del x[1] 后，x 是什么？

- A: ['b','c']
- B: ['a','b']
- C: ['a','c']
- D: []

答案：C；解析：索引 1 对应 'b'，删除后剩 'a' 和 'c'。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-negative_index · learning · lists · 难度 2
家族：negative_index；审核：pending_review。

x=[10,20,30]，x[-1] 是什么？

- A: 10
- B: 20
- C: -1
- D: 30

答案：D；解析：负索引 -1 表示最后一项。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-reverse_slice · learning · lists · 难度 3
家族：reverse_slice；审核：pending_review。

x=[0,1,2]，x[::-1] 是什么？

- A: [2,1,0]
- B: [0,1,2]
- C: [0,2]
- D: []

答案：A；解析：步长 -1 使切片按反向顺序取元素。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-slice_stop_exclusive · learning · lists · 难度 3
家族：slice_stop_exclusive；审核：pending_review。

x=[0,1,2,3,4]，x[1:4] 是什么？

- A: [1,2,3,4]
- B: [1,2,3]
- C: [0,1,2,3]
- D: [4]

答案：B；解析：切片包含起点索引 1，不含终点索引 4。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-list_alias · learning · lists · 难度 4
家族：list_alias；审核：pending_review。

执行 x=[1]; y=x; y[0]=7 后，x[0] 是多少？

- A: 1
- B: 0
- C: 7
- D: 报错

答案：C；解析：赋值没有复制列表；两个变量引用同一对象。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-sort_returns_none · learning · lists · 难度 4
家族：sort_returns_none；审核：pending_review。

执行 x=[3,1]; y=x.sort() 后，y 是什么？

- A: [1,3]
- B: [3,1]
- C: True
- D: None

答案：D；解析：sort 原地排序并返回 None。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-nested_shallow_copy · learning · lists · 难度 5
家族：nested_shallow_copy；审核：pending_review。

执行 x=[[1]]; y=x.copy(); y[0].append(2) 后，x 是什么？

- A: [[1,2]]
- B: [[1]]
- C: [1,2]
- D: [[2]]

答案：A；解析：浅复制只复制外层；内层列表仍被共享。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-lists-repeated_inner_alias · learning · lists · 难度 5
家族：repeated_inner_alias；审核：pending_review。

执行 x=[[]]*2; x[0].append(9) 后，x 是什么？

- A: [[9],[]]
- B: [[9],[9]]
- C: [[],[9]]
- D: [[9]]

答案：B；解析：重复操作复制内层引用，两项指向同一个内层列表。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-dict_literal · learning · dicts · 难度 1
家族：dict_literal；审核：pending_review。

哪个表达式创建字典？

- A: ['a',1]
- B: ('a',1)
- C: {'a':1}
- D: {'a',1}

答案：C；解析：大括号中的键冒号值构成字典项。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-dict_value_lookup · learning · dicts · 难度 1
家族：dict_value_lookup；审核：pending_review。

d={'name':'Li'}，d['name'] 的值是什么？

- A: name
- B: ['Li']
- C: None
- D: Li

答案：D；解析：用已有键索引字典得到其关联值。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-dict_insert · learning · dicts · 难度 2
家族：dict_insert；审核：pending_review。

执行 d={}; d['a']=1 后，d 是什么？

- A: {'a':1}
- B: ['a',1]
- C: {}
- D: {1:'a'}

答案：A；解析：给新键赋值将该键值对插入字典。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-dict_delete · learning · dicts · 难度 2
家族：dict_delete；审核：pending_review。

执行 d={'a':1,'b':2}; del d['a'] 后，d 是什么？

- A: {'a':1}
- B: {'b':2}
- C: {}
- D: {'a':None,'b':2}

答案：B；解析：del 删除指定的键值对。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-dict_values_list · learning · dicts · 难度 3
家族：dict_values_list；审核：pending_review。

d={'a':1,'b':2}，list(d.values()) 是什么？

- A: ['a','b']
- B: [('a',1),('b',2)]
- C: [1,2]
- D: [2,1]

答案：C；解析：values 按插入顺序提供值。此题约定 Python 3.7 及以上。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-missing_index_error · learning · dicts · 难度 3
家族：missing_index_error；审核：pending_review。

d={}，求值 d['missing'] 会怎样？

- A: 返回 None
- B: 返回 0
- C: 自动插入空值
- D: 引发 KeyError

答案：D；解析：直接索引不存在的键引发 KeyError。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-setdefault_insert · learning · dicts · 难度 4
家族：setdefault_insert；审核：pending_review。

执行 d={}; v=d.setdefault('a',[]) ; v.append(1) 后，d 是什么？

- A: {'a':[1]}
- B: {'a':[]}
- C: {}
- D: {'a':1}

答案：A；解析：缺失键时 setdefault 插入默认对象并返回同一对象。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-update_overwrite · learning · dicts · 难度 4
家族：update_overwrite；审核：pending_review。

执行 d={'a':1}; d.update({'a':3,'b':2}) 后，d 是什么？

- A: {'a':1,'b':2}
- B: {'a':3,'b':2}
- C: {'a':[1,3],'b':2}
- D: {'b':2}

答案：B；解析：update 覆盖已有键并插入新键。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-dict_shallow_copy · learning · dicts · 难度 5
家族：dict_shallow_copy；审核：pending_review。

执行 d={'x':[1]}; e=dict(d); e['x'].append(2) 后，d['x'] 是什么？

- A: [1]
- B: [2]
- C: [1,2]
- D: KeyError

答案：C；解析：dict(d) 是浅复制，嵌套列表仍被共享。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint

## learning-dicts-fromkeys_shared_value · learning · dicts · 难度 5
家族：fromkeys_shared_value；审核：pending_review。

执行 d=dict.fromkeys(['a','b'],[]); d['a'].append(1) 后，d['b'] 是什么？

- A: []
- B: None
- C: KeyError
- D: [1]

答案：D；解析：fromkeys 将同一个默认值对象关联到所有键。
来源：{'kind': 'ai_generated', 'reference': 'Codex-authored draft; Python 3.7+ list/dict semantics; human verification required'}
待核验：content, topic, difficulty, form_equivalence, family_disjoint
