# 本机 MCP Apps 开发

当前开发格式为 `runteams.creator-project/2`、`runteams.dependencies/2` 与 `runteams.release/2`。
完整员工仍使用原员工／技能随包格式，原源码 ZIP、修订、权限及正式发布回执继续复用。

## 流水线源码与构建

工程的 `entrypoints.pipelines` 可列出最多 64 份 `runteams.pipeline-source/3` JSON。
每份包含 `pipeline` 和 `employees`，可选稳定 `key` 在工程内不能重复。
`employees` 使用 `{ "ref": "reviewer", "source": "employees/main.json" }` 引用同工程已声明员工。
岗位使用 `employee_ref` 和该员工实际随包技能的 `skill_key`；审批岗位不绑定员工。
流转继续使用原 `positions`、`states`、`edges`、`when`，以及已有参数和团队规范字段。
编译会检查完整引用、技能、起点、可达性、重复条件及跨岗字段，沿用原生图规则支持配置的退回连线。

本机默认构建与桌面构建均输出对话运行目录：员工仍为原来的
`runteams.conversation-employee/v1`，流水线为 `runteams.conversation-pipeline/v1`，
只引用同目录员工源码路径；不另装员工，不把本机配置或工作资料放入资产。
源码检查、导入和构建不启动工作。本机工作接口已接通草稿的多岗位、条件流转、退回及人工决定，
沿原员工运行器、配置与授权运行，不需要先发布。连线优先级继续采用原 route／status／exception／always，
参数交接沿已有 source、writers、visible_to 规则；输入与输出使用原技能的对象形式 JSON Schema。
岗位内部注入 `runteams_pipeline_work`：read 读取当前输入、输出合同与获准的汇报引用，
submit 以稳定 operation_id 提交原 WorkResult（status、summary、output 等），read_report 只读交接时的汇报版本；
同一工作、同一岗位、同一精确员工绑定重访时，也可读取自己此前已正式提交的固定报告。
这不会使旧产出重新成为当前参数，也不允许覆盖旧报告或读取另一项工作。
宿主校验后才推进，员工不能另行派工或代替人工决定；普通 Skill 没有 work 声明时仍可处理工作并提交摘要与对象结果，
不需要伪造正式发布合同。工作汇报继续通过原 runteams_work_report 保存，不能用汇报正文修改工作状态。
本机控制接口支持先暂停、等待当前执行收尾，再原子应用全部岗位和未完成工作的更新，最后启动。
源码与配置保存不自动切换运行版本；已执行事实保持，未知发送结果不重发，员工独立工作不改绑。
接口、回执与恢复边界见仓库 `design/PIPELINE_REFACTOR_PLAN.md` 的 R03—R05 记录；构建成功不代表工作已执行。
正式发布使用显式发布构建，继续校验完整员工发布合同，并固定流水线当时的全部员工版本。
流水线发布、租用已完成源码接入与隔离验证，相关云端候选尚未部署；
流水线程序声明、构建及自身授权宿主／配置／资料接口已接通并完成隔离验证；工作投影／正式报告／统一受理已接通并完成隔离验证；工作台呈现及完整发布／租用／更新衔接已完成源码与隔离验收；R12-07 已完成源码与隔离联合验收。
R12 产品与实施范围见仓库 `design/PIPELINE_CUSTOM_WORKSPACE.md`；
当前员工式页面入口和完整版本更新联验未完成，不能把宿主接口验收当作完整工作台已交付。

### 流水线程序附件

流水线可选声明自己的完整 MCP 程序，不需要创建员工或额外的 Skill：

```json
"programs": [
  {"key": "dashboard", "source": "programs/dashboard"}
]
```

上述字段位于 `runteams.pipeline-source/3` 顶层，和 `pipeline`、`employees` 同级。
程序目录使用原 MCP 布局：`programs/dashboard/mcp/manifest.json`、`server.cjs`、可选 UI、素材及锁定依赖。
同一条流水线内 key 和 source 不得重复，路径、JavaScript 语法及完整依赖继续走原校验；
程序不会被注入岗位员工，也不会在检查、导入、构建或任务受理时自动启动。

