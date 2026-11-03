/* Private pipes are provided by the helper, never user terminal or environment. */
const enc = new TextEncoder(), dec = new TextDecoder();
function emit(value) {
  const raw = enc.encode(JSON.stringify(value) + '\n');
  let offset = 0;
  while (offset < raw.length) offset += Javy.IO.writeSync(1, raw.subarray(offset));
}
function receive(limit = 16384) {
  const bytes = [], one = new Uint8Array(1);
  while (bytes.length <= limit) {
    if (!Javy.IO.readSync(0, one)) throw Error('bridge_closed');
    if (one[0] === 10) return JSON.parse(dec.decode(new Uint8Array(bytes)));
    bytes.push(one[0]);
  }
  throw Error('frame_limit');
}
const boot = receive(128 * 1024), session = boot.session;
let sequence = 0;
function exchange(payload) {
  const seq = ++sequence;
  emit({kind: 'invoke', session, seq, operation: 'sdk.exchange', payload});
  const reply = receive();
  if (reply.session !== session || reply.seq !== seq || reply.error) throw Error(reply.error || 'wrong_reply');
  return reply.value;
}
function result(value) { emit({kind: 'result', session, value}); }
