"""Markdown and LaTeX rendering utilities for chat messages."""

import re
from typing import Optional

try:
    import markdown2
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

# Optional LaTeX support via matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    from matplotlib import mathtext
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.figure
    from io import BytesIO
    import base64
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


class MarkdownRenderer:
    """Converts markdown text to HTML with optional LaTeX support."""

    # Inline CSS styles for QLabel (simplified, no external stylesheets)
    # We apply styles inline since QLabel has limited CSS support
    TEXT_COLOR = "#e2e8f0"
    HEADING_COLOR = "#f1f5f9"
    CODE_BG = "#0f172a"
    CODE_COLOR = "#a5b4fc"
    LINK_COLOR = "#818cf8"

    def __init__(self):
        self.extras = [
            "fenced-code-blocks",
            "tables",
            "strike",
            "task_list",
            "code-friendly",
            "cuddled-lists",
        ]

    def render(self, text: str) -> str:
        """Convert markdown text to styled HTML for QLabel.

        Args:
            text: Markdown formatted text

        Returns:
            HTML string suitable for QLabel rich text
        """
        if not text:
            return ""

        if not HAS_MARKDOWN:
            # Fallback: just escape HTML and preserve newlines
            escaped = self._escape_html(text)
            return escaped.replace('\n', '<br>')

        # Handle LaTeX expressions before markdown processing
        if HAS_MATPLOTLIB:
            text = self._render_latex(text)

        # Convert markdown to HTML
        html = markdown2.markdown(text, extras=self.extras)

        # Post-process HTML to add inline styles for QLabel compatibility
        html = self._apply_inline_styles(html)

        return html

    def _apply_inline_styles(self, html: str) -> str:
        """Apply inline styles to HTML elements for QLabel compatibility."""
        # QLabel has limited CSS support, so we use inline styles
        
        # Handle fenced code blocks FIRST (before inline code)
        # These come as <pre><code>...</code></pre> from markdown2
        html = re.sub(
            r'<pre><code(?:\s+class="[^"]*")?>(.*?)</code></pre>',
            lambda m: self._style_code_block(m.group(1)),
            html,
            flags=re.DOTALL
        )
        
        # Replace heading tags with styled versions
        html = re.sub(
            r'<h1>(.*?)</h1>',
            f'<p style="font-size: 20px; font-weight: bold; color: {self.HEADING_COLOR}; margin: 8px 0;">\\1</p>',
            html
        )
        html = re.sub(
            r'<h2>(.*?)</h2>',
            f'<p style="font-size: 18px; font-weight: bold; color: {self.HEADING_COLOR}; margin: 8px 0;">\\1</p>',
            html
        )
        html = re.sub(
            r'<h3>(.*?)</h3>',
            f'<p style="font-size: 17px; font-weight: bold; color: {self.HEADING_COLOR}; margin: 6px 0;">\\1</p>',
            html
        )
        html = re.sub(
            r'<h[456]>(.*?)</h[456]>',
            f'<p style="font-size: 16px; font-weight: bold; color: {self.HEADING_COLOR}; margin: 6px 0;">\\1</p>',
            html
        )

        # Style inline code (not inside pre blocks, which are already handled)
        html = re.sub(
            r'<code>(.*?)</code>',
            f'<span style="background-color: {self.CODE_BG}; color: {self.CODE_COLOR}; padding: 2px 5px; font-family: monospace;">\\1</span>',
            html
        )

        # Style links
        html = re.sub(
            r'<a href="(.*?)">(.*?)</a>',
            f'<a href="\\1" style="color: {self.LINK_COLOR};">\\2</a>',
            html
        )

        # Style strong/bold
        html = re.sub(
            r'<strong>(.*?)</strong>',
            f'<b style="color: {self.HEADING_COLOR};">\\1</b>',
            html
        )

        # Clean up any remaining pre tags (shouldn't be any after code block handling)
        html = re.sub(
            r'<pre>(.*?)</pre>',
            r'<p>\1</p>',
            html,
            flags=re.DOTALL
        )

        return html

    def _style_code_block(self, code_content: str) -> str:
        """Style a fenced code block with proper formatting.
        
        Args:
            code_content: The code inside the block (may contain newlines)
            
        Returns:
            Styled HTML for the code block with preserved line breaks
        """
        # Convert newlines to <br> for proper display in QLabel
        # Also preserve leading spaces by converting to &nbsp;
        lines = code_content.split('\n')
        styled_lines = []
        for line in lines:
            # Preserve leading whitespace
            leading_spaces = len(line) - len(line.lstrip(' '))
            line = '&nbsp;' * leading_spaces + self._escape_html(line.lstrip(' '))
            styled_lines.append(line)
        
        formatted_code = '<br>'.join(styled_lines)
        
        return (
            f'<div style="background-color: {self.CODE_BG}; '
            f'padding: 10px; margin: 8px 0; border-radius: 6px;">'
            f'<span style="color: {self.CODE_COLOR}; font-family: monospace; '
            f'white-space: pre-wrap;">{formatted_code}</span></div>'
        )

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    def _render_latex(self, text: str) -> str:
        """Replace LaTeX expressions with rendered images.

        Handles both display math ($$...$$) and inline math ($...$).
        """
        # Display math first (greedy match)
        text = re.sub(
            r'\$\$(.+?)\$\$',
            lambda m: self._latex_to_img(m.group(1), display=True),
            text,
            flags=re.DOTALL
        )

        # Inline math (non-greedy)
        text = re.sub(
            r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)',
            lambda m: self._latex_to_img(m.group(1), display=False),
            text
        )

        return text

    def _latex_to_img(self, latex: str, display: bool = False) -> str:
        """Convert a LaTeX expression to a base64-encoded image tag.

        Args:
            latex: LaTeX math expression (without $ delimiters)
            display: If True, render as display math (larger, centered)

        Returns:
            HTML img tag with base64-encoded PNG
        """
        try:
            # Create figure for rendering
            fig = matplotlib.figure.Figure(figsize=(0.01, 0.01))
            fig.patch.set_facecolor('none')  # Transparent background

            fontsize = 16 if display else 14
            text_obj = fig.text(
                0, 0,
                f'${latex}$',
                fontsize=fontsize,
                color='#e2e8f0'  # Light text for dark mode
            )

            # Render to get bounding box
            canvas = FigureCanvasAgg(fig)
            canvas.draw()

            # Get tight bounding box
            renderer = canvas.get_renderer()
            bbox = text_obj.get_window_extent(renderer)

            # Add padding
            pad = 4
            fig.set_size_inches(
                (bbox.width + 2 * pad) / fig.dpi,
                (bbox.height + 2 * pad) / fig.dpi
            )

            # Re-render with correct size
            buf = BytesIO()
            fig.savefig(
                buf,
                format='png',
                bbox_inches='tight',
                pad_inches=0.05,
                dpi=150,
                facecolor='none',
                transparent=True
            )
            buf.seek(0)

            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            css_class = 'latex-display' if display else 'latex-inline'
            return f'<img src="data:image/png;base64,{img_base64}" class="{css_class}" alt="{self._escape_html(latex)}"/>'

        except Exception:
            # Fallback: show as styled code
            return f'<code>${latex}$</code>'


