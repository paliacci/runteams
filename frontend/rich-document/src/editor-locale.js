import React from 'react';
export const EditorLanguage=React.createContext('zh-CN');
export function useCopy(){
 const language=React.useContext(EditorLanguage);
 return (zh,en)=>language==='en'?en:zh;
}
