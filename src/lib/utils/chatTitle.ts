/**
 * Build a short conversation title from the first user message.
 * Prefers the first sentence (split on . or newline only so questions keep "?").
 */

const MAX_TITLE_LENGTH = 48;

export function messageToConversationTitle(message: string | undefined | null): string {
  if (message == null || typeof message !== 'string') return 'New chat';
  const trimmed = message.trim();
  if (!trimmed) return 'New chat';

  // Split on period or newline only so "What do we have?" stays intact
  const firstSentence = trimmed.split(/[.\n]/)[0]?.trim() ?? trimmed;
  const base = firstSentence.length > 0 ? firstSentence : trimmed;
  if (base.length <= MAX_TITLE_LENGTH) return base;
  return base.slice(0, MAX_TITLE_LENGTH).trimEnd() + '…';
}
