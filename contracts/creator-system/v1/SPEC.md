# 创作者作品协议与 SDK 1.0.0

状态：2026-10-20 接口定稿，限隔离规范与后续集成依据。没有注册生产 contracts、改写 product-model/v2 或接入正式应用。历史 0.1-draft 及其证据保持原样；不作兼容读取、隐式升级或双写。机器 schema、SDK 类型与本规范共同构成合同，冲突须修正规范并重验后冻结。

## 用户结果与来源

创作者拥有一个包含完整自有资产、可编辑模板、业务逻辑、连接声明、测试和依赖锁的文件夹。文件编辑、Agent 对话和表单指向同一个有修订的云端作品。租用者按作者开放的权限使用。业务扩展在独立 Wasm 宿主中执行，经通用 SDK 请求已经授权的能力；供应商专用逻辑放在作品中。官方 Agent 的技能、插件、MCP、终端等原生能力继续按官方机制继承，不需要作品额外声明或绑定。

“完全隔离”在这里指不可信业务扩展与宿主、凭据、其他安装的边界，和开发验收与正式产品的边界。网络、OAuth、存储、租用资格和恢复仍需要通用平台基础设施；不能解释成零外部依赖或对本机所有者绝对保密。工程样例不是经产品生成的可发布员工。

## 作品与冻结发布

根文件固定为 `project.json`，schema=`runteams.creator-project/1`，SDK 精确为 `1.0.0`。字段见 project.schema.json。员工与流水线入口是可移植来源描述；soul 只持有身份、通用表达和边界，工作方法仍在技能中。正式 work、冻结编译与派工语义复用现行 product-model/v2，不从魂文件猜工作，也不把整个业务程序重复写进员工字段。新增源包装进入现行编译器的适配尚未接线。

入口、数据 schema、迁移、连接、操作输入输出和 handler 都引用作品内真实资产。无生成物自引用。所有文件，包括普通隐藏文件和二进制，都进入完整树清单；不能仅打包入口可达文件。500 文件、总 32 MiB；路径最大240字符，UTF-8 NFC规范相对路径，禁止绝对路径、URL、反斜线、控制字符、百分号、点段、空段、大小写碰撞、链接、设备或其他特殊文件。目录结构不授予宿主文件访问。

树摘要算法：按规范路径排序，条目为 `{path,size,sha256}`；条目列表使用 UTF-8 JSON、键按字典序、无空白、非 ASCII 原样编码、整数十进制，计算 SHA256。跨语言实现必须对固定测试向量得到同一摘要；不将一般浮点 JSON 的 stringify 假称 JCS。源树和派生索引分别保存。发布前重新读取全部资源并校验字节，任何编辑都使先前验证失效。已识别凭据、私钥、登录缓存、设备数据库和运行目录禁止分发；发布的内容扫描与作者审核仍须完成，文件名黑名单不足以证明没有泄漏。

`dependencies.lock.json` 精确锁定全部传递依赖的 key、version、sha256、requires 和构建运行要求；闭包完整、无重名和环，缺依赖或字节不匹配直接失败，不现场浮动解析 latest。根包、依赖闭包和全部来源进入发布摘要；冻结后不可变。

`runteams.release/1` 单独绑定源树摘要、原锁文件摘要、全部派生 artifact 字节、SDK、helper 和 builder 摘要以及完整 dependency_blobs。发布服务核实每个blob真实字节、闭包一一对应和目标兼容，不能凭格式合法的摘要发布。签名对象是该 canonical release 的 SHA256；签名/分发层独立管理，不把私钥放入作品。签名团队、公证、更新服务信任根轮换和恢复仍须正式发行环境验收，接口冻结不等于发行完成。

## SDK 线协议与兼容

`client.js` 为可嵌入 JS/Javy 的无环境 I/O 同步客户端；`client.d.ts` 给出类型。宿主提供专用 transport，UI适配器可把相同信封封装为 Promise；本轮没有实现最终浏览器适配器。

请求严格为 `{abi:"runteams.sdk/1",id,method,params}`。id 从1单调增加，安全整数；响应严格为 `{abi,id,ok:true,result}` 或 `{abi,id,ok:false,error:{code,retry}}`。拒绝重复JSON键、非有限数、超出安全整数的整数、循环、非JSON类型、深度超过32及单帧超过16384 UTF-8字节。不得把调用者填入的身份、安装、固定发布、租用资格或本机路径提升为权限。外层原生辅助进程私有会话/序号/截止时间由可信适配器绑定，不让guest控制宿主控制通道。

