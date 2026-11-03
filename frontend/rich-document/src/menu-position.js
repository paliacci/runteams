// Keep the popup centered on its trigger until a viewport edge prevents it.
export function menuBounds(rect,width,height,viewport,submenu=false){
 const edge=8,availableHeight=Math.max(0,viewport.height-edge*2),actualHeight=Math.min(height,availableHeight);
 let left=submenu?rect.right-1:rect.left-width-4;
 if(!submenu&&left<edge)left=rect.right+4;
 if(submenu&&left+width>viewport.width-edge)left=rect.left-width+1;
 left=Math.max(edge,Math.min(left,viewport.width-width-edge));
 const preferred=submenu?rect.top:(rect.top+rect.bottom-actualHeight)/2;
 return {left,top:Math.max(edge,Math.min(preferred,viewport.height-actualHeight-edge))};
}

// Replace the library's heading-specific first-line centering offsets with
// the top of the block's own rendered content, excluding nested child blocks.
export const contentTopMiddleware={
 name:'contentTop',
 fn({y,elements}){
  const reference=elements.reference,block=reference.contextElement||reference;
  const content=block.querySelector(':scope > .bn-block-content, :scope > .bn-react-node-view-renderer > .bn-block-content')||block;
  const child=content.querySelector(':scope > .rich-widget > .widget-title-input')||content.firstElementChild,childRect=child?.getBoundingClientRect();
  const rect=childRect?.height?childRect:content.getBoundingClientRect();
  return {y:y+rect.top-reference.getBoundingClientRect().top};
 }
};
