// Standard MCP Apps author code plus the existing, unchanged UI Kit.
import {App} from '@modelcontextprotocol/ext-apps';
import {createSection} from '../ui/index.js';

const app = new App({name: '计算验收', version: '1.0.0'}, {});
const content = document.createElement('div');
content.innerHTML = '<div class="rt-form-row"><label>第一个数<input id="first" class="rt-input" type="number" value="3"></label></div>' +
  '<div class="rt-form-row"><label>第二个数<input id="second" class="rt-input" type="number" value="4"></label></div>' +
  '<button id="calculate" class="rt-button rt-primary-button" disabled>计算</button>' +
  '<p id="result" role="status">正在准备</p>';
document.body.append(createSection({title: '计算', content}).element);
const button = document.getElementById('calculate');
const theme = context => {document.documentElement.dataset.theme = context?.theme ?? 'light';};
app.onhostcontextchanged = theme;
app.ontoolinput = () => {button.disabled = false; document.getElementById('result').textContent = '输入数字后计算';};
button.addEventListener('click', async () => {
  button.disabled = true;
  try {
    const result = await app.callServerTool({name: 'calculate', arguments: {
      a: Number(document.getElementById('first').value), b: Number(document.getElementById('second').value)}});
    document.getElementById('result').textContent = '结果：' + result.structuredContent.total;
  } catch {
    document.getElementById('result').textContent = '结果未确认，请先核对原操作';
  } finally {button.disabled = false;}
});
app.connect().then(() => theme(app.getHostContext()));
