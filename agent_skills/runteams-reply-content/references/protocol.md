# RunTeams 对话数据协议 v1

将有效 JSON 放在顶层、语言为 `runteams-view` 的代码围栏中。每块一个对象，普通说明写在围栏外。不要用外层代码围栏包裹整条回复。产品解析完整围栏后渲染组件；无效格式会显示原代码，不会自动修正。

## 共用字段

| 字段 | 要求 |
| --- | --- |
| version | 数字 `1` |
| type | `table`、`chart` 或 `explorer` |
| title | 非空标题，最多 120 字符；使用人能读懂的名称 |
| columns | 1—12 个列对象，顺序即展示顺序 |
| rows | 最多 500 个行对象，只使用已声明列的 key |
| caption | 可选，最多 500 字符，说明必要口径、单位或范围 |

列对象：`{"key":"count","label":"数量（条）","format":"number"}`。
key 以英文字母开头，只含 ASCII 字母、数字、下划线、连字符，最多 50 字符；不能重复，不能为 `constructor`、`prototype`、`__proto__`。label 非空，最多 80 字符。format 为 `text`（可省略）或 `number`。

单元格只允许字符串、有限数值、布尔值或 null，不允许数组或嵌套对象。字符串最多 2000 字符；数值列只能使用 JSON 数字或 null，不可写 `"12条"`、百分号、NaN、Infinity。单位写进列名或 caption；未知值用 null。文本中的 Markdown／HTML 不会被执行或当链接显示，需要可点击来源时放到围栏外的正文。

每块含围栏不超过 100000 字符，每条回复最多 12 块；这些是上限，不是目标。通常只需少量相关列和关键记录。全文超过 1000000 字符时不解析组件，不向对话倾倒完整原始数据。

## 表格

以下仅是格式示意，不是可复用事实。真实回复必须替换为已核实的数据。

```runteams-view
{"version":1,"type":"table","title":"检查结果","columns":[{"key":"item","label":"检查项"},{"key":"result","label":"结果"}],"rows":[{"item":"示例检查项","result":"待验证"}],"caption":"格式示意"}
```

表格自带搜索、排序、每页 5 条、记录详情。无需额外添加按钮定义。

## 图表

共用字段外增加 `x`（分类列 key）和 `metrics`（1—4 个数值列 key）。产品显示横向条形图，可以切换指标、展开原数据表；不支持自定义 chartType、颜色、代码或远程数据源。

```runteams-view
{"version":1,"type":"chart","title":"各组记录数量","columns":[{"key":"group","label":"分组"},{"key":"count","label":"记录数（条）","format":"number"}],"rows":[{"group":"示例组甲","count":8},{"group":"示例组乙","count":3}],"x":"group","metrics":["count"],"caption":"仅为格式示意，并非工作结果"}
```

切换指标不会改变标题，标题应涵盖所有可选指标。例如同时提供低星、中星、高星时写“评论评分分布”，不写“低星评论数量”。不要用样本数图暗示市场规模或满意度。没有可比较的数值，就使用文字或表格。

## 交互筛选

共用字段外增加 `category`（分类列 key）和 `threshold`（数值列 key）。产品提供类别按钮与从 0 起的最低值滑块、重置及结果表格。仅适用于非负阈值，不用于负值区间、日期范围或任意查询。

```runteams-view
{"version":1,"type":"explorer","title":"按类别查看记录","columns":[{"key":"name","label":"名称"},{"key":"kind","label":"类别"},{"key":"count","label":"记录数（条）","format":"number"}],"rows":[{"name":"示例甲","kind":"类别甲","count":8},{"name":"示例乙","kind":"类别乙","count":3}],"category":"kind","threshold":"count","caption":"仅为格式示意，并非工作结果"}
```

所有交互只处理消息内的数据快照，不发起采集、授权、写入或刷新数据。数据随消息持久化，筛选状态不承诺跨整页重载恢复；复制消息得到可读文本与表格数据。不要向用户声称拥有协议之外的能力。
