import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('sidebar team creation opens an editable new conversation with the localized team prompt', async () => {
 const calls=[];
 const context={addEventListener(){},document:{addEventListener(){}},setInterval(){},
  newRailChat:async options=>calls.push(options),RunTeamsLocale:{t:key=>{
   assert.equal(key,'newConversation.pipelinePrompt');return 'Create a team for:';
  }}};
 context.window=context;
 vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/source-pipelines.js',import.meta.url),'utf8'),context);
 await context.RunTeamsSourcePipelines.newPipeline();
 assert.equal(calls.length,1);
 assert.equal(calls[0].draft,'Create a team for:');
});
