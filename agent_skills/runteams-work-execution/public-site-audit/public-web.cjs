'use strict';
const http = require('node:http');
const https = require('node:https');
const dns = require('node:dns');
const net = require('node:net');
const {ipaddr} = require('./vendor/web.cjs');

function publicURL(value, base) {
  const url = new URL(value, base);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port)
    throw Error('仅接受标准 HTTP(S) 端口上的公开网页。');
  const host = url.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '');
  if (net.isIP(host)) requirePublicIP(host);
  else if (!host.includes('.') || /(?:^|\.)(?:localhost|local|internal|onion)$/.test(host))
    throw Error('仅接受公网地址。');
  url.hash = '';
  return url;
}

function requirePublicIP(value) {
  const addr = ipaddr.parse(value);
  if (addr.range() !== 'unicast' || (addr.kind() === 'ipv6' && !addr.match(ipaddr.parse('2000::'), 3)))
    throw Error('地址不属于公网。');
}

// Some desktop DNS proxies synthesize all IPv4 answers in RFC 2544 space.
// Ask for actual A/AAAA records only for that case; never connect to the synthetic address.
async function resolveSynthetic(host) {
  const answers = await Promise.all(['A', 'AAAA'].map(async type => {
    const endpoint = new URL('https://dns.google/resolve');
    endpoint.search = new URLSearchParams({name:host, type}).toString();
    const response = await fetch(endpoint, {redirect:'error', signal:AbortSignal.timeout(3500)});
    if (!response.ok) throw Error('公开域名解析失败。');
    const reply = await response.json();
    if (reply.Status !== 0) throw Error('公开域名解析失败。');
    return (reply.Answer || []).filter(r=>r.type===(type==='A'?1:28)).map(r=>({address:r.data,family:type==='A'?4:6}));
  }));
  return answers.flat();
}

// Resolve and validate at socket creation, including every redirect.
function publicLookup(host, options, callback) {
  dns.lookup(host, {all: true, verbatim: false}, async (error, records) => {
    if (error) return callback(error);
    try {
      if (records.length && records.every(r=>r.family===4 && /^198\.(18|19)\./.test(r.address))) records = await resolveSynthetic(host);
      if (!records.length) throw Error('域名没有可用地址。');
      for (const record of records) requirePublicIP(record.address);
    } catch (reason) { return callback(reason); }
    if (options.all) return callback(null, records);
    const record = records.find(item => !options.family || item.family === options.family);
    if (!record) return callback(Error('域名没有匹配的地址。'));
    callback(null, record.address, record.family);
  });
}

function read(url, deadline, maxBytes) {
  const remaining = Math.min(6500, deadline - Date.now());
  if (remaining <= 0) throw Error('本次采样时间已用完。');
  const transport = url.protocol === 'https:' ? https : http;
  return new Promise((resolve, reject) => {
    const req = transport.get(url, {
      agent: false, lookup: publicLookup, signal: AbortSignal.timeout(remaining),
      headers: {'user-agent': 'RunTeamsSEOBot/1.0', accept: 'text/html,text/plain;q=0.9,*/*;q=0.1', 'accept-encoding': 'identity'}
    }, res => {
      const status = res.statusCode, headers = res.headers;
      const done = body => resolve({status, headers, body});
      if (status < 200 || status >= 300) { done(Buffer.alloc(0)); res.destroy(); return; }
      const chunks = [];
      let size = 0;
      res.on('error', reject);
      res.on('data', chunk => {
        size += chunk.length;
        if (size > maxBytes) { reject(Error('响应超过采样大小限制。')); res.destroy(); }
        else chunks.push(chunk);
      });
      res.on('end', () => done(Buffer.concat(chunks)));
    });
    req.on('error', reject);
  });
}

function decode({headers, body}, html) {
  if (headers['content-encoding'] && headers['content-encoding'] !== 'identity') throw Error('不支持该响应编码。');
  const charset = /charset\s*=\s*["']?([\w.-]+)/i.exec(headers['content-type'] || '')?.[1]
    || (html && /<meta\s[^>]*?charset\s*=\s*["']?([\w.-]+)/i.exec(body.subarray(0,1024).toString('latin1'))?.[1]) || 'utf-8';
  return new TextDecoder(charset).decode(body);
}
module.exports = {publicURL, read, decode};