先调用 `system.negotiate` 精确协商 SDK 和 required 能力。声明一个方法不等于宿主已实现或已授权；缺必需能力明确 unsupported_capability，不能静默降级。1.0.0 用精确锁；未来补丁只修复不改变语义，新增能力需明确协商；破坏字段、回执、权限或效果语义必须新主版本。不得把 0.1-draft 自动当成1。

| 能力 | 定稿接口 | 不可省略的服务端语义 |
| --- | --- | --- |
| 创作来源 | source.list/read/write | 每次检查源权限；CAS冲突不覆盖；写使验证失效；write必须有原操作键 |
| 大文件 | source.beginUpload/uploadChunk/finishUpload | 临时上传属于当前身份/作品；偏移和重复块一致，完成核实总大小及SHA256；blob_ref不是公共URL、没有源访问权；写入草稿仍需source.write CAS。inline/base64块最大8192字符 |
| 托管数据 | data.query/mutate | workspace+installation隔离；limit1–100、游标和查询索引有界；系统字段禁止修改；mutation批次原子、有原操作键；不暴露SQL或数据库凭据 |
| 连接 | connection.status/request/http | status不含凭据；request只创建可信授权请求；http只选已授权端点，不接受URL、header、凭据、身份；见下节 |
| 业务操作 | operation.invoke/receipt | 输入输出schema、actor与effect校验；写入原键必需；固定发布与租用授权由服务端注入 |
| 工作 | work.dispatch/status | 现行employee/skill/work合同、实际主机和租用资格；创建回执不等于工作成功 |
| 事件 | events.poll | 有界游标读取，允许重复乱序；事件ID去重，当前权限检查；触发、派工和外部效果分别去重 |
| 宿主交互 | host.openResult/requestDecision | 引用真实授权对象；请求人工处理不自动同意、不伪造业务成功 |

接口参数以 methods.json/request.schema.json 为准，返回类型以 client.d.ts、业务输出schema及本节语义为准。作者提供的业务JSON Schema只允许有限本地引用，禁止远端引用、$id重定位、动态引用和递归模式；验证器固定草案并限制复杂度，不能让schema解析触发宿主网络请求。各宿主必须校验输入和输出；客户端信封校验不是业务正确性或授权依据。只有通过对应服务验收的能力才能在 negotiate 中返回。本轮通用外部代理实际提供 connection.http/status；其余客户端接口已冻结并做编码/类型测试，产品服务适配未实现，不能称全SDK后端完成。

## 连接与供应商专用代码

connection.schema.json 定义 provider-neutral 声明：精确HTTPS origin、OAuth端点与scope、符号 client_binding、命名endpoint，每项包含method/path模板、effect、query和input/output schema。client_binding仅标识宿主受保护配置，不是 secret 或读取钥匙。授权主体必须由可信账号状态确认，OAuth使用一次性state、PKCE、精确回调、固定供应商端点和真实scope检查；不从浏览器声称成功就标ready。

发布和宿主共同拒绝读效果配写方法、路径逃逸、未声明参数、额外认证字段、私网/保留IP、DNS重新绑定和跨源重定向。生产请求按每次解析并验证后的IP连接并验证TLS hostname；不跟随redirect。可信宿主可显式选择公网DoH解析配置，以适配返回合成保留地址的网络；作品无此开关。DoH只向固定TLS验证的解析服务发送域名，不附带邮箱凭据，返回的每个IP仍必须公网可路由，不能把合成保留地址加入放行名单。TCP/TLS建立失败可在发送HTTP之前尝试另一已验证IP；请求一旦开始发送，不自动重试写入。客户端不能设置 Host、Authorization、Cookie、代理、回调URL、解析器或证书。凭据由可信宿主持有，guest和UI只见作用域内业务结果；收到回显凭据的响应必须拒绝。只有独立工程监督器可显式配置回环TLS夹具，作品没有这个开关。

creator可以实现供应商专用数据转换、MIME、查询、业务判断及恢复读取，不需要平台新增Gmail模块。平台仍需提供通用OAuth/网络/权限/回执功能、可用client配置和必要的人为授权。新增高风险服务、scope或端点不因作者声明而自动获准。

本轮Gmail只开放drafts.create/get/list，scope为gmail.compose；独立授权另用openid/email核实指定测试邮箱。没有send端点，员工不能通过此扩展发送。OAuth scope本身还允许更多供应商操作，RunTeams已授权端点是额外的实际限制；不能把scope描述成草稿专用权限。官方原生Gmail扩展继续沿其自身授权运行，不被此业务代理白名单替代。

## 写入、恢复与真实状态

