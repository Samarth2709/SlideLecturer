import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { visit } from 'unist-util-visit';

function remarkCodeBlockDefault() {
  return (tree) => {
    visit(tree, 'code', (node) => {
      if (!node.lang) {
        node.lang = 'plaintext';
      }
    });
  };
}

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content:
    "Hello! I'm your slide assistant. Upload a PDF or PPTX deck, then ask questions about the full deck or focus on one slide.",
};

const MAIN_BRANCH_ID = 'branch-main';

const DEFAULT_SPLIT_RATIO = 0.62;
const SPLIT_STORAGE_KEY = 'slidelecturer.workspace.splitRatio';
const SPLIT_MIN_RATIO = 0.2;
const SPLIT_MAX_RATIO = 0.8;
const SPLIT_MIN_PANEL_PX = 320;
const SPLITTER_WIDTH_PX = 12;
const TRANSCRIPT_POLL_INTERVAL_MS = 1800;
const DECK_PREFERENCES_STORAGE_PREFIX = 'slidelecturer.deckPreferences.v1';
const SEARCH_SNIPPET_MAX_CHARS = 180;
const MAX_CHAT_HISTORY_MESSAGES = 40;
const MAX_CONTEXT_TOTAL_LENGTH = 50000;
const CONTEXT_SEPARATOR = '\n\n---\n\n';

const EMPTY_TRANSCRIPT_STATE = Object.freeze({
  status: 'queued',
  total_slides: 0,
  completed_slides: 0,
  error: null,
  slides: [],
});

function buildEmptyTranscriptState(totalSlides = 0) {
  return {
    ...EMPTY_TRANSCRIPT_STATE,
    total_slides: totalSlides,
  };
}

function buildDeckPreferenceStorageKey(deck) {
  if (!deck?.filename) {
    return '';
  }

  const filename = String(deck.filename || '').trim().toLowerCase();
  const slideCount = Number(deck.slide_count || 0);
  if (!filename || !Number.isInteger(slideCount) || slideCount <= 0) {
    return '';
  }

  return `${DECK_PREFERENCES_STORAGE_PREFIX}:${filename}:${slideCount}`;
}

function sanitizeStoredBookmarkedSlides(value, totalSlides) {
  if (!Array.isArray(value)) {
    return [];
  }

  const upperBound = Number.isInteger(totalSlides) ? totalSlides - 1 : -1;
  const seen = new Set();
  for (const candidate of value) {
    const index = Number(candidate);
    if (!Number.isInteger(index)) {
      continue;
    }
    if (index < 0 || index > upperBound || seen.has(index)) {
      continue;
    }
    seen.add(index);
  }

  return Array.from(seen).sort((first, second) => first - second);
}

function loadDeckPreferences(storageKey, totalSlides) {
  if (typeof window === 'undefined' || !storageKey) {
    return {
      bookmarks: [],
    };
  }

  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return {
        bookmarks: [],
      };
    }

    const parsed = JSON.parse(raw);
    return {
      bookmarks: sanitizeStoredBookmarkedSlides(parsed?.bookmarks, totalSlides),
    };
  } catch (error) {
    console.warn('Failed to load deck preferences from local storage', error);
    return {
      bookmarks: [],
    };
  }
}

function persistDeckPreferences(storageKey, totalSlides, payload) {
  if (typeof window === 'undefined' || !storageKey) {
    return;
  }

  try {
    const normalizedPayload = {
      bookmarks: sanitizeStoredBookmarkedSlides(payload?.bookmarks, totalSlides),
    };
    window.localStorage.setItem(storageKey, JSON.stringify(normalizedPayload));
  } catch (error) {
    console.warn('Failed to persist deck preferences to local storage', error);
  }
}

function buildSearchSnippet(rawText, normalizedQuery, maxChars = SEARCH_SNIPPET_MAX_CHARS) {
  const text = String(rawText || '').replace(/\s+/g, ' ').trim();
  if (!text) {
    return '';
  }

  const query = String(normalizedQuery || '').toLowerCase().trim();
  if (!query) {
    return text.slice(0, maxChars);
  }

  const lowerText = text.toLowerCase();
  const matchIndex = lowerText.indexOf(query);
  if (matchIndex < 0) {
    return text.slice(0, maxChars);
  }

  const contextPadding = Math.max(24, Math.floor((maxChars - query.length) / 2));
  const start = Math.max(0, matchIndex - contextPadding);
  const end = Math.min(text.length, matchIndex + query.length + contextPadding);
  const prefix = start > 0 ? '...' : '';
  const suffix = end < text.length ? '...' : '';

  return `${prefix}${text.slice(start, end)}${suffix}`;
}

function splitTextForHighlight(text, query) {
  const input = String(text || '');
  const normalizedQuery = String(query || '').trim();
  if (!normalizedQuery) {
    return [{ text: input, isMatch: false }];
  }

  const normalizedInput = input.toLowerCase();
  const normalizedNeedle = normalizedQuery.toLowerCase();
  const output = [];
  let cursor = 0;

  while (cursor < input.length) {
    const matchIndex = normalizedInput.indexOf(normalizedNeedle, cursor);
    if (matchIndex === -1) {
      output.push({ text: input.slice(cursor), isMatch: false });
      break;
    }

    if (matchIndex > cursor) {
      output.push({ text: input.slice(cursor, matchIndex), isMatch: false });
    }

    output.push({
      text: input.slice(matchIndex, matchIndex + normalizedNeedle.length),
      isMatch: true,
    });
    cursor = matchIndex + normalizedNeedle.length;
  }

  if (!output.length) {
    return [{ text: input, isMatch: false }];
  }

  return output;
}

function describeTranscriptGeneration(state) {
  const totalSlides = Number(state?.total_slides || 0);
  const completedSlides = Number(state?.completed_slides || 0);
  const generationStatus = state?.status || 'queued';

  if (generationStatus === 'disabled') {
    return 'Narration is off for this deck.';
  }

  if (!totalSlides) {
    return '';
  }

  if (generationStatus === 'completed') {
    return `Transcripts ready: ${completedSlides}/${totalSlides}`;
  }

  if (generationStatus === 'error') {
    return state?.error
      ? `Transcripts incomplete: ${completedSlides}/${totalSlides}`
      : `Transcript generation failed (${completedSlides}/${totalSlides})`;
  }

  if (generationStatus === 'generating') {
    return `Generating transcripts: ${completedSlides}/${totalSlides}`;
  }

  return `Preparing transcripts: ${completedSlides}/${totalSlides}`;
}

function formatPlaybackClock(totalSeconds) {
  const seconds = Number(totalSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '--:--';
  }

  const rounded = Math.floor(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  }
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

function loadInitialSplitRatio() {
  if (typeof window === 'undefined') {
    return DEFAULT_SPLIT_RATIO;
  }

  const raw = Number(window.localStorage.getItem(SPLIT_STORAGE_KEY));
  if (Number.isFinite(raw) && raw >= SPLIT_MIN_RATIO && raw <= SPLIT_MAX_RATIO) {
    return raw;
  }

  return DEFAULT_SPLIT_RATIO;
}

function apiUrl(path) {
  if (!API_BASE) {
    return path;
  }
  return `${API_BASE}${path}`;
}

function normalizeError(error, fallback) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function formatApiErrorDetail(detail) {
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (typeof entry === 'string' && entry.trim()) {
          return entry.trim();
        }
        if (!entry || typeof entry !== 'object') {
          return '';
        }

        const location = Array.isArray(entry.loc)
          ? entry.loc
            .map((segment) => String(segment || '').trim())
            .filter((segment) => segment && segment !== 'body')
            .join('.')
          : '';
        const message = typeof entry.msg === 'string' ? entry.msg.trim() : '';
        if (location && message) {
          return `${location}: ${message}`;
        }
        return message || location;
      })
      .filter(Boolean);

    if (messages.length) {
      return messages.join('; ');
    }
  }

  if (detail && typeof detail === 'object') {
    for (const key of ['message', 'error']) {
      const candidate = detail[key];
      if (typeof candidate === 'string' && candidate.trim()) {
        return candidate.trim();
      }
    }

    try {
      const serialized = JSON.stringify(detail);
      if (serialized && serialized !== '{}') {
        return serialized;
      }
    } catch (error) {
      console.error('Failed to serialize API error detail', error);
    }
  }

  return '';
}

function extractApiErrorMessage(payload, fallback) {
  const formatted = formatApiErrorDetail(payload?.detail);
  return formatted || fallback;
}

function normalizeContextIndex(value) {
  if (value === null || value === undefined) return null;
  const numeric = Number(value);
  return Number.isInteger(numeric) && numeric >= 0 ? numeric : null;
}

function buildRequestContextSnapshot(context = {}) {
  return {
    currentSlideIndex: normalizeContextIndex(context.currentSlideIndex),
    focusedSlideIndex: normalizeContextIndex(context.focusedSlideIndex),
  };
}

function extractEventData(rawEvent) {
  const lines = rawEvent
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('data:'));

  if (!lines.length) {
    return null;
  }

  return lines
    .map((line) => line.slice(5).trim())
    .join('');
}

async function consumeSse(response, onEvent) {
  if (!response.body) {
    throw new Error('Streaming is not supported in this browser.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, '\n');

    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);

      if (rawEvent) {
        const data = extractEventData(rawEvent);
        if (data) {
          try {
            onEvent(JSON.parse(data));
          } catch (error) {
            console.error('Invalid SSE payload', error);
          }
        }
      }

      boundary = buffer.indexOf('\n\n');
    }
  }
}

const LANGUAGE_ALIASES = {
  js: 'javascript',
  jsx: 'jsx',
  ts: 'typescript',
  tsx: 'tsx',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  md: 'markdown',
  html: 'markup',
  xml: 'markup',
  plaintext: 'plaintext',
  text: 'plaintext',
};

const SUPPORTED_LANGUAGES = new Set([
  'bash',
  'c',
  'cpp',
  'csharp',
  'css',
  'go',
  'java',
  'javascript',
  'jsx',
  'json',
  'kotlin',
  'markup',
  'markdown',
  'php',
  'python',
  'ruby',
  'rust',
  'sql',
  'swift',
  'tsx',
  'typescript',
  'yaml',
  'plaintext',
]);

const LANGUAGE_SCORING_RULES = {
  python: [
    { pattern: /(^|\n)\s*#/g, weight: 2 },
    { pattern: /\b(def|class|import|from|lambda|elif|None|True|False|self|print)\b/g, weight: 3 },
    { pattern: /:\s*$/gm, weight: 1 },
  ],
  javascript: [
    { pattern: /\b(function|const|let|var|return|console\.log|require|module\.exports)\b/g, weight: 3 },
    { pattern: /=>|[{};]/g, weight: 1 },
  ],
  typescript: [
    { pattern: /\b(interface|type|implements|readonly|enum)\b/g, weight: 3 },
    { pattern: /:\s*[A-Za-z_$][A-Za-z0-9_$<>\[\]\s|&]*/g, weight: 1 },
  ],
  java: [
    { pattern: /\b(public|private|protected|class|static|void|new|System\.out)\b/g, weight: 3 },
    { pattern: /;\s*$/gm, weight: 1 },
  ],
  csharp: [
    { pattern: /\b(namespace|using|Console\.WriteLine|public|private|class|static|void)\b/g, weight: 3 },
    { pattern: /;\s*$/gm, weight: 1 },
  ],
  go: [
    { pattern: /\b(func|package|import|defer|go|fmt\.)\b/g, weight: 3 },
    { pattern: /:=/g, weight: 2 },
  ],
  rust: [
    { pattern: /\b(fn|let|mut|impl|match|println!|use)\b/g, weight: 3 },
    { pattern: /::|->/g, weight: 1 },
  ],
  sql: [
    { pattern: /\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|GROUP BY|ORDER BY|VALUES)\b/gi, weight: 3 },
  ],
  bash: [
    { pattern: /^#!\/.*\b(bash|zsh|sh)\b/gm, weight: 4 },
    { pattern: /\b(echo|grep|awk|sed|chmod|chown|curl|export)\b/g, weight: 2 },
    { pattern: /\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/g, weight: 1 },
  ],
  json: [
    { pattern: /^\s*[{[][\s\S]*[}\]]\s*$/g, weight: 2 },
    { pattern: /"\s*:\s*/g, weight: 2 },
  ],
  yaml: [
    { pattern: /^\s*[A-Za-z0-9_-]+\s*:\s*.+$/gm, weight: 2 },
    { pattern: /^\s*-\s+/gm, weight: 1 },
  ],
  markup: [
    { pattern: /<\/?[a-z][\s\S]*?>/gi, weight: 3 },
  ],
  css: [
    { pattern: /[.#]?[a-zA-Z0-9_-]+\s*\{[\s\S]*?\}/g, weight: 2 },
    { pattern: /[a-z-]+\s*:\s*[^;]+;/gi, weight: 2 },
  ],
};

function normalizeLanguage(language) {
  const normalized = String(language || '').trim().toLowerCase();
  const aliased = LANGUAGE_ALIASES[normalized] || normalized;
  return SUPPORTED_LANGUAGES.has(aliased) ? aliased : '';
}

function scoreLanguage(code, rules) {
  let score = 0;
  for (const rule of rules) {
    const matches = code.match(rule.pattern);
    if (matches) {
      score += matches.length * rule.weight;
    }
  }
  return score;
}

function detectLanguageFromCode(code, hintedLanguage = '') {
  const hinted = normalizeLanguage(hintedLanguage);
  if (hinted) {
    return { language: hinted, confidence: 1, source: 'fence' };
  }

  const input = String(code || '');
  const scores = Object.entries(LANGUAGE_SCORING_RULES).map(([language, rules]) => ({
    language,
    score: scoreLanguage(input, rules),
  }));

  scores.sort((a, b) => b.score - a.score);
  const top = scores[0] || { language: 'plaintext', score: 0 };
  const next = scores[1] || { language: 'plaintext', score: 0 };

  if (top.score < 2) {
    return { language: 'plaintext', confidence: 0, source: 'fallback' };
  }

  const confidence = Math.max(0, top.score - next.score) / Math.max(top.score, 1);
  if (confidence < 0.15) {
    return { language: 'plaintext', confidence, source: 'fallback' };
  }

  return { language: top.language, confidence, source: 'heuristic' };
}

function unwrapInlineCodeLine(line) {
  const trimmed = line.trim();
  if (trimmed.length < 2) {
    return null;
  }

  if (trimmed.startsWith('```')) {
    return null;
  }

  if (trimmed.startsWith('`') && trimmed.endsWith('`')) {
    return trimmed.slice(1, -1);
  }

  return null;
}

function convertInlineCodeRunsToFences(markdown) {
  const lines = String(markdown || '').split('\n');
  const output = [];
  let inFence = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (/^`{3,}/.test(trimmed)) {
      inFence = !inFence;
      output.push(line);
      continue;
    }

    if (inFence) {
      output.push(line);
      continue;
    }

    const firstUnwrapped = unwrapInlineCodeLine(line);
    if (firstUnwrapped === null) {
      output.push(line);
      continue;
    }

    const runLines = [firstUnwrapped];
    let cursor = index + 1;
    while (cursor < lines.length) {
      const candidate = lines[cursor];
      const candidateTrimmed = candidate.trim();
      if (/^`{3,}/.test(candidateTrimmed)) {
        break;
      }

      const unwrapped = unwrapInlineCodeLine(candidate);
      if (unwrapped !== null) {
        runLines.push(unwrapped);
        cursor += 1;
        continue;
      }

      if (candidateTrimmed === '') {
        const peek = lines[cursor + 1];
        if (peek !== undefined && unwrapInlineCodeLine(peek) !== null) {
          runLines.push('');
          cursor += 1;
          continue;
        }
      }

      break;
    }

    if (runLines.length >= 2) {
      const code = runLines.join('\n');
      const detected = detectLanguageFromCode(code);
      const fencedLanguage = detected.language === 'plaintext' ? '' : detected.language;
      output.push(fencedLanguage ? `\`\`\`${fencedLanguage}` : '```');
      output.push(code);
      output.push('```');
      index = cursor - 1;
      continue;
    }

    output.push(line);
  }

  return output.join('\n');
}

function preprocessAssistantMarkdown(markdown) {
  return convertInlineCodeRunsToFences(markdown);
}

function StarIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 2.6l2.9 5.88 6.49.94-4.69 4.58 1.1 6.47L12 17.43l-5.8 3.05 1.1-6.47-4.69-4.58 6.49-.94L12 2.6z"
        fill="currentColor"
      />
    </svg>
  );
}

function SpeakerIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M4.3 9h3.9l4.8-3.8v13.6L8.2 15H4.3V9z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="M16 9.1a4.1 4.1 0 010 5.8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path
        d="M18.8 6.8a7.2 7.2 0 010 10.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CopyIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="9" y="9" width="10" height="10" rx="2" ry="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="5" y="5" width="10" height="10" rx="2" ry="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function CheckIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M5 12.6l4.2 4.2L19 7" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function EditIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M14.8 4.2l5 5L9.1 19.8l-4.9 1.1 1.1-4.9L14.8 4.2z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M12.9 6.1l5 5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function BranchTreeIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="5.2" r="2.2" fill="currentColor" />
      <circle cx="5.8" cy="18.2" r="2.2" fill="currentColor" />
      <circle cx="18.2" cy="18.2" r="2.2" fill="currentColor" />
      <path d="M12 7.8v3.2M7 16.1l4.7-4.7M17 16.1l-4.7-4.7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function ClearChatIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4.5 14.2l5.6-5.6 8 8-5.6 5.6H4.5v-8z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M11.4 6.9l2.2-2.2h5.9v5.9l-2.2 2.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.9 19.9h5.8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function SendIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3 20.4l18-8.4L3 3.6l2.3 7 7.2 1.4-7.2 1.4-2.3 7z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function NoteIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9l-6-6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M14 3v6h6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M8 13h8M8 17h5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function DeleteIcon({ className = 'icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 6l1 14a2 2 0 002 2h8a2 2 0 002-2l1-14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function MessageBubble({
  message,
  isEditing,
  editDraft,
  isCopied,
  canBranch,
  onBranchFromAssistant,
  onCopy,
  onEditStart,
  onEditCancel,
  onEditSave,
  onEditDraftChange,
}) {
  const normalizedAssistantMarkdown = preprocessAssistantMarkdown(message.content);
  const canSaveEdit = editDraft.trim().length > 0 && editDraft !== message.content;

  const markdownComponents = {
    code({ className, children, ...props }) {
      const rawCode = String(children).replace(/\n$/, '');
      const languageMatch = /language-([a-zA-Z0-9_+-]+)/.exec(className || '');
      const hintedLanguage = languageMatch ? languageMatch[1] : '';
      const detected = detectLanguageFromCode(rawCode, hintedLanguage);
      const language = detected.language;

      const isBlock = /language-/.test(className || '');

      if (isBlock) {
        const displayLanguage = language === 'plaintext' ? '' : language;
        return (
          <div className="ai-code-block">
            {displayLanguage ? <span className="code-language-badge">{displayLanguage}</span> : null}
            <SyntaxHighlighter
              language={displayLanguage || undefined}
              style={vscDarkPlus}
              PreTag="div"
              customStyle={{
                margin: 0,
                padding: displayLanguage ? '1.9rem 0.8rem 0.8rem' : '0.8rem',
                borderRadius: '10px',
                background: '#0f111a',
                border: '1px solid #2a2d3a',
                fontSize: '0.98rem',
                lineHeight: '1.65',
              }}
              codeTagProps={{
                style: {
                  fontFamily:
                    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                },
              }}
              {...props}
            >
              {rawCode}
            </SyntaxHighlighter>
          </div>
        );
      }

      return (
        <code className="assistant-inline-code" {...props}>
          {children}
        </code>
      );
    },
  };

  const roleLabel = message.role === 'user' ? 'You' : 'AI';

  return (
    <article className={`message-bubble ${message.role}`}>
      <header className="message-header">
        <span className="message-header-label">{roleLabel}</span>
        <div className="message-actions">
          <button
            type="button"
            className={`message-action-btn icon-only ${isCopied ? 'success' : ''}`}
            onClick={() => onCopy(message.id)}
            aria-label={`Copy ${roleLabel} message`}
            title={isCopied ? 'Copied' : 'Copy'}
          >
            {isCopied ? <CheckIcon /> : <CopyIcon />}
          </button>
          {!isEditing ? (
            <button
              type="button"
              className="message-action-btn icon-only"
              onClick={() => onEditStart(message.id)}
              aria-label={`Edit ${roleLabel} message`}
              title="Edit"
            >
              <EditIcon />
            </button>
          ) : (
            <>
              <button
                type="button"
                className="message-action-btn primary"
                onClick={() => onEditSave(message.id)}
                disabled={!canSaveEdit}
                aria-label={`Save ${roleLabel} message edits`}
              >
                Save
              </button>
              <button
                type="button"
                className="message-action-btn"
                onClick={onEditCancel}
                aria-label={`Cancel ${roleLabel} message edits`}
              >
                Cancel
              </button>
            </>
          )}
          {message.role === 'assistant' && message.id !== WELCOME_MESSAGE.id ? (
            <button
              type="button"
              className="message-action-btn"
              onClick={() => onBranchFromAssistant(message.id)}
              disabled={!canBranch}
              aria-label={`Create branch from this ${roleLabel} response`}
            >
              Branch
            </button>
          ) : null}
        </div>
      </header>
      <div className={`message-content ${message.role}`}>
        {isEditing ? (
          <textarea
            className="message-editor"
            value={editDraft}
            onChange={(event) => onEditDraftChange(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                if (canSaveEdit) {
                  onEditSave(message.id);
                }
              } else if (event.key === 'Escape') {
                event.preventDefault();
                onEditCancel();
              }
            }}
            aria-label={`Edit ${roleLabel} message text`}
            rows={Math.min(14, Math.max(4, editDraft.split('\n').length + 1))}
          />
        ) : message.role === 'assistant' ? (
          <ReactMarkdown remarkPlugins={[remarkCodeBlockDefault, remarkMath]} rehypePlugins={[rehypeKatex]} components={markdownComponents}>{normalizedAssistantMarkdown}</ReactMarkdown>
        ) : (
          <p>{message.content}</p>
        )}
      </div>
    </article>
  );
}

function isEditableTarget(target) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const tagName = target.tagName;
  if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT') {
    return true;
  }

  return Boolean(target.isContentEditable);
}

function hasFilePayload(dataTransfer) {
  if (!dataTransfer?.types) {
    return false;
  }
  return Array.from(dataTransfer.types).includes('Files');
}

