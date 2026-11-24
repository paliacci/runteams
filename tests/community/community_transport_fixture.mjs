// Execute the shipped shared transport with an explicit test fetch/clock.
import fs from 'node:fs';
import vm from 'node:vm';
import {LocalClient} from '../../frontend/community/client.js';

export function sharedTransport(fetcher, timers = globalThis) {
  const context = {fetch:fetcher, URL, AbortController, performance, crypto,
    setTimeout:(...args)=>timers.setTimeout(...args),
    clearTimeout:(...args)=>timers.clearTimeout(...args)};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/requests.js',import.meta.url),'utf8'),context);
  return context.RunTeamsRequests;
}

export function createLocalClient(fetcher) {
  return new LocalClient({fetcher, request:sharedTransport(fetcher).request});
}

export function installSharedTransport(fetcher, timers = globalThis) {
  return globalThis.RunTeamsRequests = sharedTransport(fetcher,timers);
}
