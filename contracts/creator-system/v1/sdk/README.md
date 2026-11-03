# @runteams/creator-sdk 1.0.0

接口定稿，未发布到包仓库、未接入产品。19个方法的参数以 ../methods.json 为准，类型见 client.d.ts。ESM 使用 client.mjs；受控Javy构建器可嵌入 client.js。两者由同一份实现生成，没有第三方依赖、环境I/O或凭据读取。

```ts
import {createRunTeamsSDK} from './client.mjs';
const rt = createRunTeamsSDK(trustedTransport);
rt.negotiate(['connection.http']);
const drafts = rt.connection.http({
  connection: 'gmail', endpoint: 'drafts.list',
  query: {q: 'subject:runteams-creator-v1-example', maxResults: 20}
});
```

trustedTransport由宿主提供，不能由作品自己伪造权限。业务Wasm通过专用管道，浏览器适配器未来通过经过身份校验的frame桥；不是把凭据交给前端fetch。请求、响应、错误和限制见 ../SPEC.md。

本轮真实实现/验收：通用 connection.http/status 的宿主代理、Supabase临时权限及回执、独立OAuth、真实Gmail草稿。其余source/data/work/events/host方法的客户端和接口合同存在，但产品服务适配器还未接入；协商必须拒绝未实现能力。不要用接口存在冒充后端已实现。

测试范围：Node客户端18项、TypeScript全部方法调用和6个负向类型用例；完整来源合同、TLS夹具、冻结Wasm和真实Gmail分别单列。测试脚本位于 ../../lab/round8，证据在 ../../evidence/round8。
