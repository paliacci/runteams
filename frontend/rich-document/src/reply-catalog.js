import {defineCatalog} from '@json-render/core';
import {schema} from '@json-render/react/schema';
import {z} from 'zod';
const column=z.object({key:z.string(),label:z.string(),path:z.string(),format:z.enum(['text','number']).optional()}).strict();
const records={title:z.string(),items:z.array(z.record(z.string(),z.unknown()))};
export const catalog=defineCatalog(schema,{components:{
 Stack:{props:z.object({}).strict(),slots:['default'],description:'垂直组合少量相关组件，不重复展示相同数据。'},
 Table:{props:z.object({...records,columns:z.array(column)}).strict(),description:'记录表格，自动提供本地搜索、排序和详情。items 用 $state 引用 /data 下的记录数组，columns.path 是相对单条记录的 JSON Pointer。'},
 Chart:{props:z.object({...records,columns:z.array(column),x:z.string(),metrics:z.array(z.string())}).strict(),description:'复用横向条形图，按名称比较数值；附带可切换指标和原数据表。x 和 metrics 引用 columns.key。'},
 Messages:{props:z.object({...records,headline:z.string(),body:z.string(),meta:z.array(z.string())}).strict(),description:'通用邮件、消息、评论或文本记录。headline、body、meta 是相对单条记录的 JSON Pointer。'},
 Detail:{props:z.object({title:z.string(),value:z.unknown()}).strict(),description:'单个对象、空结果或无法可靠映射的数据；value 用 $state 引用原始数据。'}
},actions:{}});
