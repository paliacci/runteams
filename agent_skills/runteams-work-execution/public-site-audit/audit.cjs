'use strict';
const {parse, robotsParser} = require('./vendor/web.cjs');
const {publicURL, read, decode} = require('./public-web.cjs');
const {setTimeout: sleep} = require('node:timers/promises');
const {pageEvidence, descendants, excerpt} = require('./page-evidence.cjs');
const bot = 'RunTeamsSEOBot';
const redirects = new Set([301,302,303,307,308]);
const tidy = text => text.replace(/\s+/g,' ').trim();
function pageData(markup, url, headers) {
  const root = parse(markup), nodes = [root];
  const titles=[], descriptions=[], headings=[], canonicals=[], robots=[], hrefs=[];
  let base;
  const textOf = node => tidy((node.childNodes || []).map(n=>n.nodeName==='#text'?n.value:textOf(n)).join(' '));
  while(nodes.length) {
    const n=nodes.pop(), tag=n.tagName;
    if (['template','script','style','noscript','svg'].includes(tag)) continue;
    const a=Object.fromEntries((n.attrs||[]).map(attr=>[attr.name,attr.value]));
    if(tag==='title') titles.push(textOf(n));
    if(tag==='h1') headings.push(textOf(n));
    if(tag==='base' && base===undefined && a.href) base=a.href;
    if(tag==='a' && a.href && hrefs.length<1500) hrefs.push(a.href);
    if(tag==='meta' && a.name?.toLowerCase()==='description') descriptions.push(tidy(a.content||''));
    if(tag==='meta' && ['robots','googlebot'].includes(a.name?.toLowerCase())) robots.push({name:a.name,content:a.content||''});
    if(tag==='link' && (a.rel||'').toLowerCase().split(/\s+/).includes('canonical')) canonicals.push(a.href||'');
    const children=n.childNodes||[];
    for(let i=children.length-1;i>=0;i--) nodes.push(children[i]);
  }
  let baseURL=url;
  try{if(base)baseURL=new URL(base,url);}catch{}
  const links=new Set();
  for(const href of hrefs) {
    try{
      const dest=publicURL(href,baseURL);
      if(dest.origin===url.origin && !/\.(?:jpe?g|png|gif|svg|ico|pdf|zip|woff2?|mp[34]|webp)$/i.test(dest.pathname)) links.add(dest.href);
    }catch{}
  }
  const sample=items=>items.slice(0,3).map(v=>v.slice(0,240));
  return {observed:{titleCount:titles.length,titles:sample(titles),descriptionCount:descriptions.length,descriptions:sample(descriptions),
    h1Count:headings.length,h1:sample(headings),canonicals:sample(canonicals),robots:robots.slice(0,4).map(r=>({...r,content:r.content.slice(0,200)})),
    xRobotsTag:(headers['x-robots-tag']||'').slice(0,240), content:pageEvidence(root, baseURL, url.origin)}, links};
}

