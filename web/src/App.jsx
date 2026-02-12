import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

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

function MessageBubble({
  message,
  isEditing,
  editDraft,
  isCopied,
  onCopy,
  onEditStart,
  onEditCancel,
  onEditSave,
  onEditDraftChange,
}) {
  const normalizedAssistantMarkdown = preprocessAssistantMarkdown(message.content);
  const canSaveEdit = editDraft.trim().length > 0 && editDraft !== message.content;

  const markdownComponents = {
    code({ inline, className, children, ...props }) {
      const rawCode = String(children).replace(/\n$/, '');
      const languageMatch = /language-([a-zA-Z0-9_+-]+)/.exec(className || '');
      const hintedLanguage = languageMatch ? languageMatch[1] : '';
      const detected = detectLanguageFromCode(rawCode, hintedLanguage);
      const language = detected.language;

      if (!inline) {
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
            className="message-action-btn"
            onClick={() => onCopy(message.id)}
            aria-label={`Copy ${roleLabel} message`}
          >
            {isCopied ? 'Copied' : 'Copy'}
          </button>
          {!isEditing ? (
            <button
              type="button"
              className="message-action-btn"
              onClick={() => onEditStart(message.id)}
              aria-label={`Edit ${roleLabel} message`}
            >
              Edit
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
          <ReactMarkdown components={markdownComponents}>{normalizedAssistantMarkdown}</ReactMarkdown>
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
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [inputValue, setInputValue] = useState('');
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [clearingChat, setClearingChat] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState(null);
  const [messageDraft, setMessageDraft] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState(null);
  const [error, setError] = useState('');
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [focusedSlideIndex, setFocusedSlideIndex] = useState(null);
  const [slidesVisible, setSlidesVisible] = useState(true);
  const [splitRatio, setSplitRatio] = useState(() => loadInitialSplitRatio());
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);

  const workspaceRef = useRef(null);
  const slideScrollRef = useRef(null);
  const slideRefs = useRef([]);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const currentSlideIndexRef = useRef(0);
  const dragDepthRef = useRef(0);
  const copyResetTimerRef = useRef(null);

  useEffect(() => {
    currentSlideIndexRef.current = currentSlideIndex;
  }, [currentSlideIndex]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages]);

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
    return () => {
      if (copyResetTimerRef.current) {
        window.clearTimeout(copyResetTimerRef.current);
      }
    };
  }, []);

  const hasDeck = Boolean(deck?.deck_id);
  const splitPercentage = Number((splitRatio * 100).toFixed(1));

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

  async function fetchSlides(deckId) {
    const response = await fetch(apiUrl(`/api/v1/decks/${deckId}/slides`));
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || 'Failed to load slides');
    }

    const data = await response.json();
    setSlides(data.slides || []);
    setCurrentSlideIndex(0);
    setFocusedSlideIndex(null);
  }

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

  async function processUploadFile(file) {
    setError('');
    setUploading(true);

    try {
      if (deck?.deck_id) {
        await safeDeleteDeck(deck.deck_id);
      }

      const form = new FormData();
      form.append('file', file);

      const response = await fetch(apiUrl('/api/v1/decks/upload'), {
        method: 'POST',
        body: form,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Upload failed');
      }

      const payload = await response.json();
      setDeck(payload);
      setMessages([WELCOME_MESSAGE]);
      setInputValue('');
      await fetchSlides(payload.deck_id);
    } catch (uploadError) {
      setError(normalizeError(uploadError, 'Failed to upload deck'));
      setDeck(null);
      setSlides([]);
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
    const file = event.target.files?.[0];
    if (file) {
      await processUploadFile(file);
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

    const file = event.dataTransfer.files?.[0];
    resetDropState();

    if (file) {
      await processUploadFile(file);
    }
  }

  function slideImageUrl(index) {
    if (!deck?.deck_id) {
      return '';
    }
    return apiUrl(`/api/v1/decks/${deck.deck_id}/slides/${index}/image?scale=2`);
  }

  function toggleFocus(index) {
    setFocusedSlideIndex((prev) => (prev === index ? null : index));
  }

  function scrollToSlide(index) {
    const clamped = Math.max(0, Math.min(index, slides.length - 1));
    const target = slideRefs.current[clamped];
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setCurrentSlideIndex(clamped);
    }
  }

  useEffect(() => {
    const container = slideScrollRef.current;
    if (!container || !slides.length) {
      return;
    }

    const updateCurrentSlide = () => {
      const viewportTop = container.getBoundingClientRect().top;
      const viewportHeight = container.clientHeight;
      const targetTop = viewportTop + viewportHeight / 3;

      let bestIndex = currentSlideIndexRef.current;
      let bestDistance = Number.POSITIVE_INFINITY;

      slideRefs.current.forEach((node, index) => {
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
  }, [slides, slidesVisible]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (!hasDeck) {
        return;
      }

      if (isEditableTarget(event.target)) {
        return;
      }

      const { key, ctrlKey, metaKey } = event;
      const hasModifier = ctrlKey || metaKey;

      if (hasModifier) {
        return;
      }

      if (['ArrowRight', ' ', 'PageDown', 'ArrowDown'].includes(key)) {
        event.preventDefault();
        scrollToSlide(currentSlideIndexRef.current + 1);
      } else if (['ArrowLeft', 'Backspace', 'PageUp', 'ArrowUp'].includes(key)) {
        event.preventDefault();
        scrollToSlide(currentSlideIndexRef.current - 1);
      } else if (key === 'Home') {
        event.preventDefault();
        scrollToSlide(0);
      } else if (key === 'End') {
        event.preventDefault();
        scrollToSlide(slides.length - 1);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasDeck, slides.length]);

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
      setSplitRatio((previous) => clampSplitRatio(previous - 0.02));
      return;
    }

    if (event.key === 'ArrowRight') {
      event.preventDefault();
      setSplitRatio((previous) => clampSplitRatio(previous + 0.02));
      return;
    }

    if (event.key === 'Home') {
      event.preventDefault();
      setSplitRatio(() => clampSplitRatio(SPLIT_MIN_RATIO));
      return;
    }

    if (event.key === 'End') {
      event.preventDefault();
      setSplitRatio(() => clampSplitRatio(SPLIT_MAX_RATIO));
    }
  }

  const slidesPaneStyle = { flex: `0 0 ${splitPercentage}%` };

  async function clearChat() {
    if (clearingChat || sending) {
      return;
    }

    setError('');

    if (!deck?.deck_id) {
      setMessages([WELCOME_MESSAGE]);
      setInputValue('');
      setEditingMessageId(null);
      setMessageDraft('');
      setCopiedMessageId(null);
      return;
    }

    setClearingChat(true);

    try {
      const response = await fetch(apiUrl(`/api/v1/decks/${deck.deck_id}/chat/clear`), {
        method: 'POST',
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to clear chat');
      }

      setMessages([WELCOME_MESSAGE]);
      setInputValue('');
      setEditingMessageId(null);
      setMessageDraft('');
      setCopiedMessageId(null);
    } catch (clearError) {
      setError(normalizeError(clearError, 'Failed to clear chat'));
    } finally {
      setClearingChat(false);
    }
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

    setMessages((previous) =>
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

  async function sendMessage(event) {
    event.preventDefault();

    if (!deck?.deck_id || sending) {
      return;
    }

    const question = inputValue.trim();
    if (!question) {
      return;
    }

    setError('');
    setInputValue('');

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: question,
    };

    const assistantId = `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const assistantMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setSending(true);

    try {
      const response = await fetch(apiUrl(`/api/v1/decks/${deck.deck_id}/chat/stream`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question,
          focused_slide_index: focusedSlideIndex,
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to start AI stream');
      }

      await consumeSse(response, (payload) => {
        if (payload.type === 'chunk' && typeof payload.text === 'string') {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId
                ? { ...message, content: message.content + payload.text }
                : message
            )
          );
          return;
        }

        if (payload.type === 'error') {
          const message = payload.message || 'Unknown AI error';
          setMessages((prev) =>
            prev.map((item) =>
              item.id === assistantId
                ? { ...item, content: `Error: ${message}` }
                : item
            )
          );
        }
      });
    } catch (streamError) {
      const message = normalizeError(streamError, 'Failed to stream AI response');
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? { ...item, content: `Error: ${message}` }
            : item
        )
      );
      setError(message);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-copy">
          <p className="eyebrow">SlideLecturer</p>
          <h1>Slide Study Studio</h1>
          <p className="topbar-subtitle">
            Upload a deck, scroll a continuous slide viewer, and ask focused questions in real time.
          </p>
        </div>
        <div className="topbar-controls">
          <div className="header-pills">
            {uploading ? (
              <span className="status-pill">Uploading</span>
            ) : deck ? (
              <span className="status-pill">Deck Loaded</span>
            ) : (
              <span className="status-pill muted">Waiting</span>
            )}
            {deck ? (
              <p className="deck-meta">
                {deck.filename} · {deck.slide_count} slides
              </p>
            ) : (
              <p className="deck-meta muted">No deck loaded</p>
            )}
          </div>
          <input
            ref={fileInputRef}
            className="hidden-file-input"
            type="file"
            accept=".pdf,.ppt,.pptx"
            onChange={handleFileInputChange}
            disabled={uploading || sending}
          />
        </div>
      </header>

      {error ? <p className="global-error">{error}</p> : null}

      <main ref={workspaceRef} className="workspace">
        {slidesVisible ? (
          <>
            <section className="slides-panel" style={slidesPaneStyle}>
              <div className="slides-toolbar">
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={() => setSlidesVisible(false)}
                >
                  Hide Slides
                </button>
              </div>

              <div
                className="slides-viewer"
                ref={slideScrollRef}
                role="region"
                aria-label="Slides viewer"
                tabIndex={0}
              >
                {slides.length ? (
                  slides.map((slide) => {
                    const isFocused = focusedSlideIndex === slide.index;
                    return (
                      <article
                        key={slide.index}
                        ref={(node) => {
                          slideRefs.current[slide.index] = node;
                        }}
                        className={`slide-card ${isFocused ? 'focused' : ''}`}
                        onClick={() => toggleFocus(slide.index)}
                      >
                        <p className="slide-label">Slide {slide.index + 1}</p>
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
                    aria-label="Upload by dragging and dropping a PDF or PowerPoint, or click to choose a file"
                  >
                    <p className="dropzone-title">
                      {uploading
                        ? 'Uploading your deck...'
                        : isDragActive
                          ? 'Drop your file to upload'
                          : 'Drag and drop PDF/PowerPoint here'}
                    </p>
                    <p className="dropzone-subtitle">
                      {uploading ? 'Processing slides now.' : 'or click this box to choose a file'}
                    </p>
                  </div>
                )}
              </div>

              <footer className="slides-footer">
                {slides.length ? (
                  <p>
                    Slide {currentSlideIndex + 1} of {slides.length}
                  </p>
                ) : (
                  <p>No slides</p>
                )}
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
              <button type="button" className="ghost-btn" onClick={() => setSlidesVisible(true)}>
                Show Slides
              </button>
            )}
            <div className="chat-actions">
              <button
                type="button"
                className="ghost-btn"
                onClick={clearChat}
                disabled={!hasDeck || sending || clearingChat}
              >
                {clearingChat ? 'Clearing...' : 'Clear Chat'}
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
                onCopy={copyMessage}
                onEditStart={startEditingMessage}
                onEditCancel={cancelEditingMessage}
                onEditSave={saveEditingMessage}
                onEditDraftChange={setMessageDraft}
              />
            ))}
            {sending ? <p className="typing-indicator">AI is typing...</p> : null}
            <div ref={messagesEndRef} />
          </div>

          <form className="chat-input" onSubmit={sendMessage}>
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              placeholder={inputPlaceholder}
              disabled={!hasDeck || sending || clearingChat}
            />
            <button type="submit" disabled={!hasDeck || sending || clearingChat || !inputValue.trim()}>
              {sending ? '...' : 'Send'}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}

export default App;
