## What changed

<!-- Describe the user-facing or maintenance change in a few sentences. -->

## Why

<!-- Link the issue or explain the problem this solves. -->

## Scope

- [ ] Core behavior
- [ ] Agent adapter
- [ ] Persistence or recovery
- [ ] Protocol or contract
- [ ] Desktop packaging
- [ ] Documentation or tests

## Validation

<!-- Include commands and the result. -->

```text
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Checklist

- [ ] I searched for related issues and kept this PR focused.
- [ ] I added or updated tests where behavior changed.
- [ ] I updated documentation or contracts where needed.
- [ ] I did not commit credentials, personal data, generated bundles, or local runtime state.
- [ ] I considered compatibility and migration impact.
