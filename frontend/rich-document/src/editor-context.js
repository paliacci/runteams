import {closeHistory} from '@tiptap/pm/history';
const contexts=new WeakMap();
export const registerEditor=(editor,value)=>contexts.set(editor,value);
export const editorContext=editor=>contexts.get(editor);
export function separateHistory(editor){editor.prosemirrorView.dispatch(closeHistory(editor.prosemirrorState.tr));}
export function walkBlocks(blocks,visit){for(const block of blocks){visit(block);if(block.children?.length)walkBlocks(block.children,visit);}}

export function visitBlockReferences(block,visit){
 function inline(content){
  if(!Array.isArray(content))return;
  for(const node of content){
   if(node?.type==='blockReference')visit(node.props);
   if(node?.type==='link')inline(node.content);
  }
 }
 if(block.type==='reference')visit(block.props);
 if(block.content?.type==='tableContent'){
  for(const row of block.content.rows)for(const cell of row.cells)inline(cell?.content||cell);
 }else inline(block.content);
}
// Older editors recorded the active revision as the owner of a block reference.
export function resolveDocumentReferences(blocks,doc){
 const root=String(doc.document_root_id||doc.id);
 const revisions=new Set([doc.id,...(doc.document_revision_ids||[])].map(String));
 revisions.delete(root);
 if(revisions.size)walkBlocks(blocks,block=>visitBlockReferences(block,props=>{
  if(revisions.has(String(props.documentId)))props.documentId=root;
 }));
}
export function blockLabel(block){
 if(!block)return '引用内容已删除';
 const text=Array.isArray(block.content)?block.content.map(n=>n.text||n.content?.map?.(x=>x.text||'').join('')||n.props?.label||'').join(''):'';
 return (text||block.props?.title||block.props?.name||block.props?.label||({columns:'分栏',column:'栏',math:'公式',image:'图片',video:'视频',file:'附件'}[block.type])||'内容块').slice(0,90);
}
export function locateBlock(editor,id){
 const node=[...(editor.domElement?.querySelectorAll('[data-id]')||[])].find(n=>n.dataset.id===id);
 if(!node)return false;
 node.scrollIntoView({block:'center',behavior:'smooth'});node.classList.add('rt-block-arrival');setTimeout(()=>node.classList.remove('rt-block-arrival'),1600);return true;
}
