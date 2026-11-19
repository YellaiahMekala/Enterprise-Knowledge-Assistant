// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { parseSse } from './sse';

describe('parseSse', () => {
  it('returns complete events and keeps the unfinished tail', () => {
    const { events, rest } = parseSse('event: token\ndata: {"text":"a"}\n\nevent: tok');
    expect(events).toEqual([{ event: 'token', data: { text: 'a' } }]);
    expect(rest).toBe('event: tok');
  });

  it('skips heartbeat comments', () => {
    const { events } = parseSse(': heartbeat\n\nevent: done\ndata: {"ok":true}\n\n');
    expect(events).toEqual([{ event: 'done', data: { ok: true } }]);
  });

  it('handles CRLF line endings', () => {
    const { events } = parseSse('event: meta\r\ndata: {"mode":"fast"}\r\n\r\n');
    expect(events).toEqual([{ event: 'meta', data: { mode: 'fast' } }]);
  });

  it('joins multi-line data', () => {
    const { events } = parseSse('event: x\ndata: {"a":\ndata: 1}\n\n');
    expect(events[0].data).toEqual({ a: 1 });
  });

  it('keeps an event whole when it is split across chunks', () => {
    const first = parseSse('event: token\ndata: {"te');
    const second = parseSse(first.rest + 'xt":"b"}\n\n');
    expect(first.events).toEqual([]);
    expect(second.events).toEqual([{ event: 'token', data: { text: 'b' } }]);
  });
});
