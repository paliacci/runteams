/* Display grouping only. Conversation storage, runtime and authorization stay per chat. */
(function(root){
 'use strict';
 function identity(panel,state={},employee=null){
  if(panel?.kind!=='general'||panel.debug_preview||!root.RunTeamsHost.session.ready(state))return null;
  const reference=panel.employee_binding?.reference||panel.context?.source_employee||panel.context?.employee_reference||panel.work_employee?.reference;
  if(!reference)return null;
  if(reference.storage_kind==='local'){
   if(root.RunTeamsHost.session.workspace(state)||reference.schema!=='runteams.local-employee-reference/1'||reference.library_id!==root.RunTeamsHost.session.libraryId(state))return null;
   const fields=['schema','source_id','employee_source','storage_kind','library_id'];if(fields.some(key=>!reference[key]))return null;
   return {key:JSON.stringify(fields.map(key=>reference[key])),reference:Object.fromEntries(fields.map(key=>[key,reference[key]])),name:employee?.name||panel.employee_binding?.name||panel.context?.worker_name||''};
  }
  return root.RunTeamsHost.resources.employeeIdentity?.(panel,state,employee)||null;
 }
 function coalesce(rows,activeKey,identify){
  const result=[],groups=new Map(),keys=new Set();
  for(const row of rows){
   if(keys.has(row.key))continue;keys.add(row.key);
   const employee=identify(row),group=employee?'employee:'+employee.key:'window:'+row.key;
   const candidate=employee?{...row,employeeReference:employee.reference,employeeName:employee.name||row.employeeName||'',title:employee.name||row.employeeName||'员工'}:row;
   if(!groups.has(group)){groups.set(group,result.length);result.push(candidate);continue;}
   const index=groups.get(group),previous=result[index];
   if(row.key===activeKey||previous.key!==activeKey&&Number(row.lastActiveAt||0)>Number(previous.lastActiveAt||0))result[index]=candidate;
  }
  return result;
 }
 const api={identity,coalesce};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.RunTeamsEmployeeWindows=api;
})(globalThis);
