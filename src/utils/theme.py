"""Dark mode theme and styling for the application."""


class Theme:
    """Dark mode UI theme constants."""

    # Primary colors
    PRIMARY = "#6366f1"  # Indigo
    PRIMARY_HOVER = "#818cf8"
    PRIMARY_PRESSED = "#4f46e5"

    # Background colors (dark)
    BACKGROUND = "#0f0f1a"  # Darkest background
    SURFACE = "#1a1a2e"  # Card/panel background
    SURFACE_ELEVATED = "#252542"  # Elevated surfaces

    # Border colors
    BORDER = "#2d2d4a"
    BORDER_FOCUS = "#6366f1"

    # Text colors
    TEXT_PRIMARY = "#e2e8f0"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"

    # Message bubbles
    USER_BG = "#3730a3"  # Dark indigo for user
    USER_TEXT = "#e2e8f0"
    AI_BG = "#1e293b"  # Dark slate for AI
    AI_TEXT = "#e2e8f0"

    # Status colors
    SUCCESS = "#22c55e"
    ERROR = "#ef4444"
    WARNING = "#f59e0b"

    # Border radius
    RADIUS_SM = "6px"
    RADIUS_MD = "8px"
    RADIUS_LG = "12px"

    @classmethod
    def get_app_stylesheet(cls) -> str:
        """Get the main application stylesheet."""
        return f"""
            QMainWindow {{
                background-color: {cls.BACKGROUND};
            }}

            QWidget {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
                color: {cls.TEXT_PRIMARY};
                background-color: transparent;
            }}

            QPushButton {{
                background-color: {cls.PRIMARY};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: {cls.RADIUS_MD};
                font-size: 14px;
                font-weight: 600;
            }}

            QPushButton:hover {{
                background-color: {cls.PRIMARY_HOVER};
            }}

            QPushButton:pressed {{
                background-color: {cls.PRIMARY_PRESSED};
            }}

            QPushButton:disabled {{
                background-color: {cls.BORDER};
                color: {cls.TEXT_MUTED};
            }}

            QLineEdit {{
                padding: 12px 16px;
                border: 2px solid {cls.BORDER};
                border-radius: {cls.RADIUS_MD};
                font-size: 14px;
                background-color: {cls.SURFACE};
                color: {cls.TEXT_PRIMARY};
            }}

            QLineEdit:focus {{
                border-color: {cls.BORDER_FOCUS};
            }}

            QLineEdit::placeholder {{
                color: {cls.TEXT_MUTED};
            }}

            QScrollArea {{
                border: none;
                background-color: {cls.SURFACE};
            }}

            QScrollBar:vertical {{
                background: {cls.SURFACE};
                width: 10px;
                border-radius: 5px;
                margin: 2px;
            }}

            QScrollBar::handle:vertical {{
                background: {cls.BORDER};
                border-radius: 4px;
                min-height: 30px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {cls.TEXT_MUTED};
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QSplitter::handle {{
                background-color: {cls.BORDER};
            }}

            QSplitter::handle:hover {{
                background-color: {cls.PRIMARY};
            }}

            QLabel {{
                color: {cls.TEXT_PRIMARY};
            }}

            QFrame {{
                background-color: transparent;
            }}

            QTextBrowser {{
                background-color: transparent;
                border: none;
                color: {cls.TEXT_PRIMARY};
            }}
        """

    @classmethod
    def get_chat_header_style(cls) -> str:
        """Get chat header styling."""
        return f"""
            QFrame {{
                background-color: {cls.SURFACE};
                border: none;
                border-bottom: 1px solid {cls.BORDER};
            }}
        """

    @classmethod
    def get_chat_input_frame_style(cls) -> str:
        """Get chat input area styling."""
        return f"""
            QFrame {{
                background-color: {cls.SURFACE};
                border: none;
                border-top: 1px solid {cls.BORDER};
            }}
        """

    @classmethod
    def get_messages_area_style(cls) -> str:
        """Get messages scroll area styling."""
        return f"""
            QScrollArea {{
                border: none;
                background-color: {cls.BACKGROUND};
            }}
            QWidget {{
                background-color: {cls.BACKGROUND};
            }}
        """

    @classmethod
    def get_user_bubble_style(cls) -> str:
        """Get user message bubble styling."""
        return f"""
            MessageBubble {{
                background-color: {cls.USER_BG};
                border-radius: {cls.RADIUS_LG};
                margin-left: 40px;
            }}
        """

    @classmethod
    def get_ai_bubble_style(cls) -> str:
        """Get AI message bubble styling."""
        return f"""
            MessageBubble {{
                background-color: {cls.AI_BG};
                border-radius: {cls.RADIUS_LG};
                margin-right: 40px;
            }}
        """

    @classmethod
    def get_slide_viewer_style(cls) -> str:
        """Get slide viewer styling."""
        return f"""
            QLabel {{
                background-color: {cls.SURFACE};
                border-radius: {cls.RADIUS_LG};
            }}
        """

    @classmethod
    def get_slide_error_style(cls) -> str:
        """Get slide viewer error styling."""
        return f"""
            QLabel {{
                background-color: {cls.SURFACE};
                color: {cls.ERROR};
                font-size: 16px;
                padding: 20px;
                border-radius: {cls.RADIUS_LG};
            }}
        """

    @classmethod
    def get_navigator_style(cls) -> str:
        """Get slide navigator styling."""
        return f"""
            SlideNavigator {{
                background-color: {cls.SURFACE};
                border-radius: {cls.RADIUS_MD};
                padding: 8px;
            }}
        """

    @classmethod
    def get_navigator_button_style(cls) -> str:
        """Get navigation button styling."""
        return f"""
            QPushButton {{
                background-color: {cls.PRIMARY};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: {cls.RADIUS_MD};
                font-size: 14px;
                font-weight: 600;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: {cls.PRIMARY_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {cls.PRIMARY_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: {cls.BORDER};
                color: {cls.TEXT_MUTED};
            }}
        """

    @classmethod
    def get_counter_label_style(cls) -> str:
        """Get slide counter label styling."""
        return f"""
            QLabel {{
                color: {cls.TEXT_SECONDARY};
                font-size: 14px;
                font-weight: bold;
            }}
        """
