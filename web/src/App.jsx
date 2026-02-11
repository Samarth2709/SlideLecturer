import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content:
    "Hello! I'm your slide assistant. Upload a PDF or PPTX deck, then ask questions about the full deck or focus on one slide.",
};

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

function MessageBubble({ message }) {
  return (
    <article className={`message-bubble ${message.role}`}>
      <header>{message.role === 'user' ? 'You' : 'AI'}</header>
      <div className="message-content">
        {message.role === 'assistant' ? (
          <ReactMarkdown>{message.content}</ReactMarkdown>
        ) : (
          <p>{message.content}</p>
        )}
      </div>
    </article>
  );
}

function App() {
  const [deck, setDeck] = useState(null);
  const [slides, setSlides] = useState([]);
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [inputValue, setInputValue] = useState('');
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [focusedSlideIndex, setFocusedSlideIndex] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [slidesVisible, setSlidesVisible] = useState(true);

  const slideScrollRef = useRef(null);
  const slideRefs = useRef([]);
  const inputRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages]);

  const hasDeck = Boolean(deck?.deck_id);

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
    setZoom(1);
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

  async function handleFileUpload(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

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
      event.target.value = '';
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

      let bestIndex = currentSlideIndex;
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

      setCurrentSlideIndex(bestIndex);
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
  }, [slides, currentSlideIndex, slidesVisible]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (!hasDeck) {
        return;
      }

      if (inputRef.current && document.activeElement === inputRef.current) {
        return;
      }

      const { key, ctrlKey, metaKey } = event;
      const hasModifier = ctrlKey || metaKey;

      if (hasModifier) {
        if (key === '+' || key === '=') {
          event.preventDefault();
          setZoom((prev) => Math.min(2, Number((prev + 0.1).toFixed(1))));
          return;
        }

        if (key === '-') {
          event.preventDefault();
          setZoom((prev) => Math.max(0.5, Number((prev - 0.1).toFixed(1))));
          return;
        }

        if (key === '0') {
          event.preventDefault();
          setZoom(1);
          return;
        }
      }

      if (['ArrowRight', ' ', 'PageDown', 'ArrowDown'].includes(key)) {
        event.preventDefault();
        scrollToSlide(currentSlideIndex + 1);
      } else if (['ArrowLeft', 'Backspace', 'PageUp', 'ArrowUp'].includes(key)) {
        event.preventDefault();
        scrollToSlide(currentSlideIndex - 1);
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
  }, [hasDeck, currentSlideIndex, slides.length]);

  async function clearChat() {
    if (!deck?.deck_id) {
      setMessages([WELCOME_MESSAGE]);
      return;
    }

    try {
      await fetch(apiUrl(`/api/v1/decks/${deck.deck_id}/chat/clear`), {
        method: 'POST',
      });
    } catch (clearError) {
      console.warn('Failed to clear server chat state', clearError);
    }

    setMessages([WELCOME_MESSAGE]);
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
          current_slide_index: currentSlideIndex,
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
        <div>
          <p className="eyebrow">SlideLecturer</p>
          <h1>Web Study Workspace</h1>
        </div>
        <div className="topbar-controls">
          <label className={`upload-btn ${uploading ? 'busy' : ''}`}>
            <input
              type="file"
              accept=".pdf,.ppt,.pptx"
              onChange={handleFileUpload}
              disabled={uploading || sending}
            />
            {uploading ? 'Uploading...' : 'Upload PDF/PPTX'}
          </label>
          {deck ? (
            <p className="deck-meta">
              {deck.filename} · {deck.slide_count} slides
            </p>
          ) : (
            <p className="deck-meta muted">No deck loaded</p>
          )}
        </div>
      </header>

      {error ? <p className="global-error">{error}</p> : null}

      <main className={`workspace ${slidesVisible ? '' : 'slides-collapsed'}`}>
        <section className="slides-panel">
          <div className="slides-toolbar">
            <button
              type="button"
              className="ghost-btn"
              onClick={() => setSlidesVisible((prev) => !prev)}
            >
              {slidesVisible ? 'Hide Slides' : 'Show Slides'}
            </button>

            <div className="zoom-controls">
              <button
                type="button"
                onClick={() => setZoom((prev) => Math.max(0.5, Number((prev - 0.1).toFixed(1))))}
                disabled={!hasDeck}
              >
                -
              </button>
              <span>{Math.round(zoom * 100)}%</span>
              <button
                type="button"
                onClick={() => setZoom((prev) => Math.min(2, Number((prev + 0.1).toFixed(1))))}
                disabled={!hasDeck}
              >
                +
              </button>
              <button type="button" onClick={() => setZoom(1)} disabled={!hasDeck}>
                Reset
              </button>
            </div>
          </div>

          {slidesVisible ? (
            <>
              <div className="slides-scroll" ref={slideScrollRef}>
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
                            style={{ width: `${Math.round(zoom * 100)}%` }}
                            loading="lazy"
                          />
                        </div>
                        {slide.text_preview ? <p className="slide-preview">{slide.text_preview}</p> : null}
                      </article>
                    );
                  })
                ) : (
                  <div className="empty-state">
                    <p>Upload a PDF or PPTX deck to load slides.</p>
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
            </>
          ) : null}
        </section>

        <section className="chat-panel">
          <header className="chat-header">
            <h2>Ask AI</h2>
            <button type="button" className="ghost-btn" onClick={clearChat} disabled={!hasDeck || sending}>
              Clear Chat
            </button>
          </header>

          <div className="messages-list">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
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
              disabled={!hasDeck || sending}
            />
            <button type="submit" disabled={!hasDeck || sending || !inputValue.trim()}>
              {sending ? '...' : 'Send'}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}

export default App;
