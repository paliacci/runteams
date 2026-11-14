import {McpServer} from '@modelcontextprotocol/server';
import {z} from 'zod';

export function testServer() {
  const server = new McpServer({name:'RunTeams sample',version:'1.0.0'});
  server.registerTool('echo', {
    description:'Return the supplied text.',
    inputSchema:z.object({text:z.string().max(500)}),
    annotations:{readOnlyHint:true}
  }, async ({text}) => ({content:[{type:'text',text}],structuredContent:{text}}));
  server.registerTool('calculate', {
    description:'Add two numbers.',
    inputSchema:z.object({a:z.number(),b:z.number()}),
    annotations:{readOnlyHint:true}
  }, async ({a,b}) => {
    const total = a+b;
    return {content:[{type:'text',text:String(total)}],structuredContent:{total}};
  });
  return server;
}