# Singleton instance for reuse
_renderer: Optional[MarkdownRenderer] = None


def get_renderer() -> MarkdownRenderer:
    """Get the shared markdown renderer instance."""
    global _renderer
    if _renderer is None:
        _renderer = MarkdownRenderer()
    return _renderer


def render_markdown(text: str) -> str:
    """Convenience function to render markdown to HTML.

    Args:
        text: Markdown formatted text

    Returns:
        HTML string with dark mode styling
    """
    return get_renderer().render(text)


def render_markdown_streaming(text: str) -> str:
    """Render markdown that may be incomplete (during streaming).
    
    This function handles partial markdown gracefully by completing
    unclosed syntax before rendering to avoid broken HTML.

    Args:
        text: Markdown formatted text (possibly incomplete)

    Returns:
        HTML string with dark mode styling
    """
    if not text:
        return ""
    
    # Complete any unclosed markdown syntax to prevent broken HTML
    text = _complete_partial_markdown(text)
    
    return get_renderer().render(text)


def _complete_partial_markdown(text: str) -> str:
    """Complete unclosed markdown syntax for cleaner streaming display.
    
    Args:
        text: Potentially incomplete markdown text
        
    Returns:
        Text with unclosed syntax completed
    """
    # Handle unclosed bold/italic markers
    # Count ** markers (bold)
    bold_count = text.count('**')
    if bold_count % 2 != 0:
        # Unclosed bold - close it at the end
        text += '**'
    
    # Count * markers (italic) - but not ** 
    # Replace ** temporarily to count single *
    temp = text.replace('**', '\x00\x00')
    italic_count = temp.count('*')
    if italic_count % 2 != 0:
        text += '*'
    
    # Handle unclosed inline code
    # Count ` markers (but not ```)
    temp = text.replace('```', '\x00\x00\x00')
    backtick_count = temp.count('`')
    if backtick_count % 2 != 0:
        text += '`'
    
    # Handle unclosed fenced code blocks
    fence_count = text.count('```')
    if fence_count % 2 != 0:
        text += '\n```'
    
    # Handle unclosed strikethrough
    strike_count = text.count('~~')
    if strike_count % 2 != 0:
        text += '~~'
    
    return text
