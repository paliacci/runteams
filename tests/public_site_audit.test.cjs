const test=require('node:test');
const assert=require('node:assert/strict');
const {audit}=require('../agent_skills/runteams-work-execution/public-site-audit/audit.cjs');
const {publicURL}=require('../agent_skills/runteams-work-execution/public-site-audit/public-web.cjs');
const origin='https://example.org';
function pages(routes){
  return async url=>{
    assert.equal(url.origin,origin);
    const [status,body='',headers={}]=routes[url.pathname]||[404];
    return {status,body:Buffer.from(body),headers:{'content-type':'text/html',...headers}};
  };
}
test('observations remain tied to sampled pages; denied, redirected and missing pages are accounted for',async()=>{
 const read=pages({
  '/robots.txt':[200,'User-agent: *\nDisallow: /private'],
  '/':[200,'<title>Demo &amp; Co</title><h1>Hello</h1><a href="/page">x</a><a href="/private">y</a><a href="/gone">z</a><a href="/outside">q</a>'],
  '/page':[200,'<title>Demo &amp; Co</title><meta name=description content="Real description"><script>"<h1>fake</h1>"</script>'],
  '/outside':[302,'',{location:'https://other.example.org/'}],
 });
 const report=await audit(origin,5,read);
 assert.equal(report.htmlPages,2);
 assert.equal(report.urlsAttempted,5);
 assert.deepEqual(report.findings.find(f=>f.type==='duplicate_title').urls,[origin+'/',origin+'/page']);
 assert.equal(report.pages[1].observed.h1Count,0);
 assert.equal(report.pages[2].state,'robots_disallowed');
 assert.equal(report.pages[3].status,404);
 assert.equal(report.pages[4].state,'unavailable');
 assert.equal(report.queuedNotVisited,0);
});
test('failed robots check produces an explicit coverage gap, with no invented finding',async()=>{
 const report=await audit(origin,5,pages({'/robots.txt':[503]}));
 assert.equal(report.htmlPages,0); assert.equal(report.pages[0].state,'unavailable');
 assert.equal(report.robots[0].status,503);assert.equal(report.findings.length,0);
});
test('limits sampling while preserving discovery counts',async()=>{
 const report=await audit(origin,1,pages({'/':[200,'<title>Hi</title><a href="/a"></a><a href="/b"></a>']}));
 assert.equal(report.htmlPages,1);assert.equal(report.queuedNotVisited,2);
});
test('the audit accepts public HTTP(S) targets only',()=>{
 for(const u of ['http://localhost','https://127.0.0.1','http://169.254.169.254','http://[::1]','https://user:pass@example.org','file:///tmp/x','https://example.org:9999'])assert.throws(()=>publicURL(u));
});

test('quotes main copy, labels entry points and separates sitemap discovery from observation',async()=>{
  const markup='<header><a href="/account">Account</a></header><main><h1>Learn</h1><h2>Connect an agent</h2>'+
    '<p>Choose an agent and verify the connection.</p><p hidden>Private looking text</p>'+
    '<a href="/guide">Connection guide</a><button>Find an employee</button></main><footer>Footer only</footer>';
  const sitemap='<urlset><url><loc>https://example.org/other</loc></url></urlset>';
  const report=await audit(origin,2,pages({'/':[200,markup],'/guide':[200,'<p>Read the steps first.</p>'],
    '/sitemap.xml':[200,sitemap,{'content-type':'application/xml'}]}));
  const body=report.pages[0].observed.content;
  assert.deepEqual(body.headings,['Learn','Connect an agent']);
  assert.deepEqual(body.passages,['Choose an agent and verify the connection.']);
  assert.deepEqual(body.controls,['Find an employee']);
  assert.deepEqual(body.links,[{text:'Connection guide',url:origin+'/guide'}]);
  assert.equal(report.pages[1].url,origin+'/guide');
  assert.deepEqual(report.sitemap.examples,[origin+'/other']);
  assert.equal(report.htmlPages,2);
});

test('a 200 placeholder retains its conflicting title and visible message',async()=>{
  const result=await audit(origin,1,pages({'/':[200,'<title>Example item</title><main><h1>Listing unavailable</h1><a href="/">Back to home</a></main>']}));
  const page=result.pages[0];
  assert.equal(page.status,200);
  assert.deepEqual(page.observed.titles,['Example item']);
  assert.match(page.observed.content.excerpt,/Listing unavailable/);
});