已保存作品、业务模型、安装、源权限与操作回执以Supabase为权威。Gmail原始对象以Gmail为事实源。本机只持凭据、明确未同步草稿、执行恢复元数据和可丢弃验证缓存，不建立第二个业务库。

写入身份包含真人、workspace、installation、operation及原操作键；第一次请求固定release和input hash。升级、重启和换电脑不能变成新操作。相同身份/键/内容查原回执；同键不同内容拒绝。云端先原子占位才允许外部请求；云不可用不得先写供应商。可信代理证明HTTP尚未开始的前置拒绝可记failed，允许同原键再尝试；不能以“没有收到响应”推断尚未发送。供应商响应通过合同校验、回执真正提交后才能confirmed。连接授权、租用资格和源权限均不能从本机旧记录推断。

pending表示仍在核实，confirmed仅确认已核实的那次效果；unknown表示结果未知；failed/canceled只有权威证据证明未产生效果才能成为安全终态。取消执行、断网、超时、429/5xx、无效响应或进程退出均不自动证明没有效果。外部已发出的调用可以在取消后完成。错误retry只能是never/read/reconcile/reauthorize；reconcile绝不表示换键重做。

Gmail create没有本协议可依赖的供应商幂等键。未知创建不自动再POST。作品可用本轮唯一主题标记缩小drafts.list，逐项get检查X-RunTeams-Operation和真实内容；Message-ID会被Google改写，不作固定键。查不到、分页不完整、对象被改/删、无权限或重复匹配都不能证明未写入。查到供应商对象可以报告“找到测试草稿”，但guest自行声称匹配不能直接把云unknown改为confirmed；正式自动恢复需可信的供应商核对器验证或用户显式处理。本轮不以本机SQLite、JS返回值或标记搜索造成功回执。

## 版本、数据与分发

安装先验证全部源与artifact/依赖/宿主兼容，单事务切换安装指针；旧运行固定旧发布。CAS发布与重复安装有原键回执。卸载不会暗中删除云数据：重新安装默认新installation命名空间；明确恢复原安装需要原安装权限及云端恢复流程。停止租用立即停止普通访问，不能借固定旧发布绕过失权；受限完结凭证仍只允许现行合同规定的指定运行。

数据schema/index和迁移经受控数据服务执行，任意SQL、自选主库和失败转本地成功均禁止。兼容升级保持旧字段语义；破坏性迁移与任务启动使用同一并发门，等待全部非终态旧任务。失败必须保护数据和安装指针；逆向数据不兼容时拒绝假回滚。恢复使用事前核实备份和受控恢复计划；真实外部效果不会被代码回滚撤销。

模板可编辑复制；升级以原模板/当前作品/新模板做三方比较，冲突留作者解决，不静默覆盖。源码read/export/history逐次经服务端授权；下发UI/业务代码只做合理分发保护。签名helper的JIT内存权限仅授予该辅助进程，guest无宿主环境、预开目录、Shell或原生网络。

## 实测范围与放行门槛

当前基线是macOS ARM64、Javy9.1.0、Wasmtime49和此目录精确SDK；TS须先由受控编译器转为JS，再进Javy。支持纯计算JS和经此目标验证的依赖，不承诺完整Node/Python/npm。当前Javy静态构建不保证同源码重复构建字节一致；发布冻结一次实际构建的字节，运行只校验并复用该artifact，不现场重编译。输入和私有会话通过独立管道传入，不进入生成物。新增库/目标逐项锁版本并编译/运行，不能只因包能安装就称兼容。

本轮检查根/依赖/连接/来源合同、客户端编码和TypeScript类型，以及真实Wasm/TLS/临时Supabase的隔离Gmail形状用例。真实Gmail独立列证据，不能以形状夹具替代。正式产品源包装适配、来源上传服务、数据/work/event/UI服务接线、真实发行信任链与更新服务、目标设备/托管容量和产品创作至租用闭环仍是放行门槛。协议定稿不把这些未完成工作改成已验收。


## 官方供应商依据

- [Gmail drafts.create](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create)：HTTP路径、输入输出及scope依据。
- [Gmail drafts.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/list)、[drafts.get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/get)：标记检索、分页及独立内容核对依据。
- [Google桌面OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)：独立授权和PKCE依据；本轮复用的是已配置web客户端的精确本机回调，不假称新建native客户端。
- [Google Public DNS DoH JSON](https://developers.google.com/speed/public-dns/docs/doh/json)：可信宿主解析配置依据；本轮保持全部目的IP的公网检查。

真实Gmail成功证明当前隔离样例的草稿能力和受控提交后崩溃恢复边界；没有证明任意供应商、所有scope、自然失效、全自动可信核对或正式产品全流程都已完成。
