import { test } from "node:test";
import assert from "node:assert/strict";
import { formatJsonForDisplay } from "./json-display.mjs";

test("JSON objects and arrays display with two-space indentation", () => {
  const source = '{"name":"员工","skills":[{"enabled":true},null],"empty":{}}';
  const displayed = formatJsonForDisplay("employees/main.json", source);
  assert.equal(displayed, '{\n  "name": "员工",\n  "skills": [\n    {\n      "enabled": true\n    },\n    null\n  ],\n  "empty": {}\n}');
  assert.deepEqual(JSON.parse(displayed), JSON.parse(source));
  assert.equal(formatJsonForDisplay("employees/main.JSON", displayed), displayed);
});

test("display preserves number literals, key order, duplicate keys and escaped strings", () => {
  const source = '{"z":900719925474099312345,"n":1.00e+400,"z":-0,"text":"a \\" b \\n {} [,]"}';
  assert.doesNotThrow(() => JSON.parse(source));
  const displayed = formatJsonForDisplay("data.json", source);
  assert.ok(displayed.startsWith("{\n"));
  assert.equal(displayed.replace(/\n */g, "").replace(/: /g, ":"), source);
});

test("invalid JSON and other file formats remain readable verbatim", () => {
  for (const [path, source] of [["bad.json", '{"unfinished":'], ["script.js", '{"a":1}'], ["SOUL.md", "  原始正文\n"]]) {
    assert.equal(formatJsonForDisplay(path, source), source);
  }
});

test("empty containers and scalar JSON stay valid without extra blank lines", () => {
  for (const source of ["{}", "[]", "null", '"含空格  : ,"', "[{},[],2]"]) {
    const displayed = formatJsonForDisplay("data.json", source);
    assert.deepEqual(JSON.parse(displayed), JSON.parse(source));
    assert.ok(!displayed.includes("\n\n"));
  }
});

test("extreme nesting keeps the original text instead of expanding indentation", () => {
  const source = "[".repeat(257) + "0" + "]".repeat(257);
  assert.equal(formatJsonForDisplay("data.json", source), source);
});
