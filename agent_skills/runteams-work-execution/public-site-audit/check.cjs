'use strict';
const {audit} = require('./audit.cjs');

audit(process.argv[2], Number(process.argv[3])).then(report => {
  process.stdout.write(JSON.stringify(report));
}).catch(error => {
  process.stderr.write(String(error.message).slice(0, 300));
  process.exitCode = 1;
});
