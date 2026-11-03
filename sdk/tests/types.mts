import {createRuntime, operationKey as runtimeKey, type RuntimeHost} from 'runteams-runtime';
import {createViewClient, operationKey, type ViewBridge} from 'runteams-view';
declare const host: RuntimeHost;
declare const bridge: ViewBridge;
const runtime=createRuntime(host);
const view=createViewClient(bridge);
const row=runtime.data.query<{total: number}>({collection:'quote',limit:100}).items[0];
const revision: string=row.revision;
runtime.data.mutate({collection:'quote',operation_key:runtimeKey('save:1'),mutations:[{id:'q',base_revision:revision,value:{total:3}}]});
view.operation.invoke({operation:'save',input:{total:3},objects:[],operation_key:operationKey('save-1')});
// @ts-expect-error Runtime has no author-source access.
runtime.source.read({path:'employees/soul.md'});
// @ts-expect-error UI has no direct business collection access.
view.data.query({collection:'quote',limit:1});
// @ts-expect-error Collection revisions are strings, not UI revision numbers.
runtime.data.mutate({collection:'quote',operation_key:runtimeKey('save'),mutations:[{id:'q',base_revision:1,value:{}}]});
// @ts-expect-error UI revisions are numbers, not collection revisions.
view.context.update({base_context:'1',data:{}});
// @ts-expect-error A runtime key cannot be used as a view key.
view.operation.invoke({operation:'save',input:{},objects:[],operation_key:runtimeKey('save:1')});
// @ts-expect-error No result exists on the error branch.
view.context.read().then(reply=>reply.result);