本机对话目录的 `pipeline_programs` 按流水线源码入口保存完整附件；
便携发布定义的 `program_bundles` 固定同一 MCPB 的字节、大小、摘要、key 和 source。
独立的 MCP 产物也进入原签名清单；去除或修改附件，即使重新签名，也不能通过完整源码比对。
共享程序在不同流水线定义中仍各有归属，全部定义的附件展开同样受 32 MiB 产物预算约束。
程序与配置按下述现有宿主运行；工作投影及统一受理按下述 R12-04 使用，工作台呈现复用原员工组件和宿主，不得另造派工或暂停机制。

### 流水线自身配置与授权资料（R12-03）

`pipeline-source/3` 顶层可选 `configuration`，直接使用员工的 `runteams.employee-configuration/1` 字段声明、必需项、资料来源及校验规则。声明进入完整开发／便携发布定义；使用者的配置值和资料授权仅留本机，不写回源码或发布包。流水线自身值、流水线内员工使用值、独立员工默认值分别保存，不能相互代入。

自身程序只绑定流水线自己的 workspace 会话，不是员工，不自动注入岗位。首次运行前通过原暂停→应用更新→启动取得整条流水线的已应用版本，然后在可信宿主明确启用相应程序；打开／读取／导入不执行作者代码。保存源码或配置只改草稿，运行仍用已应用的原程序和配置，缺项时整批更新失败并保持暂停。

宿主复用原 MCP 客户端、Apps 桥、确认、调用回执与未知结果防重放。原生对话沿已支持的 Codex 渠道；其他渠道仍按原审批能力门禁拒绝，不绕过原生确认。页面复用现有组件，后端控制地址为 `/api/chat/<id>/pipeline-mcp`，请求的 origin、当前账户范围、绑定摘要和明确启用规则与员工一致。

已授权的 Node 程序只得到当次存活宿主的 `RUNTEAMS_PIPELINE_HOST` 和 `RUNTEAMS_PIPELINE_CAPABILITY`，不继承应用的模型／账号凭据。向该地址 POST JSON-RPC 2.0，带 `Authorization: Bearer <capability>`：

