import type { AbstainReason, CueCode, DetectorInfo, Explanation, Strictness, Verdict } from './types'

// Fake detector until the real model is served from the backend.
// Deterministic so the same answer always scores the same in demos.
// Cues are loosely based on real detector signals (formality, uniform rhythm, length).
//
// This stands in for backend policy too, not just the model. The real detector
// only hands back a score. Turning a strictness level into a threshold, deciding
// when to abstain, and naming the verdict all happen on the server.
// TODO(PP): replace with POST /api/checks once the checks module exists

export const MODEL_VERSION = 'roberta-base-detector-v0'

// Strictness maps to a threshold here the way the server will map it to a
// calibrated one. A higher threshold flags fewer answers
const THRESHOLDS: Record<Strictness, number> = {
  lenient: 0.4,
  standard: 0.5,
  strict: 0.65,
}

// Target false positive rates from the spec. Provisional until calibration
const TARGET_FPR: Record<Strictness, number> = {
  lenient: 0.05,
  standard: 0.01,
  strict: 0.001,
}

// Scores this close to the threshold sit too near the line to call
const ABSTENTION_BAND = 0.08

// Below this many words the detector abstains outright instead of guessing
const MIN_SIGNAL_WORDS = 10

const FORMAL_MARKERS = [
  'furthermore',
  'moreover',
  'typically',
  'utilize',
  'thereby',
  'consequently',
  'in addition',
  'specifically',
  'is defined as',
  'refers to',
  'ensures',
  'facilitates',
]

const INFORMAL_PATTERN = /\b(idk|lol|dunno|stuff|kinda|gonna|btw|imo)\b/i

// FNV-1a, a standard tiny string hash. Gives each answer a pseudo-random base
function hashToUnit(text: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0) / 0xffffffff
}

export interface Analysis {
  rawScore: number
  verdict: Verdict
  abstainReason: AbstainReason
  explanation: Explanation | null
  detector: DetectorInfo
}

export function analyseAnswer(
  answerText: string,
  strictness: Strictness = 'standard',
  usedQuestionText = false,
): Analysis {
  const text = answerText.trim()
  const words = text.split(/\s+/).filter(Boolean)
  const sentences = text
    .split(/[.!?]+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)

  let score = 0.25 + 0.5 * hashToUnit(text.toLowerCase())
  const cues: CueCode[] = []

  const lower = text.toLowerCase()
  const formalHits = FORMAL_MARKERS.filter((marker) => lower.includes(marker)).length
  if (formalHits > 0) {
    score += Math.min(formalHits * 0.05, 0.16)
    cues.push('formal_vocabulary')
  }

  if (sentences.length >= 2) {
    const lengths = sentences.map((sentence) => sentence.split(/\s+/).length)
    const spread = Math.max(...lengths) - Math.min(...lengths)
    if (spread <= 4) {
      score += 0.08
      cues.push('uniform_sentence_length')
    }
  }

  const avgSentenceLen = words.length / Math.max(sentences.length, 1)
  if (avgSentenceLen >= 18) {
    score += 0.08
    cues.push('long_sentences')
  }

  if (INFORMAL_PATTERN.test(text)) {
    score -= 0.28
    cues.push('informal_phrasing')
  }

  const tooShort = words.length < MIN_SIGNAL_WORDS
  if (tooShort) {
    // under 10 words barely any signal, squeeze towards 0.5
    score = 0.5 + (score - 0.5) * 0.45
    cues.push('short_answer')
  }

  score = Math.min(0.97, Math.max(0.03, score))
  score = Math.round(score * 100) / 100

  const threshold = THRESHOLDS[strictness]

  return {
    rawScore: score,
    ...decide(score, threshold, tooShort),
    explanation: cues.length > 0 ? { cues } : null,
    detector: {
      modelVersion: MODEL_VERSION,
      // null until real calibration exists, which is what the contract expects
      calibrationVersion: null,
      strictnessApplied: strictness,
      thresholdApplied: threshold,
      targetFpr: TARGET_FPR[strictness],
      usedQuestionText,
    },
  }
}

// Too short or too close to the line both come back uncertain, with the reason attached
function decide(
  score: number,
  threshold: number,
  tooShort: boolean,
): { verdict: Verdict; abstainReason: AbstainReason } {
  if (tooShort) {
    return { verdict: 'uncertain', abstainReason: 'answer_too_short' }
  }
  if (Math.abs(score - threshold) <= ABSTENTION_BAND) {
    return { verdict: 'uncertain', abstainReason: 'score_in_abstention_band' }
  }
  return { verdict: score > threshold ? 'ai_generated' : 'human_written', abstainReason: null }
}