async function audit(input, limit=5, request=read) {
  const start=publicURL(input.includes('://')?input:'https://'+input), startedAt=new Date().toISOString();
  const deadline=Date.now()+29000, queue=[start], discovered=new Set([start.href]), pages=[], findings=[];
  const policies=new Map(), inspected=new Set(), bodyLinks=new Set();
  const scopeHost=start.hostname.replace(/^www\./,'');
  const inScope=url=>url.hostname.replace(/^www\./,'')===scopeHost;
  async function rulesFor(url) {
    if(policies.has(url.origin)) return policies.get(url.origin);
    const origin=url.origin, robotsURL=new URL('/robots.txt',origin);
    let current=robotsURL, policy={url:robotsURL.href,last:0};
    try {
      for(let i=0;i<=3;i++){
        const res=await request(current,deadline,512000);
        policy.status=res.status;
        if(redirects.has(res.status)&&res.headers.location){
          current=publicURL(res.headers.location,current);
          if(!inScope(current)||i===3)throw Error('robots.txt 重定向超出范围。');
          continue;
        }
        if(res.status===404||res.status===410) break;
        if(res.status<200||res.status>=300)throw Error('robots.txt 暂不可用。');
        policy.parser=robotsParser(robotsURL.href,decode(res,false));break;
      }
    }catch(e){policy.error=e.message;}
    policies.set(origin,policy);return policy;
  }
  async function siteMap(origin) {
    const policy = await rulesFor(new URL(origin));
    if (policy.error) return;
    const candidates = policy.parser?.getSitemaps() || [];
    const raw = candidates[0] || new URL('/sitemap.xml', origin).href;
    try {
      const url = publicURL(raw, origin);
      if (url.origin !== origin || policy.parser?.isAllowed(url.href, bot) === false) return;
      const delay = (policy.parser?.getCrawlDelay(bot) || 0) * 1000;
      if (Date.now() < policy.last + delay) return;
      policy.last = Date.now();
      const res = await request(url, deadline, 512000);
      if (res.status !== 200) return;
      const tree = parse(decode(res, false));
      const nodes = [...descendants(tree)];
      const index = nodes.some(node => node.tagName === 'sitemapindex');
      if (!index && !nodes.some(node => node.tagName === 'urlset')) return;
      const urls = new Set();
      for (const node of nodes) {
        if (node.tagName !== 'loc') continue;
        try {
          const target = publicURL(excerpt(node, 2048));
          if (target.origin === origin) urls.add(target.href);
        } catch {}
      }
      return {url:url.href, kind:index ? 'index' : 'urlset', count:urls.size, examples:[...urls].slice(0,55)};
    } catch { return; }
  }

  async function inspect(seed) {
    const row={requestedUrl:seed.href,url:seed.href,checkedAt:new Date().toISOString(),redirects:[]};
    pages.push(row);
    let url=seed;
    try{
      for(let hop=0;hop<=4;hop++){
        row.url=url.href;
        if(inspected.has(url.href)){row.state='already_checked';return;}
        const policy=await rulesFor(url);
        if(policy.error)throw Error(policy.error);
        if(policy.parser?.isAllowed(url.href,bot)===false){row.state='robots_disallowed';return;}
        const wait=policy.last+(policy.parser?.getCrawlDelay(bot)||0)*1000-Date.now();
        if(wait>0){if(Date.now()+wait>=deadline)throw Error('抓取间隔超过本次采样时间。'); await sleep(wait);}
        policy.last=Date.now();
        const res=await request(url,deadline,2*1024*1024);
        row.status=res.status;
        if(redirects.has(res.status)&&res.headers.location){
          const next=publicURL(res.headers.location,url);
          row.redirects.push({from:url.href,status:res.status,to:next.href});
          if(!inScope(next)||hop===4)throw Error('页面重定向超出本站采样范围。');
          url=next;continue;
        }
        inspected.add(url.href);
        if(res.status<200||res.status>=300){row.state='http_error';return;}
        if(!/^text\/html\b|^application\/xhtml\+xml\b/i.test(res.headers['content-type']||'')){row.state='non_html';return;}
        const {observed,links}=pageData(decode(res,true),url,res.headers);
        row.observed=observed;row.state='html';
        for (const link of observed.content.links) bodyLinks.add(link.url);
        for(const link of links)if(!discovered.has(link)){discovered.add(link);queue.push(new URL(link));}
        const note=(type,field)=>findings.push({type,urls:[url.href],field});
        if(!observed.titles[0])note('missing_or_empty_title','titles');
        if(!observed.descriptions[0])note('missing_or_empty_description','descriptions');
        if(!observed.h1Count)note('missing_h1','h1Count');
        return;
      }
    }catch(e){row.state='unavailable';row.reason=String(e.message).slice(0,220);}
  }
  let sitemap;
  while (queue.length && pages.length < limit && Date.now() < deadline) {
    // Prefer an in-content destination and a fresh branch over repeated navigation links.
    const families = new Set(pages.map(page => new URL(page.url).pathname.split('/')[1]));
    const score = url => Number(bodyLinks.has(url.href)) * 2 +
      Number(!families.has(url.pathname.split('/')[1]));
    queue.sort((a,b) => score(b) - score(a));
    await inspect(queue.shift());
    if (pages.length === 1 && pages[0].state === 'html' && limit > 1) {
      sitemap = await siteMap(new URL(pages[0].url).origin);
    }
  }
  const html=pages.filter(p=>p.state==='html'), byTitle=new Map();
  for(const page of html){
    const title=page.observed.titles[0];
    if(!title||title.length>=240)continue;
    if(!byTitle.has(title))byTitle.set(title,[]);
    byTitle.get(title).push(page.url);
  }
  for(const [value,urls] of byTitle)if(urls.length>1)findings.push({type:'duplicate_title',field:'titles',value,urls});
  return {startUrl:start.href,startedAt,finishedAt:new Date().toISOString(),mode:'public_static_html',sampleLimit:limit,
    urlsAttempted:pages.length,htmlPages:html.length,queuedNotVisited:queue.length,sitemap,robots:[...policies.values()].map(({url,status,error})=>({url,status,error})),pages,findings};
}
module.exports={audit,pageData};
