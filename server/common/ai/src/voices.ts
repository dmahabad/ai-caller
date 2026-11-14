import { readFileSync } from 'node:fs';
const catalog = JSON.parse(readFileSync(new URL('../../voice-catalog.json', import.meta.url), 'utf8')) as {defaultVoice: string, voices: {id: string}[]};
const voices = new Set(catalog.voices.map(voice => voice.id));
export function validateVoice(voice: unknown = catalog.defaultVoice): string {
  if (typeof voice !== 'string' || !voices.has(voice)) throw new Error('invalid_voice');
  return voice;
}
