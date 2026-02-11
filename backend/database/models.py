"""Database models for feedback system - SIMPLIFIED VERSION"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timedelta
import uuid

Base = declarative_base()

# ============================================================================
# ChatSession Model - NEW (Create this table)
# ============================================================================

class ChatSession(Base):
    """
    Track chat sessions with 5-minute context windows
    """
    __tablename__ = 'chat_sessions'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, unique=True, index=True)
    
    # Session timing
    start_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Context window timing
    context_window_start = Column(DateTime, default=datetime.utcnow, nullable=False)
    context_expires_at = Column(DateTime, nullable=False)
    
    last_activity = Column(DateTime, default=datetime.utcnow, nullable=False)
    message_count = Column(Integer, default=0)
    context_resets = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def is_context_expired(self):
        """Check if the 5-minute context window has expired"""
        return datetime.utcnow() > self.context_expires_at
    
    def time_remaining_in_context(self):
        """Calculate seconds remaining in current context window"""
        if self.is_context_expired():
            return 0
        return (self.context_expires_at - datetime.utcnow()).total_seconds()
    
    def reset_context_window(self, duration_minutes=5):
        """Reset the context window to start fresh"""
        self.context_window_start = datetime.utcnow()
        self.context_expires_at = datetime.utcnow() + timedelta(minutes=duration_minutes)
        self.context_resets += 1
    
    def get_current_context_window_id(self):
        """Generate unique ID for current context window"""
        return f"{self.session_id}_ctx_{self.context_resets}"
    
    def __repr__(self):
        return f"<ChatSession(session_id={self.session_id}, context_resets={self.context_resets})>"


# ============================================================================
# FeedbackInteraction Model - SIMPLIFIED (Use existing columns only)
# ============================================================================

class FeedbackInteraction(Base):
    """
    Store chat interactions and feedback
    Uses ONLY the existing database columns - no migration needed!
    """
    __tablename__ = 'feedback_interactions'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    message_id = Column(String, nullable=False, unique=True, index=True)
    
    # Use 'timestamp' for everything - it already exists!
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Interaction data
    question = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    provider_used = Column(String)
    tokens_used = Column(Integer)
    
    # Feedback data
    feedback_type = Column(String)
    feedback_comment = Column(Text)
    feedback_timestamp = Column(DateTime)
    
    def __repr__(self):
        return f"<FeedbackInteraction(id={self.id}, timestamp={self.timestamp})>"