```js
async function pipelineHost(method, params) {
  const response = await fetch(process.env.RUNTEAMS_PIPELINE_HOST, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${process.env.RUNTEAMS_PIPELINE_CAPABILITY}` },
    body: JSON.stringify({ jsonrpc: '2.0', id: crypto.randomUUID(), method, params })
  });
  const reply = await response.json();
  if (reply.error) throw new Error(reply.error.message);
  return reply.result;
}
```

| 方法 | 参数和结果 |
| --- | --- |
| `configuration/read` | 参数 `{}`；返回已应用的 `values`、`states`、`resources`。本机文件提供经过原授权及内容校验的输入副本，不传原件可写路径 |
| `data/call` | 沿员工集合的同一操作规则，先 `{operation:'list'}` 查看字段别名和记录结构；支持 query、read、upsert、upsert_many、receipt。resource 只接受本流水线获准的字段别名，不接受任意集合 ID、权限或员工身份 |

普通集合仍是原记录，读写沿原 Collections 的版本、稳定业务键、operation_id、事务和回执；写入来源记录真实流水线／程序／会话。只有明确声明的 managed_resources 才由共用机制维护相应资料；调用期间的写入租约由流水线宿主取得并收尾，不要求程序记住可靠性顺序。原员工租约与协议不改变。

业务写入仅允许当前获准工具调用期间进行，资源发现／页面加载没有写权限。暂停会停止自身程序、取消原确认及在途回合，确认停止后才能更新；旧能力连接、旧页面和已关闭程序均不能继续执行作者业务；已打开工作台的可信工作投影在暂停期间仍可读。结果未知保留原调用编号，不能换键重放；业务保存可用原 operation_id 查 receipt。此入口没有派工、验收、人工决定、计划或任意执行控制方法；这些继续走统一工作机制。信任边界仍是普通本机扩展，不声称恶意代码隔离。

配置后端 `/api/device/work/source-pipelines/configuration` 复用 read／save／receipt，精确流水线 reference 为身份；资料选择沿原 `/api/employee-configuration/resources`（及 import），使用 `pipeline_reference` 代替 employee 目标字段，GET 将该引用编码为 JSON 字符串。原定义摘要、完整值、绑定、预期修订和操作回执规则保留；这些路径名属于共用实现，不增加员工或另一种资产。

### 流水线工作进度、正式报告与交办（R12-04）

流水线自己的会话提供两个 RunTeams 原生工具。身份来自实际保存的 workspace 会话，参数不能指定另一个流水线、员工、账号或工作目录。没有程序的流水线也可使用；不是给某个岗位额外授予管理权限。岗位仍只使用原 runteams_pipeline_work，不能代替人工决定。

| 工具 | 实际行为 |
| --- | --- |
| `runteams_pipeline_workspace` | operation 为 list、read、read_report、contract、receipt；读取同一原工作台账、岗位访问和固定交付报告，不执行作者程序，不触发确认或派工 |
| `runteams_propose_pipeline_work` | 原生工具获准后，由当前对话原提交机制将工作交给同一个 R03 source_pipeline_work.create；不是作者程序直接派发某个下游员工 |

list 返回当前已应用图、总数／各状态计数、当前结果摘要及其产生岗位、阻塞／等待／未知状态、最近原操作编号，以及有界 items 与 next_cursor。最多100项，每页卡片约256KiB，不能只读第一页就声称全量。会话起始上下文也使用同一投影（20项），不复制员工现场或用模型日志推断进度。暂停中／已暂停取原控制投影，读取不会启动工作或恢复程序。

read 指定 workflow_id，可读取此流水线这项工作的访问尝试与正式报告引用。read_report 必须提供 workflow_id、report_id、revision；只取岗位提交时固定的 artifact 和摘要校验，后续编辑不能替换原交付版本。未提交草稿、其他工作／流水线、员工个人现场和编辑权限不在此读取范围；原报告删除或缺失会明确不可用，不退回最新版本或补造报告。

交办参数为 `{operation_id, title, payload, start_column_key?}`，payload 使用原 `runteams.task-input/v2`。先读 contract，选择实际存在的开始岗位，遵守该列输入／资料声明；不固定从第一个员工开始。只能提供已声明的用户参数，不能填写员工产出、声明岗位身份或批准人工关卡。源码草稿不改变已应用的合同；暂停拒绝新受理，版本改变后原提案必须重新核对。已提交的原操作仍可恢复，不因此新建工作。

本机文件的原授权规则保持：流水线用户会话沿现有 composer 引用和 local_references.bind_task 绑定用户实际提供的附件，复核已授权身份和类型；原输入合同现同时返回 assets。不能凭任意路径、授权编号取得资料。作者工作台不能借用用户会话的私有附件；业务记录仍经 R12-03 授权资料接口维护，可将业务记录键等作为原声明参数交办，不复制集合或给岗位自动扩权。

工作台通过已有 MCP Apps 的 `app.callServerTool` 调用同名宿主工具，例如：

```js
const facts = await app.callServerTool({
  name: 'runteams_pipeline_workspace', arguments: { operation: 'list', limit: 20 }
});
const receipt = await app.callServerTool({
  name: 'runteams_propose_pipeline_work',
  arguments: { operation_id: crypto.randomUUID(), title: '按实际输入处理', payload }
});
```

示例中的 operation_id 必须由一次真实用户操作创建并持久保留，接续时沿原编号查 receipt；不能每次刷新都重新生成后调用。普通读取直接由可信宿主返回，不转发作者工具。工作台交办必须通过现有 RunTeams 原生确认，作者页面不能传 accepted／confirm 冒充同意；同一在途意图不重复弹确认，拒绝或暂停期间取消则不受理。确认后直接返回原工作回执，不恢复旧方案卡片、伪造用户聊天或启动额外模型。读取回执中断、页面重连或重复代理号均读取同一工作，原岗位交接、返工、恢复和人工决定不改变。

这些宿主工具由 RunTeams 提供，作者程序不得声明同名工具；发生冲突拒绝打开。Node 的 configuration/read、data/call 能力连接不新增派工或决定方法。可信原生绑定、文档代际、精确版本和启用仍校验；暂停保留已打开界面的可信读取，作者业务工具继续禁止执行。界面入口与交互呈现沿 R12-05 的共用员工工作台，发布和运行升级沿下述 R12-06 规则。

平台只读后端为 `/api/chat/<id>/pipeline-work`：GET 读取默认列表，POST 使用上述读取 operation；保留原 loopback origin／当前本机 scope 校验。它不开放派工、确认或控制 POST，作者 iframe 也不能直接访问。业务受理成功后唤醒原工作执行服务，唤醒或后续显示失败不撤销已受理事实，不要求重新派工。

### 发布、租用与运行更新（R12-06）

发布沿现有完整源码构建与签名流程：流水线程序、UI／素材、锁定依赖及所有员工内容和版本关联一起固定。程序改动形成新的整套发布；员工内容未变时继续引用原不可变员工版本。历史发布不能被后来的源码、资源或员工修改替换。构建、发布和资产下载均不运行作者代码，不带使用者的资料、配置值、授权凭据或对话。

商店选择的版本号须与取得的完整签名发布版本一致；完整清单、来源、依赖和程序附件均沿原校验。租用仅能使用开放配置及发布内容，不能改创作模式或重发布。取得新版只改变待应用的选择，不立即替换运行中的程序和岗位。

使用原暂停→确认停止→应用更新→启动：停止覆盖流水线自身及岗位程序／在途确认；更新对全部岗位及未完成工作一次提交，自身配置也按同次版本冻结。缺配置、内容损坏、原岗位不再兼容等错误保留旧版和暂停，不执行半套版本。历史交付及未知调用记录留在本机，不重发原业务操作。

启动只解除当前已明确启用程序的暂停，不执行工具、不创建模型回合、不授予新版本信任。同版本中保留的工作台页面重新核对实际绑定后使用原调用／确认／回执；用户主动停用、关闭或版本变化不会借此自动运行。新版本仍须在原本机功能面板明确启用，不绕过岗位交接或人工决定，也不改独立员工默认值和执行器。

以上已完成源码与隔离原数据库／签名资产／实际 Node 宿主验证；云端候选未部署，运行中的服务、安装包和 SDK 分发包未自动升级。R12-07 已完成同一工程的完整链路及实际浏览器联合验收，记录见 `design/PIPELINE_CUSTOM_WORKSPACE_ACCEPTANCE.md`；工程样例不代表员工自主业务成果。

## 员工程序与界面

`source/` 是作者可编辑源码。`skills/<技能>/mcp/manifest.json` 是 MCPB 0.3 清单，
`server.cjs` 是可直接运行的 Node 程序，`ui/` 是可选的 MCP Apps 页面。
`vendor/` 提供精确锁定的官方 MCP／Apps 库与原 UI Kit；修改依赖时须更新完整字节与锁，
不能只写包名、浮动版本或等待使用者安装。生成的 `mcp/employee.mcpb` 是构建产物，不写回源码。

这是 JavaScript 首批交付。检查／构建不会运行作者代码：构建使用平台固定 Node 做语法检查，
固定解析器核对静态导入的完整闭包，再确定性打包完整资源。动态路径仍是作者行为，不能静态证明所有运行分支。程序入口须是已准备好的 JS／CJS／MJS；本轮不自动执行 npm／pip 脚本，
不承诺 TypeScript、其他语言／原生附件和未验证系统的自动转换。技能员工可以不包含程序或界面。

可直接使用既有 Python 环境运行 `runteams.py`，依赖版本见 requirements.txt：

```sh
python runteams.py doctor
python runteams.py check
python runteams.py build
python runteams.py test --trust-local-code
python runteams.py preview
python runteams.py pack --output dist/employee-source.zip
python runteams.py inspect dist/employee-source.zip
python runteams.py init ../another-employee --key another-employee --name 新员工
python runteams.py open /absolute/employee-source.zip ../continued-employee
```

自测和预览会实际执行作者程序，以普通用户身份访问本机和网络。只对可信源码使用
`--trust-local-code`；浏览器预览在明确勾选启用后才启动。检查、构建、打包、导入不授予运行权限。
预览目录保存的是开发过程，不是正式员工工作或平台业务账本；本段未验收预览文件的完整备份／换机恢复。
自测须提供非空 `runteams.mcp-dev-tests/1` 案例，断言实际工具 structuredContent；从产品导出的
任意项目不继承示例断言。未知调用不能用换键或重开当作成功，不把本机输出当平台业务回执。

源代码变更后重新检查、构建，只补受影响自测。UI 改动须打开真实预览、操作相关状态并查看截图；
组件和主题继续使用 UI Kit，不重做平台布局。固定工具与 Runtime、技能、插件和 MCP 保持完整，
不引入裸模型 API，不修改开发者全局 Agent 配置。Skill 提供专业方法与上下文；
工作受理、锁、回执、重试和恢复由 RunTeams 现有机制保证，不依赖模型记住操作顺序。

产品普通对话中发送完整源码文件夹，由 Agent 使用当前附件编号导入；Agent 与编辑器编辑同一修订，构建与试运行采用同一格式。
正式发布仍由原产品发布入口校验当前权限、精确版本及可信构建签名，并以原请求回执确认。
本工具不提供直接写数据库、发布、部署或安装命令。完成本机自测不代表正式交付或供应商业务成功。

平台维护者准备新开发包时，复用 `runteams_core/devtools/export_creator_devkit.py --profile mcp`，
提供已核验的 `--runtime-root`、`--libraries` 和固定 `--esbuild`，不提供模型或供应商凭据。
`prepare_creator_builder.sdk_archive(..., profile='mcp', runtime_root=..., libraries=...)`
生成独立分发的开发包 ZIP 与摘要；产品不提供临时开发包下载入口。

可信发布 worker 使用 `runteams.creator-release-builder/3`：`runtime` 包含平台资源绝对
`root` 和 `manifest_sha256`，`esbuild` 包含解析器绝对 `path` 和 `sha256`，
另有 `signing_key_file` 与原 `trusted_keys`。配置和签名私钥须是仅维护者可读的文件；
这些路径／钥匙属于可信构建服务，不进入作者源码、开发包或客户端。实际密钥、正式资源
签名、托管 worker、部署与发布仍需单独准备和确认，不用示例密钥开放正式门禁。


## 员工名字与头像

员工身份显示由 `project.json` 的员工入口文件声明。修改当前员工的 `name` 和
`avatar`，不要修改员工 `key`、身份引用、历史记录或数据库字段。多员工工程应先
核对当前创作会话的员工入口；不要用名字猜目标。当前创作目录与文件编辑器共用
修订记录，图片与 JSON 一起提交；并发冲突保留修改，不覆盖另一份编辑。

`avatar` 可以使用工程根目录相对路径，例如 `assets/avatar.webp`。图片必须包含在
源码树中；支持不超过 512 KB、边长不超过 4096 的静态 PNG、JPEG、WebP，以及
无脚本、无外部资源的静态 SVG。构建将精确图片字节及摘要纳入员工包，导出、
导入和备份均随包保留。`preset:bottts:nova` 可作为应用默认头像；SDK 不另带头像库。

用户要求换头像时优先使用当前对话上传的图片或已有工程图片；有可用生图能力时
才生成新图片。没有图片或生成失败时保留原头像，不声称已完成。预设选择器及
手动上传也保存为包内图片。创作保存不会替换正在工作的冻结版本或重载工作台，
发布、应用更新和运行权限沿原流程。
