# Third-party notices

## replica-skill (the `replica-*` folders in this directory)

- Source: https://github.com/Jakeschincariol/replica-skill
- Version: 1.0.0, commit `77c9436fb3d18c3d58169efb8caf4fe906b0dc51` (2026-10-03)
- What was copied: the 11 `replica-*` skill folders, unmodified. The upstream
  `tests/`, README and plugin manifest were left out.
- License: MIT (full text below)

To update to a newer upstream version:

```bash
git clone --depth 1 https://github.com/Jakeschincariol/replica-skill.git /tmp/replica-skill
rm -rf .claude/skills/replica-*
cp -r /tmp/replica-skill/replica-* .claude/skills/
git diff --stat
```

Read the diff before you commit it. Skills are instructions Claude follows.

### License

MIT License

Copyright (c) 2026 Jake Schincariol

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
