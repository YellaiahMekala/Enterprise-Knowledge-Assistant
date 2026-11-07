export interface SseEvent {
  event: string;
  data: unknown;
}

// Splits a buffer into complete server-sent events. Whatever follows the last blank line comes
// back as `rest`, to be prepended to the next chunk. Comment lines (heartbeats) are skipped.
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n');
  const rest = blocks.pop() ?? '';
  const events: SseEvent[] = [];
  for (const block of blocks) {
    let event = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (data.length > 0) events.push({ event, data: JSON.parse(data.join('\n')) });
  }
  return { events, rest };
}
