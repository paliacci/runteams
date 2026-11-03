let sequence = 0;
export const nextId = () => `rt-module-${++sequence}`;
export function element(doc, tag, className, text) {
  const node = doc.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
export function button(doc, label, kind = '') {
  const node = element(doc, 'button', `rt-button ${kind}`, label);
  node.type = 'button';
  return node;
}
export function icon(doc, kind) {
  const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', kind === 'expand' ? '0 0 20 20' : kind === 'collapse' ? '0 0 16 16' : '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = doc.createElementNS(svg.namespaceURI, 'path');
  if (kind === 'collapse') {
    const group = doc.createElementNS(svg.namespaceURI, 'g');
    group.setAttribute('transform', 'translate(16 0) scale(-1 1)');
    path.setAttribute('d', "M11.5 2.30762C13.1707 2.30762 14.5254 3.66235 14.5254 5.33301V10.666C14.5254 12.3367 13.1707 13.6914 11.5 13.6914H4.5C2.82934 13.6914 1.47461 12.3367 1.47461 10.666V5.33301C1.47461 3.66235 2.82934 2.30762 4.5 2.30762H11.5ZM6.52539 12.6416H11.5C12.5908 12.6416 13.4746 11.7568 13.4746 10.666V5.33301C13.4746 4.24225 12.5908 3.3584 11.5 3.3584H6.52539V12.6416ZM4.5 3.3584C3.40924 3.3584 2.52539 4.24225 2.52539 5.33301V10.666C2.52539 11.7568 3.40924 12.6416 4.5 12.6416H5.47461V3.3584H4.5Z");
    path.setAttribute('fill', 'currentColor');path.setAttribute('stroke', 'none');path.setAttribute('fill-rule', 'evenodd');
    group.append(path);svg.append(group);return svg;
  }
  path.setAttribute('d', kind === 'expand' ? 'M7 3H3v4m0-4 5 5m5-5h4v4m0-4-5 5M3 13v4h4m-4 0 5-5m9 1v4h-4m4 0-5-5' : 'm15 18-6-6 6-6');
  svg.append(path);
  return svg;
}
