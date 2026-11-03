export const isJsonPath = path => /\.json$/i.test(String(path || ""));

// Only whitespace is rewritten. Parsing and reserializing would round large
// numbers, normalize number literals and discard duplicate object keys.
export function formatJsonForDisplay(path, value) {
  const source = String(value ?? "");
  if (!isJsonPath(path)) return source;
  try { JSON.parse(source); } catch { return source; }
  const tokens = source.match(/"(?:\\[\s\S]|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:]+/g) || [];
  const output = [];
  let depth = 0;
  const line = () => output.push("\n", "  ".repeat(depth));
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token === "{" || token === "[") {
      output.push(token);
      if (tokens[index + 1] !== (token === "{" ? "}" : "]")) {
        if (++depth > 256) return source;
        line();
      }
    } else if (token === "}" || token === "]") {
      if (tokens[index - 1] !== (token === "}" ? "{" : "[")) {
        depth--;
        line();
      }
      output.push(token);
    } else if (token === ",") {
      output.push(token);
      line();
    } else if (token === ":") output.push(": ");
    else output.push(token);
  }
  return output.join("");
}
