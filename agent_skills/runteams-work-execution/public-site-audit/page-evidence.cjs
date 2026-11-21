'use strict';
const {publicURL} = require('./public-web.cjs');

const tidy = text => text.replace(/\s+/g, ' ').trim();
const omitted = new Set(['template', 'script', 'style', 'head', 'noscript', 'svg']);
const chrome = new Set(['nav', 'footer', 'aside']);
const attr = (node, name) => node.attrs?.find(item => item.name === name)?.value;
const hidden = node => omitted.has(node.tagName) || attr(node, 'hidden') !== undefined ||
  attr(node, 'aria-hidden') === 'true';

function *descendants(root, exclude = () => false) {
  const nodes = [root];
  while (nodes.length) {
    const node = nodes.pop();
    if (exclude(node)) continue;
    yield node;
    const children = node.childNodes || [];
    for (let i = children.length - 1; i >= 0; i--) nodes.push(children[i]);
  }
}

function excerpt(root, length = 170) {
  let text = '';
  for (const node of descendants(root, hidden)) {
    if (node.nodeName === '#text') text += ' ' + tidy(node.value);
    if (text.length > length + 10) break;
  }
  return tidy(text).slice(0, length);
}

function pageEvidence(root, baseURL, origin) {
  const elements = [...descendants(root, hidden)];
  const main = elements.find(node => node.tagName === 'main' || attr(node, 'role') === 'main');
  const body = elements.find(node => node.tagName === 'body') || root;
  const headings = [], passages = [], links = [], controls = [];
  const seen = new Set();
  let textCharacters = 0, anchorCount = 0;
  for (const node of descendants(main || body, node => hidden(node) || chrome.has(node.tagName) ||
    (!main && node.tagName === 'header') || attr(node, 'role') === 'navigation')) {
    const tag = node.tagName;
    if (node.nodeName === '#text') textCharacters += tidy(node.value).length;
    if (/^h[1-4]$/.test(tag) && headings.length < 10) {
      const text = excerpt(node, 105);
      if (text) headings.push(text);
    }
    if (['p','li','dd','pre','blockquote'].includes(tag) && passages.length < 5) {
      const text = excerpt(node, 170);
      if (text.length >= 12 && !passages.includes(text)) passages.push(text);
    }
    if (tag === 'button' || attr(node, 'role') === 'button') {
      const label = attr(node, 'aria-label') || excerpt(node, 90);
      if (label && controls.length < 6) controls.push(label.slice(0,90));
    }
    if (tag !== 'a' || !attr(node, 'href') || attr(node,'href').startsWith('#')) continue;
    let target;
    try { target = publicURL(attr(node, 'href'), baseURL); } catch { continue; }
    if (target.origin !== origin) continue;
    anchorCount++;
    if (seen.has(target.href) || links.length >= 12) continue;
    seen.add(target.href);
    links.push({text:(excerpt(node, 76) || attr(node, 'aria-label') || '').slice(0,76), url:target.href});
  }
  return {region:main ? 'main' : 'body', textCharacters, headings, passages,
    ...(passages.length ? {} : {excerpt:excerpt(main || body,220)}),
    internalAnchorCount:anchorCount, links, controls};
}

module.exports = {pageEvidence, descendants, excerpt};
