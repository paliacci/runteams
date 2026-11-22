import React from 'react';
export const EditorLanguage=React.createContext('zh-CN');
export function useCopy(){
 const language=React.useContext(EditorLanguage);
 return (zh,en)=>language==='en'?en:zh;
}

const editorErrors=new Map([
 ['内容已变化，请重新选择插入位置。','The document changed. Select where to insert the content and try again.'],
 ['插入位置已变化。','The insertion point changed. Select a new location and try again.'],
 ['请选择图片文件。','Choose an image file.'],
 ['请输入完整网址，例如 https://example.com。','Enter a full URL, such as https://example.com.'],
 ['仅支持网页和邮件链接。','Use a web or email link.'],
 ['公式语法有误，请检查括号和命令。','Check the equation for missing brackets or invalid commands.'],
 ['请输入公式。','Enter an equation.'],
 ['这次操作未完成，请重试。','Couldn’t complete the action. Try again.'],
 ["附件读取失败。","Couldn’t read the attachment."],
 ["请选择不超过20 MB的非空文件。","Choose a nonempty file up to 20 MB."],
 ["操作结果尚未确认，请保留当前内容后重试。","The result is unconfirmed. Keep your current content and try again."],
 ["浏览器无法访问剪贴板。","The clipboard is unavailable."],
 ["数据来源缺失，未复制不完整的内容。","The data source is missing. Nothing was copied."],
 ["内容格式不完整。","The content format is incomplete."],
 ["包含当前编辑器不支持的内容。","The content includes blocks this editor doesn’t support."],
 ["数据来源缺失。","The data source is missing."],
 ["插入位置已变化，请重新选择。","The insertion point changed. Select a new location."],
 ["当前浏览器无法复制完整内容，请使用导出文档。","Export the document to copy the complete content."],
 ["当前内容已变化，请重新选择。","The content changed. Select it again."],
 ["内容已复制，但原内容已变化，因此没有剪切。","The content was copied. The original changed and is still in place."],
 ["复制的内容过大，请使用导出文档。","The copied content is too large. Export the document instead."],
 ["复制的内容不完整，请重新复制。","The copied content is incomplete. Copy it again."],
 ["这份数据无法作为表格打开，原始内容仍保留。","This data can’t be opened as a table. The original content is preserved."],
 ["编辑副本中的待修正数据无法读取，原始内容仍保留。","Couldn’t read pending corrections in the edited copy. The original data is preserved."],
 ["编辑副本暂时无法读取，原始内容仍保留。","Couldn’t read the edited copy. The original data is preserved."],
 ["单元格已发生变化，请重新选择。","The cell changed. Select it again."],
 ["请输入有效数字。","Enter a valid number."],
 ["列名不能为空。","Enter a column name."],
 ["已有同名列，请换一个名称。","That column name is already in use. Choose another name."],
 ["请填写不重复的列名。","Enter a unique column name."],
 ["请至少保留一列。","Keep at least one column."],
 ["这次修改未完成，请重试。","Couldn’t complete the change. Try again."]
]);

export function useEditorError(){
 const copy=useCopy();
 return message=>copy(message,editorErrors.get(message)||message);
}
