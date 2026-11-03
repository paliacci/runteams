import {closeHistory} from '@tiptap/pm/history';
const contexts=new WeakMap();
export const registerEditor=(editor,value)=>contexts.set(editor,value);
export const editorContext=editor=>contexts.get(editor);
export function separateHistory(editor){editor.prosemirrorView.dispatch(closeHistory(editor.prosemirrorState.tr));}
export function walkBlocks(blocks,visit){for(const block of blocks){visit(block);if(block.children?.length)walkBlocks(block.children,visit);}}
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
