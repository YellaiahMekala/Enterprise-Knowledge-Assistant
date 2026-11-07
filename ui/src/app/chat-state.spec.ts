import { applyEvent, startAnswer } from './chat-state';

const event = (name: string, data: unknown) => ({ event: name, data });

describe('applyEvent', () => {
  it('records the conversation id from meta', () => {
    const state = applyEvent(startAnswer(null), event('meta', { conversation_id: 'c1', mode: 'fast' }));
    expect(state.conversationId).toBe('c1');
  });

  it('appends streamed tokens and marks fast-mode text as provisional', () => {
    let state = startAnswer('c1');
    state = applyEvent(state, event('token', { text: 'Hel', provisional: true }));
    state = applyEvent(state, event('token', { text: 'lo', provisional: true }));
    expect(state.answer.content).toBe('Hello');
    expect(state.answer.provisional).toBe(true);
  });

  it('replaces text that failed verification', () => {
    let state = applyEvent(startAnswer('c1'), event('token', { text: 'wrong', provisional: true }));
    state = applyEvent(state, event('replace', { text: 'right' }));
    expect(state.answer.content).toBe('right');
  });

  it('finishes with the checked answer and its citations', () => {
    const citation = { chunk_id: 'k', document_id: 'd', filename: 'a.md', index: 1, locator: {}, quote: 'q' };
    const state = applyEvent(
      applyEvent(startAnswer('c1'), event('token', { text: 'draft', provisional: true })),
      event('done', { answer: 'final [1]', citations: [citation], refused: false, refusal_reason: null, verified: true }),
    );
    expect(state.answer).toMatchObject({ content: 'final [1]', verified: true, provisional: false });
    expect(state.answer.citations).toEqual([citation]);
  });

  it('shows a refusal with its reason', () => {
    const state = applyEvent(
      startAnswer('c1'),
      event('done', { answer: 'I cannot answer that.', citations: [], refused: true, refusal_reason: 'low_relevance', verified: true }),
    );
    expect(state.answer.refused).toBe(true);
    expect(state.answer.refusalReason).toBe('low_relevance');
  });

  it('surfaces a stream error', () => {
    const state = applyEvent(startAnswer('c1'), event('error', { status: 504, type: 'model-timeout', detail: 'Too slow' }));
    expect(state.error).toBe('Too slow');
  });
});