async function copyTextToClipboard(text) {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  if (typeof document === 'undefined') {
    throw new Error('Clipboard is unavailable');
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'absolute';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();

  const copied = document.execCommand('copy');
  document.body.removeChild(textarea);

  if (!copied) {
    throw new Error('Failed to copy text');
  }
}

function App() {
  const [deck, setDeck] = useState(null);
  const [slides, setSlides] = useState([]);
  const [branchesById, setBranchesById] = useState(() => ({
    [MAIN_BRANCH_ID]: {
      id: MAIN_BRANCH_ID,
      label: 'Branch 1',
      parentBranchId: null,
      parentMessageId: null,
      messages: [WELCOME_MESSAGE],
    },
  }));
  const [branchOrder, setBranchOrder] = useState([MAIN_BRANCH_ID]);
  const [activeBranchId, setActiveBranchId] = useState(MAIN_BRANCH_ID);
  const [inputValue, setInputValue] = useState('');
  const [queuedMessagesByBranch, setQueuedMessagesByBranch] = useState(() => ({
    [MAIN_BRANCH_ID]: [],
  }));
  const [editingQueuedMessageId, setEditingQueuedMessageId] = useState(null);
  const [queueDraftSnapshot, setQueueDraftSnapshot] = useState('');
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamingBranchId, setStreamingBranchId] = useState(null);
  const [clearingChat, setClearingChat] = useState(false);
  const [isBranchMapOpen, setIsBranchMapOpen] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState(null);
  const [messageDraft, setMessageDraft] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState(null);
  const [error, setError] = useState('');
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [focusedSlideIndex, setFocusedSlideIndex] = useState(null);
  const [slidesVisible, setSlidesVisible] = useState(true);
  const [transcriptState, setTranscriptState] = useState(() => buildEmptyTranscriptState());
  const [activeTranscriptSlideIndex, setActiveTranscriptSlideIndex] = useState(null);
  const [activeSpeechSlideIndex, setActiveSpeechSlideIndex] = useState(null);
  const [speechStatus, setSpeechStatus] = useState('idle');
  const [speechCurrentTimeSeconds, setSpeechCurrentTimeSeconds] = useState(0);
  const [speechDurationSeconds, setSpeechDurationSeconds] = useState(0);
  const [speechIsBuffering, setSpeechIsBuffering] = useState(false);
  const [narrateEnabled, setNarrateEnabled] = useState(true);
  const [bookmarkedSlideIndices, setBookmarkedSlideIndices] = useState([]);
  const [showBookmarkedOnly, setShowBookmarkedOnly] = useState(false);
  const [slideSearchQuery, setSlideSearchQuery] = useState('');
  const [splitRatio, setSplitRatio] = useState(() => loadInitialSplitRatio());
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);
  const [contextEntries, setContextEntries] = useState([]);
  const [contextDraft, setContextDraft] = useState('');
  const [editingContextIndex, setEditingContextIndex] = useState(null);
  const [isContextModalOpen, setIsContextModalOpen] = useState(false);
  const [activeFileTabIndex, setActiveFileTabIndex] = useState(null);

  const workspaceRef = useRef(null);
  const slideScrollRef = useRef(null);
  const slideRefs = useRef([]);
  const inputRef = useRef(null);
  const slideSearchInputRef = useRef(null);
  const fileInputRef = useRef(null);
  const currentSlideIndexRef = useRef(0);
  const dragDepthRef = useRef(0);
  const copyResetTimerRef = useRef(null);
  const branchCounterRef = useRef(1);
  const branchesRef = useRef(branchesById);
  const queuedMessagesByBranchRef = useRef(queuedMessagesByBranch);
  const editingQueuedMessageIdRef = useRef(editingQueuedMessageId);
  const activeBranchIdRef = useRef(activeBranchId);
  const branchOrderRef = useRef(branchOrder);
  const clearingChatRef = useRef(clearingChat);
  const sendingRef = useRef(sending);
  const speechAudioRef = useRef(null);
  const speechObjectUrlRef = useRef('');
  const speechRequestIdRef = useRef(0);
  const contextSentValueRef = useRef(null);
  const contextEntriesRef = useRef(contextEntries);

  const activeBranch = branchesById[activeBranchId] || branchesById[MAIN_BRANCH_ID];
  const messages = activeBranch?.messages || [WELCOME_MESSAGE];
  const activeBranchIndex = Math.max(0, branchOrder.indexOf(activeBranchId));
  const queuedMessages = queuedMessagesByBranch[activeBranchId] || [];
  const queueEditingIndex = queuedMessages.findIndex(
    (queuedMessage) => queuedMessage.id === editingQueuedMessageId
  );
  const resetSpeechPlaybackState = useCallback(() => {
    setActiveSpeechSlideIndex(null);
    setSpeechStatus('idle');
    setSpeechCurrentTimeSeconds(0);
    setSpeechDurationSeconds(0);
    setSpeechIsBuffering(false);
  }, []);
  const clearSpeechAudio = useCallback(() => {
    const activeAudio = speechAudioRef.current;
    const activeObjectUrl = speechObjectUrlRef.current;
    speechAudioRef.current = null;
    speechObjectUrlRef.current = '';

    if (activeAudio) {
      activeAudio.onplay = null;
      activeAudio.onpause = null;
      activeAudio.onended = null;
      activeAudio.onerror = null;
      activeAudio.ontimeupdate = null;
      activeAudio.ondurationchange = null;
      activeAudio.onloadedmetadata = null;
      activeAudio.onwaiting = null;
      activeAudio.oncanplay = null;
      activeAudio.oncanplaythrough = null;
      activeAudio.pause();
      activeAudio.removeAttribute('src');
      activeAudio.load();
    }

    if (activeObjectUrl && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
      URL.revokeObjectURL(activeObjectUrl);
    }
  }, []);

  const branchTree = useMemo(() => {
    const nonWelcomeMessagesFor = (branch) =>
      branch.messages.filter((message) => message.id !== WELCOME_MESSAGE.id);

    const assistantMessagesFor = (branch) =>
      nonWelcomeMessagesFor(branch).filter((message) => message.role === 'assistant');

    const normalizeSnippet = (text) => String(text || '').replace(/\s+/g, ' ').trim();

    const tailSnippet = (text, maxChars = 56) => {
      const normalized = normalizeSnippet(text);
      if (!normalized) {
        return 'No user prompt captured';
      }
      if (normalized.length <= maxChars) {
        return normalized;
      }

      return `...${normalized.slice(-maxChars)}`;
    };

    const findTurnForMessageId = (messageId) => {
      if (!messageId) {
        return null;
      }

      for (const branchId of branchOrder) {
        const branch = branchesById[branchId];
        if (!branch) {
          continue;
        }

        const nonWelcomeMessages = nonWelcomeMessagesFor(branch);
        const messageIndex = nonWelcomeMessages.findIndex((message) => message.id === messageId);
        if (messageIndex !== -1) {
          return Math.ceil((messageIndex + 1) / 2);
        }
      }

      return null;
    };

    const findUserMessageForAssistant = (messageId) => {
      if (!messageId) {
        return '';
      }

      for (const branchId of branchOrder) {
        const branch = branchesById[branchId];
        if (!branch) {
          continue;
        }

        const nonWelcomeMessages = nonWelcomeMessagesFor(branch);
        const assistantIndex = nonWelcomeMessages.findIndex(
          (message) => message.id === messageId && message.role === 'assistant'
        );
        if (assistantIndex < 0) {
          continue;
        }

        for (let cursor = assistantIndex - 1; cursor >= 0; cursor -= 1) {
          const candidate = nonWelcomeMessages[cursor];
          if (candidate.role === 'user') {
            return candidate.content;
          }
        }
      }

      return '';
    };

    const promptPreviewCache = new Map();
    const getPromptPreview = (messageId) => {
      if (!messageId) {
        return 'No user prompt captured';
      }

      if (promptPreviewCache.has(messageId)) {
        return promptPreviewCache.get(messageId);
      }

      const preview = tailSnippet(findUserMessageForAssistant(messageId));
      promptPreviewCache.set(messageId, preview);
      return preview;
    };

    const branchOrderIndex = new Map(branchOrder.map((branchId, index) => [branchId, index]));
    const branchSummaries = new Map();
    const branchesAtContext = new Map();
    const contextIdOrder = [];
    const seenContextIds = new Set();
    const topContextIds = [];
    const seenTopContexts = new Set();
    const rootBranchIds = [];

    const ensureContextOrder = (contextId) => {
      if (!contextId || seenContextIds.has(contextId)) {
        return;
      }
      seenContextIds.add(contextId);
      contextIdOrder.push(contextId);
    };

    for (const branchId of branchOrder) {
      const branch = branchesById[branchId];
      if (!branch) {
        continue;
      }

      const nonWelcomeMessages = nonWelcomeMessagesFor(branch);
      const assistantMessages = assistantMessagesFor(branch);
      const turnCount = Math.ceil(nonWelcomeMessages.length / 2);

      let derivedFrom = 'initial conversation context';
      if (branch.parentMessageId) {
        derivedFrom = `context "${getPromptPreview(branch.parentMessageId)}"`;
      }

      branchSummaries.set(branchId, {
        id: branch.id,
        label: branch.label,
        turnCount,
        messageCount: nonWelcomeMessages.length,
        isActive: branch.id === activeBranchId,
        derivedFrom,
      });

      if (!assistantMessages.length) {
        rootBranchIds.push(branchId);
        continue;
      }

      const firstContextId = assistantMessages[0].id;
      if (!seenTopContexts.has(firstContextId)) {
        seenTopContexts.add(firstContextId);
        topContextIds.push(firstContextId);
      }

      for (let index = 0; index < assistantMessages.length; index += 1) {
        const contextId = assistantMessages[index].id;
        const nextContextId = assistantMessages[index + 1]?.id || null;

        ensureContextOrder(contextId);
        if (nextContextId) {
          ensureContextOrder(nextContextId);
        }

        if (!branchesAtContext.has(contextId)) {
          branchesAtContext.set(contextId, []);
        }

        branchesAtContext.get(contextId).push({
          branchId,
          contextId,
          nextContextId,
        });
      }
    }

    const contextLabelById = new Map();
    contextIdOrder.forEach((contextId, index) => {
      contextLabelById.set(contextId, `Context Node ${index + 1}`);
    });

    const sortContextRefs = (refs) =>
      [...refs].sort((firstRef, secondRef) => {
        const firstIndex = branchOrderIndex.get(firstRef.branchId) ?? Number.MAX_SAFE_INTEGER;
        const secondIndex = branchOrderIndex.get(secondRef.branchId) ?? Number.MAX_SAFE_INTEGER;
        if (firstIndex !== secondIndex) {
          return firstIndex - secondIndex;
        }

        return firstRef.branchId.localeCompare(secondRef.branchId);
      });

    const buildContextNode = (contextId, ancestry = new Set()) => {
      if (!contextId) {
        return null;
      }

      const ancestryKey = `context:${contextId}`;
      if (ancestry.has(ancestryKey)) {
        return null;
      }

      const nextAncestry = new Set(ancestry);
      nextAncestry.add(ancestryKey);

      const contextTurn = findTurnForMessageId(contextId);
      const branchRefs = sortContextRefs(branchesAtContext.get(contextId) || []);
      const preferredSourceRef =
        branchRefs.find((reference) => reference.branchId === activeBranchId) || branchRefs[0] || null;
      const sourceBranchId = preferredSourceRef?.branchId || null;
      const branchNodes = branchRefs
        .map((reference) => {
          const summary = branchSummaries.get(reference.branchId);
          if (!summary) {
            return null;
          }

          const childContextNode = reference.nextContextId
            ? buildContextNode(reference.nextContextId, nextAncestry)
            : null;
          const hasChildContext = Boolean(childContextNode);
          const actionDescription = 'Click to switch to this branch.';

          return {
            key: `branch:${reference.branchId}:${reference.contextId}`,
            branchId: summary.id,
            label: summary.label,
            turnCount: summary.turnCount,
            messageCount: summary.messageCount,
            isActive: summary.isActive,
            hasChildContext,
            kindLabel: 'Branch · click to switch',
            tooltip: `${summary.label} derives from ${summary.derivedFrom}. ${actionDescription}`,
            childContext: childContextNode,
          };
        })
        .filter(Boolean);

      const contextPreview = getPromptPreview(contextId);
      const contextSummary = `Prompt: "${contextPreview}"`;
      const contextAction = sourceBranchId
        ? 'Click to branch from this context.'
        : 'No branch action available for this context yet.';

      return {
        key: `context:${contextId}`,
        contextId,
        title: contextLabelById.get(contextId) || 'Context Node',
        summary: contextSummary,
        tooltip: `${contextSummary} ${contextAction}`,
        sourceBranchId,
        sourceMessageId: contextId,
        canBranch: Boolean(sourceBranchId),
        branches: branchNodes,
      };
    };

    const rootContextNodes = topContextIds
      .map((contextId) => buildContextNode(contextId))
      .filter(Boolean);

    if (rootContextNodes.length) {
      return {
        rootContexts: rootContextNodes,
        hasNodes: true,
      };
    }

    const rootBranches = rootBranchIds
      .map((branchId) => {
        const summary = branchSummaries.get(branchId);
        if (!summary) {
          return null;
        }

        return {
          key: `branch:${summary.id}:root`,
          branchId: summary.id,
          label: summary.label,
          turnCount: summary.turnCount,
          messageCount: summary.messageCount,
          isActive: summary.isActive,
          kindLabel: 'Branch · click to switch',
          tooltip: `${summary.label} derives from ${summary.derivedFrom}. Click to switch to this branch.`,
          hasChildContext: false,
          childContext: null,
        };
      })
      .filter(Boolean);

    if (!rootBranches.length) {
      return {
        rootContexts: [],
        hasNodes: false,
      };
    }

    return {
      rootContexts: [
        {
          key: 'context:root',
          contextId: 'root',
          title: 'Context Node 1',
          summary: 'Initial conversation context',
          tooltip: 'Initial conversation context',
          sourceBranchId: null,
          sourceMessageId: null,
          canBranch: false,
          branches: rootBranches,
        },
      ],
      hasNodes: true,
    };
  }, [branchesById, branchOrder, activeBranchId]);

  useEffect(() => {
    branchesRef.current = branchesById;
  }, [branchesById]);

  useEffect(() => {
    queuedMessagesByBranchRef.current = queuedMessagesByBranch;
  }, [queuedMessagesByBranch]);

  useEffect(() => {
    editingQueuedMessageIdRef.current = editingQueuedMessageId;
  }, [editingQueuedMessageId]);

  useEffect(() => {
    activeBranchIdRef.current = activeBranchId;
  }, [activeBranchId]);

  useEffect(() => {
    branchOrderRef.current = branchOrder;
  }, [branchOrder]);

  useEffect(() => {
    clearingChatRef.current = clearingChat;
  }, [clearingChat]);

  useEffect(() => {
    sendingRef.current = sending;
  }, [sending]);

  useEffect(() => {
    contextEntriesRef.current = contextEntries;
  }, [contextEntries]);

  const resetBranches = useCallback(() => {
    const resetBranchState = {
      [MAIN_BRANCH_ID]: {
        id: MAIN_BRANCH_ID,
        label: 'Branch 1',
        parentBranchId: null,
        parentMessageId: null,
        messages: [WELCOME_MESSAGE],
      },
    };
    branchesRef.current = resetBranchState;
    setBranchesById(resetBranchState);
    setBranchOrder([MAIN_BRANCH_ID]);
    setActiveBranchId(MAIN_BRANCH_ID);
    const resetQueueState = {
      [MAIN_BRANCH_ID]: [],
    };
    queuedMessagesByBranchRef.current = resetQueueState;
    setQueuedMessagesByBranch(resetQueueState);
    editingQueuedMessageIdRef.current = null;
    setEditingQueuedMessageId(null);
    setQueueDraftSnapshot('');
    setStreamingBranchId(null);
    setIsBranchMapOpen(false);
    branchCounterRef.current = 1;
  }, []);

  const restoreBranches = useCallback((conversationData) => {
    const { branches_by_id, branch_order, active_branch_id, branch_counter } = conversationData;

    const restoredBranches = {};
    for (const [id, branch] of Object.entries(branches_by_id)) {
      restoredBranches[id] = {
        ...branch,
        messages: [WELCOME_MESSAGE, ...branch.messages],
      };
    }

    if (!restoredBranches[MAIN_BRANCH_ID]) {
      restoredBranches[MAIN_BRANCH_ID] = {
        id: MAIN_BRANCH_ID,
        label: 'Branch 1',
        parentBranchId: null,
        parentMessageId: null,
        messages: [WELCOME_MESSAGE],
      };
    }

    branchesRef.current = restoredBranches;
    setBranchesById(restoredBranches);

    const restoredOrder =
      branch_order && branch_order.length > 0 ? branch_order : [MAIN_BRANCH_ID];
    branchOrderRef.current = restoredOrder;
    setBranchOrder(restoredOrder);

    const restoredActiveBranch =
      active_branch_id && restoredBranches[active_branch_id]
        ? active_branch_id
        : MAIN_BRANCH_ID;
    activeBranchIdRef.current = restoredActiveBranch;
    setActiveBranchId(restoredActiveBranch);

    const resetQueueState = {};
    for (const branchId of restoredOrder) {
      resetQueueState[branchId] = [];
    }
    queuedMessagesByBranchRef.current = resetQueueState;
    setQueuedMessagesByBranch(resetQueueState);

    editingQueuedMessageIdRef.current = null;
    setEditingQueuedMessageId(null);
    setQueueDraftSnapshot('');
    setStreamingBranchId(null);
    setIsBranchMapOpen(false);

    branchCounterRef.current = typeof branch_counter === 'number' ? branch_counter : 1;
  }, []);

  async function saveConversationToBackend(deckId) {
    if (!deckId) return;

    const currentBranches = branchesRef.current;
    const currentBranchOrder = branchOrderRef.current;
    const currentActiveBranchId = activeBranchIdRef.current;

    const sanitizedBranches = {};
    for (const [id, branch] of Object.entries(currentBranches)) {
      sanitizedBranches[id] = {
        ...branch,
        messages: branch.messages.filter((m) => m.id !== WELCOME_MESSAGE.id),
      };
    }

    const hasUserMessages = Object.values(sanitizedBranches).some((branch) =>
      branch.messages.some((m) => m.role === 'user')
    );
    if (!hasUserMessages) return;

    try {
      await fetch(apiUrl(`/api/v1/decks/${deckId}/conversation/save`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          branches_by_id: sanitizedBranches,
          branch_order: currentBranchOrder,
          active_branch_id: currentActiveBranchId,
          branch_counter: branchCounterRef.current,
          context_entries: contextEntriesRef.current,
        }),
      });
    } catch (err) {
      console.warn('Failed to save conversation', err);
    }
  }

  const resetTranscriptState = useCallback((totalSlides = 0) => {
    setTranscriptState(buildEmptyTranscriptState(totalSlides));
    setActiveTranscriptSlideIndex(null);
  }, []);

  const updateQueueForBranch = useCallback((branchId, updater) => {
    if (!branchId) {
      return [];
    }

    const previousState = queuedMessagesByBranchRef.current;
    const previousQueue = previousState[branchId] || [];
    const computedQueue = typeof updater === 'function' ? updater(previousQueue) : updater;
    const nextQueue = Array.isArray(computedQueue) ? computedQueue : [];
    const nextState = {
      ...previousState,
      [branchId]: nextQueue,
    };
    queuedMessagesByBranchRef.current = nextState;
    setQueuedMessagesByBranch(nextState);
    return nextQueue;
  }, []);

  const enqueueMessageForBranch = useCallback(
    (branchId, content, requestContext = null) => {
      const trimmedContent = String(content || '').trim();
      if (!trimmedContent) {
        return null;
      }

      const queuedMessage = {
        id: `queued-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        content: trimmedContent,
        createdAt: Date.now(),
        requestContext: buildRequestContextSnapshot(requestContext || {}),
      };

      updateQueueForBranch(branchId, (existingQueue) => [...existingQueue, queuedMessage]);
      return queuedMessage;
    },
    [updateQueueForBranch]
  );

  const removeQueuedMessage = useCallback(
    (branchId, queuedMessageId) => {
      if (!branchId || !queuedMessageId) {
        return;
      }

      updateQueueForBranch(
        branchId,
        (existingQueue) =>
          existingQueue.filter((queuedMessage) => queuedMessage.id !== queuedMessageId)
      );
    },
    [updateQueueForBranch]
  );

  const updateQueuedMessage = useCallback(
    (branchId, queuedMessageId, content) => {
      if (!branchId || !queuedMessageId) {
        return;
      }

      updateQueueForBranch(
        branchId,
        (existingQueue) =>
          existingQueue.map((queuedMessage) =>
            queuedMessage.id === queuedMessageId
              ? { ...queuedMessage, content: String(content || '') }
              : queuedMessage
          )
      );
    },
    [updateQueueForBranch]
  );

  const getNextQueuedMessageToSend = useCallback((branchId) => {
    if (!branchId) {
      return null;
    }

    const branchQueue = queuedMessagesByBranchRef.current[branchId] || [];
    if (!branchQueue.length) {
      return null;
    }

    const editingQueuedId = editingQueuedMessageIdRef.current;
    if (!editingQueuedId) {
      return branchQueue[0];
    }

    const editingIndex = branchQueue.findIndex(
      (queuedMessage) => queuedMessage.id === editingQueuedId
    );
    if (editingIndex < 0) {
      return branchQueue[0];
    }

    if (editingIndex === 0) {
      return null;
    }

    return branchQueue[0];
  }, []);

  const selectBranch = useCallback(
    (branchId, options = { closeMap: false }) => {
      if (!branchesById[branchId]) {
        return;
      }

      setActiveBranchId(branchId);
      setEditingMessageId(null);
      setMessageDraft('');
      setCopiedMessageId(null);
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
      setQueueDraftSnapshot('');

      if (options.closeMap) {
        setIsBranchMapOpen(false);
      }
    },
    [branchesById]
  );

  const createBranchFromSource = useCallback(
    (sourceBranchId, messageId, options = { closeMap: false }) => {
      const sourceBranch = branchesById[sourceBranchId];
      if (!sourceBranch) {
        return null;
      }

      const sourceIndex = sourceBranch.messages.findIndex(
        (message) => message.id === messageId && message.role === 'assistant'
      );
      if (sourceIndex < 0) {
        setError('Unable to branch from this node because no assistant response was found.');
        return null;
      }

      const branchId = `branch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      branchCounterRef.current += 1;

      setBranchesById((previous) => {
        const nextState = {
          ...previous,
          [branchId]: {
            id: branchId,
            label: `Branch ${branchCounterRef.current}`,
            parentBranchId: sourceBranchId,
            parentMessageId: messageId,
            messages: sourceBranch.messages.slice(0, sourceIndex + 1).map((message) => ({ ...message })),
          },
        };
        branchesRef.current = nextState;
        return nextState;
      });
      updateQueueForBranch(branchId, []);
      setBranchOrder((previous) => [...previous, branchId]);
      setActiveBranchId(branchId);
      setEditingMessageId(null);
      setMessageDraft('');
      setCopiedMessageId(null);
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
      setQueueDraftSnapshot('');
      setError('');

      if (options.closeMap) {
        setIsBranchMapOpen(false);
      }

      window.setTimeout(() => void saveConversationToBackend(deck?.deck_id), 50);

      return branchId;
    },
    [branchesById, updateQueueForBranch]
  );

  const createBranchFromAssistant = useCallback(
    (messageId) => {
      createBranchFromSource(activeBranchId, messageId);
    },
    [activeBranchId, createBranchFromSource]
  );

  const handleTreeNodeClick = useCallback(
    (node) => {
      if (!node) {
        return;
      }

      selectBranch(node.branchId, { closeMap: true });
    },
    [selectBranch]
  );

  const handleContextNodeClick = useCallback(
    (node) => {
      if (sendingRef.current || clearingChatRef.current) {
        return;
      }

      if (!node || !node.canBranch || !node.sourceBranchId || !node.sourceMessageId) {
        return;
      }

      createBranchFromSource(node.sourceBranchId, node.sourceMessageId, { closeMap: true });
    },
    [createBranchFromSource]
  );

  const updateBranchMessages = useCallback((branchId, updater) => {
    setBranchesById((previous) => {
      const targetBranch = previous[branchId];
      if (!targetBranch) {
        return previous;
      }

      const nextMessages =
        typeof updater === 'function' ? updater(targetBranch.messages) : updater;

      const nextState = {
        ...previous,
        [branchId]: {
          ...targetBranch,
          messages: nextMessages,
        },
      };
      branchesRef.current = nextState;
      return nextState;
    });
  }, []);

  const updateActiveBranchMessages = useCallback(
    (updater) => {
      updateBranchMessages(activeBranchId, updater);
    },
    [activeBranchId, updateBranchMessages]
  );

  const switchBranchByOffset = useCallback(
    (offset) => {
      if (branchOrder.length <= 1) {
        return;
      }

      const currentIndex = branchOrder.indexOf(activeBranchId);
      if (currentIndex < 0) {
        return;
      }

      const nextIndex =
        (currentIndex + offset + branchOrder.length) % branchOrder.length;
      const nextBranchId = branchOrder[nextIndex];
      if (!nextBranchId) {
        return;
      }

      selectBranch(nextBranchId);
    },
    [activeBranchId, branchOrder, selectBranch]
  );

  useEffect(() => {
    currentSlideIndexRef.current = currentSlideIndex;
  }, [currentSlideIndex]);


  useEffect(() => {
    if (!editingMessageId) {
      return;
    }

    const exists = messages.some((message) => message.id === editingMessageId);
    if (!exists) {
      setEditingMessageId(null);
      setMessageDraft('');
    }
  }, [messages, editingMessageId]);

  useEffect(() => {
    if (!branchesById[activeBranchId]) {
      return;
    }

    if (queuedMessagesByBranchRef.current[activeBranchId]) {
      return;
    }

    updateQueueForBranch(activeBranchId, []);
  }, [activeBranchId, branchesById, updateQueueForBranch]);

  useEffect(() => {
    if (!editingQueuedMessageId) {
      return;
    }

    const exists = queuedMessages.some((queuedMessage) => queuedMessage.id === editingQueuedMessageId);
    if (!exists) {
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
    }
  }, [queuedMessages, editingQueuedMessageId]);

  useEffect(() => {
    return () => {
      if (copyResetTimerRef.current) {
        window.clearTimeout(copyResetTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    speechRequestIdRef.current += 1;
    clearSpeechAudio();
    resetSpeechPlaybackState();
  }, [deck?.deck_id, clearSpeechAudio, resetSpeechPlaybackState]);

  useEffect(() => {
    return () => {
      clearSpeechAudio();
    };
  }, [clearSpeechAudio]);

  useEffect(() => {
    if (!branchesById[activeBranchId]) {
      setActiveBranchId(MAIN_BRANCH_ID);
    }
  }, [activeBranchId, branchesById]);

  useEffect(() => {
    setQueueDraftSnapshot('');
  }, [activeBranchId]);

  useEffect(() => {
    if (!isBranchMapOpen) {
      return;
    }

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setIsBranchMapOpen(false);
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isBranchMapOpen]);

  const hasDeck = Boolean(deck?.deck_id);
  const isDeckNarrationEnabled = deck?.narrate_enabled !== false;
  const splitPercentage = Number((splitRatio * 100).toFixed(1));
  const transcriptsBySlide = useMemo(() => {
    const mapping = new Map();
    for (const entry of transcriptState.slides || []) {
      mapping.set(entry.index, entry);
    }
    return mapping;
  }, [transcriptState.slides]);
  const transcriptProgressLabel = useMemo(
    () => describeTranscriptGeneration(transcriptState),
    [transcriptState]
  );
  const deckPreferenceStorageKey = useMemo(
    () => buildDeckPreferenceStorageKey(deck),
    [deck]
  );
  const bookmarkedSlideSet = useMemo(
    () => new Set(bookmarkedSlideIndices),
    [bookmarkedSlideIndices]
  );
  const tabFilteredSlides = useMemo(() => {
    const sourceFiles = deck?.source_files;
    if (!sourceFiles || sourceFiles.length <= 1 || activeFileTabIndex === null) {
      return slides;
    }
    const tab = sourceFiles[activeFileTabIndex];
    if (!tab) return slides;
    const start = tab.start_slide;
    const end = start + tab.slide_count;
    return slides.filter((slide) => slide.index >= start && slide.index < end);
  }, [slides, deck, activeFileTabIndex]);

  const slidesToRender = useMemo(() => {
    if (!showBookmarkedOnly) {
      return tabFilteredSlides;
    }
    return tabFilteredSlides.filter((slide) => bookmarkedSlideSet.has(slide.index));
  }, [bookmarkedSlideSet, showBookmarkedOnly, tabFilteredSlides]);
  const navigableSlideIndices = useMemo(
    () => slidesToRender.map((slide) => slide.index),
    [slidesToRender]
  );
  const normalizedSlideSearchQuery = useMemo(
    () => slideSearchQuery.trim().toLowerCase(),
    [slideSearchQuery]
  );
  const slideSearchResults = useMemo(() => {
    if (!normalizedSlideSearchQuery) {
      return [];
    }

    const results = [];

    for (const slide of tabFilteredSlides) {
      const slideIndex = slide.index;
      const transcriptEntry = transcriptsBySlide.get(slideIndex);
      const transcript = String(transcriptEntry?.transcript || '');
      const preview = String(slide.text_preview || '');

      const normalizedTranscript = transcript.toLowerCase();
      const normalizedPreview = preview.toLowerCase();

      let score = 0;
      let snippet = '';
      let matchedSource = '';

      if (normalizedTranscript.includes(normalizedSlideSearchQuery)) {
        score += 4;
        if (!snippet) {
          snippet = buildSearchSnippet(transcript, normalizedSlideSearchQuery);
          matchedSource = 'Transcript';
        }
      }

      if (normalizedPreview.includes(normalizedSlideSearchQuery)) {
        score += 2;
        if (!snippet) {
          snippet = buildSearchSnippet(preview, normalizedSlideSearchQuery);
          matchedSource = 'Slide text';
        }
      }

      if (score === 0) {
        continue;
      }

      if (bookmarkedSlideSet.has(slideIndex)) {
        score += 1;
      }

      results.push({
        slideIndex,
        score,
        snippet,
        source: matchedSource || 'Slide text',
        isBookmarked: bookmarkedSlideSet.has(slideIndex),
      });
    }

    results.sort((first, second) => {
      if (second.score !== first.score) {
        return second.score - first.score;
      }
      return first.slideIndex - second.slideIndex;
    });

    return results.slice(0, 30);
  }, [bookmarkedSlideSet, normalizedSlideSearchQuery, tabFilteredSlides, transcriptsBySlide]);

  useEffect(() => {
    const totalSlides = Number(deck?.slide_count || 0);
    if (!deckPreferenceStorageKey || !totalSlides) {
      setBookmarkedSlideIndices([]);
      setShowBookmarkedOnly(false);
      setSlideSearchQuery('');
      return;
    }

    const loaded = loadDeckPreferences(deckPreferenceStorageKey, totalSlides);
    setBookmarkedSlideIndices(loaded.bookmarks);
    setShowBookmarkedOnly(false);
    setSlideSearchQuery('');
  }, [deck?.slide_count, deckPreferenceStorageKey]);

  useEffect(() => {
    const totalSlides = Number(deck?.slide_count || 0);
    if (!deckPreferenceStorageKey || !totalSlides) {
      return;
    }

    persistDeckPreferences(deckPreferenceStorageKey, totalSlides, {
      bookmarks: bookmarkedSlideIndices,
    });
  }, [bookmarkedSlideIndices, deck?.slide_count, deckPreferenceStorageKey]);

  useEffect(() => {
    if (!showBookmarkedOnly) {
      return;
    }

    if (bookmarkedSlideIndices.length) {
      return;
    }

    setShowBookmarkedOnly(false);
  }, [bookmarkedSlideIndices.length, showBookmarkedOnly]);

  useEffect(() => {
    if (!showBookmarkedOnly || !slidesToRender.length) {
      return;
    }

    const isCurrentVisible = slidesToRender.some((slide) => slide.index === currentSlideIndexRef.current);
    if (isCurrentVisible) {
      return;
    }

    const firstVisible = slidesToRender[0];
    if (!firstVisible) {
      return;
    }

    setCurrentSlideIndex(firstVisible.index);
  }, [showBookmarkedOnly, slidesToRender]);

  useEffect(() => {
    if (activeTranscriptSlideIndex === null) {
      return;
    }

    const handleEscape = (event) => {
      if (event.key !== 'Escape') {
        return;
      }

      event.preventDefault();
      setActiveTranscriptSlideIndex(null);
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [activeTranscriptSlideIndex]);

  const clampSplitRatio = useCallback((ratio, containerWidth = 0) => {
    const safeRatio = Number.isFinite(ratio) ? ratio : DEFAULT_SPLIT_RATIO;
    const width = Number.isFinite(containerWidth) && containerWidth > 0
      ? containerWidth
      : workspaceRef.current?.clientWidth || window.innerWidth;
    const availableWidth = Math.max(1, width - SPLITTER_WIDTH_PX);
    const minByPixels = SPLIT_MIN_PANEL_PX / availableWidth;
    const minBound = Math.max(SPLIT_MIN_RATIO, Math.min(0.45, minByPixels));
    const maxBound = Math.min(SPLIT_MAX_RATIO, 1 - minBound);

    if (maxBound <= minBound) {
      return 0.5;
    }

    return Math.min(maxBound, Math.max(minBound, safeRatio));
  }, []);

  const updateSplitFromClientX = useCallback(
    (clientX) => {
      if (!slidesVisible) {
        return;
      }

      const workspace = workspaceRef.current;
      if (!workspace) {
        return;
      }

      const rect = workspace.getBoundingClientRect();
      const availableWidth = rect.width - SPLITTER_WIDTH_PX;
      if (availableWidth <= 0) {
        return;
      }

      const raw = (clientX - rect.left - SPLITTER_WIDTH_PX / 2) / availableWidth;
      const clamped = clampSplitRatio(raw, rect.width);

      setSplitRatio((previous) => (Math.abs(previous - clamped) < 0.001 ? previous : clamped));
    },
    [clampSplitRatio, slidesVisible]
  );

  const inputPlaceholder = useMemo(() => {
    if (!hasDeck) {
      return 'Upload a deck first to start asking questions...';
    }
    if (focusedSlideIndex !== null) {
      return `Ask about Slide ${focusedSlideIndex + 1} (focus mode)...`;
    }
    return 'Ask a question about the slides...';
  }, [focusedSlideIndex, hasDeck]);

  async function fetchTranscriptSnapshot(deckId) {
    const response = await fetch(apiUrl(`/api/v1/decks/${deckId}/transcripts`));
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(extractApiErrorMessage(data, 'Failed to load transcripts'));
    }
    return response.json();
  }

  function transcriptSpeechStreamUrl(deckId, slideIndex) {
    return apiUrl(`/api/v1/decks/${deckId}/slides/${slideIndex}/transcript/speech/stream`);
  }

  async function readResponseMessage(response, fallback) {
    const statusSuffix = Number.isInteger(response.status) && response.status > 0 ? ` (${response.status})` : '';
    const defaultMessage = `${fallback}${statusSuffix}`;
    const contentType = String(response.headers.get('content-type') || '').toLowerCase();

    if (contentType.includes('application/json')) {
      const payload = await response.json().catch(() => null);
      if (payload && typeof payload === 'object') {
        return extractApiErrorMessage(payload, defaultMessage);
      }
    }

    const responseText = await response.text().catch(() => '');
    const normalized = String(responseText || '').replace(/\s+/g, ' ').trim();
    if (normalized) {
      return normalized.length > 240 ? `${normalized.slice(0, 237)}...` : normalized;
    }

    return defaultMessage;
  }

  async function fetchTranscriptSpeechBlobUrl(deckId, slideIndex) {
    const response = await fetch(transcriptSpeechStreamUrl(deckId, slideIndex));
    const contentType = String(response.headers.get('content-type') || '').toLowerCase();

    if (!response.ok) {
      throw new Error(await readResponseMessage(response, 'Failed to load narration audio'));
    }

    if (!contentType.startsWith('audio/')) {
      throw new Error(
        await readResponseMessage(
          response,
          `Narration response is not audio (received ${contentType || 'unknown content type'})`
        )
      );
    }

    const blob = await response.blob();
    if (!blob.size) {
      throw new Error('Narration response was empty.');
    }
    if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
      throw new Error('Audio playback is not supported in this browser.');
    }

    return URL.createObjectURL(blob);
  }

  async function fetchSlides(deckId) {
    const response = await fetch(apiUrl(`/api/v1/decks/${deckId}/slides`));
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(extractApiErrorMessage(data, 'Failed to load slides'));
    }

    const data = await response.json();
    setSlides(data.slides || []);
    setCurrentSlideIndex(0);
    setFocusedSlideIndex(null);
  }

  useEffect(() => {
    if (!deck?.deck_id) {
      return;
    }

    let isCancelled = false;
    let timeoutId = null;

    const pollTranscriptState = async () => {
      try {
        const snapshot = await fetchTranscriptSnapshot(deck.deck_id);
        if (isCancelled) {
          return;
        }

        setTranscriptState(snapshot);

        if (snapshot.status === 'queued' || snapshot.status === 'generating') {
          timeoutId = window.setTimeout(pollTranscriptState, TRANSCRIPT_POLL_INTERVAL_MS);
        }
      } catch (pollError) {
        if (!isCancelled) {
          setTranscriptState((previous) => ({
            ...previous,
            status: 'error',
            error: normalizeError(pollError, 'Failed to load transcripts'),
          }));
        }
      }
    };

    pollTranscriptState();

    return () => {
      isCancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [deck?.deck_id]);

  async function safeDeleteDeck(deckId) {
    if (!deckId) {
      return;
    }

    try {
      await fetch(apiUrl(`/api/v1/decks/${deckId}`), {
        method: 'DELETE',
      });
    } catch (deleteError) {
      console.warn('Failed to delete previous deck', deleteError);
    }
  }

  async function processUploadFiles(files) {
    setError('');
    setUploading(true);
    resetTranscriptState(0);

    try {
      if (deck?.deck_id) {
        await safeDeleteDeck(deck.deck_id);
      }

      const form = new FormData();
      for (const file of files) {
        form.append('files', file);
      }
      form.append('narrate_enabled', String(narrateEnabled));

      const response = await fetch(apiUrl('/api/v1/decks/upload'), {
        method: 'POST',
        body: form,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(extractApiErrorMessage(data, 'Upload failed'));
      }

      const payload = await response.json();
      setDeck(payload);
      setActiveFileTabIndex(null);
      if (typeof payload?.narrate_enabled === 'boolean') {
        setNarrateEnabled(payload.narrate_enabled);
      }
      if (payload.conversation) {
        restoreBranches(payload.conversation);
        const restoredContext = Array.isArray(payload.conversation.context_entries)
          ? payload.conversation.context_entries
          : [];
        setContextEntries(restoredContext);
      } else {
        resetBranches();
        setContextEntries([]);
      }
      resetTranscriptState(payload.slide_count || 0);
      setInputValue('');
      contextSentValueRef.current = null;
      await fetchSlides(payload.deck_id);
    } catch (uploadError) {
      setError(normalizeError(uploadError, 'Failed to upload deck'));
      setDeck(null);
      setSlides([]);
      resetBranches();
      resetTranscriptState(0);
    } finally {
      setUploading(false);
    }
  }

  function triggerFilePicker() {
    if (uploading || sending) {
      return;
    }
    fileInputRef.current?.click();
  }

  async function handleFileInputChange(event) {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) {
      await processUploadFiles(files);
    }
    event.target.value = '';
  }

  function resetDropState() {
    dragDepthRef.current = 0;
    setIsDragActive(false);
  }

  function handleDropZoneDragEnter(event) {
    if (!hasFilePayload(event.dataTransfer)) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current += 1;
    setIsDragActive(true);
  }

  function handleDropZoneDragOver(event) {
    if (!hasFilePayload(event.dataTransfer)) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
    setIsDragActive(true);
  }

  function handleDropZoneDragLeave(event) {
    if (!hasFilePayload(event.dataTransfer)) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragActive(false);
    }
  }

  async function handleDropZoneDrop(event) {
    if (!hasFilePayload(event.dataTransfer)) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    const files = Array.from(event.dataTransfer.files || []);
    resetDropState();

    if (uploading || sending || files.length === 0) {
      return;
    }

    await processUploadFiles(files);
  }

  function slideImageUrl(index) {
    if (!deck?.deck_id) {
      return '';
    }
    return apiUrl(`/api/v1/decks/${deck.deck_id}/slides/${index}/image?scale=2`);
  }

  function toggleBookmarkedFilter() {
    setShowBookmarkedOnly((previous) => {
      const next = !previous;
      if (!next) {
        return next;
      }

      const firstBookmarked = bookmarkedSlideIndices[0];
      if (firstBookmarked !== undefined) {
        window.setTimeout(() => {
          scrollToSlide(firstBookmarked);
        }, 0);
      }

      return next;
    });
  }

  function toggleBookmark(slideIndex) {
    setBookmarkedSlideIndices((previous) => {
      const alreadyBookmarked = previous.includes(slideIndex);
      if (alreadyBookmarked) {
        return previous.filter((index) => index !== slideIndex);
      }
      return [...previous, slideIndex].sort((first, second) => first - second);
    });
  }

  function jumpToSearchResult(slideIndex) {
    if (!Number.isInteger(slideIndex) || slideIndex < 0) {
      return;
    }

    if (showBookmarkedOnly) {
      setShowBookmarkedOnly(false);
    }

    window.setTimeout(() => {
      scrollToSlide(slideIndex);
    }, 0);
  }

  function renderSearchSnippetWithHighlights(snippet) {
    const segments = splitTextForHighlight(snippet, slideSearchQuery);
    return segments.map((segment, index) =>
      segment.isMatch ? (
        <mark key={`match-${index}`}>{segment.text}</mark>
      ) : (
        <span key={`text-${index}`}>{segment.text}</span>
      )
    );
  }

  function toggleFocus(index) {
    setFocusedSlideIndex((prev) => (prev === index ? null : index));
  }

  function openTranscriptModal(slideIndex) {
    setActiveTranscriptSlideIndex((previous) => (previous === slideIndex ? null : slideIndex));
  }

  function closeTranscriptModal() {
    setActiveTranscriptSlideIndex(null);
  }

  async function toggleTranscriptSpeech(slideIndex, transcriptText) {
    if (!deck?.deck_id) {
      return;
    }
    if (deck?.narrate_enabled === false) {
      return;
    }

    const normalizedTranscript = String(transcriptText || '').trim();
    if (!normalizedTranscript) {
      return;
    }

    const activeAudio = speechAudioRef.current;
    const isCurrentSlideActive = activeSpeechSlideIndex === slideIndex && activeAudio;
    if (isCurrentSlideActive) {
      if (speechStatus === 'playing' || speechStatus === 'loading') {
        activeAudio.pause();
        return;
      }

      if (speechStatus === 'paused') {
        try {
          setSpeechIsBuffering(true);
          await activeAudio.play();
        } catch (playError) {
          setSpeechIsBuffering(false);
          setError(normalizeError(playError, 'Failed to resume transcript speech'));
        }
        return;
      }
    }

    if (typeof Audio === 'undefined') {
      setError('Audio playback is not supported in this browser.');
      return;
    }

    const requestId = speechRequestIdRef.current + 1;
    speechRequestIdRef.current = requestId;
    clearSpeechAudio();

    setError('');
    setActiveSpeechSlideIndex(slideIndex);
    setSpeechStatus('loading');
    setSpeechCurrentTimeSeconds(0);
    setSpeechDurationSeconds(0);
    setSpeechIsBuffering(true);

    let blobUrl = '';
    try {
      blobUrl = await fetchTranscriptSpeechBlobUrl(deck.deck_id, slideIndex);
      if (speechRequestIdRef.current !== requestId) {
        URL.revokeObjectURL(blobUrl);
        return;
      }

      const audio = new Audio();
      audio.preload = 'auto';
      audio.src = blobUrl;
      speechAudioRef.current = audio;
      speechObjectUrlRef.current = blobUrl;

      const syncProgress = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        setSpeechCurrentTimeSeconds(audio.currentTime || 0);
        const nextDuration = Number(audio.duration);
        if (Number.isFinite(nextDuration) && nextDuration > 0) {
          setSpeechDurationSeconds(nextDuration);
        }
      };

      audio.onloadedmetadata = syncProgress;
      audio.ondurationchange = syncProgress;
      audio.ontimeupdate = syncProgress;

      audio.onwaiting = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        setSpeechIsBuffering(true);
      };

      audio.oncanplay = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        setSpeechIsBuffering(false);
      };

      audio.oncanplaythrough = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        setSpeechIsBuffering(false);
      };

      audio.onplay = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        setSpeechStatus('playing');
        setSpeechIsBuffering(false);
      };

      audio.onpause = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        if (audio.ended) {
          return;
        }
        setSpeechStatus('paused');
        setSpeechIsBuffering(false);
      };

      audio.onended = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        clearSpeechAudio();
        resetSpeechPlaybackState();
      };

      audio.onerror = () => {
        if (speechRequestIdRef.current !== requestId || speechAudioRef.current !== audio) {
          return;
        }
        clearSpeechAudio();
        resetSpeechPlaybackState();
        setError('Speech playback failed.');
      };

      await audio.play();
    } catch (speechError) {
      if (speechRequestIdRef.current !== requestId) {
        return;
      }
      clearSpeechAudio();
      resetSpeechPlaybackState();
      setError(normalizeError(speechError, 'Failed to play transcript speech'));
    }
  }

  function seekTranscriptSpeechBy(secondsOffset) {
    const audio = speechAudioRef.current;
    if (!audio || activeSpeechSlideIndex === null) {
      return;
    }

    const current = Number(audio.currentTime || 0);
    const duration = Number(audio.duration);
    const boundedDuration = Number.isFinite(duration) && duration > 0 ? duration : Number.POSITIVE_INFINITY;
    const next = Math.max(0, Math.min(current + Number(secondsOffset || 0), boundedDuration));
    if (!Number.isFinite(next)) {
      return;
    }

    audio.currentTime = next;
    setSpeechCurrentTimeSeconds(next);
  }

  function scrollToSlide(index) {
    if (!slides.length) {
      return;
    }

    const numericIndex = Number(index);
    if (!Number.isFinite(numericIndex)) {
      return;
    }

    const clamped = Math.max(0, Math.min(Math.round(numericIndex), slides.length - 1));
    const target = slideRefs.current[clamped];
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    setCurrentSlideIndex(clamped);
  }

  function scrollToRelativeSlide(offset) {
    if (!navigableSlideIndices.length || !Number.isInteger(offset) || offset === 0) {
      return;
    }

    const currentIndex = currentSlideIndexRef.current;
    const currentPosition = navigableSlideIndices.indexOf(currentIndex);
    const basePosition =
      currentPosition >= 0
        ? currentPosition
        : offset > 0
          ? -1
          : navigableSlideIndices.length;

    const nextPosition = Math.max(
      0,
      Math.min(basePosition + offset, navigableSlideIndices.length - 1)
    );
    const nextSlideIndex = navigableSlideIndices[nextPosition];
    if (nextSlideIndex !== undefined) {
      scrollToSlide(nextSlideIndex);
    }
  }

  function scrollToVisibleEdge(direction) {
    if (!navigableSlideIndices.length) {
      return;
    }

    if (direction === 'start') {
      scrollToSlide(navigableSlideIndices[0]);
      return;
    }

    scrollToSlide(navigableSlideIndices[navigableSlideIndices.length - 1]);
  }

  useEffect(() => {
    const container = slideScrollRef.current;
    if (!container || !slidesToRender.length) {
      return;
    }

    const updateCurrentSlide = () => {
      const viewportTop = container.getBoundingClientRect().top;
      const viewportHeight = container.clientHeight;
      const targetTop = viewportTop + viewportHeight / 3;

      let bestIndex = currentSlideIndexRef.current;
      if (!slidesToRender.some((slide) => slide.index === bestIndex)) {
        bestIndex = slidesToRender[0].index;
      }
      let bestDistance = Number.POSITIVE_INFINITY;

      slidesToRender.forEach((slide) => {
        const index = slide.index;
        const node = slideRefs.current[index];
        if (!node) {
          return;
        }

        const rect = node.getBoundingClientRect();
        const visible = rect.bottom > viewportTop && rect.top < viewportTop + viewportHeight;
        if (!visible) {
          return;
        }

        const distance = Math.abs(rect.top - targetTop);
        if (distance < bestDistance) {
          bestDistance = distance;
          bestIndex = index;
        }
      });

      setCurrentSlideIndex((previous) => (previous === bestIndex ? previous : bestIndex));
    };

    updateCurrentSlide();

    const handleScroll = () => {
      window.requestAnimationFrame(updateCurrentSlide);
    };

    container.addEventListener('scroll', handleScroll);
    window.addEventListener('resize', updateCurrentSlide);

    return () => {
      container.removeEventListener('scroll', handleScroll);
      window.removeEventListener('resize', updateCurrentSlide);
    };
  }, [slidesToRender, slidesVisible]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (isBranchMapOpen) {
        return;
      }

      if (isEditableTarget(event.target)) {
        return;
      }

      const { key, ctrlKey, metaKey, altKey, repeat } = event;
      const normalizedKey = String(key || '').toLowerCase();
      const hasModifier = ctrlKey || metaKey || altKey;

      if (normalizedKey === 'h' && !hasModifier) {
        if (repeat) {
          return;
        }
        event.preventDefault();
        setSlidesVisible((previous) => !previous);
        return;
      }

      if (!hasDeck) {
        return;
      }

      if (normalizedKey === '/' && !hasModifier) {
        event.preventDefault();
        slideSearchInputRef.current?.focus();
        return;
      }

      if (hasModifier) {
        return;
      }

      if (repeat && ['q', 's', 't'].includes(normalizedKey)) {
        return;
      }

      const currentIndexValue = Number(currentSlideIndexRef.current);
      const activeSlideShortcutIndex = Number.isFinite(currentIndexValue)
        ? Math.max(0, Math.min(Math.round(currentIndexValue), slides.length - 1))
        : 0;

      if (normalizedKey === 'q') {
        event.preventDefault();
        const composer = inputRef.current;
        if (!composer || composer.disabled) {
          return;
        }

        composer.focus();
        const cursor = composer.value.length;
        composer.setSelectionRange(cursor, cursor);
        return;
      }

      if (normalizedKey === 's' && slidesVisible && slides.length) {
        event.preventDefault();
        toggleBookmark(activeSlideShortcutIndex);
        return;
      }

      if (normalizedKey === 't' && slidesVisible && slides.length && isDeckNarrationEnabled) {
        event.preventDefault();
        setActiveTranscriptSlideIndex((previous) =>
          previous === activeSlideShortcutIndex ? null : activeSlideShortcutIndex
        );
        return;
      }

      if (key === 'ArrowLeft' && branchOrder.length > 1) {
        event.preventDefault();
        switchBranchByOffset(-1);
        return;
      }

      if (key === 'ArrowRight' && branchOrder.length > 1) {
        event.preventDefault();
        switchBranchByOffset(1);
        return;
      }

      if ([' ', 'PageDown', 'ArrowDown'].includes(key)) {
        event.preventDefault();
        scrollToRelativeSlide(1);
      } else if (['Backspace', 'PageUp', 'ArrowUp'].includes(key)) {
        event.preventDefault();
        scrollToRelativeSlide(-1);
      } else if (key === 'Home') {
        event.preventDefault();
        scrollToVisibleEdge('start');
      } else if (key === 'End') {
        event.preventDefault();
        scrollToVisibleEdge('end');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    hasDeck,
    branchOrder.length,
    switchBranchByOffset,
    isBranchMapOpen,
    navigableSlideIndices,
    isDeckNarrationEnabled,
    slides.length,
    slidesVisible,
  ]);

  useEffect(() => {
    if (activeTranscriptSlideIndex === null) {
      return;
    }
    if (activeTranscriptSlideIndex < slides.length) {
      return;
    }
    setActiveTranscriptSlideIndex(null);
  }, [activeTranscriptSlideIndex, slides.length]);

  useEffect(() => {
    if (activeSpeechSlideIndex === null) {
      return;
    }
    if (activeSpeechSlideIndex < slides.length) {
      return;
    }

    speechRequestIdRef.current += 1;
    clearSpeechAudio();
    resetSpeechPlaybackState();
  }, [activeSpeechSlideIndex, slides.length, clearSpeechAudio, resetSpeechPlaybackState]);

  useEffect(() => {
    const handleResize = () => {
      setSplitRatio((previous) =>
        clampSplitRatio(previous, workspaceRef.current?.clientWidth || window.innerWidth)
      );
    };

    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [clampSplitRatio]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem(SPLIT_STORAGE_KEY, String(splitRatio));
  }, [splitRatio]);

  useEffect(() => {
    if (!isResizingSplit || !slidesVisible) {
      return;
    }

    const handlePointerMove = (event) => {
      updateSplitFromClientX(event.clientX);
    };

    const stopResizing = () => {
      setIsResizingSplit(false);
    };

    document.body.classList.add('is-resizing-split');
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', stopResizing);
    window.addEventListener('pointercancel', stopResizing);

    return () => {
      document.body.classList.remove('is-resizing-split');
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopResizing);
      window.removeEventListener('pointercancel', stopResizing);
    };
  }, [isResizingSplit, slidesVisible, updateSplitFromClientX]);

  function startSplitResize(event) {
    if (event.button !== 0 || !slidesVisible) {
      return;
    }

    event.preventDefault();
    updateSplitFromClientX(event.clientX);
    setIsResizingSplit(true);
  }

  function handleDividerKeyDown(event) {
    if (!slidesVisible) {
      return;
    }

    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      event.stopPropagation();
      setSplitRatio((previous) => clampSplitRatio(previous - 0.02));
      return;
    }

    if (event.key === 'ArrowRight') {
      event.preventDefault();
      event.stopPropagation();
      setSplitRatio((previous) => clampSplitRatio(previous + 0.02));
      return;
    }

    if (event.key === 'Home') {
      event.preventDefault();
      event.stopPropagation();
      setSplitRatio(() => clampSplitRatio(SPLIT_MIN_RATIO));
      return;
    }

    if (event.key === 'End') {
      event.preventDefault();
      event.stopPropagation();
      setSplitRatio(() => clampSplitRatio(SPLIT_MAX_RATIO));
    }
  }

  const slidesPaneStyle = { flex: `0 0 ${splitPercentage}%` };

  async function clearChat() {
    if (clearingChatRef.current || sendingRef.current) {
      return;
    }

    setError('');

    if (!deck?.deck_id) {
      resetBranches();
      setInputValue('');
      setEditingMessageId(null);
      setMessageDraft('');
      setCopiedMessageId(null);
      return;
    }

    clearingChatRef.current = true;
    setClearingChat(true);

    try {
      const response = await fetch(apiUrl(`/api/v1/decks/${deck.deck_id}/chat/clear`), {
        method: 'POST',
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(extractApiErrorMessage(data, 'Failed to clear chat'));
      }

      resetBranches();
      setInputValue('');
      setEditingMessageId(null);
      setMessageDraft('');
      setCopiedMessageId(null);
      contextSentValueRef.current = null;
    } catch (clearError) {
      setError(normalizeError(clearError, 'Failed to clear chat'));
    } finally {
      clearingChatRef.current = false;
      setClearingChat(false);
    }
  }

  function openContextModal() {
    setContextDraft('');
    setEditingContextIndex(null);
    setIsContextModalOpen(true);
  }

  function closeContextModal() {
    setIsContextModalOpen(false);
    setEditingContextIndex(null);
    setContextDraft('');
  }

  function getJoinedContextLength(entries) {
    if (!entries.length) return 0;
    return entries.join(CONTEXT_SEPARATOR).length;
  }

  function addContextEntry() {
    const trimmed = contextDraft.trim();
    if (!trimmed) return;
    const prospective = editingContextIndex !== null
      ? contextEntries.map((entry, i) => (i === editingContextIndex ? trimmed : entry))
      : [...contextEntries, trimmed];
    if (getJoinedContextLength(prospective) > MAX_CONTEXT_TOTAL_LENGTH) {
      return;
    }
    setContextEntries(prospective);
    if (editingContextIndex !== null) {
      setEditingContextIndex(null);
    }
    setContextDraft('');
  }

  function startEditingContextEntry(index) {
    setEditingContextIndex(index);
    setContextDraft(contextEntries[index]);
  }

  function cancelEditingContextEntry() {
    setEditingContextIndex(null);
    setContextDraft('');
  }

  function deleteContextEntry(index) {
    setContextEntries((prev) => prev.filter((_, i) => i !== index));
    if (editingContextIndex === index) {
      setEditingContextIndex(null);
      setContextDraft('');
    } else if (editingContextIndex !== null && editingContextIndex > index) {
      setEditingContextIndex((prev) => prev - 1);
    }
  }

  function deleteAllContextEntries() {
    setContextEntries([]);
    setEditingContextIndex(null);
    setContextDraft('');
  }

  function startEditingMessage(messageId) {
    const message = messages.find((item) => item.id === messageId);
    if (!message) {
      return;
    }

    setEditingMessageId(messageId);
    setMessageDraft(message.content);
  }

  function cancelEditingMessage() {
    setEditingMessageId(null);
    setMessageDraft('');
  }

  function saveEditingMessage(messageId) {
    if (messageId !== editingMessageId) {
      return;
    }

    if (!messageDraft.trim()) {
      return;
    }

    updateActiveBranchMessages((previous) =>
      previous.map((message) =>
        message.id === messageId
          ? { ...message, content: messageDraft }
          : message
      )
    );
    setEditingMessageId(null);
    setMessageDraft('');
  }

  async function copyMessage(messageId) {
    const message = messages.find((item) => item.id === messageId);
    if (!message) {
      return;
    }

    try {
      await copyTextToClipboard(message.content);
      setCopiedMessageId(messageId);
      if (copyResetTimerRef.current) {
        window.clearTimeout(copyResetTimerRef.current);
      }
      copyResetTimerRef.current = window.setTimeout(() => {
        setCopiedMessageId(null);
      }, 1500);
    } catch (copyError) {
      setError(normalizeError(copyError, 'Failed to copy message'));
    }
  }

  async function streamMessageToBranch({
    branchId,
    question,
    queuedMessageId = null,
    requestContext = null,
  }) {
    const normalizedQuestion = String(question || '').trim();
    if (!deck?.deck_id || !branchId || sendingRef.current || !normalizedQuestion) {
      return false;
    }

    const branchSnapshot = branchesRef.current[branchId];
    if (!branchSnapshot) {
      return false;
    }

    const contextSnapshot = [...contextEntries];

    if (queuedMessageId) {
      removeQueuedMessage(branchId, queuedMessageId);
    }

    setError('');
    const branchHistory = branchSnapshot.messages
      .filter((message) => message.id !== WELCOME_MESSAGE.id && message.content?.trim())
      .slice(-MAX_CHAT_HISTORY_MESSAGES)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));
    const normalizedRequestContext = buildRequestContextSnapshot(
      requestContext || {
        currentSlideIndex,
        focusedSlideIndex,
      }
    );

    const timestamp = Date.now();
    const randomId = Math.random().toString(36).slice(2, 8);
    const userMessage = {
      id: `user-${timestamp}-${randomId}`,
      role: 'user',
      content: normalizedQuestion,
    };

    const assistantId = `assistant-${timestamp}-${Math.random().toString(36).slice(2, 8)}`;
    const assistantMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
    };

    updateBranchMessages(branchId, (previous) => [
      ...previous,
      userMessage,
      assistantMessage,
    ]);
    sendingRef.current = true;
    setSending(true);
    setStreamingBranchId(branchId);

    try {
      const response = await fetch(apiUrl(`/api/v1/decks/${deck.deck_id}/chat/stream`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: normalizedQuestion,
          history: branchHistory,
          current_slide_index: normalizedRequestContext.currentSlideIndex,
          focused_slide_index: normalizedRequestContext.focusedSlideIndex,
          additional_context: (() => {
            if (!contextSnapshot.length) return null;
            const joined = contextSnapshot.join(CONTEXT_SEPARATOR);
            return joined !== contextSentValueRef.current ? joined : null;
          })(),
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(extractApiErrorMessage(data, 'Failed to start AI stream'));
      }

      await consumeSse(response, (payload) => {
        if (payload.type === 'chunk' && typeof payload.text === 'string') {
          updateBranchMessages(branchId, (previous) =>
            previous.map((message) =>
              message.id === assistantId
                ? { ...message, content: message.content + payload.text }
                : message
            )
          );
          return;
        }

        if (payload.type === 'error') {
          const message = payload.message || 'Unknown AI error';
          updateBranchMessages(branchId, (previous) =>
            previous.map((item) =>
              item.id === assistantId
                ? { ...item, content: `Error: ${message}` }
                : item
            )
          );
        }
      });

      if (contextSnapshot.length) {
        const joined = contextSnapshot.join(CONTEXT_SEPARATOR);
        if (joined !== contextSentValueRef.current) {
          contextSentValueRef.current = joined;
        }
      }
    } catch (streamError) {
      const message = normalizeError(streamError, 'Failed to stream AI response');
      updateBranchMessages(branchId, (previous) =>
        previous.map((item) =>
          item.id === assistantId
            ? { ...item, content: `Error: ${message}` }
            : item
        )
      );
      setError(message);
    } finally {
      sendingRef.current = false;
      setSending(false);
      setStreamingBranchId(null);

      void saveConversationToBackend(deck?.deck_id);

      const nextQueuedMessage = getNextQueuedMessageToSend(branchId);
      if (nextQueuedMessage?.content?.trim()) {
        window.setTimeout(() => {
          void streamMessageToBranch({
            branchId,
            question: nextQueuedMessage.content,
            queuedMessageId: nextQueuedMessage.id,
            requestContext:
              nextQueuedMessage.requestContext || buildRequestContextSnapshot({}),
          });
        }, 0);
      } else if (branchId === activeBranchIdRef.current) {
        inputRef.current?.focus();
      }
    }

    return true;
  }

  function continueQueuedMessagesIfPossible(branchId) {
    if (sendingRef.current || clearingChatRef.current) {
      return;
    }

    const nextQueuedMessage = getNextQueuedMessageToSend(branchId);
    if (!nextQueuedMessage?.content?.trim()) {
      return;
    }

    void streamMessageToBranch({
      branchId,
      question: nextQueuedMessage.content,
      queuedMessageId: nextQueuedMessage.id,
      requestContext: nextQueuedMessage.requestContext || buildRequestContextSnapshot({}),
    });
  }

  async function submitComposerMessage() {
    if (!deck?.deck_id || clearingChatRef.current) {
      return;
    }

    const question = inputValue.trim();
    if (!question) {
      return;
    }

    if (sendingRef.current) {
      if (!editingQueuedMessageId) {
        enqueueMessageForBranch(activeBranchId, question, {
          currentSlideIndex,
          focusedSlideIndex,
        });
      }
      setInputValue('');
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
      setQueueDraftSnapshot('');
      return;
    }

    if (editingQueuedMessageId) {
      setInputValue('');
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
      setQueueDraftSnapshot('');
      window.setTimeout(() => {
        continueQueuedMessagesIfPossible(activeBranchId);
      }, 0);
      return;
    }

    setInputValue('');
    await streamMessageToBranch({
      branchId: activeBranchId,
      question,
      queuedMessageId: null,
    });
  }

  async function sendMessage(event) {
    event.preventDefault();
    await submitComposerMessage();
  }

  async function sendQueuedMessageNow(queuedMessageId) {
    if (sendingRef.current || clearingChatRef.current) {
      return;
    }

    if (editingQueuedMessageId === queuedMessageId) {
      return;
    }

    const branchQueue = queuedMessagesByBranchRef.current[activeBranchId] || [];
    const queuedMessage = branchQueue.find((item) => item.id === queuedMessageId);
    if (!queuedMessage?.content?.trim()) {
      return;
    }

    setInputValue('');
    editingQueuedMessageIdRef.current = null;
    setEditingQueuedMessageId(null);
    setQueueDraftSnapshot('');

    await streamMessageToBranch({
      branchId: activeBranchId,
      question: queuedMessage.content,
      queuedMessageId,
      requestContext: queuedMessage.requestContext || buildRequestContextSnapshot({}),
    });
  }

  function focusQueuedMessageForEditing(queuedMessageId) {
    const branchQueue = queuedMessagesByBranchRef.current[activeBranchId] || [];
    const queuedMessage = branchQueue.find((item) => item.id === queuedMessageId);
    if (!queuedMessage) {
      return;
    }

    if (!editingQueuedMessageId) {
      setQueueDraftSnapshot(inputValue);
    }
    editingQueuedMessageIdRef.current = queuedMessageId;
    setEditingQueuedMessageId(queuedMessageId);
    setInputValue(queuedMessage.content);
    inputRef.current?.focus();
  }

  function removeQueuedMessageFromActiveBranch(queuedMessageId) {
    removeQueuedMessage(activeBranchId, queuedMessageId);
    if (editingQueuedMessageId === queuedMessageId) {
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
      setQueueDraftSnapshot('');
      setInputValue('');
      inputRef.current?.focus();
      window.setTimeout(() => {
        continueQueuedMessagesIfPossible(activeBranchId);
      }, 0);
    }
  }

  function handleComposerChange(event) {
    const nextValue = event.target.value;
    setInputValue(nextValue);

    if (!editingQueuedMessageId) {
      return;
    }

    if (!nextValue.trim()) {
      removeQueuedMessage(activeBranchId, editingQueuedMessageId);
      editingQueuedMessageIdRef.current = null;
      setEditingQueuedMessageId(null);
      setQueueDraftSnapshot('');
      window.setTimeout(() => {
        continueQueuedMessagesIfPossible(activeBranchId);
      }, 0);
      return;
    }

    updateQueuedMessage(activeBranchId, editingQueuedMessageId, nextValue);
  }

  function handleComposerKeyDown(event) {
    if (event.nativeEvent?.isComposing) {
      return;
    }

    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submitComposerMessage();
      return;
    }

    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      if (editingQueuedMessageId) {
        editingQueuedMessageIdRef.current = null;
        setEditingQueuedMessageId(null);
        setQueueDraftSnapshot('');
        window.setTimeout(() => {
          continueQueuedMessagesIfPossible(activeBranchId);
        }, 0);
      }

      event.currentTarget.blur();
      return;
    }

    if (event.key === 'ArrowUp') {
      const atStart =
        event.currentTarget.selectionStart === 0 &&
        event.currentTarget.selectionEnd === 0;
      if (!atStart || !queuedMessages.length) {
        return;
      }

      event.preventDefault();
      if (queueEditingIndex < 0) {
        const newestIndex = queuedMessages.length - 1;
        const newestMessage = queuedMessages[newestIndex];
        if (!newestMessage) {
          return;
        }
        setQueueDraftSnapshot(inputValue);
        editingQueuedMessageIdRef.current = newestMessage.id;
        setEditingQueuedMessageId(newestMessage.id);
        setInputValue(newestMessage.content);
        return;
      }

      const previousIndex = Math.max(0, queueEditingIndex - 1);
      const previousMessage = queuedMessages[previousIndex];
      if (!previousMessage) {
        return;
      }
      editingQueuedMessageIdRef.current = previousMessage.id;
      setEditingQueuedMessageId(previousMessage.id);
      setInputValue(previousMessage.content);
      return;
    }

    if (event.key === 'ArrowDown' && queueEditingIndex >= 0) {
      const atEnd =
        event.currentTarget.selectionStart === inputValue.length &&
        event.currentTarget.selectionEnd === inputValue.length;
      if (!atEnd) {
        return;
      }

      event.preventDefault();
      const nextIndex = queueEditingIndex + 1;
      if (nextIndex >= queuedMessages.length) {
        editingQueuedMessageIdRef.current = null;
        setEditingQueuedMessageId(null);
        setInputValue(queueDraftSnapshot);
        setQueueDraftSnapshot('');
        window.setTimeout(() => {
          continueQueuedMessagesIfPossible(activeBranchId);
        }, 0);
        return;
      }

      const nextMessage = queuedMessages[nextIndex];
      if (!nextMessage) {
        return;
      }
      editingQueuedMessageIdRef.current = nextMessage.id;
      setEditingQueuedMessageId(nextMessage.id);
      setInputValue(nextMessage.content);
    }
  }

  function renderBranchNodes(nodes, depth = 0) {
    if (!nodes.length) {
      return null;
    }

    return (
      <ul className={`branch-tree-level ${depth === 0 ? 'root' : 'nested'}`} role={depth === 0 ? 'list' : undefined}>
        {nodes.map((node) => (
          <li key={node.key} className="branch-tree-item">
            <button
              type="button"
              className={`branch-node ${node.isActive ? 'active' : ''}`}
              onClick={() => handleTreeNodeClick(node)}
              title={node.tooltip}
            >
              <div className="branch-node-head">
                <span className="branch-node-title">{node.label}</span>
                <span className="branch-node-meta">
                  {node.turnCount} turns · {node.messageCount} messages
                </span>
              </div>
              <p className="branch-node-kind">
                {node.kindLabel}
              </p>
              <span className="branch-node-tooltip" role="tooltip">
                {node.tooltip}
              </span>
            </button>
            {node.childContext ? renderContextNodes([node.childContext], depth + 1) : null}
          </li>
        ))}
      </ul>
    );
  }

  function renderContextNodes(nodes, depth = 0) {
    if (!nodes.length) {
      return null;
    }

    return (
      <ul className={`branch-tree-level ${depth === 0 ? 'root' : 'nested'}`} role={depth === 0 ? 'list' : undefined}>
        {nodes.map((node) => (
          <li key={node.key} className="branch-tree-item">
            {node.canBranch && !sending && !clearingChat ? (
              <button
                type="button"
                className="branch-context-node interactive"
                title={node.tooltip}
                onClick={() => handleContextNodeClick(node)}
              >
                <p className="branch-context-title">{node.title}</p>
                <p className="branch-context-meta">{node.summary}</p>
              </button>
            ) : (
              <div className="branch-context-node" title={node.tooltip}>
                <p className="branch-context-title">{node.title}</p>
                <p className="branch-context-meta">{node.summary}</p>
              </div>
            )}
            {renderBranchNodes(node.branches, depth + 1)}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <h1>Slide Study Studio</h1>
        {deck ? (
          <p className="topbar-deck-name" title={deck.filename}>
            {deck.filename}
          </p>
        ) : null}
        <input
          ref={fileInputRef}
          className="hidden-file-input"
          type="file"
          accept=".pdf,.ppt,.pptx"
          multiple
          onChange={handleFileInputChange}
          disabled={uploading || sending}
        />
      </header>

      {error ? <p className="global-error">{error}</p> : null}

      <main ref={workspaceRef} className="workspace">
        {slidesVisible ? (
          <>
            <section className="slides-panel" style={slidesPaneStyle}>
              {deck?.source_files?.length > 1 ? (
                <div className="file-tabs">
                  <button
                    type="button"
                    className={`file-tab ${activeFileTabIndex === null ? 'active' : ''}`}
                    onClick={() => setActiveFileTabIndex(null)}
                  >
                    All
                  </button>
                  {deck.source_files.map((file, index) => (
                    <button
                      key={index}
                      type="button"
                      className={`file-tab ${activeFileTabIndex === index ? 'active' : ''}`}
                      onClick={() => setActiveFileTabIndex(index)}
                      title={file.filename}
                    >
                      {file.filename.replace(/\.[^/.]+$/, '')}
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="slides-toolbar">
                <div className="slides-toolbar-main">
                  <button
                    type="button"
                    className={`ghost-btn ${narrateEnabled ? 'active' : ''}`}
                    onClick={() => setNarrateEnabled((previous) => !previous)}
                    disabled={uploading || sending}
                    aria-pressed={narrateEnabled}
                    title="Toggle narration generation for the next upload"
                  >
                    Narrate: {narrateEnabled ? 'On' : 'Off'}
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    onClick={() => setSlidesVisible(false)}
                    title="Hide slides (H)"
                    aria-keyshortcuts="h"
                  >
                    Hide Slides
                  </button>
                  <button
                    type="button"
                    className={`ghost-btn ${showBookmarkedOnly ? 'active' : ''}`}
                    onClick={toggleBookmarkedFilter}
                    disabled={!bookmarkedSlideIndices.length && !showBookmarkedOnly}
                    aria-pressed={showBookmarkedOnly}
                  >
                    {showBookmarkedOnly ? 'Show All' : `Starred (${bookmarkedSlideIndices.length})`}
                  </button>
                </div>
                <div className="slides-toolbar-search">
                  <input
                    ref={slideSearchInputRef}
                    type="search"
                    value={slideSearchQuery}
                    onChange={(event) => setSlideSearchQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        const firstResult = slideSearchResults[0];
                        if (firstResult) {
                          jumpToSearchResult(firstResult.slideIndex);
                        }
                        return;
                      }

                      if (event.key === 'Escape') {
                        event.preventDefault();
                        if (slideSearchQuery.trim()) {
                          setSlideSearchQuery('');
                        } else {
                          event.currentTarget.blur();
                        }
                      }
                    }}
                    className="slides-search-input"
                    placeholder="Search slides and transcripts (/)"
                    disabled={!slides.length}
                    aria-label="Search slides and transcripts"
                    aria-keyshortcuts="/"
                  />
                  {slideSearchQuery.trim() ? (
                    <button
                      type="button"
                      className="ghost-btn"
                      onClick={() => setSlideSearchQuery('')}
                    >
                      Clear
                    </button>
                  ) : null}
                </div>
                {transcriptProgressLabel ? (
                  <p
                    className={`transcript-progress transcript-progress-${transcriptState.status}`}
                    aria-live="polite"
                  >
                    {transcriptProgressLabel}
                  </p>
                ) : null}
              </div>

              {normalizedSlideSearchQuery ? (
                <section className="slide-search-results" aria-live="polite">
                  <p className="slide-search-summary">
                    {slideSearchResults.length
                      ? `${slideSearchResults.length} matching slides`
                      : `No matches for "${slideSearchQuery.trim()}"`}
                  </p>
                  {slideSearchResults.length ? (
                    <ul className="slide-search-list">
                      {slideSearchResults.map((result) => (
                        <li key={`search-result-${result.slideIndex}`}>
                          <button
                            type="button"
                            className="slide-search-item"
                            onClick={() => jumpToSearchResult(result.slideIndex)}
                          >
                            <span className="slide-search-item-title">
                              Slide {result.slideIndex + 1} · {result.source}
                              {result.isBookmarked ? ' · Starred' : ''}
                            </span>
                            <span className="slide-search-item-snippet">
                              {renderSearchSnippetWithHighlights(result.snippet)}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              ) : null}

              <div
                className="slides-viewer"
                ref={slideScrollRef}
                role="region"
                aria-label="Slides viewer"
                tabIndex={0}
              >
                {slides.length ? (
                  slidesToRender.length ? (
                    slidesToRender.map((slide) => {
                      const isFocused = focusedSlideIndex === slide.index;
                      const isTranscriptOpen = activeTranscriptSlideIndex === slide.index;
                      const slideTranscript = transcriptsBySlide.get(slide.index) || null;
                      const hasTranscript = Boolean(slideTranscript?.transcript);
                      const narrationEnabledForDeck = deck?.narrate_enabled !== false;
                      const isBookmarked = bookmarkedSlideSet.has(slide.index);
                      const isSpeechSelected = activeSpeechSlideIndex === slide.index;
                      const isSpeechLoading = isSpeechSelected && speechStatus === 'loading';
                      const isSpeechPlaying = isSpeechSelected && speechStatus === 'playing';
                      const isSpeechPaused = isSpeechSelected && speechStatus === 'paused';
                      const isSpeechActive = isSpeechSelected && (isSpeechPlaying || isSpeechPaused);
                      const canSeekSpeech =
                        isSpeechSelected && speechStatus !== 'idle' && speechStatus !== 'loading';
                      const transcriptStatus = slideTranscript?.status || 'pending';
                      const transcriptButtonLabel = isTranscriptOpen
                        ? 'Hide'
                        : !narrationEnabledForDeck
                          ? 'Narration Off'
                        : hasTranscript
                          ? 'Transcript'
                          : transcriptStatus === 'generating' || transcriptState.status === 'queued'
                            ? 'Preparing'
                            : transcriptStatus === 'error'
                              ? 'Unavailable'
                              : 'Pending';
                      const speechButtonTitle = !narrationEnabledForDeck
                        ? `Narration is disabled for Slide ${slide.index + 1}`
                        : !hasTranscript
                        ? `Transcript is not ready for Slide ${slide.index + 1}`
                        : isSpeechLoading
                          ? `Generating narration for Slide ${slide.index + 1}`
                          : isSpeechPlaying
                            ? `Pause narration for Slide ${slide.index + 1}`
                            : isSpeechPaused
                              ? `Resume narration for Slide ${slide.index + 1}`
                            : `Play narration for Slide ${slide.index + 1}`;
                      return (
                        <article
                          key={slide.index}
                          ref={(node) => {
                            slideRefs.current[slide.index] = node;
                          }}
                          className={`slide-card ${isFocused ? 'focused' : ''}`}
                          onClick={() => toggleFocus(slide.index)}
                        >
                          <div className="slide-card-header">
                            <p className="slide-label">Slide {slide.index + 1}</p>
                            <div className="slide-card-actions">
                              <button
                                type="button"
                                className={`slide-bookmark-btn ${isBookmarked ? 'active' : ''}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  toggleBookmark(slide.index);
                                }}
                                aria-label={`${isBookmarked ? 'Remove' : 'Add'} bookmark for Slide ${slide.index + 1}`}
                                aria-pressed={isBookmarked}
                                title={`${isBookmarked ? 'Remove' : 'Add'} bookmark for Slide ${slide.index + 1} (S)`}
                                aria-keyshortcuts="s"
                              >
                                <StarIcon />
                              </button>
                              <button
                                type="button"
                                className={`slide-transcript-btn ${hasTranscript ? 'ready' : ''}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openTranscriptModal(slide.index);
                                }}
                                aria-label={`${isTranscriptOpen ? 'Hide' : 'Open'} transcript for Slide ${slide.index + 1}`}
                                title={`${isTranscriptOpen ? 'Hide' : 'Open'} transcript for Slide ${slide.index + 1} (T)`}
                                aria-keyshortcuts="t"
                                disabled={!narrationEnabledForDeck}
                              >
                                {transcriptButtonLabel}
                              </button>
                              <button
                                type="button"
                                className={`slide-speech-btn ${isSpeechActive ? 'active' : ''} ${isSpeechLoading ? 'loading' : ''}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  toggleTranscriptSpeech(slide.index, slideTranscript?.transcript);
                                }}
                                aria-label={`${isSpeechActive ? 'Pause or resume' : 'Play'} narration for Slide ${slide.index + 1}`}
                                title={speechButtonTitle}
                                aria-pressed={isSpeechActive}
                                disabled={!hasTranscript || !narrationEnabledForDeck}
                              >
                                <SpeakerIcon />
                              </button>
                            </div>
                          </div>
                          {isSpeechSelected ? (
                            <section
                              className="slide-speech-row"
                              onClick={(event) => {
                                event.stopPropagation();
                              }}
                            >
                              <div className="slide-speech-row-main">
                                <div className="slide-speech-row-controls">
                                  <button
                                    type="button"
                                    className="slide-speech-control-btn"
                                    onClick={() => seekTranscriptSpeechBy(-15)}
                                    disabled={!canSeekSpeech}
                                    aria-label={`Jump back 15 seconds for Slide ${slide.index + 1} narration`}
                                  >
                                    -15s
                                  </button>
                                  <button
                                    type="button"
                                    className="slide-speech-control-btn primary"
                                    onClick={() => toggleTranscriptSpeech(slide.index, slideTranscript?.transcript)}
                                    aria-label={`${isSpeechPlaying ? 'Pause' : 'Play'} Slide ${slide.index + 1} narration`}
                                  >
                                    {isSpeechPlaying ? 'Pause' : isSpeechLoading ? 'Loading' : 'Play'}
                                  </button>
                                  <button
                                    type="button"
                                    className="slide-speech-control-btn"
                                    onClick={() => seekTranscriptSpeechBy(15)}
                                    disabled={!canSeekSpeech}
                                    aria-label={`Jump forward 15 seconds for Slide ${slide.index + 1} narration`}
                                  >
                                    +15s
                                  </button>
                                </div>
                                <p className="slide-speech-row-time">
                                  {formatPlaybackClock(speechCurrentTimeSeconds)} / {formatPlaybackClock(speechDurationSeconds)}
                                </p>
                              </div>
                              {speechIsBuffering ? (
                                <p className="slide-speech-row-state">Buffering narration…</p>
                              ) : null}
                            </section>
                          ) : null}
                          {isTranscriptOpen ? (
                            <section
                              className="slide-transcript-row"
                              onClick={(event) => {
                                event.stopPropagation();
                                closeTranscriptModal();
                              }}
                            >
                              <div className="slide-transcript-row-body">
                                {hasTranscript ? (
                                  <p className="slide-transcript-row-text">{slideTranscript.transcript}</p>
                                ) : !narrationEnabledForDeck ? (
                                  <p className="slide-transcript-row-state">
                                    Narration is disabled for this deck.
                                  </p>
                                ) : transcriptStatus === 'error' ? (
                                  <p className="slide-transcript-row-state error">
                                    {slideTranscript?.error || 'Transcript generation failed for this slide.'}
                                  </p>
                                ) : transcriptState.status === 'error' ? (
                                  <p className="slide-transcript-row-state error">
                                    {transcriptState.error || 'Transcript generation ended with errors.'}
                                  </p>
                                ) : (
                                  <p className="slide-transcript-row-state">
                                    Transcript is being prepared for this slide.
                                  </p>
                                )}
                              </div>
                            </section>
                          ) : null}
                          <div className="slide-image-wrap">
                            <img
                              src={slideImageUrl(slide.index)}
                              alt={`Slide ${slide.index + 1}`}
                              loading="lazy"
                            />
                          </div>
                        </article>
                      );
                    })
                  ) : (
                    <div className="empty-state">
                      <p className="dropzone-title">No starred slides yet</p>
                      <p className="dropzone-subtitle">Star slides to build a focused review list.</p>
                    </div>
                  )
                ) : (
                  <div
                    className={`empty-state upload-dropzone ${isDragActive ? 'drag-over' : ''}`}
                    onClick={triggerFilePicker}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        triggerFilePicker();
                      }
                    }}
                    onDragEnter={handleDropZoneDragEnter}
                    onDragOver={handleDropZoneDragOver}
                    onDragLeave={handleDropZoneDragLeave}
                    onDrop={handleDropZoneDrop}
                    role="button"
                    tabIndex={uploading || sending ? -1 : 0}
                    aria-disabled={uploading || sending}
                    aria-label="Upload by dragging and dropping one or more PDFs or PowerPoint files, or click to choose files"
                  >
                    <p className="dropzone-title">
                      {uploading
                        ? 'Uploading your deck...'
                        : isDragActive
                          ? 'Drop files to upload'
                          : 'Drag and drop PDF/PowerPoint files here'}
                    </p>
                    <p className="dropzone-subtitle">
                      {uploading ? 'Processing slides now.' : 'or click to choose files — select multiple to combine'}
                    </p>
                  </div>
                )}
              </div>

              <footer className="slides-footer">
                {slides.length ? (
                  <p>
                    Slide {currentSlideIndex + 1} of {slides.length}
                    {showBookmarkedOnly ? ` · Showing ${slidesToRender.length} starred slides` : ''}
                  </p>
                ) : (
                  <p>No slides</p>
                )}
                {slides.length ? (
                  <p className="shortcut-hint">
                    Shortcuts: / search · S star current slide · T transcript · H hide/show slides · Q ask AI
                  </p>
                ) : null}
              </footer>
            </section>

            <button
              type="button"
              className="pane-divider"
              onPointerDown={startSplitResize}
              onKeyDown={handleDividerKeyDown}
              aria-label="Resize slides and AI panels"
              aria-valuemin={20}
              aria-valuemax={80}
              aria-valuenow={Math.round(splitPercentage)}
              role="separator"
              aria-orientation="vertical"
            >
              <span />
            </button>
          </>
        ) : null}

        <section className="chat-panel">
          <header className="chat-header">
            {slidesVisible ? (
              <h2>Ask AI</h2>
            ) : (
              <button
                type="button"
                className="ghost-btn"
                onClick={() => setSlidesVisible(true)}
                title="Show slides (H)"
                aria-keyshortcuts="h"
              >
                Show Slides
              </button>
            )}
            <div className="chat-actions">
              <p className="branch-status">
                {activeBranch?.label || 'Branch'} {activeBranchIndex + 1}/{branchOrder.length} · Queue {queuedMessages.length} · Use ←/→
              </p>
              <button
                type="button"
                className="ghost-btn icon-btn"
                onClick={() => setIsBranchMapOpen(true)}
                disabled={!branchTree.hasNodes}
                aria-label="View conversation branches"
                title="View branches"
              >
                <BranchTreeIcon />
              </button>
              <button
                type="button"
                className={`ghost-btn icon-btn${contextEntries.length ? ' has-context' : ''}`}
                onClick={openContextModal}
                disabled={!hasDeck}
                aria-label={contextEntries.length ? `Additional context (${contextEntries.length})` : 'Add additional context'}
                title={contextEntries.length ? `Additional context (${contextEntries.length})` : 'Add additional context'}
              >
                <NoteIcon />
              </button>
              <button
                type="button"
                className="ghost-btn icon-btn"
                onClick={clearChat}
                disabled={!hasDeck || sending || clearingChat}
                aria-label={clearingChat ? 'Clearing chat' : 'Clear chat'}
                title={clearingChat ? 'Clearing chat' : 'Clear chat'}
              >
                <ClearChatIcon />
              </button>
            </div>
          </header>

          <div className="messages-list">
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                isEditing={editingMessageId === message.id}
                editDraft={editingMessageId === message.id ? messageDraft : ''}
                isCopied={copiedMessageId === message.id}
                canBranch={!sending && !clearingChat}
                onBranchFromAssistant={createBranchFromAssistant}
                onCopy={copyMessage}
                onEditStart={startEditingMessage}
                onEditCancel={cancelEditingMessage}
                onEditSave={saveEditingMessage}
                onEditDraftChange={setMessageDraft}
              />
            ))}
            {sending ? <p className="typing-indicator">AI is typing...</p> : null}
          </div>

          {queuedMessages.length ? (
            <section className="queued-messages-panel" aria-live="polite">
              <div className="queued-messages-header">
                <p>
                  Queued on {activeBranch?.label || 'Branch'}: {queuedMessages.length}
                </p>
                {sending && streamingBranchId === activeBranchId ? (
                  <span>Sending in order...</span>
                ) : editingQueuedMessageId ? (
                  <span>Queue paused at edited item.</span>
                ) : null}
              </div>
              <ul className="queued-message-list">
                {queuedMessages.map((queuedMessage, index) => (
                  <li
                    key={queuedMessage.id}
                    className={`queued-message-item ${
                      editingQueuedMessageId === queuedMessage.id ? 'active' : ''
                    }`}
                  >
                    <button
                      type="button"
                      className="queued-message-text"
                      title={queuedMessage.content}
                      onClick={() => focusQueuedMessageForEditing(queuedMessage.id)}
                    >
                      <span className="queued-message-index">#{index + 1}</span>
                      <span>{queuedMessage.content}</span>
                    </button>
                    <div className="queued-message-actions">
                      {!sending &&
                      !clearingChat &&
                      index === 0 &&
                      editingQueuedMessageId !== queuedMessage.id ? (
                        <button
                          type="button"
                          className="message-action-btn primary"
                          onClick={() => sendQueuedMessageNow(queuedMessage.id)}
                        >
                          Send Next
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="message-action-btn icon-only"
                        onClick={() => focusQueuedMessageForEditing(queuedMessage.id)}
                        aria-label={
                          editingQueuedMessageId === queuedMessage.id
                            ? 'Editing queued message'
                            : 'Edit queued message'
                        }
                        title={
                          editingQueuedMessageId === queuedMessage.id
                            ? 'Editing queued message'
                            : 'Edit'
                        }
                      >
                        <EditIcon />
                      </button>
                      <button
                        type="button"
                        className="message-action-btn"
                        onClick={() => removeQueuedMessageFromActiveBranch(queuedMessage.id)}
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <form className="chat-input" onSubmit={sendMessage}>
            <textarea
              ref={inputRef}
              value={inputValue}
              onChange={handleComposerChange}
              onKeyDown={handleComposerKeyDown}
              placeholder={inputPlaceholder}
              disabled={!hasDeck || clearingChat}
              rows={Math.min(5, Math.max(1, inputValue.split('\n').length))}
              aria-label="Message composer"
              aria-keyshortcuts="q"
            />
            <button
              type="submit"
              className="chat-send-btn"
              disabled={!hasDeck || sending || clearingChat || !inputValue.trim()}
              aria-label="Send message"
              title="Send"
            >
              <SendIcon />
            </button>
            <p className="composer-hint">
              {sending
                ? 'AI is still responding. Press Enter to queue this branch message. Shortcuts: /, S, T, H, Q.'
                : editingQueuedMessageId
                  ? 'Editing queued message. Press Esc to leave queue edit mode. Shortcuts: /, S, T, H, Q.'
                  : 'Press Enter to send. Shift+Enter adds a new line. Use ↑/↓ to browse queued prompts. Shortcuts: /, S, T, H, Q.'}
            </p>
          </form>
        </section>
      </main>

      {isBranchMapOpen ? (
        <div
          className="branch-map-backdrop"
          role="presentation"
          onClick={() => setIsBranchMapOpen(false)}
        >
          <section
            className="branch-map-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Conversation branch map"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="branch-map-header">
              <div>
                <h3>Conversation Branches</h3>
                <p>Click a branch to switch. Click a context node to create a new branch from that context.</p>
              </div>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => setIsBranchMapOpen(false)}
              >
                Close
              </button>
            </header>

            <div className="branch-map-tree">
              {branchTree.rootContexts.length ? (
                <div className="branch-tree-shell">
                  {renderContextNodes(branchTree.rootContexts)}
                </div>
              ) : (
                <p className="branch-tree-empty">No branches yet.</p>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {isContextModalOpen ? (
        <div
          className="context-modal-backdrop"
          role="presentation"
          onClick={closeContextModal}
        >
          <section
            className="context-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Additional context"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="context-modal-header">
              <div>
                <h3>Additional Context</h3>
                <p>{contextEntries.length ? `${contextEntries.length} entr${contextEntries.length === 1 ? 'y' : 'ies'}` : 'No entries yet'}</p>
              </div>
              <div className="context-modal-header-actions">
                {contextEntries.length > 0 ? (
                  <button
                    type="button"
                    className="ghost-btn danger-btn"
                    onClick={deleteAllContextEntries}
                  >
                    Clear All
                  </button>
                ) : null}
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={closeContextModal}
                >
                  Close
                </button>
              </div>
            </header>

            <div className="context-modal-body">
              {contextEntries.length > 0 ? (
                <ul className="context-entry-list">
                  {contextEntries.map((entry, index) => (
                    <li key={index} className="context-entry-item">
                      <div className="context-entry-text">{entry}</div>
                      <div className="context-entry-actions">
                        <button
                          type="button"
                          className="message-action-btn"
                          onClick={() => startEditingContextEntry(index)}
                          title="Edit"
                        >
                          <EditIcon />
                        </button>
                        <button
                          type="button"
                          className="message-action-btn"
                          onClick={() => deleteContextEntry(index)}
                          title="Delete"
                        >
                          <DeleteIcon />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : null}

              <div className="context-entry-form">
                {(() => {
                  const trimmed = contextDraft.trim();
                  const prospective = !trimmed ? contextEntries
                    : editingContextIndex !== null
                      ? contextEntries.map((e, i) => (i === editingContextIndex ? trimmed : e))
                      : [...contextEntries, trimmed];
                  const totalLength = getJoinedContextLength(prospective);
                  const overLimit = trimmed && totalLength > MAX_CONTEXT_TOTAL_LENGTH;
                  const currentLength = getJoinedContextLength(contextEntries);
                  return (
                    <>
                      <textarea
                        className="context-modal-textarea"
                        value={contextDraft}
                        onChange={(event) => setContextDraft(event.target.value)}
                        placeholder="Enter additional context (e.g., course notes, syllabus details, key topics to focus on...)"
                        rows={4}
                        autoFocus
                      />
                      <div className="context-entry-form-actions">
                        {currentLength > 0 ? (
                          <span className={`context-char-count${overLimit ? ' over-limit' : ''}`}>
                            {currentLength.toLocaleString()} / {MAX_CONTEXT_TOTAL_LENGTH.toLocaleString()}
                          </span>
                        ) : null}
                        {editingContextIndex !== null ? (
                          <>
                            <button
                              type="button"
                              className="ghost-btn"
                              onClick={cancelEditingContextEntry}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="ghost-btn primary-btn"
                              onClick={addContextEntry}
                              disabled={!trimmed || overLimit}
                            >
                              Save
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className="ghost-btn primary-btn"
                            onClick={addContextEntry}
                            disabled={!trimmed || overLimit}
                          >
                            Add
                          </button>
                        )}
                      </div>
                    </>
                  );
                })()}
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export default App;
